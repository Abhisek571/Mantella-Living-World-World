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

#include "Battle.h"

#include "Personal.h"
#include "Writer.h"

#include <atomic>
#include <cmath>
#include <map>

namespace MLWW::Battle
{
	namespace
	{
		using Clock = std::chrono::steady_clock;

		constexpr auto  kQuiet = 5s;          // nobody in combat and no blows for this long ends a fight
		constexpr auto  kRecheck = 300ms;     // health is read again this long after a blow lands
		constexpr auto  kBlowBlame = 3s;      // health lost this soon after a blow is that blow's
		constexpr auto  kOverTimeBlame = 10s; // health lost later, after harmful magic, is that caster's
		constexpr auto  kDangerWindow = 15s;  // a rescue lands this soon after someone went down or below kLow
		constexpr auto  kLiveWrite = 5s;      // a fight in progress is written at most this often
		constexpr auto  kCastWindow = 5s;     // the player's harmful magic counts only this soon after a cast of it
		constexpr std::size_t kMaxCasts = 16;
		constexpr float kLow = 0.15f;
		constexpr float kRange = 8192.0f;       // further from the player than this is another fight
		constexpr float kBystanderRange = 3072.0f;
		constexpr std::size_t kMaxFighters = 40;
		constexpr std::size_t kMaxBystanders = 10;
		constexpr std::size_t kMaxKept = 6;
		constexpr double      kKeepDays = 3.0;  // ended fights stay this long so the Hub can still remember them
		constexpr std::string_view kPlugin = "Mantella Living World - World.esp";
		const std::filesystem::path kFile{ L"Data/SKSE/Plugins/StorageUtilData/MantellaLivingWorld/battles.json" };

		enum class Role
		{
			kPlayer,
			kParty,
			kAlly,
			kEnemy,
			kSummon,
			kBystander
		};

		struct Fighter
		{
			RE::ActorHandle   handle;
			RE::FormID        id{ 0 };
			std::string       name;
			std::string       ref;
			std::string       base;
			int               side{ 0 };  // 0 the player's side, 1 against the player
			Role              role{ Role::kAlly };
			RE::FormID        owner{ 0 };  // a summon's summoner
			bool              unique{ false };
			bool              dragon{ false };
			bool              hostile{ false };  // hostile to the player at some point
			bool              struck{ false };   // landed a blow on the other side (the player: a real attack, PlayerBlow)
			bool              byPlayer{ false }; // the player landed a real blow or cast real harm on them: a kill may be his
			bool              helped{ false };   // cast a helping spell on a fighter
			float             last{ -1.0f };     // health at the last read
			float             lowest{ 1.0f };    // lowest health fraction seen
			float             now{ 1.0f };       // health fraction at the last read
			float             dealt{ 0.0f };     // health they took from the other side
			float             taken{ 0.0f };
			bool              low{ false };
			bool              down{ false };
			bool              dead{ false };
			bool              recheck{ false };
			RE::FormID        killer{ 0 };
			RE::FormID        lastHitter{ 0 };
			Clock::time_point lastHitAt{};
			RE::FormID        overTime{ 0 };
			Clock::time_point overTimeAt{};
			RE::FormID        dangerBy{ 0 };
			Clock::time_point dangerUntil{};
			std::vector<std::pair<RE::FormID, std::string>> rescuedBy;
			std::map<std::string, std::vector<RE::FormID>>   harm;
			std::map<std::string, std::vector<RE::FormID>>   help;
			std::vector<RE::FormID>                          kills;
		};

		struct Fight
		{
			bool                active{ false };
			bool                dirty{ false };
			std::uint64_t       id{ 0 };
			double              start{ 0.0 };
			float               seconds{ 0.0f };  // unpaused time
			std::string         place;
			Clock::time_point   lastActivity{};
			Clock::time_point   lastTick{};
			Clock::time_point   lastWrite{};
			std::deque<Fighter> fighters;  // a deque: adding one keeps references to the others valid
		};

		// Main thread only.
		Fight                      g_fight;
		std::deque<nlohmann::json> g_ended;  // newest first
		bool                       g_prune = false;
		bool                       g_gameLoaded = false;  // a game was loaded or started this session (Reset)
		// A fight just ended while the player is still flagged in combat: the flag alone does not start the next one
		// (it can stick with no foe around); a blow, a kill, a hostile combatant or leaving combat does.
		bool                       g_waitNew = false;
		RE::FormID                 g_onID = 0;
		RE::FormID                 g_bystandersID = 0;
		RE::FormID                 g_hoursID = 0;
		std::atomic<std::uint32_t> g_epoch{ 0 };
		std::atomic<bool>          g_live{ false };  // a fight is going on: what the sinks may read
		// Spells (or scrolls, staffs) the player cast lately, newest last, with when (main thread only).
		std::deque<std::pair<RE::FormID, Clock::time_point>> g_playerCasts;
		// Real blows the player landed lately on someone already dead (a one-shot kill), by target, with when (main thread).
		std::deque<std::pair<RE::FormID, Clock::time_point>> g_playerBlows;

		template <class F>
		void Task(F&& a_fn, std::uint32_t a_epoch = g_epoch.load())
		{
			SKSE::GetTaskInterface()->AddTask([a_epoch, fn = std::forward<F>(a_fn)]() {
				if (a_epoch == g_epoch.load()) {
					fn();
				}
			});
		}

		RE::PlayerCharacter* Player() { return RE::PlayerCharacter::GetSingleton(); }

		float Setting(RE::FormID a_id, float a_default)
		{
			auto* global = a_id ? RE::TESForm::LookupByID<RE::TESGlobal>(a_id) : nullptr;
			return global ? global->value : a_default;
		}
		bool   On() { return Setting(g_onID, 1.0f) != 0.0f; }
		bool   WithBystanders() { return Setting(g_bystandersID, 0.0f) != 0.0f; }
		double KeepHours() { return std::clamp(static_cast<double>(Setting(g_hoursID, 6.0f)), 1.0, 72.0); }

		double Today()
		{
			const auto* calendar = RE::Calendar::GetSingleton();
			return calendar ? static_cast<double>(calendar->GetDaysPassed()) : 0.0;
		}

		std::string Hex(RE::FormID a_id, int a_digits)
		{
			const auto text = std::format("{:08X}", a_id);
			return text.substr(text.size() - a_digits);
		}

		std::string NameOf(RE::Actor* a_actor)
		{
			const char* name = a_actor->GetDisplayFullName();
			return name && *name ? name : "someone";
		}

		// "" (never "someone") when there is no name yet: the Hub reads this file's player as the current character.
		std::string PlayerName()
		{
			auto*       player = Player();
			const char* name = player ? player->GetDisplayFullName() : nullptr;
			return name ? name : "";
		}

		float Health(RE::Actor* a_actor) { return a_actor->AsActorValueOwner()->GetActorValue(RE::ActorValue::kHealth); }

		Fighter* Find(RE::FormID a_id)
		{
			for (auto& f : g_fight.fighters) {
				if (f.id == a_id) {
					return &f;
				}
			}
			return nullptr;
		}

		// The player, a party member, or a summon of either.
		bool PlayerSide(RE::Actor* a_actor)
		{
			if (!a_actor) {
				return false;
			}
			if (a_actor == Player() || Personal::InParty(a_actor)) {
				return true;
			}
			auto commander = a_actor->IsCommandedActor() ? a_actor->GetCommandingActor() : RE::NiPointer<RE::Actor>{};
			return commander && (commander.get() == Player() || Personal::InParty(commander.get()));
		}

		bool Near(RE::Actor* a_actor)
		{
			auto* player = Player();
			return player && a_actor->GetPosition().GetDistance(player->GetPosition()) <= kRange;
		}

		// Adds a_actor to the fight. a_side is the side it is on when nothing else says (the other side of whoever
		// it struck or was struck by). nullptr when the fight is full or the actor is too far away.
		Fighter* Join(RE::Actor* a_actor, int a_side)
		{
			if (!a_actor) {
				return nullptr;
			}
			if (auto* known = Find(a_actor->GetFormID())) {
				return known;
			}
			auto* player = Player();
			const bool isPlayer = a_actor == player;
			const bool party = !isPlayer && Personal::InParty(a_actor);
			if (!isPlayer && !party && (g_fight.fighters.size() >= kMaxFighters || !Near(a_actor))) {
				return nullptr;
			}
			Fighter f;
			f.handle = a_actor->GetHandle();
			f.id = a_actor->GetFormID();
			f.name = NameOf(a_actor);
			f.ref = Hex(f.id, 8);
			auto* base = a_actor->GetActorBase();
			f.base = base ? Hex(base->GetFormID(), 6) : std::string{};
			f.unique = base && base->IsUnique();
			f.dragon = a_actor->HasKeywordString("ActorTypeDragon");
			f.hostile = !isPlayer && player && a_actor->IsHostileToActor(player);
			auto commander = a_actor->IsCommandedActor() ? a_actor->GetCommandingActor() : RE::NiPointer<RE::Actor>{};
			if (isPlayer) {
				f.role = Role::kPlayer;
				f.side = 0;
			} else if (party) {
				f.role = Role::kParty;
				f.side = 0;
			} else if (commander) {
				f.role = Role::kSummon;
				f.owner = commander->GetFormID();
				auto* owner = Find(f.owner);
				f.side = PlayerSide(commander.get()) ? 0 : owner ? owner->side : f.hostile ? 1 : a_side;
			} else if (f.hostile) {
				f.role = Role::kEnemy;
				f.side = 1;
			} else {
				f.side = a_side;
				f.role = a_side == 0 ? Role::kAlly : Role::kEnemy;
			}
			const float most = a_actor->GetActorValueMax(RE::ActorValue::kHealth);
			f.last = Health(a_actor);
			f.now = f.lowest = most > 0.0f ? std::clamp(f.last / most, 0.0f, 1.0f) : 1.0f;
			f.dead = a_actor->IsDead();
			g_fight.fighters.push_back(std::move(f));
			g_fight.dirty = true;
			return &g_fight.fighters.back();
		}

		void Begin()
		{
			auto* player = Player();
			g_fight = {};
			g_fight.active = true;
			g_waitNew = false;
			g_live = true;
			g_fight.id = static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count());
			g_fight.start = Today();
			g_fight.lastActivity = g_fight.lastTick = Clock::now();
			if (player) {
				auto* location = player->GetCurrentLocation();
				const char* place = location ? location->GetName() : nullptr;
				if ((!place || !*place) && player->GetParentCell()) {
					place = player->GetParentCell()->GetFullName();
				}
				g_fight.place = place ? place : "";
				Join(player, 0);
			}
			for (auto* member : Personal::PartyHere()) {
				Join(member, 0);
			}
		}

		void Danger(Fighter& a_f, RE::FormID a_by)
		{
			if (a_by) {
				a_f.dangerBy = a_by;
			}
			a_f.dangerUntil = Clock::now() + kDangerWindow;
		}

		// Who the health a fighter just lost is put down to: the last blow, else harmful magic over time.
		RE::FormID Blame(const Fighter& a_f, Clock::time_point a_now)
		{
			if (a_f.lastHitter && a_now - a_f.lastHitAt <= kBlowBlame) {
				return a_f.lastHitter;
			}
			if (a_f.overTime && a_now - a_f.overTimeAt <= kOverTimeBlame) {
				return a_f.overTime;
			}
			return 0;
		}

		void Lost(Fighter& a_f, float a_amount, RE::FormID a_by)
		{
			a_f.taken += a_amount;
			if (auto* by = a_by ? Find(a_by) : nullptr; by && by->side != a_f.side) {
				by->dealt += a_amount;
			}
			g_fight.dirty = true;
		}

		// a_f died: a_blow landed the final blow, a_credit gets the kill (a summon's summoner). Either may be null.
		// Only Find()s, never Join()s, so it is safe while walking g_fight.fighters.
		void MarkDead(Fighter& a_f, Fighter* a_credit, Fighter* a_blow, Clock::time_point a_now)
		{
			a_f.dead = true;
			if (a_f.last > 0.0f) {
				Lost(a_f, a_f.last, a_blow ? a_blow->id : 0);  // the final blow, which no later read sees
			}
			a_f.last = 0.0f;
			a_f.now = a_f.lowest = 0.0f;
			g_fight.lastActivity = a_now;
			g_fight.dirty = true;
			if (!a_credit || a_credit == &a_f) {
				return;
			}
			a_f.killer = a_credit->id;
			if (a_credit->side != a_f.side) {
				a_credit->kills.push_back(a_f.id);
			}
			// Killing whoever put someone in danger, while they still are: a rescue.
			for (auto& f : g_fight.fighters) {
				if (&f != a_credit && !f.dead && f.side == a_credit->side && f.dangerBy == a_f.id && a_now <= f.dangerUntil) {
					f.rescuedBy.emplace_back(a_credit->id, "kill");  // danger_by stays: the account names who was killed
				}
			}
		}

		void ReadHealth(Fighter& a_f)
		{
			auto actor = a_f.handle.get();
			if (!actor || a_f.dead) {
				return;
			}
			const auto now = Clock::now();
			if (actor->IsDead()) {
				// Died with no death event seen: far away, or the console "kill" (no killer, health untouched).
				Fighter* blow = a_f.lastHitter && now - a_f.lastHitAt <= kBlowBlame ? Find(a_f.lastHitter) : nullptr;
				Fighter* credit = blow && blow->role == Role::kSummon && blow->owner ? Find(blow->owner) : nullptr;
				MarkDead(a_f, credit ? credit : blow, blow, now);
				return;
			}
			const float health = Health(actor.get());
			const float most = actor->GetActorValueMax(RE::ActorValue::kHealth);
			if (a_f.last >= 0.0f && health < a_f.last - 0.5f) {
				Lost(a_f, a_f.last - health, Blame(a_f, now));
			}
			a_f.last = health;
			a_f.now = most > 0.0f ? std::clamp(health / most, 0.0f, 1.0f) : 1.0f;
			a_f.lowest = std::min(a_f.lowest, a_f.now);
			if (a_f.now < kLow && !a_f.low) {
				a_f.low = true;
				Danger(a_f, Blame(a_f, now));
			}
		}

		void Recheck(RE::ActorHandle a_who)
		{
			auto who = a_who.get();
			if (!who) {
				return;
			}
			if (auto* f = Find(who->GetFormID())) {
				f->recheck = false;
				ReadHealth(*f);
			}
		}

		void QueueRecheck(Fighter& a_f)
		{
			if (a_f.recheck) {
				return;
			}
			a_f.recheck = true;
			Writer::RunLater(kRecheck, [who = a_f.handle, epoch = g_epoch.load()]() {
				Task([=]() { Recheck(who); }, epoch);
			});
		}

		bool PlayerBlow(RE::FormID a_source, bool a_swinging, Clock::time_point a_now);  // below, beside PlayerCast
		bool PlayerStruck(RE::FormID a_victim, const Fighter* a_fv, Clock::time_point a_now);

		void OnHitTask(RE::ActorHandle a_target, RE::ActorHandle a_cause, RE::FormID a_source, bool a_swinging)
		{
			auto target = a_target.get();
			auto cause = a_cause.get();
			if (!target || !cause || target == cause || !On()) {
				return;
			}
			const bool byPlayer = cause->IsPlayerRef();
			if (byPlayer && !PlayerBlow(a_source, a_swinging, Clock::now())) {
				return;  // a cloak, aura or other passive hit of the player's is no attack: no blow, no blame, no fight
			}
			Fighter* ft = g_fight.active ? Find(target->GetFormID()) : nullptr;
			Fighter* fc = g_fight.active ? Find(cause->GetFormID()) : nullptr;
			if (!ft && !fc) {
				// Only a blow by or on the player's side starts a fight or brings two strangers into one.
				if (!PlayerSide(cause.get()) && !PlayerSide(target.get())) {
					return;
				}
				if (!g_fight.active) {
					Begin();
				}
				ft = Find(target->GetFormID());
				fc = Find(cause->GetFormID());
			}
			if (!fc) {
				fc = Join(cause.get(), ft ? 1 - ft->side : 1);
			}
			if (!ft) {
				ft = Join(target.get(), fc ? 1 - fc->side : 1);
			}
			if (!fc || !ft) {
				return;
			}
			const auto now = Clock::now();
			if (fc->side != ft->side) {
				fc->struck = true;
			}
			if (byPlayer) {
				ft->byPlayer = true;
			}
			if (auto* player = Player(); ft->side == 1 && !ft->hostile && player) {
				ft->hostile = target->IsHostileToActor(player);
			}
			ft->lastHitter = fc->id;
			ft->lastHitAt = now;
			g_fight.lastActivity = now;
			g_fight.dirty = true;
			QueueRecheck(*ft);
		}

		void OnBleedoutTask(RE::ActorHandle a_who)
		{
			auto who = a_who.get();
			if (!who || !g_fight.active) {
				return;
			}
			if (auto* f = Find(who->GetFormID())) {
				ReadHealth(*f);
				f->down = true;
				f->lowest = 0.0f;
				Danger(*f, Blame(*f, Clock::now()));
				g_fight.lastActivity = Clock::now();
				g_fight.dirty = true;
			}
		}

		void NotePlayerBlow(RE::ActorHandle a_target, RE::FormID a_source, bool a_swinging)
		{
			auto       target = a_target.get();
			const auto now = Clock::now();
			if (!target || !PlayerBlow(a_source, a_swinging, now)) {
				return;
			}
			g_playerBlows.emplace_back(target->GetFormID(), now);
			while (g_playerBlows.size() > kMaxCasts) {
				g_playerBlows.pop_front();
			}
		}

		// a_killer is who landed the blow; the kill is credited to its summoner when a summon did it. A kill the game gives
		// the player himself is his only after a real attack of his on the victim (PlayerStruck); without one it is looked
		// at again a moment later (the blow that killed can be reported after the death), then the killer stays unknown.
		void OnDeathTask(RE::ActorHandle a_victim, RE::ActorHandle a_killer, bool a_late = false)
		{
			auto victim = a_victim.get();
			auto killer = a_killer.get();
			if (!victim || !On()) {
				return;
			}
			if (killer && killer->IsPlayerRef()) {
				Fighter* known = g_fight.active ? Find(victim->GetFormID()) : nullptr;
				if (known && known->dead) {
					return;  // already counted
				}
				if (!PlayerStruck(victim->GetFormID(), known, Clock::now())) {
					if (!a_late) {
						Writer::RunLater(kRecheck, [a_victim, a_killer, epoch = g_epoch.load()]() {
							Task([=]() { OnDeathTask(a_victim, a_killer, true); }, epoch);
						});
						return;
					}
					killer = nullptr;  // no attack of his on them: the kill is nobody's, not his
				}
			}
			RE::NiPointer<RE::Actor> credit = killer && killer->IsCommandedActor() ? killer->GetCommandingActor() : killer;
			if (!credit) {
				credit = killer;  // a summon whose summoner is gone
			}
			Fighter* fv = g_fight.active ? Find(victim->GetFormID()) : nullptr;
			if (fv && fv->dead) {
				return;  // already counted: the dying and the dead event both come, or a read saw it first
			}
			if (!fv) {
				// Someone the player's side killed outright, before any blow was seen.
				if (!credit || !PlayerSide(credit.get())) {
					return;
				}
				if (!g_fight.active) {
					Begin();
				}
				fv = Join(victim.get(), 1);
				if (!fv) {
					return;
				}
			}
			Fighter* fk = credit ? Join(credit.get(), 1 - fv->side) : nullptr;
			Fighter* blow = killer && killer != credit ? Join(killer.get(), 1 - fv->side) : fk;
			MarkDead(*fv, fk, blow, Clock::now());
		}

		// "" for an effect the account does not name.
		std::string HarmKind(const RE::EffectSetting* a_effect)
		{
			using Archetype = RE::EffectSetting::Archetype;
			const auto av = a_effect->data.primaryAV;
			if (a_effect->HasArchetype(Archetype::kParalysis)) {
				return "paralysis";
			}
			if (av == RE::ActorValue::kSpeedMult) {
				return "slow";
			}
			switch (a_effect->data.resistVariable) {
			case RE::ActorValue::kResistFire:
				return "fire";
			case RE::ActorValue::kResistFrost:
				return "frost";
			case RE::ActorValue::kResistShock:
				return "shock";
			case RE::ActorValue::kPoisonResist:
				return "poison";
			default:
				break;
			}
			if (a_effect->HasArchetype(Archetype::kAbsorb) ||
				((av == RE::ActorValue::kMagicka || av == RE::ActorValue::kStamina) &&
					(a_effect->HasArchetype(Archetype::kValueModifier) || a_effect->HasArchetype(Archetype::kDualValueModifier)))) {
				return "drain";
			}
			return "";
		}

		std::string HelpKind(const RE::EffectSetting* a_effect)
		{
			using Archetype = RE::EffectSetting::Archetype;
			const auto av = a_effect->data.primaryAV;
			if (av == RE::ActorValue::kHealth && (a_effect->HasArchetype(Archetype::kValueModifier) || a_effect->HasArchetype(Archetype::kDualValueModifier))) {
				return "healing";
			}
			if (av == RE::ActorValue::kWardPower) {
				return "ward";
			}
			if (av == RE::ActorValue::kDamageResist) {
				return "armor";
			}
			return "";
		}

		// A spell the actor really cast: not an ability, a constant effect, an enchantment (worn or on a weapon), a disease
		// or an addiction, and sent from a hand or the voice, not instantly (a cloak or aura applies its effect instantly,
		// as a script's Cast does).
		bool IsCast(const RE::ActiveEffect& a_active)
		{
			const auto* spell = a_active.spell;
			if (!spell) {
				return false;
			}
			using Type = RE::MagicSystem::SpellType;
			switch (spell->GetSpellType()) {
			case Type::kAbility:
			case Type::kEnchantment:
			case Type::kDisease:
			case Type::kAddiction:
				return false;
			default:
				break;
			}
			if (spell->GetCastingType() == RE::MagicSystem::CastingType::kConstantEffect) {
				return false;
			}
			return a_active.castingSource != RE::MagicSystem::CastingSource::kInstant;
		}

		// Whether this harmful effect on the target came from a cast by the caster. Live test 8: an aura, ability or
		// enchantment on the player that drains or slows was recorded as the player casting drain and slow magic on his
		// own follower. Only the active effect knows its spell; none left (an instant hit already over) counts as a cast.
		bool FromCast(RE::Actor* a_target, RE::Actor* a_caster, const RE::EffectSetting* a_effect)
		{
			auto* magic = a_target->AsMagicTarget();
			auto* list = magic ? magic->GetActiveEffectList() : nullptr;
			if (!list) {
				return true;
			}
			bool seen = false;
			for (auto* active : *list) {
				if (!active || active->GetBaseObject() != a_effect || active->caster.get().get() != a_caster) {
					continue;
				}
				if (IsCast(*active)) {
					return true;
				}
				seen = true;
			}
			return !seen;
		}

		// Whether the player cast something carrying this effect within kCastWindow. Live test 9: drain and slow put down
		// to the player on a follower and the wolf with no cast seen; the effect had no active effect left to check (an instant
		// one, or one whose conditions kept it off), which FromCast counts as a cast. A match keeps the cast fresh, so a
		// concentration spell held longer than the window still counts.
		bool PlayerCast(const RE::EffectSetting* a_effect, Clock::time_point a_now)
		{
			std::erase_if(g_playerCasts, [&](const auto& a_cast) { return a_now - a_cast.second > kCastWindow; });
			for (auto& [id, at] : g_playerCasts) {
				const auto* item = RE::TESForm::LookupByID<RE::MagicItem>(id);
				if (item && std::ranges::any_of(item->effects, [&](const RE::Effect* a_e) { return a_e && a_e->baseEffect == a_effect; })) {
					at = a_now;
					return true;
				}
			}
			return false;
		}

		// Whether a hit by the player is a real attack: its source is a weapon (fists are the bare-hand weapon), a spell,
		// scroll or staff carrying an effect of something he cast just before (PlayerCast), or, with no source named, his
		// melee swing is under way. Live test 10: the player was put down for 23 damage and the kill in three fights he
		// never joined; a cloak or aura on him hits with its own spell, which is none of these.
		bool PlayerBlow(RE::FormID a_source, bool a_swinging, Clock::time_point a_now)
		{
			auto* form = a_source ? RE::TESForm::LookupByID(a_source) : nullptr;
			if (!form) {
				return a_swinging;
			}
			if (form->Is(RE::FormType::Weapon)) {
				return true;
			}
			auto* item = form->As<RE::MagicItem>();
			return item && std::ranges::any_of(item->effects, [&](const RE::Effect* a_e) { return a_e && a_e->baseEffect && PlayerCast(a_e->baseEffect, a_now); });
		}

		// Whether the kill of a_victim can be the player's: a real blow or real harm of his landed on them in this fight,
		// or a real blow just before they died (a one-shot kill, seen after the death).
		bool PlayerStruck(RE::FormID a_victim, const Fighter* a_fv, Clock::time_point a_now)
		{
			if (a_fv && a_fv->byPlayer) {
				return true;
			}
			return std::ranges::any_of(g_playerBlows, [&](const auto& a_blow) { return a_blow.first == a_victim && a_now - a_blow.second <= kCastWindow; });
		}

		void AddOnce(std::vector<RE::FormID>& a_list, RE::FormID a_id)
		{
			if (std::ranges::find(a_list, a_id) == a_list.end()) {
				a_list.push_back(a_id);
			}
		}

		void OnMagicTask(RE::ActorHandle a_target, RE::ActorHandle a_caster, RE::FormID a_effect)
		{
			auto target = a_target.get();
			auto caster = a_caster.get();
			auto* effect = RE::TESForm::LookupByID<RE::EffectSetting>(a_effect);
			if (!target || !caster || !effect || !g_fight.active) {
				return;  // magic outside a fight (a heal in town) is no fight
			}
			Fighter* ft = Find(target->GetFormID());
			if (!ft || ft->dead || target->IsDead()) {
				return;  // an aura or cloak still touching a body is no fighting: it must not keep the fight open
			}
			const bool harmful = effect->IsHostile() || effect->IsDetrimental();
			const auto kind = harmful ? HarmKind(effect) : HelpKind(effect);
			if (kind.empty() || (harmful && !FromCast(target.get(), caster.get(), effect))) {
				return;  // harm from an ability, a constant effect, an enchantment or an aura is nobody's cast
			}
			const auto now = Clock::now();
			if (harmful && caster->IsPlayerRef() && !PlayerCast(effect, now)) {
				return;  // the player's harm counts only with a cast of it seen just before (a perk or passive is no cast)
			}
			Fighter* fc = Join(caster.get(), harmful ? 1 - ft->side : ft->side);
			if (!fc) {
				return;
			}
			if (harmful) {
				if (caster->IsPlayerRef()) {
					ft->byPlayer = true;  // passed PlayerCast above: a kill of them can be his
				}
				AddOnce(ft->harm[kind], fc->id);
				ft->overTime = fc->id;
				ft->overTimeAt = now;
				g_fight.lastActivity = now;
			} else {
				fc->helped = true;
				AddOnce(ft->help[kind], fc->id);
				const bool inDanger = ft->down || now <= ft->dangerUntil || target->AsActorState()->IsBleedingOut();
				const bool known = std::ranges::any_of(ft->rescuedBy, [&](const auto& a_r) { return a_r.first == fc->id; });
				if (kind == "healing" && inDanger && !known) {
					ft->rescuedBy.emplace_back(fc->id, "heal");
				}
			}
			g_fight.dirty = true;
		}

		const char* RoleName(Role a_role)
		{
			switch (a_role) {
			case Role::kPlayer:
				return "player";
			case Role::kParty:
				return "party";
			case Role::kEnemy:
				return "enemy";
			case Role::kSummon:
				return "summon";
			case Role::kBystander:
				return "bystander";
			default:
				return "ally";
			}
		}

		// Someone on the player's side who neither struck nor helped anyone: caught in the fight, not in it.
		bool IsBystander(const Fighter& a_f)
		{
			return a_f.role == Role::kBystander || (a_f.role == Role::kAlly && !a_f.struck && !a_f.helped);
		}

		nlohmann::json RefList(const std::vector<RE::FormID>& a_ids)
		{
			auto out = nlohmann::json::array();
			for (auto id : a_ids) {
				if (auto* f = Find(id)) {
					out.push_back(f->ref);
				}
			}
			return out;
		}

		nlohmann::json ToJson(double a_end)
		{
			const bool bystanders = WithBystanders();
			// "player": whose game the fight is from, so Prune drops it after another character's save is loaded
			nlohmann::json fight{ { "id", std::to_string(g_fight.id) }, { "active", g_fight.active ? 1 : 0 }, { "start", g_fight.start },
				{ "end", a_end }, { "seconds", static_cast<int>(g_fight.seconds + 0.5f) }, { "place", g_fight.place }, { "player", PlayerName() } };
			auto fighters = nlohmann::json::array();
			for (const auto& f : g_fight.fighters) {
				const bool bystander = IsBystander(f);
				if (bystander && !bystanders) {
					continue;
				}
				nlohmann::json j{ { "name", f.name }, { "ref_id", f.ref }, { "base_id", f.base }, { "role", bystander ? "bystander" : RoleName(f.role) },
					{ "side", f.side }, { "unique", f.unique ? 1 : 0 }, { "dragon", f.dragon ? 1 : 0 }, { "hostile", f.hostile ? 1 : 0 },
					{ "lowest", std::round(f.lowest * 100.0f) / 100.0f }, { "health", std::round(f.now * 100.0f) / 100.0f },
					{ "dealt", static_cast<int>(f.dealt + 0.5f) }, { "taken", static_cast<int>(f.taken + 0.5f) }, { "down", f.down ? 1 : 0 },
					{ "dead", f.dead ? 1 : 0 }, { "struck", f.struck ? 1 : 0 } };
				auto* owner = f.owner ? Find(f.owner) : nullptr;
				j["owner"] = owner ? owner->ref : "";
				auto* killer = f.killer ? Find(f.killer) : nullptr;
				j["killer"] = killer ? killer->ref : "";
				auto* danger = f.dangerBy ? Find(f.dangerBy) : nullptr;
				j["danger_by"] = danger ? danger->ref : "";
				auto rescued = nlohmann::json::array();
				for (const auto& [id, how] : f.rescuedBy) {
					if (auto* by = Find(id)) {
						rescued.push_back({ { "ref", by->ref }, { "how", how } });
					}
				}
				j["rescued_by"] = std::move(rescued);
				j["harm"] = nlohmann::json::object();
				for (const auto& [kind, ids] : f.harm) {
					j["harm"][kind] = RefList(ids);
				}
				j["help"] = nlohmann::json::object();
				for (const auto& [kind, ids] : f.help) {
					j["help"][kind] = RefList(ids);
				}
				j["kills"] = RefList(f.kills);
				fighters.push_back(std::move(j));
			}
			fight["fighters"] = std::move(fighters);
			return fight;
		}

		bool InPrompt(const nlohmann::json& a_fight, double a_today)
		{
			return a_fight.value("end", 0.0) + KeepHours() / 24.0 >= a_today;
		}

		void Write()
		{
			const double today = Today();
			nlohmann::json root{ { "player", PlayerName() }, { "fights", nlohmann::json::array() } };
			if (g_fight.active) {
				auto live = ToJson(today);
				live["in_prompt"] = 1;
				root["fights"].push_back(std::move(live));
			}
			for (auto& fight : g_ended) {
				fight["in_prompt"] = InPrompt(fight, today) ? 1 : 0;
				root["fights"].push_back(fight);
			}
			g_fight.dirty = false;
			g_fight.lastWrite = Clock::now();
			Writer::Save(kFile, root.dump(-1, ' ', false, nlohmann::json::error_handler_t::replace));
		}

		// One look around when a fight ends: people close by who were not in it saw it.
		void AddBystanders()
		{
			auto* player = Player();
			auto* lists = RE::ProcessLists::GetSingleton();
			if (!player || !lists) {
				return;
			}
			const auto  here = player->GetPosition();
			std::size_t added = 0;
			lists->ForEachHighActor([&](RE::Actor* a_actor) {
				if (added >= kMaxBystanders) {
					return RE::BSContainer::ForEachResult::kStop;
				}
				if (a_actor && a_actor != player && !a_actor->IsDead() && a_actor->Is3DLoaded() && a_actor->HasKeywordString("ActorTypeNPC") &&
					!Find(a_actor->GetFormID()) && a_actor->GetPosition().GetDistance(here) <= kBystanderRange && !a_actor->IsHostileToActor(player)) {
					if (auto* f = Join(a_actor, 0)) {
						f->role = Role::kBystander;
						++added;
					}
				}
				return RE::BSContainer::ForEachResult::kContinue;
			});
		}

		void End()
		{
			for (auto& f : g_fight.fighters) {
				ReadHealth(f);
			}
			if (WithBystanders()) {
				AddBystanders();
			}
			// Hunting a deer or a quarrel nobody felt is no fight: an enemy must have been hostile, or the player's side hurt.
			const bool enemy = std::ranges::any_of(g_fight.fighters, [](const Fighter& f) { return f.side == 1 && f.role != Role::kSummon; });
			const bool real = std::ranges::any_of(g_fight.fighters, [](const Fighter& f) { return (f.side == 1 && f.hostile) || (f.side == 0 && f.taken > 0.0f); });
			// the file changes only when the fight is kept, or when its live account was written while it went on
			const bool written = (enemy && real) || g_fight.lastWrite != Clock::time_point{};
			if (enemy && real) {
				g_fight.active = false;
				g_ended.push_front(ToJson(Today()));
				while (g_ended.size() > kMaxKept) {
					g_ended.pop_back();
				}
				logger::info("fight ended: {} fighters, {} s", g_fight.fighters.size(), static_cast<int>(g_fight.seconds));
			}
			g_fight = {};
			g_live = false;
			g_waitNew = true;
			if (written) {
				Write();
			}
		}

		// An enemy in combat with the player's side and hostile to the player (a new foe while the combat flag stuck).
		bool HostileCombatant()
		{
			auto* player = Player();
			auto* lists = RE::ProcessLists::GetSingleton();
			if (!player || !lists) {
				return false;
			}
			bool found = false;
			lists->ForEachHighActor([&](RE::Actor* a_actor) {
				if (a_actor && a_actor->IsInCombat() && !a_actor->IsDead() && a_actor->IsHostileToActor(player)) {
					auto target = a_actor->GetActorRuntimeData().currentCombatTarget.get();
					if (target && PlayerSide(target.get())) {
						found = true;
						return RE::BSContainer::ForEachResult::kStop;
					}
				}
				return RE::BSContainer::ForEachResult::kContinue;
			});
			return found;
		}

		// Enemies fighting the player's side that have not struck or been struck yet (an archer who keeps missing).
		void AddCombatants()
		{
			auto* player = Player();
			auto* lists = RE::ProcessLists::GetSingleton();
			if (!player || !lists) {
				return;
			}
			lists->ForEachHighActor([&](RE::Actor* a_actor) {
				if (a_actor && a_actor->IsInCombat() && !a_actor->IsDead() && !Find(a_actor->GetFormID())) {
					auto target = a_actor->GetActorRuntimeData().currentCombatTarget.get();
					if (auto* side = target ? Find(target->GetFormID()) : nullptr) {
						Join(a_actor, 1 - side->side);
					}
				}
				return RE::BSContainer::ForEachResult::kContinue;
			});
		}

		void Prune()
		{
			if (auto* ui = RE::UI::GetSingleton(); ui && ui->IsMenuOpen(RE::LoadingMenu::MENU_NAME)) {
				return;  // the loaded game's clock is not there yet
			}
			g_prune = false;
			const double today = Today();
			const auto   player = PlayerName();
			std::erase_if(g_ended, [&](const nlohmann::json& a_fight) {
				return a_fight.value("end", 0.0) > today + 0.001 || a_fight.value("player", player) != player;
			});
			Write();
		}

		void LoadExisting()
		{
			std::error_code ec;
			if (!std::filesystem::exists(kFile, ec)) {
				return;
			}
			std::ifstream in(kFile, std::ios::binary);
			auto          root = nlohmann::json::parse(in, nullptr, false);
			if (root.is_discarded() || !root.is_object() || !root.contains("fights") || !root["fights"].is_array()) {
				return;
			}
			const auto player = root.value("player", std::string{});
			for (auto& fight : root["fights"]) {
				if (fight.is_object() && fight.value("active", 0) == 0 && g_ended.size() < kMaxKept) {
					if (!fight.contains("player") || !fight["player"].is_string()) {
						fight["player"] = player;  // checked against the loaded game's player by Prune
					}
					g_ended.push_back(fight);
				}
			}
		}
	}

	void Start()
	{
		if (auto* data = RE::TESDataHandler::GetSingleton()) {
			g_onID = data->LookupFormID(0x813, kPlugin);
			g_bystandersID = data->LookupFormID(0x814, kPlugin);
			g_hoursID = data->LookupFormID(0x815, kPlugin);
		}
		try {
			LoadExisting();
		} catch (...) {
			g_ended.clear();
		}
		logger::info("battle accounts ready (settings {}found, {} earlier fights)", g_onID ? "" : "not ", g_ended.size());
	}

	void Hit(const RE::TESHitEvent& a_event)
	{
		auto* target = a_event.target ? a_event.target->As<RE::Actor>() : nullptr;
		auto* cause = a_event.cause ? a_event.cause->As<RE::Actor>() : nullptr;
		if (!target || !cause || target == cause || !On() || (!Near(target) && !Near(cause))) {
			return;
		}
		// read at the blow: the player's melee swing still under way (a hit naming no weapon or spell)
		const auto state = cause->IsPlayerRef() ? cause->AsActorState()->GetAttackState() : RE::ATTACK_STATE_ENUM::kNone;
		const bool swinging = state >= RE::ATTACK_STATE_ENUM::kDraw && state <= RE::ATTACK_STATE_ENUM::kBash;
		if (target->IsDead()) {
			if (cause->IsPlayerRef()) {  // the player's one-shot kill: the blow can be reported after the death
				Task([targetHandle = target->GetHandle(), source = a_event.source, swinging]() { NotePlayerBlow(targetHandle, source, swinging); });
			}
			return;
		}
		Task([targetHandle = target->GetHandle(), causeHandle = cause->GetHandle(), source = a_event.source, swinging]() {
			OnHitTask(targetHandle, causeHandle, source, swinging);
		});
	}

	void Death(const RE::TESDeathEvent& a_event)
	{
		auto* victim = a_event.actorDying ? a_event.actorDying->As<RE::Actor>() : nullptr;
		auto* killer = a_event.actorKiller ? a_event.actorKiller->As<RE::Actor>() : nullptr;
		// Both the dying (dead == false) and the dead event are taken; the fighter's dead flag counts it once.
		// A fighter who dies out of range is caught by ReadHealth on the next tick.
		if (!victim || victim == Player() || !On() || !Near(victim)) {
			return;
		}
		Task([victimHandle = victim->GetHandle(), killerHandle = killer ? killer->GetHandle() : RE::ActorHandle{}]() { OnDeathTask(victimHandle, killerHandle); });
	}

	void Bleedout(const RE::TESEnterBleedoutEvent& a_event)
	{
		auto* actor = a_event.actor ? a_event.actor->As<RE::Actor>() : nullptr;
		if (actor && g_live && Near(actor)) {
			Task([who = actor->GetHandle()]() { OnBleedoutTask(who); });
		}
	}

	void Magic(const RE::TESMagicEffectApplyEvent& a_event)
	{
		auto* target = a_event.target ? a_event.target->As<RE::Actor>() : nullptr;
		auto* caster = a_event.caster ? a_event.caster->As<RE::Actor>() : nullptr;
		if (!target || !caster || target == caster || !g_live || !Near(target)) {
			return;  // no fight going on, a potion or a self spell, or far away
		}
		Task([targetHandle = target->GetHandle(), casterHandle = caster->GetHandle(), effect = a_event.magicEffect]() { OnMagicTask(targetHandle, casterHandle, effect); });
	}

	void Cast(const RE::TESSpellCastEvent& a_event)
	{
		auto* who = a_event.object.get();
		if (!who || who != Player() || !a_event.spell || !On()) {
			return;
		}
		Task([spell = a_event.spell]() {
			g_playerCasts.emplace_back(spell, Clock::now());
			while (g_playerCasts.size() > kMaxCasts) {
				g_playerCasts.pop_front();
			}
		});
	}

	void Tick()
	{
		auto* player = Player();
		if (!player || !g_gameLoaded) {
			return;  // the main menu at start-up: no clock and no player name of a loaded game yet
		}
		if (auto* ui = RE::UI::GetSingleton(); ui && ui->IsMenuOpen(RE::LoadingMenu::MENU_NAME)) {
			return;  // the loaded game's clock is not there yet
		}
		if (!On()) {
			if (g_fight.active || !g_ended.empty()) {
				g_fight = {};
				g_live = false;
				g_ended.clear();
				Write();
			}
			return;
		}
		if (g_prune) {
			Prune();
		}
		const auto now = Clock::now();
		if (!g_fight.active) {
			if (!player->IsInCombat()) {
				g_waitNew = false;
			} else if (!g_waitNew || HostileCombatant()) {
				Begin();
			}
		}
		if (g_fight.active) {
			if (auto* ui = RE::UI::GetSingleton(); ui && !ui->GameIsPaused()) {
				g_fight.seconds += std::min(2.0f, std::chrono::duration<float>(now - g_fight.lastTick).count());
			}
			g_fight.lastTick = now;
			bool fighting = player->IsInCombat();
			for (auto* member : Personal::PartyHere()) {
				if (member->IsInCombat()) {
					Join(member, 0);
					fighting = true;
				}
			}
			if (fighting) {
				AddCombatants();
			}
			for (auto& f : g_fight.fighters) {
				ReadHealth(f);
				if (auto actor = f.side == 1 && !f.hostile ? f.handle.get() : RE::NiPointer<RE::Actor>{}; actor && !f.dead) {
					f.hostile = actor->IsHostileToActor(player);
				}
			}
			// Being "in combat" only keeps the fight going while a foe is still standing: after a killing with nobody
			// left to fight, the combat flag can linger (or a follower keeps searching) and would hold it open for good.
			if (fighting && std::ranges::any_of(g_fight.fighters, [](const Fighter& a_f) { return a_f.side == 1 && !a_f.dead && a_f.hostile; })) {
				g_fight.lastActivity = now;
			}
			if (now - g_fight.lastActivity >= kQuiet) {
				End();
				return;
			}
			if (g_fight.dirty && now - g_fight.lastWrite >= kLiveWrite) {
				Write();
			}
			return;
		}
		// An account leaves the prompt after the hours set; the fight is forgotten after kKeepDays.
		const double today = Today();
		bool         changed = false;
		for (auto& fight : g_ended) {
			const int in = InPrompt(fight, today) ? 1 : 0;
			changed = changed || fight.value("in_prompt", -1) != in;
		}
		changed = std::erase_if(g_ended, [&](const nlohmann::json& a_fight) { return a_fight.value("end", 0.0) + kKeepDays < today; }) > 0 || changed;
		if (changed) {
			Write();
		}
	}

	void Reset(bool a_forget)
	{
		++g_epoch;
		g_fight = {};
		g_playerCasts.clear();
		g_playerBlows.clear();
		g_live = false;
		g_waitNew = false;
		if (a_forget) {
			g_ended.clear();
		}
		g_prune = true;
		g_gameLoaded = true;
	}
}
