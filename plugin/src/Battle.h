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

// Battle accounts: each fight near the player (who fought on which side, who died, how hurt each was, how much each
// did, close calls, rescues, magic, kills), written to MantellaLivingWorld/battles.json for the Integration Hub, which
// turns it into words. Nothing goes into the save. Settings are World.esp globals on the Hub's MCM World page.
namespace MLWW::Battle
{
	// Finds the settings and reads what an earlier session left in battles.json. Call at kDataLoaded.
	void Start();

	// Called from World's own sinks, in the event: they only filter and queue.
	void Hit(const RE::TESHitEvent& a_event);
	void Death(const RE::TESDeathEvent& a_event);
	void Bleedout(const RE::TESEnterBleedoutEvent& a_event);
	void Magic(const RE::TESMagicEffectApplyEvent& a_event);
	void Cast(const RE::TESSpellCastEvent& a_event);  // the player's casts: their harmful magic counts only after one

	// Main thread, once a second (World's poll): starts and ends fights, reads the fighters' health, expires accounts.
	void Tick();

	// Main thread, when a game is loaded or started: drops the fight in progress; a_forget also drops ended fights
	// (a new game). Ended fights from a later time or another character are dropped at the next Tick.
	void Reset(bool a_forget);
}
