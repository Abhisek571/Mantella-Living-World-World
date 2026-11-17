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

#include "Listener.h"

#include "Writer.h"

#include <map>

namespace MLWW::Listener
{
	namespace
	{
		constexpr float       kMaxDistance = 2048.0f;
		constexpr std::size_t kMinWords = 6;
		constexpr auto        kRepeatWindow = 10s;
		constexpr auto        kMantellaSubtitleDelay = 500ms;
		constexpr auto        kMantellaFile = "Mantella.esp"sv;

		struct LastLine
		{
			std::string                           text;
			std::chrono::steady_clock::time_point when;
			RE::FormID                            info{ 0 };  // the same line again is skipped before its text is built
		};

		// Main thread only (touched from SKSE tasks).
		std::unordered_map<RE::FormID, LastLine> g_lastBySpeaker;

		std::string Trim(std::string_view a_text)
		{
			const auto first = a_text.find_first_not_of(" \t\r\n");
			if (first == std::string_view::npos) {
				return {};
			}
			const auto last = a_text.find_last_not_of(" \t\r\n");
			return std::string(a_text.substr(first, last - first + 1));
		}

		std::size_t WordCount(std::string_view a_text)
		{
			std::size_t count = 0;
			bool        inWord = false;
			for (const char c : a_text) {
				const bool space = c == ' ' || c == '\t' || c == '\r' || c == '\n';
				if (!space && !inWord) {
					++count;
				}
				inWord = !space;
			}
			return count;
		}

		bool IsFromMantella(RE::TESTopicInfo* a_info)
		{
			const auto* file = a_info->GetFile(0);  // the plugin that defines the info
			if (!file) {
				return false;
			}
			const auto name = file->GetFilename();
			return name.size() == kMantellaFile.size() &&
			       std::ranges::equal(name, kMantellaFile, [](char a, char b) { return std::tolower(static_cast<unsigned char>(a)) == std::tolower(static_cast<unsigned char>(b)); });
		}

		// Builds the same DialogueItem the engine builds to speak the info, and joins its
		// response texts. Response text is not kept in memory, so the engine loads it here.
		// The engine allocates the response list on its own heap, and the library's list
		// destructor would free it on the CRT heap, so the item is built in raw storage and
		// never destroyed. That leaves a few hundred bytes per spoken line on the engine heap.
		std::string ReadInfoText(RE::TESTopicInfo* a_info, RE::Actor* a_speaker)
		{
			auto* topic = a_info->parentTopic;
			if (!topic) {
				return {};
			}
			alignas(RE::DialogueItem) std::byte storage[sizeof(RE::DialogueItem)];
			auto* item = std::construct_at(reinterpret_cast<RE::DialogueItem*>(storage), topic->ownerQuest, topic, a_info, a_speaker);
			std::string text;
			for (const auto* response : item->responses) {
				if (!response || response->text.empty()) {
					continue;
				}
				if (!text.empty()) {
					text += ' ';
				}
				text += response->text.c_str();
			}
			return Trim(text);
		}

		std::string FindSubtitle(RE::Actor* a_speaker)
		{
			auto* manager = RE::SubtitleManager::GetSingleton();
			if (!manager) {
				return {};
			}
			RE::BSSpinLockGuard guard(manager->lock);
			for (auto& info : manager->subtitles) {
				auto ref = info.speaker.get();
				if (ref && ref.get() == a_speaker && !info.subtitle.empty()) {
					return Trim(info.subtitle.c_str());
				}
			}
			return {};
		}

		void SendModEvent(const char* a_name, const std::string& a_text, float a_num, RE::Actor* a_sender)
		{
			SKSE::ModCallbackEvent event{ a_name, a_text.c_str(), a_num, a_sender };
			SKSE::GetModCallbackEventSource()->SendEvent(&event);
		}

		std::string BaseID(RE::Actor* a_actor)
		{
			const auto* base = a_actor->GetActorBase();
			return base ? std::format("{:06X}", base->GetFormID() & 0xFFFFFF) : std::string{};
		}

		double UnixNow()
		{
			return std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count();
		}

		// --- Menu dialogue with the player, kept per NPC from game load --------------------------------------------------
		// Live test 12: Mantella's own store of menu dialogue missed an exchange spoken before its first talk of the
		// session, while this listener heard every line. Each line an NPC speaks in the dialogue menu with the player is
		// kept with the topic the player chose (empty for a greeting or a line the player did not pick), in
		// MantellaLivingWorld/menu_dialogue.json, for the Hub to hand to that NPC's next talk. Lines of any plugin, voiced
		// or silent; a greeting the player did not choose is kept only from a plugin that is not a base game master
		// (vanilla hellos and rumours are chatter). Nothing expires: the lines stay until the Hub has turned them into a
		// memory at that NPC's next talk, however much later (it notes which it used, per save). Bounded so a playthrough
		// cannot overflow before a talk: kMenuPerNpc exchanges per NPC (when full, a base game line goes first, then the
		// oldest, and the NPC's "dropped" count says how many), kMenuNpcs NPCs (the one talked with longest ago goes).
		constexpr std::size_t kMenuPerNpc = 60;
		constexpr std::size_t kMenuNpcs = 200;
		constexpr std::size_t kMenuSaidChars = 300;
		constexpr std::size_t kMenuLineChars = 500;
		const std::filesystem::path kMenuFile{ L"Data/SKSE/Plugins/StorageUtilData/MantellaLivingWorld/menu_dialogue.json" };

		struct MenuLine
		{
			std::string said;  // the topic text the player chose, "" for a greeting
			std::string line;  // what the NPC said
			double      time{ 0.0 };  // real time (unix seconds)
			double      day{ 0.0 };   // game days passed (with the time of day)
			std::string plugin;       // the plugin of the line, so the Hub can tell a dialogue mod's lines
			std::string place;        // where it was said
			bool        vanilla{ false };  // a base game master's line: the first to go when the NPC's store is full
		};
		struct MenuNpc
		{
			std::string           name;
			std::deque<MenuLine>  lines;
			int                   dropped{ 0 };  // lines that had to go because the store was full
		};
		std::map<std::string, MenuNpc> g_menu;  // by base id, the current character's lines; main thread only
		bool                           g_menuLoaded = false;
		std::string                    g_menuPlayer;  // the character g_menu belongs to
		nlohmann::json                 g_menuOthers = nlohmann::json::object();  // other characters' lines: name -> npcs, kept as read
		constexpr std::size_t          kMenuOthers = 8;  // other characters kept (the one seen longest ago goes)
		// menu_ack.json (written by the Hub's side): {"<player>": {"<npc key>": <unix seconds>}}: every line of that player
		// and NPC whose "time" (real capture time, unix seconds) is at or before that value is stored as a memory and may go.
		// Real time, not game time: game time goes back when an older save is loaded. Nothing else removes a line except the caps.
		const std::filesystem::path    kMenuAckFile{ L"Data/SKSE/Plugins/StorageUtilData/MantellaLivingWorld/menu_ack.json" };
		nlohmann::json                 g_menuAck = nlohmann::json::object();
		std::uintmax_t                 g_menuAckSize = 0;
		std::filesystem::file_time_type g_menuAckTime{};

		std::string Clip(std::string a_text, std::size_t a_max)
		{
			if (a_text.size() > a_max) {
				a_text.resize(a_max);
				a_text += "...";
			}
			return a_text;
		}

		bool FromBaseGame(RE::TESTopicInfo* a_info)
		{
			const auto* file = a_info->GetFile(0);
			if (!file) {
				return true;
			}
			std::string name{ file->GetFilename() };
			std::ranges::transform(name, name.begin(), [](char c) { return static_cast<char>(std::tolower(static_cast<unsigned char>(c))); });
			return name == "skyrim.esm" || name == "update.esm" || name == "dawnguard.esm" || name == "hearthfires.esm" || name == "dragonborn.esm";
		}

		std::string PluginOf(RE::TESTopicInfo* a_info)
		{
			const auto* file = a_info->GetFile(0);
			return file ? std::string{ file->GetFilename() } : std::string{};
		}

		std::string PlaceOf(RE::Actor* a_actor)
		{
			if (auto* location = a_actor->GetCurrentLocation(); location && location->GetName() && *location->GetName()) {
				return location->GetName();
			}
			auto* cell = a_actor->GetParentCell();
			const char* name = cell ? cell->GetFullName() : nullptr;
			return name ? name : "";
		}

		double GameDay()
		{
			const auto* calendar = RE::Calendar::GetSingleton();
			return calendar ? static_cast<double>(calendar->GetDaysPassed()) : 0.0;
		}

		std::string PlayerName()
		{
			auto*       player = RE::PlayerCharacter::GetSingleton();
			const char* name = player ? player->GetDisplayFullName() : nullptr;
			return name ? name : "";
		}

		// What an earlier session left (lines no talk has used yet): the Hub drops what it already handed in.
		void ReadMenuAck();

		void LoadMenu()
		{
			g_menuLoaded = true;
			std::error_code ec;
			if (!std::filesystem::exists(kMenuFile, ec)) {
				return;
			}
			try {
				std::ifstream in(kMenuFile, std::ios::binary);
				auto          root = nlohmann::json::parse(in, nullptr, false);
				if (root.is_discarded() || !root.is_object() || !root.contains("npcs") || !root["npcs"].is_object()) {
					return;
				}
				g_menuPlayer = PlayerName();
				if (root.contains("others") && root["others"].is_object()) {
					g_menuOthers = root["others"];
				}
				// lines of another character never become this one's (live audit: a character switch relabelled them)
				const auto owner = root.value("player", std::string{});
				if (!owner.empty() && owner != g_menuPlayer) {
					g_menuOthers[owner] = root["npcs"];
					root["npcs"] = g_menuOthers.contains(g_menuPlayer) ? g_menuOthers[g_menuPlayer] : nlohmann::json::object();
				}
				g_menuOthers.erase(g_menuPlayer);
				ReadMenuAck();  // on game load: the file is read once here, then again only when it changes
				if (!root["npcs"].is_object()) {
					return;
				}
				for (auto& [base, npc] : root["npcs"].items()) {
					if (!npc.is_object() || !npc.contains("lines") || !npc["lines"].is_array()) {
						continue;
					}
					auto& kept = g_menu[base];
					kept.name = npc.value("name", std::string{});
					kept.dropped = npc.value("dropped", 0);
					for (auto& l : npc["lines"]) {
						if (l.is_object() && kept.lines.size() < kMenuPerNpc) {
							kept.lines.push_back({ l.value("said", std::string{}), l.value("line", std::string{}), l.value("time", 0.0),
								l.value("day", 0.0), l.value("plugin", std::string{}), l.value("place", std::string{}), l.value("vanilla", 0) != 0 });
						}
					}
				}
			} catch (...) {
				g_menu.clear();
			}
		}

		// Reads menu_ack.json again only when its size or write time changed. Missing, unreadable or half-written: nothing
		// is acknowledged (never drop on doubt).
		void ReadMenuAck()
		{
			std::error_code ec;
			const auto size = std::filesystem::file_size(kMenuAckFile, ec);
			if (ec) {
				g_menuAck = nlohmann::json::object();
				g_menuAckSize = 0;
				return;
			}
			const auto time = std::filesystem::last_write_time(kMenuAckFile, ec);
			if (ec || (size == g_menuAckSize && time == g_menuAckTime)) {
				return;
			}
			g_menuAckSize = size;
			g_menuAckTime = time;
			std::ifstream in(kMenuAckFile, std::ios::binary);
			auto          root = nlohmann::json::parse(in, nullptr, false);
			g_menuAck = !root.is_discarded() && root.is_object() ? root : nlohmann::json::object();
		}

		// The acknowledged real capture time (unix seconds) for a player's NPC, or a negative value when there is none.
		double AckedDay(const std::string& a_player, const std::string& a_npc)
		{
			if (!g_menuAck.contains(a_player) || !g_menuAck[a_player].is_object()) {
				return -1.0;
			}
			const auto& npcs = g_menuAck[a_player];
			auto        it = npcs.find(a_npc);
			return it != npcs.end() && it->is_number() ? it->get<double>() : -1.0;
		}

		// Drops the lines of other characters (kept as read under "others") that their own player's entry acknowledges.
		void PruneOthers()
		{
			for (auto& [player, npcs] : g_menuOthers.items()) {
				if (!npcs.is_object()) {
					continue;
				}
				for (auto it = npcs.begin(); it != npcs.end();) {
					const double acked = AckedDay(player, it.key());
					auto&        lines = (*it)["lines"];
					if (acked >= 0.0 && lines.is_array()) {
						auto kept = nlohmann::json::array();
						for (auto& l : lines) {
							const double time = l.is_object() ? l.value("time", 0.0) : 0.0;
							if (!l.is_object() || time <= 0.0 || time > acked) {  // no real time: never pruned by acknowledgement
								kept.push_back(l);
							}
						}
						lines = std::move(kept);
					}
					it = lines.is_array() && lines.empty() ? npcs.erase(it) : std::next(it);
				}
			}
		}

		nlohmann::json MenuJson(const std::map<std::string, MenuNpc>& a_menu)
		{
			auto npcs = nlohmann::json::object();
			for (const auto& [base, npc] : a_menu) {
				auto lines = nlohmann::json::array();
				for (const auto& l : npc.lines) {
					lines.push_back({ { "said", l.said }, { "line", l.line }, { "time", l.time }, { "day", l.day }, { "plugin", l.plugin },
						{ "place", l.place }, { "vanilla", l.vanilla ? 1 : 0 } });
				}
				npcs[base] = { { "name", npc.name }, { "dropped", npc.dropped }, { "lines", std::move(lines) } };
			}
			return npcs;
		}

		// Another character's save was loaded in this session: the lines kept so far go with their own character, and
		// this character's earlier lines (if any) come back.
		void SwitchMenuPlayer()
		{
			const auto now = PlayerName();
			if (now == g_menuPlayer) {
				return;
			}
			if (!g_menuPlayer.empty() && !g_menu.empty()) {
				g_menuOthers[g_menuPlayer] = MenuJson(g_menu);
			}
			g_menu.clear();
			if (g_menuOthers.contains(now) && g_menuOthers[now].is_object()) {
				for (auto& [base, npc] : g_menuOthers[now].items()) {
					if (!npc.is_object() || !npc.contains("lines") || !npc["lines"].is_array()) {
						continue;
					}
					auto& kept = g_menu[base];
					kept.name = npc.value("name", std::string{});
					kept.dropped = npc.value("dropped", 0);
					for (auto& l : npc["lines"]) {
						if (l.is_object() && kept.lines.size() < kMenuPerNpc) {
							kept.lines.push_back({ l.value("said", std::string{}), l.value("line", std::string{}), l.value("time", 0.0),
								l.value("day", 0.0), l.value("plugin", std::string{}), l.value("place", std::string{}), l.value("vanilla", 0) != 0 });
						}
					}
				}
			}
			g_menuOthers.erase(now);
			g_menuPlayer = now;
		}

		void SaveMenu()
		{
			const double today = GameDay();
			ReadMenuAck();
			for (auto it = g_menu.begin(); it != g_menu.end();) {
				auto&        lines = it->second.lines;
				const double acked = AckedDay(g_menuPlayer, it->first);
				// from a later time of another save (an earlier one was loaded): never this game's; and a line already
				// stored as a memory (menu_ack.json). Age alone never removes a line.
				std::erase_if(lines, [&](const MenuLine& l) { return l.day > today + 0.01 || (acked >= 0.0 && l.time > 0.0 && l.time <= acked); });
				it = lines.empty() ? g_menu.erase(it) : std::next(it);
			}
			PruneOthers();
			while (g_menu.size() > kMenuNpcs) {  // the NPC talked with longest ago goes first
				auto oldest = std::ranges::min_element(g_menu, {}, [](const auto& a_npc) { return a_npc.second.lines.back().time; });
				logger::warn("menu dialogue store full ({} NPCs): {} lines of {} dropped", kMenuNpcs, oldest->second.lines.size(), oldest->second.name);
				g_menu.erase(oldest);
			}
			while (g_menuOthers.size() > kMenuOthers) {
				g_menuOthers.erase(g_menuOthers.begin());
			}
			// a copy goes to the worker thread, which builds and writes the file: no JSON work on the main thread
			Writer::RunLater(std::chrono::milliseconds(0), [menu = g_menu, player = g_menuPlayer, others = g_menuOthers]() {
				nlohmann::json root{ { "player", player }, { "npcs", MenuJson(menu) }, { "others", others } };
				Writer::Save(kMenuFile, root.dump(-1, ' ', false, nlohmann::json::error_handler_t::replace));
			});
		}

		// a_actor spoke a_info in the dialogue menu with the player.
		void KeepMenuLine(RE::Actor* a_actor, RE::TESTopicInfo* a_info, RE::MenuTopicManager* a_topics, const std::string& a_text)
		{
			if (!g_menuLoaded) {
				LoadMenu();
			}
			SwitchMenuPlayer();
			std::string said;
			if (const auto* chosen = a_topics->lastSelectedDialogue; chosen && chosen->parentTopic && chosen->parentTopic == a_info->parentTopic) {
				said = Trim(chosen->topicText.c_str());
			}
			// Live test 15: the chosen entry is often gone by the time this runs (8 of 11 lines of a dialogue mod had no
			// topic). A mod's own line answers the topic the player chose, whose name is what the menu showed.
			if (said.empty() && !FromBaseGame(a_info) && a_info->parentTopic) {
				const char* topic = a_info->parentTopic->GetFullName();
				said = Trim(topic ? topic : "");
			}
			if (FromBaseGame(a_info) && (said.empty() || WordCount(a_text) < 4)) {
				return;  // a vanilla greeting or rumour the player did not choose, or a stock "Lead the way.": chatter
			}
			const auto base = BaseID(a_actor);
			if (base.empty() || a_text.empty()) {
				return;
			}
			auto&       npc = g_menu[base];
			const char* name = a_actor->GetDisplayFullName();
			npc.name = name ? name : "";
			if (!npc.lines.empty() && npc.lines.back().line == a_text && npc.lines.back().said == said) {
				return;  // the same line again (a repeated greeting)
			}
			npc.lines.push_back({ Clip(said, kMenuSaidChars), Clip(a_text, kMenuLineChars), UnixNow(), GameDay(), PluginOf(a_info),
				PlaceOf(a_actor), FromBaseGame(a_info) });
			while (npc.lines.size() > kMenuPerNpc) {  // full: a base game line goes first, then the oldest
				auto vanilla = std::ranges::find_if(npc.lines, [](const MenuLine& l) { return l.vanilla; });
				npc.lines.erase(vanilla != npc.lines.end() ? vanilla : npc.lines.begin());
				npc.dropped += 1;
			}
			SaveMenu();
		}

		// Mantella speaks its generated text through its own topic, with the real text injected
		// into the subtitle. Read it from the subtitle list shortly after the line starts.
		void HandleMantellaLine(RE::ActorHandle a_speaker)
		{
			Writer::RunLater(kMantellaSubtitleDelay, [a_speaker]() {
				SKSE::GetTaskInterface()->AddTask([a_speaker]() {
					auto actor = a_speaker.get();
					if (!actor) {
						return;
					}
					const auto text = FindSubtitle(actor.get());
					const float duration = std::max(2.0f, static_cast<float>(WordCount(text)) * 0.4f);
					SendModEvent("MLWW_MantellaLine", text, duration, actor.get());
					logger::info("mantella line from {:08X}: {} words, {:.1f}s", actor->GetFormID(), WordCount(text), duration);
				});
			});
		}

		void HandleLine(RE::NiPointer<RE::TESObjectREFR> a_ref, RE::FormID a_infoID)
		{
			auto* actor = a_ref ? a_ref->As<RE::Actor>() : nullptr;
			auto* player = RE::PlayerCharacter::GetSingleton();
			if (!actor || !player || actor == player) {
				return;
			}
			auto* info = RE::TESForm::LookupByID<RE::TESTopicInfo>(a_infoID);
			if (!info) {
				return;
			}

			if (IsFromMantella(info)) {
				HandleMantellaLine(actor->GetHandle());
				return;
			}
			std::string text;  // built once (each build leaves a small engine allocation behind, see ReadInfoText)
			bool        read = false;
			if (auto* topics = RE::MenuTopicManager::GetSingleton(); topics && topics->menuOpen) {
				auto speaker = topics->speaker.get();
				if (speaker && speaker.get() == actor) {
					text = ReadInfoText(info, actor);
					read = true;
					KeepMenuLine(actor, info, topics, text);
				}
			}

			const float distance = player->GetPosition().GetDistance(actor->GetPosition());
			if (distance > kMaxDistance) {
				return;
			}
			if (actor->IsInCombat() || actor->IsHostileToActor(player)) {
				return;  // combat barks and enemies' lines are not talk to repeat in the next conversation
			}
			if (actor->GetCurrentScene()) {
				return;  // a quest scene: its actors are not to be pulled into a Mantella talk
			}

			const auto now = std::chrono::steady_clock::now();
			auto&      last = g_lastBySpeaker[actor->GetFormID()];
			if (last.info == a_infoID && now - last.when < kRepeatWindow) {
				return;  // the same line again: skipped before its text is built
			}
			if (!read) {
				text = ReadInfoText(info, actor);
			}
			if (WordCount(text) < kMinWords) {
				return;
			}
			if (last.text == text && now - last.when < kRepeatWindow) {
				return;
			}
			last.text = text;
			last.when = now;
			last.info = a_infoID;

			const char* name = actor->GetDisplayFullName();
			Writer::Push({ name ? name : "", BaseID(actor), text, UnixNow() });
			SendModEvent("MLWW_VoicedLine", text, distance, actor);
			logger::info("line from {} ({:08X}, info {:08X}, {:.0f} units): {}", name ? name : "", actor->GetFormID(), a_infoID, distance, text);
		}

		class TopicInfoSink final : public RE::BSTEventSink<RE::TESTopicInfoEvent>
		{
		public:
			static TopicInfoSink* GetSingleton()
			{
				static TopicInfoSink singleton;
				return &singleton;
			}

			RE::BSEventNotifyControl ProcessEvent(const RE::TESTopicInfoEvent* a_event, RE::BSTEventSource<RE::TESTopicInfoEvent>*) override
			{
				if (!a_event || !a_event->speakerRef || a_event->type.get() != RE::TESTopicInfoEvent::TopicInfoEventType::kTopicBegin) {
					return RE::BSEventNotifyControl::kContinue;
				}
				// The sink may run off the main thread; do the game reads in a task.
				auto       ref = a_event->speakerRef;
				const auto infoID = a_event->topicInfoFormID;
				SKSE::GetTaskInterface()->AddTask([ref, infoID]() { HandleLine(ref, infoID); });
				return RE::BSEventNotifyControl::kContinue;
			}
		};
	}

	void Register()
	{
		auto* holder = RE::ScriptEventSourceHolder::GetSingleton();
		if (!holder) {
			logger::error("ScriptEventSourceHolder missing; listener not registered");
			return;
		}
		holder->AddEventSink<RE::TESTopicInfoEvent>(TopicInfoSink::GetSingleton());
		logger::info("TESTopicInfoEvent listener registered");
	}
}
