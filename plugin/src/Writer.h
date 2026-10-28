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

#pragma once

namespace MLWW::Writer
{
	struct Line
	{
		std::string speaker;
		std::string baseID;
		std::string text;
		double      time;
	};

	// Starts the background worker. Call once.
	void Start();

	// Queues a line for said_nearby.json. Never blocks on file I/O.
	void Push(Line a_line);

	// Runs a_fn on the worker thread after a_delay. a_fn must not touch game state
	// directly; it should hand game work back through the SKSE task interface.
	void RunLater(std::chrono::milliseconds a_delay, std::function<void()> a_fn);
}
