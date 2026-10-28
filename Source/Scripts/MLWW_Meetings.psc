Scriptname MLWW_Meetings extends MLWW_Job
{Mantella Living World - World: "since we last met". Each NPC keeps the day they last talked with the player and a
snapshot of the player's standing (fame and bounty in the NPC's hold, war side, Thane holds). When the NPC joins a
conversation on a later day, one line tells Mantella what changed since then, at most three things. The same day
sends nothing.}

MLWW_State Property World Auto

string Property KEY_DAY = "MLWW_LastMetDay" AutoReadOnly
string Property KEY_SNAPSHOT = "MLWW_LastMetSnapshot" AutoReadOnly
int Property MAX_ITEMS = 3 AutoReadOnly

; Snapshot slots.
int Property SNAP_FAME = 0 AutoReadOnly
int Property SNAP_BOUNTY = 1 AutoReadOnly
int Property SNAP_WAR = 2 AutoReadOnly
int Property SNAP_THANE = 3 AutoReadOnly
int Property SNAP_HOLD = 4 AutoReadOnly

Function Register()
	RegisterForModEvent("MantellaConversation_NPC_Added", "OnNpcAdded")
EndFunction

Event OnNpcAdded(Form akActor)
	Actor npc = akActor as Actor
	If !npc || npc == PlayerRef || npc.IsDead()
		Return
	EndIf
	string line = Changes(npc)
	If line != ""
		MLWW_Util.Send("meetings", line)
	EndIf
EndEvent

; Works out the line for this meeting and stores the new snapshot. "" when there is nothing to say.
string Function Changes(Actor akNpc)
	float now = Utility.GetCurrentGameTime()
	int hold = World.ActorHold(akNpc)
	If hold < 0
		hold = World.CurrentHold()
	EndIf
	int[] snap = Snapshot(hold)
	If !StorageUtil.HasFloatValue(akNpc, KEY_DAY) || StorageUtil.IntListCount(akNpc, KEY_SNAPSHOT) != 5
		Store(akNpc, now, snap)
		Return ""
	EndIf
	float last = StorageUtil.GetFloatValue(akNpc, KEY_DAY)
	If (last as int) == (now as int)
		Return ""
	EndIf
	string[] items = new string[4]
	int n = 0
	string player = MLWW_Util.PlayerName()
	; The old snapshot's hold decides what "here" meant last time.
	int oldHold = StorageUtil.IntListGet(akNpc, KEY_SNAPSHOT, SNAP_HOLD)
	int oldThane = StorageUtil.IntListGet(akNpc, KEY_SNAPSHOT, SNAP_THANE)
	int newThane = snap[SNAP_THANE]
	int i = 0
	While i < 9 && n < MAX_ITEMS
		int bit = Math.LeftShift(1, i)
		If Math.LogicalAnd(newThane, bit) != 0 && Math.LogicalAnd(oldThane, bit) == 0
			items[n] = player + " became Thane of " + World.HoldText(i)
			n += 1
		EndIf
		i += 1
	EndWhile
	int oldWar = StorageUtil.IntListGet(akNpc, KEY_SNAPSHOT, SNAP_WAR)
	If n < MAX_ITEMS && snap[SNAP_WAR] != oldWar && snap[SNAP_WAR] != 0
		items[n] = player + " joined the " + WarName(snap[SNAP_WAR])
		n += 1
	EndIf
	If n < MAX_ITEMS && oldHold == hold && hold >= 0
		int oldBounty = StorageUtil.IntListGet(akNpc, KEY_SNAPSHOT, SNAP_BOUNTY)
		int newBounty = snap[SNAP_BOUNTY]
		If newBounty > oldBounty
			items[n] = player + "'s bounty in " + World.HoldText(hold) + " rose from " + oldBounty + " to " + newBounty + " gold"
			n += 1
		ElseIf newBounty < oldBounty && newBounty == 0
			items[n] = player + "'s bounty in " + World.HoldText(hold) + " was cleared"
			n += 1
		ElseIf newBounty < oldBounty
			items[n] = player + "'s bounty in " + World.HoldText(hold) + " fell from " + oldBounty + " to " + newBounty + " gold"
			n += 1
		EndIf
	EndIf
	If n < MAX_ITEMS && oldHold == hold && hold >= 0 && snap[SNAP_FAME] > StorageUtil.IntListGet(akNpc, KEY_SNAPSHOT, SNAP_FAME)
		items[n] = player + " is better known in " + World.HoldText(hold) + " now"
		n += 1
	EndIf
	Store(akNpc, now, snap)
	If n == 0
		Return ""
	EndIf
	int days = (now - last) as int
	string when = days + " days ago"
	If days <= 1
		when = "yesterday"
	EndIf
	string line = akNpc.GetDisplayName() + " last saw " + player + " " + when + "; since then: "
	i = 0
	While i < n
		If i > 0
			line += "; "
		EndIf
		line += items[i]
		i += 1
	EndWhile
	Return line + "."
EndFunction

int[] Function Snapshot(int aiHold)
	int[] snap = new int[5]
	snap[SNAP_FAME] = World.Fame(aiHold)
	snap[SNAP_BOUNTY] = World.Bounty(aiHold)
	string side = World.WarSide()
	If side == "Legion"
		snap[SNAP_WAR] = 1
	ElseIf side == "Stormcloaks"
		snap[SNAP_WAR] = 2
	EndIf
	snap[SNAP_THANE] = World.ThaneMask()
	snap[SNAP_HOLD] = aiHold
	Return snap
EndFunction

Function Store(Actor akNpc, float afDay, int[] akSnap)
	StorageUtil.SetFloatValue(akNpc, KEY_DAY, afDay)
	StorageUtil.IntListClear(akNpc, KEY_SNAPSHOT)
	int i = 0
	While i < akSnap.Length
		StorageUtil.IntListAdd(akNpc, KEY_SNAPSHOT, akSnap[i])
		i += 1
	EndWhile
EndFunction

string Function WarName(int aiSide)
	If aiSide == 1
		Return "Imperial Legion"
	EndIf
	Return "Stormcloaks"
EndFunction
