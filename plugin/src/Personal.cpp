// MLWW_Listener - nearby voiced line listener for Mantella Living World - World
// Copyright (C) 2026 itsPigeon2000
//
// This program is free software: you can redistribute it and/or modify it under the terms
// of the GNU General Public License as published by the Free Software Foundation, either
// version 3 of the License, or (at your option) any later version.
//
// This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
// without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
// See the GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License along with this program.
// If not, see <https://www.gnu.org/licenses/>.

#include "Personal.h"

#include "Writer.h"

#include <atomic>
#include <unordered_set>

namespace MLWW::Personal
{
	namespace
	{
		constexpr auto kCrimePoll = 1s;
		constexpr auto kCaughtWindow = 3s;  // a bounty this soon after an owned take or a pickpocket means caught
		constexpr auto kHitRepeat = 60s;    // one "struck" per NPC per minute of real time
		constexpr auto kRecheck = 500ms;        // health is read again this long after a heal or a friendly hit
		constexpr auto kHealthRead = 2s;        // the once-a-second health read can be this old when the main thread is busy
		constexpr auto kHealRepeat = 60s;       // one "healed" per NPC and direction per minute: healing over time counts once
		constexpr auto kFriendlyRepeat = 10s;   // one "friendly fire" per NPC and direction in this time
		constexpr auto kRescueWindow = 15s;     // a rescue must land this soon after going down or the last hit below kLowHealth
		constexpr auto kDefendWindow = 5s;      // a follower's hit defends the player this soon after that enemy hit the player
		constexpr auto kMinFight = 5s;          // shorter fights are not counted
		constexpr auto kFightQuiet = 5s;        // out of combat this long ends a fight
		constexpr auto kWakeCheck = 1s;         // a sleeper the player activated is looked at again after this
		constexpr float kLowHealth = 0.25f;
		constexpr float kPartyRange = 8192.0f;  // a party member further away than this was not there

		using Clock = std::chrono::steady_clock;

		// Main thread only (touched from SKSE tasks).
		struct Take
		{
			RE::TESForm*      owner{ nullptr };  // TESNPC whose item it was
			std::string       kind;              // "theft" or "pickpocketing"
			Clock::time_point when{};
		};
		Take                                        g_lastTake;
		float                                       g_crimeTotal = -1.0f;
		RE::ActorHandle                             g_pickpocketTarget;
		Clock::time_point                           g_pickpocketUntil{};
		RE::ActorHandle                             g_barterTarget;
		std::int32_t                                g_barterGold = 0;
		std::unordered_map<RE::FormID, Clock::time_point> g_lastHit;
		std::unordered_map<std::string, std::int32_t>     g_barterSold;  // items the player sold in this barter menu
		std::int32_t                                      g_barterSpent = 0;   // gold the player paid in this barter menu
		std::int32_t                                      g_barterEarned = 0;  // gold the player was paid in this barter menu
		RE::ActorHandle                                   g_tradeTarget;       // follower whose inventory window is open
		std::int32_t                                      g_tradeGold = 0;     // their gold when it opened
		std::unordered_set<RE::FormID>                    g_assaulted;         // struck by the player while not hostile to them

		struct Attack
		{
			RE::ActorHandle   attacker;
			Clock::time_point when{};
		};
		std::unordered_map<RE::FormID, Attack>            g_lastAttacker;     // party member -> who last hit them
		std::unordered_map<RE::FormID, Attack>            g_down;             // party member in bleedout -> who put them there (when = the rescue deadline)
		Attack                                            g_playerLow;        // who last hit the player below kLowHealth (when = the rescue deadline)
		std::unordered_map<RE::FormID, Clock::time_point> g_playerAttackers;  // who hit the player in this fight
		struct PartyHit
		{
			RE::FormID        cause{ 0 };  // who hit them last
			Clock::time_point when{};      // when
			Clock::time_point other{};     // when anyone other than that one last hit them
		};
		std::unordered_map<RE::FormID, PartyHit>          g_partyHits;        // player and party members
		std::unordered_map<RE::FormID, float>             g_health;           // player and party, read once a second
		std::unordered_map<std::uint64_t, Clock::time_point> g_repeat;        // rate limit per NPC, direction and kind
		std::unordered_set<RE::FormID>                    g_fighters;         // party members in combat during this fight
		std::unordered_set<RE::FormID>                    g_defenders;        // party members who hit an attacker of the player in this fight
		bool                                              g_inFight = false;
		Clock::time_point                                 g_fightStart{};
		Clock::time_point                                 g_lastCombat{};
		bool                                              g_crimeRoseInFight = false;  // the player's own crime made this fight

		void SendModEvent(const char* a_name, const std::string& a_text, float a_num, RE::TESForm* a_sender)
		{
			SKSE::ModCallbackEvent event{ a_name, a_text.c_str(), a_num, a_sender };
			SKSE::GetModCallbackEventSource()->SendEvent(&event);
		}

		RE::PlayerCharacter* Player() { return RE::PlayerCharacter::GetSingleton(); }

		// Raised by ResetFight: work queued before a load or a new game is dropped instead of running in the next one.
		std::atomic<std::uint32_t> g_epoch{ 0 };

		template <class F>
		void Task(F&& a_fn, std::uint32_t a_epoch = g_epoch.load())
		{
			SKSE::GetTaskInterface()->AddTask([a_epoch, fn = std::forward<F>(a_fn)]() {
				if (a_epoch == g_epoch.load()) {
					fn();
				}
			});
		}

		std::vector<RE::TESFaction*> g_crimeFactions;  // every faction that tracks crime, found once at kDataLoaded

		// The player's bounty (violent and non-violent) summed over every crime faction.
		float CrimeTotal()
		{
			float total = 0.0f;
			for (auto* faction : g_crimeFactions) {
				total += static_cast<float>(faction->GetCrimeGold());
			}
			return total;
		}

		// Not Actor::GetGoldAmount: it dereferences the Gold default object unchecked, which crashes when that is empty.
		std::int32_t GoldOf(RE::TESObjectREFR* a_ref)
		{
			std::int32_t gold = 0;
			for (auto& [obj, count] : a_ref->GetInventoryCounts([](RE::TESBoundObject& a_obj) { return a_obj.IsGold(); })) {
				gold += count;
			}
			return gold > 0 ? gold : 0;  // gold taken out of the base container can count below 0
		}

		std::int32_t ChestGold(RE::Actor* a_merchant)
		{
			auto* faction = a_merchant ? a_merchant->GetVendorFaction() : nullptr;
			auto* chest = faction ? faction->vendorData.merchantContainer : nullptr;
			return chest ? GoldOf(chest) : -1;
		}

		bool PickpocketActive() { return Clock::now() < g_pickpocketUntil; }

		// A bounty that appeared right after an owned take or a pickpocket: the owner knows.
		void CheckCrime()
		{
			const float total = CrimeTotal();
			const bool  rose = g_crimeTotal >= 0.0f && total > g_crimeTotal + 0.5f;
			if (total != g_crimeTotal) {
				logger::info("bounty total {:.0f} -> {:.0f}", g_crimeTotal, total);
			}
			g_crimeTotal = total;
			if (!rose) {
				return;
			}
			if (g_inFight || (Player() && Player()->IsInCombat())) {
				g_crimeRoseInFight = true;  // guards and townsfolk the player turned on are no enemies beaten
			}
			const auto now = Clock::now();
			const bool takeAfter = g_lastTake.owner && g_lastTake.when > g_pickpocketUntil;  // an owned take after the pickpocket menu closed is the newer crime
			if (auto target = g_pickpocketTarget.get(); target && now < g_pickpocketUntil + kCaughtWindow && !takeAfter) {
				SendModEvent("MLWW_Caught", "pickpocketing", 0.0f, target.get());
				logger::info("caught pickpocketing {:08X}", target->GetFormID());
				g_pickpocketTarget.reset();
				return;
			}
			if (g_lastTake.owner && now - g_lastTake.when < kCaughtWindow) {
				SendModEvent("MLWW_Caught", g_lastTake.kind, 0.0f, g_lastTake.owner);
				logger::info("caught stealing from {:08X}", g_lastTake.owner->GetFormID());
				g_lastTake = {};
			}
		}

		void CheckParty();

		void PollCrime()
		{
			Writer::RunLater(kCrimePoll, []() {
				SKSE::GetTaskInterface()->AddTask([]() {
					CheckCrime();
					CheckParty();
				});
				PollCrime();  // re-armed from the worker thread, never from inside the task
			});
		}

		RE::Actor* LiveActor(RE::TESObjectREFR* a_ref)
		{
			auto* actor = a_ref ? a_ref->As<RE::Actor>() : nullptr;
			return actor && actor != Player() && !actor->IsDead() ? actor : nullptr;
		}

		// a_hostile, a_ally and a_crime are read in the death event itself.
		void OnDeath(RE::NiPointer<RE::TESObjectREFR> a_dying, RE::NiPointer<RE::TESObjectREFR> a_killer, bool a_hostile, bool a_ally, RE::FormID a_crime)
		{
			auto* actor = a_dying ? a_dying->As<RE::Actor>() : nullptr;
			auto* base = actor ? actor->GetActorBase() : nullptr;
			if (!actor || actor == Player() || !base) {
				return;
			}
			const bool byPlayer = a_killer && a_killer.get() == Player();
			// A murder: a person (no enemy, not the party's own) killed by the player. Someone the player struck while
			// they were not hostile was murdered even if they fought back. Sent for anyone, named or not, with the
			// victim's crime faction, so a report is only backed in that hold.
			if (byPlayer && !a_ally && actor->HasKeywordString("ActorTypeNPC") && (!a_hostile || g_assaulted.contains(actor->GetFormID()))) {
				SendModEvent("MLWW_Murder", a_crime ? std::to_string(static_cast<std::int32_t>(a_crime)) : std::string{}, 0.0f, actor);  // signed: Papyrus reads it with Game.GetFormEx
				logger::info("murder {:08X} (crime faction {:08X})", actor->GetFormID(), a_crime);
			}
			if (!base->IsUnique()) {
				return;  // only named people have relatives who grieve
			}
			SendModEvent("MLWW_Died", "", byPlayer ? 1.0f : 0.0f, actor);
			logger::info("died {:08X}{}", actor->GetFormID(), byPlayer ? " (player)" : "");
		}

		// a_wasHostile is read when the hit lands: by the time a task runs, the hit itself may have made them hostile.
		void OnHit(RE::NiPointer<RE::TESObjectREFR> a_target, RE::FormID a_source, bool a_wasHostile)
		{
			auto* actor = LiveActor(a_target.get());
			if (!actor || a_wasHostile) {
				return;  // enemies are expected to be hit
			}
			if (auto* magic = RE::TESForm::LookupByID<RE::MagicItem>(a_source); magic && !magic->IsHostile()) {
				return;  // healing and other friendly spells
			}
			if (g_assaulted.size() >= 256) {
				g_assaulted.clear();
			}
			g_assaulted.insert(actor->GetFormID());
			const auto now = Clock::now();
			auto&      last = g_lastHit[actor->GetFormID()];
			if (now - last < kHitRepeat) {
				return;
			}
			last = now;
			SendModEvent("MLWW_Struck", "", 0.0f, actor);
			logger::info("struck {:08X}", actor->GetFormID());
		}

		// A moment after the player activated a sleeper: only someone who really got up was woken.
		void OnWakeCheck(RE::ActorHandle a_who, float a_hour)
		{
			auto woken = a_who.get();
			if (!woken || woken->AsActorState()->GetSitSleepState() == RE::SIT_SLEEP_STATE::kIsSleeping) {
				return;
			}
			SendModEvent("MLWW_Woken", "", a_hour, woken.get());
			logger::info("woke {:08X} at {:.1f}h", woken->GetFormID(), a_hour);
		}

		// Runs in the event: the sleep state is read before the activation wakes them; the event is sent from a task.
		void OnActivate(RE::NiPointer<RE::TESObjectREFR> a_target, RE::NiPointer<RE::TESObjectREFR> a_by)
		{
			if (!a_by || a_by.get() != Player() || Player()->IsSneaking()) {
				return;  // activating a sleeper while sneaking opens the pickpocket menu and leaves them asleep
			}
			auto* actor = LiveActor(a_target.get());
			if (actor && actor->AsActorState()->GetSitSleepState() == RE::SIT_SLEEP_STATE::kIsSleeping) {
				const auto* calendar = RE::Calendar::GetSingleton();
				const float hour = calendar ? calendar->GetHour() : 12.0f;
				Writer::RunLater(kWakeCheck, [who = actor->GetHandle(), hour, epoch = g_epoch.load()]() {
					Task([=]() { OnWakeCheck(who, hour); }, epoch);
				});
			}
		}

		// The NPC who owns an item the player just took, read from where it came from. Runs in the event itself:
		// a picked-up reference is gone by the time a task runs.
		RE::TESForm* OwnerOfTake(RE::FormID a_from, RE::ObjectRefHandle a_ref)
		{
			RE::TESForm* owner = nullptr;
			if (auto* source = RE::TESForm::LookupByID<RE::TESObjectREFR>(a_from); source && !source->As<RE::Actor>()) {
				owner = source->GetOwner();
			} else if (a_from == 0) {
				if (auto ref = a_ref.get()) {
					owner = ref->GetOwner();
				}
			}
			return owner && owner->Is(RE::FormType::NPC) ? owner : nullptr;
		}

		// Fallback: the owner kept on the item in the player's inventory.
		RE::TESForm* OwnerInInventory(RE::TESBoundObject* a_item)
		{
			auto* player = Player();
			if (!player || !a_item) {
				return nullptr;
			}
			auto inv = player->GetInventory([a_item](RE::TESBoundObject& a_obj) { return &a_obj == a_item; });
			for (auto& [obj, data] : inv) {
				auto& entry = data.second;
				if (!entry || !entry->extraLists) {
					continue;
				}
				for (auto* list : *entry->extraLists) {
					auto* owner = list ? list->GetOwner() : nullptr;
					if (owner && owner->Is(RE::FormType::NPC)) {
						return owner;
					}
				}
			}
			return nullptr;
		}

		void OnMoved(RE::FormID a_from, RE::FormID a_to, RE::FormID a_baseID, std::int32_t a_count, RE::TESForm* a_owner)
		{
			auto* player = Player();
			auto* item = RE::TESForm::LookupByID<RE::TESBoundObject>(a_baseID);
			if (!player || !item || a_count <= 0) {
				return;
			}
			auto*      ui = RE::UI::GetSingleton();
			const bool barter = ui && ui->IsMenuOpen(RE::BarterMenu::MENU_NAME);
			// Training gold goes into the trainer's inventory (vanilla lets it be pickpocketed back): a fee, not a gift.
			const bool training = ui && ui->IsMenuOpen(RE::TrainingMenu::MENU_NAME);
			if (a_from == player->GetFormID() && a_to != player->GetFormID()) {
				if (barter || training) {
					const char* sold = item->GetName();
					if (barter && item->IsGold()) {
						g_barterSpent += a_count;
					} else if (barter && sold && *sold) {
						g_barterSold[sold] += a_count;
					}
					return;
				}
				// A gift: into a living NPC's own inventory, not while reverse-pickpocketing.
				auto* actor = LiveActor(RE::TESForm::LookupByID<RE::TESObjectREFR>(a_to));
				if (!actor || PickpocketActive()) {
					return;
				}
				// Mannequins are living actors of an immobile race (vanilla ManikinRace 0x10760A): dressing one is no gift.
				auto* race = actor->GetRace();
				if (race && (race->data.flags.any(RE::RACE_DATA::Flag::kImmobile) || race->GetFormID() == 0x0010760A)) {
					return;
				}
				const char* name = item->GetName();
				// The gift menu (M.A.R.A.S gifts) has its own event: remembered, but scored by M.A.R.A.S itself. Tested
				// before the follower test: a ring given to a follower spouse through it is a gift.
				const bool giftMenu = ui && ui->IsMenuOpen(RE::GiftMenu::MENU_NAME);
				if (!giftMenu && actor->IsPlayerTeammate()) {
					return;  // followers carry things for the player; gold to them counts once, when their inventory closes
				}
				SendModEvent(giftMenu ? "MLWW_GiftMenu" : "MLWW_Gift", name ? name : "", static_cast<float>(a_count), actor);
				logger::info("gift to {:08X}: {} x{}", actor->GetFormID(), name ? name : "", a_count);
				return;
			}
			if (a_to == player->GetFormID() && barter && item->IsGold()) {
				g_barterEarned += a_count;
			}
			if (a_to != player->GetFormID() || PickpocketActive() || barter) {
				return;  // bought goods are not a take
			}
			// Taken by the player: remember whose it was, in case a bounty follows.
			RE::TESForm* owner = a_owner ? a_owner : OwnerInInventory(item);
			if (owner) {
				g_lastTake = { owner, "theft", Clock::now() };
				logger::info("took an item owned by {:08X}", owner->GetFormID());
			}
		}

		void OnMenu(std::string_view a_menu, bool a_opening)
		{
			auto* player = Player();
			if (!player) {
				return;
			}
			if (a_menu == RE::ContainerMenu::MENU_NAME) {
				const auto mode = RE::ContainerMenu::GetContainerMode();
				if (a_opening && mode == RE::ContainerMenu::ContainerMode::kPickpocket) {
					auto target = RE::TESObjectREFR::LookupByHandle(RE::ContainerMenu::GetTargetRefHandle());
					auto* actor = target ? target->As<RE::Actor>() : nullptr;
					g_pickpocketTarget = actor ? actor->GetHandle() : RE::ActorHandle{};
					g_pickpocketUntil = Clock::time_point::max() - kCaughtWindow;
					logger::info("pickpocket menu on {:08X}", actor ? actor->GetFormID() : 0);
				} else if (a_opening && mode == RE::ContainerMenu::ContainerMode::kNPCMode) {
					// A follower's inventory: gold moved in and out while it is open counts once, as the net, on close.
					auto  target = RE::TESObjectREFR::LookupByHandle(RE::ContainerMenu::GetTargetRefHandle());
					auto* actor = LiveActor(target.get());
					g_tradeTarget = actor && actor->IsPlayerTeammate() ? actor->GetHandle() : RE::ActorHandle{};
					g_tradeGold = actor ? GoldOf(actor) : 0;
				} else if (!a_opening && PickpocketActive()) {  // only the pickpocket menu itself; any other container keeps the old window
					g_pickpocketUntil = Clock::now();  // a failed pickpocket closes the menu; the bounty may land just after
				}
				if (!a_opening) {
					auto follower = g_tradeTarget.get();
					g_tradeTarget.reset();
					const std::int32_t given = follower && !follower->IsDead() ? GoldOf(follower.get()) - g_tradeGold : 0;
					if (given > 0) {
						SendModEvent("MLWW_Gift", "Gold", static_cast<float>(given), follower.get());
						logger::info("gift to {:08X}: Gold x{} (net over the inventory window)", follower->GetFormID(), given);
					}
				}
				return;
			}
			if (a_menu != RE::BarterMenu::MENU_NAME) {
				return;
			}
			if (a_opening) {
				auto target = RE::TESObjectREFR::LookupByHandle(RE::BarterMenu::GetTargetRefHandle());
				auto* actor = target ? target->As<RE::Actor>() : nullptr;
				g_barterTarget = actor ? actor->GetHandle() : RE::ActorHandle{};
				g_barterGold = GoldOf(player);
				g_barterSold.clear();
				g_barterSpent = 0;
				g_barterEarned = 0;
				return;
			}
			auto merchant = g_barterTarget.get();
			g_barterTarget.reset();
			if (!merchant) {
				return;
			}
			const std::int32_t delta = GoldOf(player) - g_barterGold;  // above 0: the player sold
			const std::int32_t chest = ChestGold(merchant.get());
			// Both directions: selling 4,000 and buying 4,200 in one menu is not "bought 200". When no gold move was
			// seen, the net change stands for the one direction it shows.
			std::int32_t spent = g_barterSpent;
			std::int32_t earned = g_barterEarned;
			if (spent == 0 && earned == 0) {
				spent = delta < 0 ? -delta : 0;
				earned = delta > 0 ? delta : 0;
			}
			g_barterSpent = 0;
			g_barterEarned = 0;
			if (spent > 0 || earned > 0) {
				SendModEvent("MLWW_Trade", std::format("{}|{}|{}", chest, spent, earned), static_cast<float>(delta), merchant.get());
				logger::info("trade with {:08X}: player paid {}, was paid {}, chest {}", merchant->GetFormID(), spent, earned, chest);
			}
			if (auto most = std::ranges::max_element(g_barterSold, {}, [](const auto& a_sold) { return a_sold.second; }); most != g_barterSold.end()) {
				SendModEvent("MLWW_TradeGoods", most->first, static_cast<float>(most->second), merchant.get());
			}
		}

		template <class T>
		class Sink final : public RE::BSTEventSink<T>
		{
		public:
			using Handler = std::function<void(const T&)>;
			explicit Sink(Handler a_handler) :
				handler(std::move(a_handler)) {}

			RE::BSEventNotifyControl ProcessEvent(const T* a_event, RE::BSTEventSource<T>*) override
			{
				if (a_event) {
					handler(*a_event);
				}
				return RE::BSEventNotifyControl::kContinue;
			}

		private:
			Handler handler;
		};

		// ---------------------------------------------------------------------------
		// What the player and the party do for and to each other. Each On*Event runs in the event itself and filters
		// before anything is queued; the rest runs on the main thread.
		// ---------------------------------------------------------------------------

		float Health(RE::Actor* a_actor) { return a_actor->AsActorValueOwner()->GetActorValue(RE::ActorValue::kHealth); }

		// A follower set as a teammate and with the player (not told to wait somewhere); a summon is not one.
		bool IsMember(RE::Actor* a_actor)
		{
			return a_actor && a_actor != Player() && a_actor->IsPlayerTeammate() && !a_actor->IsCommandedActor() && !a_actor->IsDead() &&
			       a_actor->AsActorValueOwner()->GetActorValue(RE::ActorValue::kWaitingForPlayer) <= 0.0f;
		}

		std::vector<RE::Actor*> PartyNow()
		{
			std::vector<RE::Actor*> party;
			auto* player = Player();
			auto* lists = RE::ProcessLists::GetSingleton();
			if (!player || !lists) {
				return party;
			}
			const auto here = player->GetPosition();
			lists->ForEachHighActor([&](RE::Actor* a_actor) {
				if (IsMember(a_actor) && a_actor->Is3DLoaded() && a_actor->GetPosition().GetDistance(here) <= kPartyRange) {
					party.push_back(a_actor);
				}
				return RE::BSContainer::ForEachResult::kContinue;
			});
			return party;
		}

		// True at most once per a_every for this NPC, direction and kind.
		template <class D>
		bool Allowed(RE::FormID a_npc, std::uint32_t a_kind, D a_every)
		{
			const auto now = Clock::now();
			auto&      last = g_repeat[(static_cast<std::uint64_t>(a_kind) << 32) | a_npc];
			if (last != Clock::time_point{} && now - last < a_every) {
				return false;
			}
			last = now;
			return true;
		}

		// Once a second: health before the next hit, and fights the party took part in.
		void CheckParty()
		{
			auto* player = Player();
			if (!player) {
				return;
			}
			const auto now = Clock::now();
			const auto party = PartyNow();
			g_health[player->GetFormID()] = Health(player);
			for (auto* member : party) {
				g_health[member->GetFormID()] = Health(member);
			}
			if (player->IsInCombat()) {
				if (!g_inFight) {
					g_inFight = true;
					g_fightStart = now;
				}
				g_lastCombat = now;
				for (auto* member : party) {
					if (member->IsInCombat()) {
						g_fighters.insert(member->GetFormID());
					}
				}
				return;
			}
			if (!g_inFight || now - g_lastCombat < kFightQuiet) {
				return;
			}
			g_inFight = false;
			const bool ownCrime = g_crimeRoseInFight;
			g_crimeRoseInFight = false;
			if (g_lastCombat - g_fightStart >= kMinFight && !ownCrime) {
				for (auto* member : party) {
					if (g_fighters.contains(member->GetFormID())) {
						SendModEvent("MLWW_Fought", "", 0.0f, member);
					}
				}
			}
			g_fighters.clear();
			g_defenders.clear();
			g_playerAttackers.clear();
			g_lastAttacker.clear();
		}

		void OnFriendlyHit(RE::ActorHandle a_target, RE::ActorHandle a_npc, bool a_byPlayer, float a_atHit, Clock::time_point a_when)
		{
			auto target = a_target.get();
			auto npc = a_npc.get();
			if (!target || !npc) {
				return;
			}
			// Someone else's hit since the last health read or before the second one: the lost health may be theirs.
			if (auto hit = g_partyHits.find(target->GetFormID()); hit != g_partyHits.end()) {
				const auto hitter = a_byPlayer ? Player()->GetFormID() : npc->GetFormID();
				if ((hit->second.cause != hitter ? hit->second.when : hit->second.other) + kHealthRead >= a_when) {
					return;
				}
			}
			// The second read sees damage that lands after the event, the once-a-second read damage that landed before it.
			float before = a_atHit;
			if (auto seen = g_health.find(target->GetFormID()); seen != g_health.end()) {
				before = std::max(before, seen->second);
			}
			if (Health(target.get()) >= before - 0.5f || !Allowed(npc->GetFormID(), a_byPlayer ? 1 : 2, kFriendlyRepeat)) {
				return;
			}
			SendModEvent("MLWW_FriendlyFire", "", a_byPlayer ? 1.0f : 0.0f, npc.get());
			logger::info("friendly fire {:08X} ({})", npc->GetFormID(), a_byPlayer ? "by player" : "on player");
		}

		void OnAttacked(RE::ActorHandle a_target, RE::ActorHandle a_attacker)
		{
			auto target = a_target.get();
			auto attacker = a_attacker.get();
			if (!target || !attacker) {
				return;
			}
			const auto now = Clock::now();
			if (target.get() != Player()) {
				g_lastAttacker[target->GetFormID()] = { a_attacker, now };
				return;
			}
			if (g_playerAttackers.size() >= 64) {
				g_playerAttackers.clear();
			}
			g_playerAttackers[attacker->GetFormID()] = now;
			const float most = target->GetActorValueMax(RE::ActorValue::kHealth);
			if (most > 0.0f && Health(target.get()) / most < kLowHealth) {
				g_playerLow = { a_attacker, now + kRescueWindow };
			}
		}

		void NoteHit(RE::FormID a_target, RE::FormID a_cause)
		{
			auto& hit = g_partyHits[a_target];
			if (hit.cause != a_cause) {
				hit.other = hit.when;
				hit.cause = a_cause;
			}
			hit.when = Clock::now();
		}

		void OnMemberStruck(RE::ActorHandle a_member, RE::FormID a_target)
		{
			auto member = a_member.get();
			auto attacked = g_playerAttackers.find(a_target);
			if (!member || attacked == g_playerAttackers.end() || Clock::now() - attacked->second > kDefendWindow) {
				return;
			}
			if (g_defenders.insert(member->GetFormID()).second) {
				SendModEvent("MLWW_Defended", "", 0.0f, member.get());
			}
		}

		void OnPartyHitEvent(const RE::TESHitEvent& a_event)
		{
			auto* player = Player();
			auto* target = a_event.target ? a_event.target->As<RE::Actor>() : nullptr;
			auto* cause = a_event.cause ? a_event.cause->As<RE::Actor>() : nullptr;
			if (!player || !target || !cause || target == cause) {
				return;
			}
			const bool byPlayer = cause == player;
			const bool onPlayer = target == player;
			const bool byMember = !byPlayer && IsMember(cause);
			const bool onMember = !onPlayer && IsMember(target);
			// A summon of the player or a party member is on the party's side, not an attacker.
			const auto commander = cause->IsCommandedActor() ? cause->GetCommandingActor() : RE::NiPointer<RE::Actor>{};
			const bool byParty = byPlayer || byMember || (commander && (commander.get() == player || IsMember(commander.get())));
			auto*      magic = RE::TESForm::LookupByID<RE::MagicItem>(a_event.source);
			if (magic && !magic->IsHostile()) {
				return;  // healing and other friendly spells
			}
			if (onPlayer || onMember) {
				Task([id = target->GetFormID(), by = cause->GetFormID()]() { NoteHit(id, by); });
			}
			if ((byPlayer && onMember) || (byMember && onPlayer)) {
				Writer::RunLater(kRecheck, [targetHandle = target->GetHandle(), npc = (byPlayer ? target : cause)->GetHandle(), byPlayer, atHit = Health(target),
											   when = Clock::now(), epoch = g_epoch.load()]() {
					Task([=]() { OnFriendlyHit(targetHandle, npc, byPlayer, atHit, when); }, epoch);
				});
			} else if (!byParty && (onPlayer || onMember)) {
				Task([targetHandle = target->GetHandle(), attacker = cause->GetHandle()]() { OnAttacked(targetHandle, attacker); });
			} else if (byMember && !onPlayer && !onMember) {
				Task([member = cause->GetHandle(), id = target->GetFormID()]() { OnMemberStruck(member, id); });
			}
		}

		void OnBleedoutEvent(const RE::TESEnterBleedoutEvent& a_event)
		{
			auto* actor = a_event.actor ? a_event.actor->As<RE::Actor>() : nullptr;
			if (!IsMember(actor)) {
				return;
			}
			Task([member = actor->GetHandle()]() {
				auto who = member.get();
				if (!who) {
					return;
				}
				const auto now = Clock::now();
				RE::ActorHandle attacker;
				if (auto last = g_lastAttacker.find(who->GetFormID()); last != g_lastAttacker.end() && now - last->second.when <= kRescueWindow) {
					attacker = last->second.attacker;
				}
				g_down[who->GetFormID()] = { attacker, now + kRescueWindow };
				logger::info("party member down {:08X}", who->GetFormID());
			});
		}

		void OnHealLanded(RE::ActorHandle a_target, RE::ActorHandle a_npc, bool a_byPlayer, float a_before)
		{
			auto target = a_target.get();
			auto npc = a_npc.get();
			if (!target || !npc) {
				return;
			}
			// More than the regeneration of half a second.
			const float least = std::max(1.0f, target->GetActorValueMax(RE::ActorValue::kHealth) * 0.005f);
			if (Health(target.get()) - a_before < least) {
				return;
			}
			if (a_byPlayer) {
				if (auto down = g_down.find(npc->GetFormID()); down != g_down.end()) {
					if (Clock::now() <= down->second.when) {
						SendModEvent("MLWW_Saved", "heal", 1.0f, npc.get());
						logger::info("player saved {:08X} with a heal", npc->GetFormID());
					}
					g_down.erase(down);
				}
			}
			if (Allowed(npc->GetFormID(), a_byPlayer ? 3 : 4, kHealRepeat)) {
				SendModEvent("MLWW_Healed", "", a_byPlayer ? 1.0f : 0.0f, npc.get());
				logger::info("healed {:08X} ({})", npc->GetFormID(), a_byPlayer ? "by player" : "healed player");
			}
		}

		void OnMagicEffectEvent(const RE::TESMagicEffectApplyEvent& a_event)
		{
			auto* player = Player();
			if (!player || !a_event.target || !a_event.caster || a_event.target == a_event.caster || (a_event.target.get() != player && a_event.caster.get() != player)) {
				return;
			}
			auto* target = a_event.target->As<RE::Actor>();
			auto* caster = a_event.caster->As<RE::Actor>();
			if (!target || !caster) {
				return;
			}
			const bool byPlayer = caster == player;
			auto*      npc = byPlayer ? target : caster;
			if (!IsMember(npc)) {
				return;
			}
			auto* effect = RE::TESForm::LookupByID<RE::EffectSetting>(a_event.magicEffect);
			if (!effect || effect->IsHostile() || effect->IsDetrimental() || effect->data.primaryAV != RE::ActorValue::kHealth ||
				(!effect->HasArchetype(RE::EffectSetting::Archetype::kValueModifier) && !effect->HasArchetype(RE::EffectSetting::Archetype::kDualValueModifier))) {
				return;
			}
			Writer::RunLater(kRecheck, [targetHandle = target->GetHandle(), npcHandle = npc->GetHandle(), byPlayer, before = Health(target), epoch = g_epoch.load()]() {
				Task([=]() { OnHealLanded(targetHandle, npcHandle, byPlayer, before); }, epoch);
			});
		}

		// a_killer is who gets the credit: the summoner, when a summon made the kill.
		void OnKill(RE::NiPointer<RE::TESObjectREFR> a_victim, RE::ActorHandle a_killer, bool a_wasHostile)
		{
			auto* victim = a_victim ? a_victim->As<RE::Actor>() : nullptr;
			auto  killer = a_killer.get();
			if (!victim || !killer) {
				return;
			}
			const auto now = Clock::now();
			if (killer.get() == Player()) {
				for (auto down = g_down.begin(); down != g_down.end();) {
					auto* member = RE::TESForm::LookupByID<RE::Actor>(down->first);
					if (now > down->second.when) {
						down = g_down.erase(down);
					} else if (member && !member->IsDead() && down->second.attacker.get().get() == victim) {
						SendModEvent("MLWW_Saved", "kill", 1.0f, member);
						logger::info("player saved {:08X} by killing {:08X}", member->GetFormID(), victim->GetFormID());
						down = g_down.erase(down);
					} else {
						++down;
					}
				}
			} else if (g_playerLow.attacker.get().get() == victim && now <= g_playerLow.when) {
				SendModEvent("MLWW_Saved", "kill", 0.0f, killer.get());
				logger::info("{:08X} saved the player by killing {:08X}", killer->GetFormID(), victim->GetFormID());
				g_playerLow = {};
			}
			if (!a_wasHostile && !g_playerAttackers.contains(victim->GetFormID())) {
				return;  // a murder is not an enemy beaten
			}
			// Someone the player struck while they were peaceful, or in a hold faction the player has a bounty with
			// (guards and townsfolk the player's crime turned hostile; bandits have no crime faction): no enemy beaten.
			if (g_assaulted.contains(victim->GetFormID())) {
				return;
			}
			if (auto* crime = victim->GetCrimeFaction(); crime && crime->GetCrimeGold() > 0) {
				return;
			}
			auto*       base = victim->GetActorBase();
			const char* name = victim->GetDisplayFullName();
			const float score = static_cast<float>(std::min<std::uint16_t>(victim->GetLevel(), 999)) +
			                    (base && base->IsUnique() ? 1000.0f : 0.0f) + (victim->HasKeywordString("ActorTypeDragon") ? 2000.0f : 0.0f);
			SendModEvent("MLWW_Kill", name ? name : "", score, killer.get());
		}

		void OnPartyDeathEvent(const RE::TESDeathEvent& a_event)
		{
			auto* player = Player();
			auto* victim = a_event.actorDying ? a_event.actorDying->As<RE::Actor>() : nullptr;
			auto* killer = a_event.actorKiller ? a_event.actorKiller->As<RE::Actor>() : nullptr;
			if (!a_event.dead || !player || !victim || !killer || victim == player || victim->IsPlayerTeammate()) {
				return;
			}
			RE::NiPointer<RE::Actor> commander = killer->IsCommandedActor() ? killer->GetCommandingActor() : RE::NiPointer<RE::Actor>{};
			auto*                    credit = commander ? commander.get() : killer;
			if (credit != player && !IsMember(credit)) {
				return;
			}
			Task([dying = a_event.actorDying, killerHandle = credit->GetHandle(), hostile = victim->IsHostileToActor(player)]() { OnKill(dying, killerHandle, hostile); });
		}

		// Natives
		std::vector<RE::Actor*> Party(RE::StaticFunctionTag*) { return PartyNow(); }

		// Gold in the merchant's vendor chest now; -1 when they have none.
		std::int32_t ChestGoldOf(RE::StaticFunctionTag*, RE::Actor* a_merchant) { return ChestGold(a_merchant); }

		RE::BSFixedString WornStolenFrom(RE::StaticFunctionTag*, RE::Actor* a_npc)
		{
			auto* player = Player();
			auto* base = a_npc ? a_npc->GetActorBase() : nullptr;
			if (!player || !base) {
				return "";
			}
			std::string names;
			for (auto& [obj, data] : player->GetInventory()) {
				auto& entry = data.second;
				if (!entry || !entry->IsWorn() || entry->GetOwner() != base) {
					continue;
				}
				const char* name = entry->GetDisplayName();
				if (!name || !*name) {
					continue;
				}
				if (!names.empty()) {
					names += ", ";
				}
				names += name;
			}
			return names;
		}
	}

	void Register()
	{
		auto* holder = RE::ScriptEventSourceHolder::GetSingleton();
		auto* ui = RE::UI::GetSingleton();
		if (!holder || !ui) {
			logger::error("event sources missing; personal events not registered");
			return;
		}
		static Sink<RE::TESDeathEvent> death([](const RE::TESDeathEvent& e) {
			OnPartyDeathEvent(e);
			if (e.dead) {
				auto*            victim = e.actorDying ? e.actorDying->As<RE::Actor>() : nullptr;
				auto*            player = Player();
				const bool       hostile = !victim || !player || victim->IsHostileToActor(player);
				const bool       ally = victim && (victim->IsPlayerTeammate() || victim->IsCommandedActor());
				auto*            crime = victim ? victim->GetCrimeFaction() : nullptr;
				const RE::FormID crimeID = crime ? crime->GetFormID() : 0;
				Task([dying = e.actorDying, killer = e.actorKiller, hostile, ally, crimeID]() { OnDeath(dying, killer, hostile, ally, crimeID); });
			}
		});
		static Sink<RE::TESHitEvent> hit([](const RE::TESHitEvent& e) {
			OnPartyHitEvent(e);
			auto* player = Player();
			auto* actor = e.target ? e.target->As<RE::Actor>() : nullptr;
			if (!actor || !e.cause || e.cause.get() != player || actor->IsPlayerTeammate() || actor->IsCommandedActor()) {
				return;  // the party's own get friendly fire instead
			}
			const bool hostile = actor->IsHostileToActor(player);
			Task([target = e.target, source = e.source, hostile]() { OnHit(target, source, hostile); });
		});
		static Sink<RE::TESMagicEffectApplyEvent> magic(OnMagicEffectEvent);
		static Sink<RE::TESEnterBleedoutEvent>    bleedout(OnBleedoutEvent);
		static Sink<RE::TESActivateEvent> activate([](const RE::TESActivateEvent& e) {
			// The sleep state is read right away: the activation is what wakes them.
			if (e.actionRef && e.actionRef.get() == Player()) {
				OnActivate(e.objectActivated, e.actionRef);
			}
		});
		static Sink<RE::TESContainerChangedEvent> moved([](const RE::TESContainerChangedEvent& e) {
			auto*        player = Player();
			RE::TESForm* owner = player && e.newContainer == player->GetFormID() ? OwnerOfTake(e.oldContainer, e.reference) : nullptr;
			Task([from = e.oldContainer, to = e.newContainer, base = e.baseObj, count = e.itemCount, owner]() { OnMoved(from, to, base, count, owner); });
		});
		static Sink<RE::MenuOpenCloseEvent> menu([](const RE::MenuOpenCloseEvent& e) {
			std::string name(e.menuName.c_str());
			if (name == RE::LoadingMenu::MENU_NAME && e.opening) {
				Writer::Clear();  // a loading screen leaves the place behind: what was said there is not "nearby" any more
			}
			if (name == RE::ContainerMenu::MENU_NAME || name == RE::BarterMenu::MENU_NAME) {
				Task([name, opening = e.opening]() { OnMenu(name, opening); });
			}
		});
		holder->AddEventSink<RE::TESDeathEvent>(&death);
		holder->AddEventSink<RE::TESHitEvent>(&hit);
		holder->AddEventSink<RE::TESMagicEffectApplyEvent>(&magic);
		holder->AddEventSink<RE::TESEnterBleedoutEvent>(&bleedout);
		holder->AddEventSink<RE::TESActivateEvent>(&activate);
		holder->AddEventSink<RE::TESContainerChangedEvent>(&moved);
		ui->AddEventSink<RE::MenuOpenCloseEvent>(&menu);
		if (auto* data = RE::TESDataHandler::GetSingleton()) {
			for (auto* faction : data->GetFormArray<RE::TESFaction>()) {
				if (faction && (faction->data.flags & RE::FACTION_DATA::Flag::kTrackCrime)) {
					g_crimeFactions.push_back(faction);
				}
			}
		}
		PollCrime();
		logger::info("personal event listeners registered ({} crime factions)", g_crimeFactions.size());
	}

	void ResetFight()
	{
		++g_epoch;
		g_crimeTotal = -1.0f;  // the next save's bounty is not a rise
		g_lastTake = {};
		g_pickpocketTarget.reset();
		g_pickpocketUntil = {};
		g_barterTarget.reset();
		g_barterSold.clear();
		g_barterSpent = 0;
		g_barterEarned = 0;
		g_tradeTarget.reset();
		g_tradeGold = 0;
		g_assaulted.clear();
		g_crimeRoseInFight = false;
		g_lastHit.clear();
		g_repeat.clear();
		g_partyHits.clear();
		g_inFight = false;
		g_fighters.clear();
		g_defenders.clear();
		g_playerAttackers.clear();
		g_lastAttacker.clear();
		g_down.clear();
		g_playerLow = {};
		g_health.clear();
	}

	bool RegisterFunctions(RE::BSScript::IVirtualMachine* a_vm)
	{
		a_vm->RegisterFunction("WornStolenFrom", "MLWW_Native", WornStolenFrom);
		a_vm->RegisterFunction("Party", "MLWW_Native", Party);
		a_vm->RegisterFunction("ChestGold", "MLWW_Native", ChestGoldOf);
		return true;
	}
}
