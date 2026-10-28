Scriptname MLWW_Pairs extends MLWW_Job
{Mantella Living World - World: who knows whom. When an NPC joins a conversation that already has another NPC, one
short line per new pair tells Mantella how well the two know each other, from game data only:
  3 close: vanilla relationship (friend, family, lover; rivals too), living in the same house, or 3+ Mantella
    conversations together
  2 acquainted: same workplace (shop, inn, temple...), same guild, guards of the same hold, or 1-2 conversations together
  1 know of: same hold
  0 strangers
Conversations together are counted when a conversation ends or one of the two leaves it.}

MLWW_State Property World Auto

string Property KEY_MEMBERS = "MLWW_PairMembers" AutoReadOnly
string Property KEY_TOLD = "MLWW_PairsTold" AutoReadOnly
string Property KEY_COTALKS = "MLWW_CoTalks_" AutoReadOnly
int Property CLOSE_TALKS = 3 AutoReadOnly

Function Register()
	RegisterForModEvent("MantellaConversation_NPC_Added", "OnNpcAdded")
	RegisterForModEvent("MantellaConversation_NPC_Removed", "OnNpcRemoved")
	RegisterForModEvent("MantellaConversation_Ended", "OnConversationEnded")
	RegisterForModEvent("MantellaConversation_Started", "OnConversationStarted")
	; A game load ends any conversation; members left from before the load are stale.
	StorageUtil.FormListClear(None, KEY_MEMBERS)
	StorageUtil.StringListClear(None, KEY_TOLD)
EndFunction

Event OnNpcAdded(Form akActor)
	Actor npc = akActor as Actor
	If !npc || npc == PlayerRef
		Return
	EndIf
	If StorageUtil.FormListHas(None, KEY_MEMBERS, npc)
		Return
	EndIf
	int count = StorageUtil.FormListCount(None, KEY_MEMBERS)
	int i = 0
	While i < count
		Actor other = StorageUtil.FormListGet(None, KEY_MEMBERS, i) as Actor
		If other && other != npc && !other.IsDead()
			string pair = PairKey(npc, other)
			If !StorageUtil.StringListHas(None, KEY_TOLD, pair)
				StorageUtil.StringListAdd(None, KEY_TOLD, pair)
				MLWW_Util.Send("pairs", Line(npc, other, Level(npc, other)))
			EndIf
		EndIf
		i += 1
	EndWhile
	StorageUtil.FormListAdd(None, KEY_MEMBERS, npc, false)
	StorageUtil.SetFloatValue(npc, "MLWW_PairsAdded", Utility.GetCurrentRealTime())
EndEvent

Event OnNpcRemoved(Form akActor)
	Actor npc = akActor as Actor
	If !npc || !StorageUtil.FormListHas(None, KEY_MEMBERS, npc)
		Return
	EndIf
	StorageUtil.FormListRemove(None, KEY_MEMBERS, npc, true)
	CountTalks(npc)
EndEvent

; Ended does not always arrive, and Started comes after the first NPC_Added (as in the Hub's channel): members who
; joined more than 30 seconds before this talk started are left over from an earlier one.
Event OnConversationStarted()
	float now = Utility.GetCurrentRealTime()
	int i = StorageUtil.FormListCount(None, KEY_MEMBERS)
	While i > 0
		i -= 1
		Form npc = StorageUtil.FormListGet(None, KEY_MEMBERS, i)
		If !npc || now - StorageUtil.GetFloatValue(npc, "MLWW_PairsAdded", 0.0) > 30.0
			StorageUtil.FormListRemoveAt(None, KEY_MEMBERS, i)
		EndIf
	EndWhile
EndEvent

Event OnConversationEnded()
	While StorageUtil.FormListCount(None, KEY_MEMBERS) > 0
		Actor npc = StorageUtil.FormListGet(None, KEY_MEMBERS, 0) as Actor
		StorageUtil.FormListRemoveAt(None, KEY_MEMBERS, 0)
		If npc
			CountTalks(npc)
		EndIf
	EndWhile
	StorageUtil.StringListClear(None, KEY_TOLD)
EndEvent

; One more conversation together for akNpc and everyone still in it.
Function CountTalks(Actor akNpc)
	int i = 0
	int count = StorageUtil.FormListCount(None, KEY_MEMBERS)
	While i < count
		Actor other = StorageUtil.FormListGet(None, KEY_MEMBERS, i) as Actor
		If other && other != akNpc
			StorageUtil.AdjustIntValue(akNpc, KEY_COTALKS + MLWW_Util.Hex(other.GetFormID(), 8), 1)
			StorageUtil.AdjustIntValue(other, KEY_COTALKS + MLWW_Util.Hex(akNpc.GetFormID(), 8), 1)
		EndIf
		i += 1
	EndWhile
EndFunction

int Function CoTalks(Actor akA, Actor akB)
	Return StorageUtil.GetIntValue(akA, KEY_COTALKS + MLWW_Util.Hex(akB.GetFormID(), 8))
EndFunction

; 0 strangers, 1 know of, 2 acquainted, 3 close.
int Function Level(Actor akA, Actor akB)
	int rank = akA.GetRelationshipRank(akB)
	int talks = CoTalks(akA, akB)
	Location homeA = akA.GetEditorLocation()
	Location homeB = akB.GetEditorLocation()
	bool sameSpot = homeA && homeA == homeB && !Generic(homeA)
	If rank != 0 || talks >= CLOSE_TALKS || (sameSpot && IsHome(homeA))
		Return 3
	EndIf
	If talks > 0 || sameSpot || SharedGuild(akA, akB)
		Return 2
	EndIf
	int holdA = World.ActorHold(akA)
	If holdA >= 0 && holdA == World.ActorHold(akB)
		Return 1
	EndIf
	Return 0
EndFunction

string Function Line(Actor akA, Actor akB, int aiLevel)
	string both = akA.GetDisplayName() + " and " + akB.GetDisplayName()
	If aiLevel == 3
		If akA.GetRelationshipRank(akB) < 0
			Return both + " know each other well and do not get along."
		EndIf
		Return both + " know each other well."
	ElseIf aiLevel == 2
		Return both + " are acquainted."
	ElseIf aiLevel == 1
		Return both + " know of each other but have hardly talked."
	EndIf
	Return both + " are strangers to each other."
EndFunction

; Cities, towns, settlements and holds hold everyone: sharing one says nothing.
bool Function Generic(Location akLocation)
	Return LocHasKeyword(akLocation, 0x013168) || LocHasKeyword(akLocation, 0x013166) || LocHasKeyword(akLocation, 0x013167) || LocHasKeyword(akLocation, 0x016771)
EndFunction

; Houses and dwellings: the people placed there live together.
bool Function IsHome(Location akLocation)
	Return LocHasKeyword(akLocation, 0x01CB85) || LocHasKeyword(akLocation, 0x0130DC)
EndFunction

bool Function LocHasKeyword(Location akLocation, int aiKeyword)
	Keyword k = Game.GetFormFromFile(aiKeyword, "Skyrim.esm") as Keyword
	Return k && akLocation.HasKeyword(k)
EndFunction

; Companions, College, Thieves Guild, Dark Brotherhood; or guards of the same hold.
bool Function SharedGuild(Actor akA, Actor akB)
	int[] guilds = new int[4]
	guilds[0] = 0x048362
	guilds[1] = 0x01F259
	guilds[2] = 0x029DA9
	guilds[3] = 0x01BDB3
	int i = 0
	While i < guilds.Length
		Faction f = Game.GetFormFromFile(guilds[i], "Skyrim.esm") as Faction
		If f && akA.IsInFaction(f) && akB.IsInFaction(f)
			Return true
		EndIf
		i += 1
	EndWhile
	Faction crimeA = akA.GetCrimeFaction()
	Return akA.IsGuard() && akB.IsGuard() && crimeA && crimeA == akB.GetCrimeFaction()
EndFunction

string Function PairKey(Actor akA, Actor akB)
	Actor first = akA
	Actor second = akB
	If akB.GetFormID() < akA.GetFormID()
		first = akB
		second = akA
	EndIf
	Return MLWW_Util.Hex(first.GetFormID(), 8) + "_" + MLWW_Util.Hex(second.GetFormID(), 8)
EndFunction
