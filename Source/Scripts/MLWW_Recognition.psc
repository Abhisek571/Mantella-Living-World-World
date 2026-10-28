Scriptname MLWW_Recognition extends MLWW_Job
{Mantella Living World - World: hiding and recognition. When an NPC joins a conversation while the player sneaks
unseen, or hides their face under a hood or helmet in a hold where they are not famous, Mantella is told the NPC
does not recognise the player. People who know the player personally still do. Uncanny observers (observation 4+
in the NPC's Knowledge file npc/<baseid>.json, default 2) see through it, and Mantella is told that instead.}

MLWW_State Property World Auto

string Property NPC_FOLDER = "MantellaLivingWorld/npc/" AutoReadOnly
int Property OBSERVATION_DEFAULT = 2 AutoReadOnly
int Property UNCANNY = 4 AutoReadOnly
; Fame in this hold at which a face under a hood is still known.
int Property FAME_KNOWN = 3 AutoReadOnly
; Biped slots 30 (head) and 31 (hair): hoods, helmets, masks.
int Property SLOT_HEAD = 0x00000001 AutoReadOnly
int Property SLOT_HAIR = 0x00000002 AutoReadOnly

Function Register()
	RegisterForModEvent("MantellaConversation_NPC_Added", "OnNpcAdded")
EndFunction

Event OnNpcAdded(Form akActor)
	Actor npc = akActor as Actor
	If !npc || npc == PlayerRef || npc.IsDead()
		Return
	EndIf
	string line = Verdict(npc)
	If line != ""
		MLWW_Util.Send("recognition", line)
	EndIf
EndEvent

string Function Verdict(Actor akNpc)
	string npc = akNpc.GetDisplayName()
	string player = MLWW_Util.PlayerName()
	int observation = Observation(akNpc)
	bool seesThrough = observation >= UNCANNY
	If PlayerRef.IsSneaking() && !PlayerRef.IsDetectedBy(akNpc)
		If seesThrough
			Return npc + " senses " + player + " sneaking nearby and knows who it is."
		EndIf
		Return npc + " does not recognise " + player + ", who stays hidden out of sight."
	EndIf
	If !FaceHidden() || KnowsPersonally(akNpc)
		Return ""
	EndIf
	int hold = World.CurrentHold()
	If World.Fame(hold) >= FAME_KNOWN
		Return ""
	EndIf
	If seesThrough
		Return npc + " sees through " + player + "'s hood and knows who they are."
	EndIf
	Return npc + " does not recognise " + player + ": a hood hides their face."
EndFunction

int Function Observation(Actor akNpc)
	string file = NPC_FOLDER + MLWW_Util.BaseId(akNpc) + ".json"
	If !JsonUtil.JsonExists(file)
		Return OBSERVATION_DEFAULT
	EndIf
	; an int field of the NPC's file (JsonUtil keeps it under "int"). The file is shared with the Hub, Relationships
	; and Missives, so it is never unloaded here: that would drop their unsaved writes.
	Return JsonUtil.GetIntValue(file, "observation", OBSERVATION_DEFAULT)
EndFunction

bool Function FaceHidden()
	Armor head = PlayerRef.GetWornForm(SLOT_HEAD) as Armor
	If !head
		head = PlayerRef.GetWornForm(SLOT_HAIR) as Armor
	EndIf
	Return head != None
EndFunction

; Friends, lovers, followers and anyone the player has spent time with know the voice and the walk.
bool Function KnowsPersonally(Actor akNpc)
	If akNpc.GetRelationshipRank(PlayerRef) >= 1 || akNpc.IsPlayerTeammate()
		Return true
	EndIf
	Faction follower = Game.GetFormFromFile(0x05C84E, "Skyrim.esm") as Faction
	Return follower && akNpc.IsInFaction(follower)
EndFunction
