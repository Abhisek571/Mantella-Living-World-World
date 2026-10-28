Scriptname MLWW_Initiative extends MLWW_Job
{Mantella Living World - World: an NPC with a reason walks up to the player and starts a one-on-one Mantella talk.

A reason is set with WantToTell(npc, why) by any module (a promise, a job, news for their hold). Every 30 seconds the
nearest NPC within 10 m that has a reason may come over, if: initiative is on, the player is calm (not sneaking, fighting, in a menu or a Mantella talk), the NPC is calm, and
the hub's pacing allows it (MLW_Pace.TryClaim "initiative", 10 minutes). A reason is used once. No reason, nobody
comes. Why they came reaches Mantella through MantellaLivingWorld/banter.json (seed), read by the Hub's extension for
the first reply.}

GlobalVariable Property MLWW_InitiativeOn Auto

string Property KEY_WANTS = "MLWW_WantsToTell" AutoReadOnly
string Property KEY_WHY = "MLWW_WantsToTellWhy" AutoReadOnly
float Property RADIUS = 700.0 AutoReadOnly  ; about 10 m
float Property COOLDOWN = 600.0 AutoReadOnly
float Property SCAN = 30.0 AutoReadOnly

string Property BANTER_FILE = "MantellaLivingWorld/banter.json" AutoReadOnly

bool busy
bool seeded

Function Register()
	busy = false
	RegisterForModEvent("MantellaConversation_Ended", "OnConversationEnded")
	RegisterForModEvent("MLWW_MantellaLine", "OnMantellaLine")
	RegisterForModEvent("MLW_ReportRequest", "OnReportRequest")
	RegisterForSingleUpdate(SCAN)
EndFunction

Event OnReportRequest()
	MLW_Hub hub = MLWW_Util.Hub()
	If !hub
		Return
	EndIf
	hub.ReportAdd("world initiative", "on " + MLWW_InitiativeOn.GetValueInt() + ", " + StorageUtil.FormListCount(None, KEY_WANTS) + " NPC(s) with something to tell")
	int i = 0
	While i < StorageUtil.StringListCount(None, "MLWW_InitiativeRecent")
		hub.ReportAdd("world initiative", "recent: " + StorageUtil.StringListGet(None, "MLWW_InitiativeRecent", i))
		i += 1
	EndWhile
EndEvent

; Why they came is for the opening line only; after the first spoken line it would repeat on every reply.
Event OnMantellaLine(string asEventName, string asText, float afSeconds, Form akSpeaker)
	If seeded
		seeded = false
		JsonUtil.SetIntValue(BANTER_FILE, "active", 0)
		JsonUtil.Save(BANTER_FILE)
	EndIf
EndEvent

Event OnConversationEnded()
	If seeded
		seeded = false
		JsonUtil.SetIntValue(BANTER_FILE, "active", 0)
		JsonUtil.Save(BANTER_FILE)
	EndIf
EndEvent

; Any module: this NPC has something to tell the player. asWhy is a short reason for Mantella, e.g. "has news about
; the golden claw".
Function WantToTell(Actor akNpc, string asWhy)
	If !akNpc || akNpc == PlayerRef
		Return
	EndIf
	StorageUtil.FormListAdd(None, KEY_WANTS, akNpc, false)
	StorageUtil.SetStringValue(akNpc, KEY_WHY, asWhy)
EndFunction

Function Forget(Actor akNpc)
	StorageUtil.FormListRemove(None, KEY_WANTS, akNpc, true)
	StorageUtil.UnsetStringValue(akNpc, KEY_WHY)
EndFunction

Event OnUpdate()
	If !busy
		Scan()
	EndIf
	RegisterForSingleUpdate(SCAN)
EndEvent

; Picks the nearest NPC with a reason and brings them over. Returns the NPC, or None (testing calls this directly).
Actor Function Scan()
	If !MLWW_InitiativeOn || MLWW_InitiativeOn.GetValueInt() != 1 || !Calm(PlayerRef)
		Return None
	EndIf
	Actor best = None
	float bestDist = RADIUS
	int i = StorageUtil.FormListCount(None, KEY_WANTS)
	While i > 0
		i -= 1
		Actor npc = StorageUtil.FormListGet(None, KEY_WANTS, i) as Actor
		If !npc || npc.IsDead()
			StorageUtil.FormListRemoveAt(None, KEY_WANTS, i)
		ElseIf npc.Is3DLoaded() && Calm(npc) && !npc.IsHostileToActor(PlayerRef)
			float d = npc.GetDistance(PlayerRef)
			If d <= bestDist
				best = npc
				bestDist = d
			EndIf
		EndIf
	EndWhile
	If !best || !MLW_Pace.TryClaim("initiative", COOLDOWN)
		Return None
	EndIf
	string why = StorageUtil.GetStringValue(best, KEY_WHY)
	Forget(best)
	Approach(best, why)
	Return best
EndFunction

; Mantella's own "NPC approaches" pattern: start the talk, then send the NPC over with Mantella's MoveTo package
; (a plain PathToReference loses to the NPC's own AI package and they wander back to work).
Function Approach(Actor akNpc, string asWhy)
	busy = true
	MantellaConversation c = Game.GetFormFromFile(0x03D41A, "Mantella.esp") as MantellaConversation
	If c && !c.IsRunning() && Calm(PlayerRef)
		string line = akNpc.GetDisplayName() + " walks up to " + MLWW_Util.PlayerName() + " to start the talk"
		If asWhy != ""
			line += ": " + akNpc.GetDisplayName() + " " + asWhy
		EndIf
		JsonUtil.SetStringValue(BANTER_FILE, "seed", line + ".")
		JsonUtil.SetIntValue(BANTER_FILE, "active", 1)
		JsonUtil.Save(BANTER_FILE)
		seeded = true
		Actor[] actors = new Actor[2]
		actors[0] = PlayerRef
		actors[1] = akNpc
		c.Start()
		c.StartConversation(actors)
		c.TriggerApproachMoveAction(akNpc)
		MLWW_Util.Log("initiative: " + line)
		Remember(line)
	Else
		MLWW_Util.Log("initiative dropped: " + akNpc.GetDisplayName())
	EndIf
	busy = false
EndFunction

bool Function Calm(Actor akActor)
	If akActor.IsInCombat() || (akActor == PlayerRef && (PlayerRef.IsSneaking() || Utility.IsInMenuMode()))
		Return false
	EndIf
	Quest c = Game.GetFormFromFile(0x03D41A, "Mantella.esp") as Quest
	Return !(c && c.IsRunning())
EndFunction

Function Remember(string asLine)
	StorageUtil.StringListAdd(None, "MLWW_InitiativeRecent", asLine)
	While StorageUtil.StringListCount(None, "MLWW_InitiativeRecent") > 5
		StorageUtil.StringListRemoveAt(None, "MLWW_InitiativeRecent", 0)
	EndWhile
EndFunction
