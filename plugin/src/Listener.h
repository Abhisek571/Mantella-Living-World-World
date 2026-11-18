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

namespace MLWW::Listener
{
	// Registers the TESTopicInfoEvent sink. Call at kDataLoaded.
	void Register();

	// Writes kept menu dialogue now when a coalesced save is still pending. Main thread (a game save or load).
	void FlushMenu();

	// A save was loaded or a new game started: lines from a later time of the game are kept aside, not shown. After a
	// load the stored lines are split by the loaded save's time and written about 2 s later.
	void GameLoaded(bool a_newGame);
}
