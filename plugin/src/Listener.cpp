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

			const float distance = player->GetPosition().GetDistance(actor->GetPosition());
			if (distance > kMaxDistance) {
				return;
			}

			const auto text = ReadInfoText(info, actor);
			if (WordCount(text) < kMinWords) {
				return;
			}

			const auto now = std::chrono::steady_clock::now();
			auto&      last = g_lastBySpeaker[actor->GetFormID()];
			if (last.text == text && now - last.when < kRepeatWindow) {
				return;
			}
			last.text = text;
			last.when = now;

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
