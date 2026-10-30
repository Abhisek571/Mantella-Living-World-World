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

namespace MLWW::Personal
{
	namespace
	{
		constexpr auto kCrimePoll = 1s;
		constexpr auto kCaughtWindow = 3s;  // a bounty this soon after an owned take or a pickpocket means caught
		constexpr auto kHitRepeat = 60s;    // one "struck" per NPC per minute of real time

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

		void SendModEvent(const char* a_name, const std::string& a_text, float a_num, RE::TESForm* a_sender)
		{
			SKSE::ModCallbackEvent event{ a_name, a_text.c_str(), a_num, a_sender };
			SKSE::GetModCallbackEventSource()->SendEvent(&event);
		}

		RE::PlayerCharacter* Player() { return RE::PlayerCharacter::GetSingleton(); }

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

		std::int32_t ChestGold(RE::Actor* a_merchant)
		{
			auto* faction = a_merchant ? a_merchant->GetVendorFaction() : nullptr;
			auto* chest = faction ? faction->vendorData.merchantContainer : nullptr;
			if (!chest) {
				return -1;
			}
			std::int32_t gold = 0;
			for (auto& [obj, count] : chest->GetInventoryCounts([](RE::TESBoundObject& a_obj) { return a_obj.IsGold(); })) {
				gold += count;
			}
			return gold;
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
			const auto now = Clock::now();
			if (auto target = g_pickpocketTarget.get(); target && now < g_pickpocketUntil + kCaughtWindow) {
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

		void PollCrime()
		{
			Writer::RunLater(kCrimePoll, []() {
				SKSE::GetTaskInterface()->AddTask([]() { CheckCrime(); });
				PollCrime();  // re-armed from the worker thread, never from inside the task
			});
		}

		RE::Actor* LiveActor(RE::TESObjectREFR* a_ref)
		{
			auto* actor = a_ref ? a_ref->As<RE::Actor>() : nullptr;
			return actor && actor != Player() && !actor->IsDead() ? actor : nullptr;
		}

		void OnDeath(RE::NiPointer<RE::TESObjectREFR> a_dying, RE::NiPointer<RE::TESObjectREFR> a_killer)
		{
			auto* actor = a_dying ? a_dying->As<RE::Actor>() : nullptr;
			auto* base = actor ? actor->GetActorBase() : nullptr;
			if (!actor || actor == Player() || !base || !base->IsUnique()) {
				return;  // only named people have relatives who grieve
			}
			const bool byPlayer = a_killer && a_killer.get() == Player();
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
			const auto now = Clock::now();
			auto&      last = g_lastHit[actor->GetFormID()];
			if (now - last < kHitRepeat) {
				return;
			}
			last = now;
			SendModEvent("MLWW_Struck", "", 0.0f, actor);
			logger::info("struck {:08X}", actor->GetFormID());
		}

		void OnActivate(RE::NiPointer<RE::TESObjectREFR> a_target, RE::NiPointer<RE::TESObjectREFR> a_by)
		{
			if (!a_by || a_by.get() != Player()) {
				return;
			}
			auto* actor = LiveActor(a_target.get());
			if (actor && actor->AsActorState()->GetSitSleepState() == RE::SIT_SLEEP_STATE::kIsSleeping) {
				const auto* calendar = RE::Calendar::GetSingleton();
				const float hour = calendar ? calendar->GetHour() : 12.0f;
				SendModEvent("MLWW_Woken", "", hour, actor);
				logger::info("woke {:08X} at {:.1f}h", actor->GetFormID(), hour);
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
			if (a_from == player->GetFormID() && a_to != player->GetFormID()) {
				// A gift: into a living NPC's own inventory, not while bartering or reverse-pickpocketing.
				auto* actor = LiveActor(RE::TESForm::LookupByID<RE::TESObjectREFR>(a_to));
				auto* ui = RE::UI::GetSingleton();
				if (!actor || PickpocketActive() || (ui && ui->IsMenuOpen(RE::BarterMenu::MENU_NAME))) {
					return;
				}
				if (actor->IsPlayerTeammate() && !item->IsGold()) {
					return;  // followers carry things for the player; only gold to them is a gift
				}
				const char* name = item->GetName();
				SendModEvent("MLWW_Gift", name ? name : "", static_cast<float>(a_count), actor);
				logger::info("gift to {:08X}: {} x{}", actor->GetFormID(), name ? name : "", a_count);
				return;
			}
			if (a_to != player->GetFormID() || PickpocketActive()) {
				return;
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
				if (a_opening && RE::ContainerMenu::GetContainerMode() == RE::ContainerMenu::ContainerMode::kPickpocket) {
					auto target = RE::TESObjectREFR::LookupByHandle(RE::ContainerMenu::GetTargetRefHandle());
					auto* actor = target ? target->As<RE::Actor>() : nullptr;
					g_pickpocketTarget = actor ? actor->GetHandle() : RE::ActorHandle{};
					g_pickpocketUntil = Clock::time_point::max() - kCaughtWindow;
					logger::info("pickpocket menu on {:08X}", actor ? actor->GetFormID() : 0);
				} else if (!a_opening && g_pickpocketTarget) {
					g_pickpocketUntil = Clock::now();  // a failed pickpocket closes the menu; the bounty may land just after
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
				g_barterGold = player->GetGoldAmount();
				return;
			}
			auto merchant = g_barterTarget.get();
			g_barterTarget.reset();
			if (!merchant) {
				return;
			}
			const std::int32_t delta = player->GetGoldAmount() - g_barterGold;  // above 0: the player sold
			const std::int32_t chest = ChestGold(merchant.get());
			if (delta != 0) {
				SendModEvent("MLWW_Trade", std::to_string(chest), static_cast<float>(delta), merchant.get());
				logger::info("trade with {:08X}: player gold {:+d}, chest {}", merchant->GetFormID(), delta, chest);
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

		template <class F>
		void Task(F&& a_fn)
		{
			SKSE::GetTaskInterface()->AddTask(std::forward<F>(a_fn));
		}

		// Natives
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
			if (e.dead) {
				Task([dying = e.actorDying, killer = e.actorKiller]() { OnDeath(dying, killer); });
			}
		});
		static Sink<RE::TESHitEvent> hit([](const RE::TESHitEvent& e) {
			auto* player = Player();
			auto* actor = e.target ? e.target->As<RE::Actor>() : nullptr;
			if (!actor || !e.cause || e.cause.get() != player) {
				return;
			}
			const bool hostile = actor->IsHostileToActor(player);
			Task([target = e.target, source = e.source, hostile]() { OnHit(target, source, hostile); });
		});
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
			if (name == RE::ContainerMenu::MENU_NAME || name == RE::BarterMenu::MENU_NAME) {
				Task([name, opening = e.opening]() { OnMenu(name, opening); });
			}
		});
		holder->AddEventSink<RE::TESDeathEvent>(&death);
		holder->AddEventSink<RE::TESHitEvent>(&hit);
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

	bool RegisterFunctions(RE::BSScript::IVirtualMachine* a_vm)
	{
		a_vm->RegisterFunction("WornStolenFrom", "MLWW_Native", WornStolenFrom);
		return true;
	}
}
