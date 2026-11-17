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

#include "Writer.h"

#include <map>

namespace MLWW::Writer
{
	namespace
	{
		using clock = std::chrono::steady_clock;

		constexpr std::size_t kMaxLines = 10;
		const std::filesystem::path kFile{ L"Data/SKSE/Plugins/StorageUtilData/MantellaLivingWorld/said_nearby.json" };

		struct TimedJob
		{
			clock::time_point     due;
			std::function<void()> fn;
		};

		std::mutex              g_lock;
		std::condition_variable g_cv;
		std::vector<Line>       g_pending;  // new lines not yet written
		std::vector<TimedJob>   g_jobs;
		bool                    g_started = false;

		// Worker-thread only.
		std::deque<nlohmann::json> g_lines;
		std::map<std::filesystem::path, std::uint64_t> g_writeGen;  // the newest write of each file

		constexpr int  kRenameTries = 100;
		constexpr auto kRenameRetry = std::chrono::milliseconds(100);

		void LoadExisting()
		{
			std::error_code ec;
			if (!std::filesystem::exists(kFile, ec)) {
				return;
			}
			std::ifstream in(kFile, std::ios::binary);
			if (!in) {
				return;
			}
			auto j = nlohmann::json::parse(in, nullptr, false);
			if (j.is_discarded() || !j.is_object() || !j.contains("lines") || !j["lines"].is_array()) {
				return;
			}
			for (auto& line : j["lines"]) {
				if (line.is_object()) {
					g_lines.push_back(line);
				}
			}
			while (g_lines.size() > kMaxLines) {
				g_lines.pop_front();
			}
		}

		std::filesystem::path TempOf(const std::filesystem::path& a_file)
		{
			auto tmp = a_file;
			tmp += L".tmp";
			return tmp;
		}

		// The temp file of write a_gen replaces a_file once no reader holds it open. A newer write of the same file
		// (which reuses the temp file) ends these retries; after kRenameTries the temp file stays and is logged.
		void RetryRename(std::filesystem::path a_file, std::uint64_t a_gen, int a_tries)
		{
			RunLater(kRenameRetry, [file = std::move(a_file), a_gen, a_tries]() {
				if (g_writeGen[file] != a_gen) {
					return;
				}
				std::error_code ec;
				std::filesystem::rename(TempOf(file), file, ec);
				if (!ec) {
					return;
				}
				if (a_tries + 1 < kRenameTries) {
					RetryRename(file, a_gen, a_tries + 1);
				} else {
					logger::warn("rename to {} kept failing ({}); the new data stays in the .tmp file", file.string(), ec.message());
				}
			});
		}

		void WriteText(const std::filesystem::path& a_file, const std::string& text)
		{
			const auto gen = ++g_writeGen[a_file];
			std::error_code ec;
			std::filesystem::create_directories(a_file.parent_path(), ec);

			const auto tmp = TempOf(a_file);
			{
				std::ofstream out(tmp, std::ios::binary | std::ios::trunc);
				if (!out) {
					logger::warn("cannot open {} for writing", tmp.string());
					return;
				}
				out.write(text.data(), static_cast<std::streamsize>(text.size()));
				if (!out) {
					logger::warn("write to {} failed", tmp.string());
					return;
				}
			}
			// std::filesystem::rename replaces an existing target on Windows, but not while a reader has it open (the
			// Mantella side reading it). Never a direct, truncating write (a reader could see half a file): the rename is
			// tried again later from the job queue, so the worker's other timed jobs never wait behind it.
			std::filesystem::rename(tmp, a_file, ec);
			if (ec) {
				RetryRename(a_file, gen, 0);
			}
		}

		void WriteFile()
		{
			nlohmann::json root;
			root["lines"] = nlohmann::json::array();
			for (auto& line : g_lines) {
				root["lines"].push_back(line);
			}
			WriteText(kFile, root.dump(-1, ' ', false, nlohmann::json::error_handler_t::replace));
		}

		void Worker()
		{
			LoadExisting();

			std::unique_lock lock(g_lock);
			for (;;) {
				// Run due timed jobs.
				const auto now = clock::now();
				std::vector<std::function<void()>> due;
				for (auto it = g_jobs.begin(); it != g_jobs.end();) {
					if (it->due <= now) {
						due.push_back(std::move(it->fn));
						it = g_jobs.erase(it);
					} else {
						++it;
					}
				}
				std::vector<Line> lines;
				lines.swap(g_pending);

				if (!due.empty() || !lines.empty()) {
					lock.unlock();
					for (auto& fn : due) {
						fn();
					}
					if (!lines.empty()) {
						for (auto& l : lines) {
							g_lines.push_back({ { "speaker", l.speaker }, { "base_id", l.baseID }, { "text", l.text }, { "time", l.time } });
						}
						while (g_lines.size() > kMaxLines) {
							g_lines.pop_front();
						}
						WriteFile();
					}
					lock.lock();
					continue;
				}

				if (g_jobs.empty()) {
					g_cv.wait(lock, [] { return !g_pending.empty() || !g_jobs.empty(); });
				} else {
					auto next = std::ranges::min_element(g_jobs, {}, &TimedJob::due)->due;
					g_cv.wait_until(lock, next);
				}
			}
		}
	}

	void Start()
	{
		{
			std::scoped_lock lock(g_lock);
			if (g_started) {
				return;
			}
			g_started = true;
		}
		std::thread(Worker).detach();
	}

	void Push(Line a_line)
	{
		{
			std::scoped_lock lock(g_lock);
			g_pending.push_back(std::move(a_line));
		}
		g_cv.notify_one();
	}

	void Clear()
	{
		{
			std::scoped_lock lock(g_lock);
			g_pending.clear();
			// Due now, so it runs before any line pushed after this call is written.
			g_jobs.push_back({ clock::now(), []() {
								  if (!g_lines.empty()) {
									  g_lines.clear();
									  WriteFile();
								  }
							  } });
		}
		g_cv.notify_one();
	}

	void Save(std::filesystem::path a_file, std::string a_text)
	{
		RunLater(0ms, [file = std::move(a_file), text = std::move(a_text)]() { WriteText(file, text); });
	}

	void RunLater(std::chrono::milliseconds a_delay, std::function<void()> a_fn)
	{
		{
			std::scoped_lock lock(g_lock);
			g_jobs.push_back({ clock::now() + a_delay, std::move(a_fn) });
		}
		g_cv.notify_one();
	}
}
