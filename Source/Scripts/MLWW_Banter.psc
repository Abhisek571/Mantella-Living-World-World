Scriptname MLWW_Banter extends MLWW_Job
{Mantella Living World - World: party banter. A party member may react to a voiced line said nearby (Serana Dialogue
Add-On, idle chatter), to walking into an inn, or to the end of a fight. The reaction is a short Mantella talk between
two NPCs (no player), ended after one line, two when the other one replies (20%).

Guards: banter on, the chance roll (default 30%), player not sneaking, not fighting and not in a menu, nobody in combat,
and the hub's pacing (MLW_Pace.TryClaim "banter", 2 minutes; at most the hourly limit for all ambient lines). The roll
happens at once, the reaction 4-8 seconds later, re-checked then: a talk the player started in between wins and the
reaction is dropped. What was said nearby reaches Mantella through said_nearby.json (the listener plugin); the reason
for the talk goes in MantellaLivingWorld/banter.json for the Hub's extension.}

GlobalVariable Property MLWW_BanterOn Auto
GlobalVariable Property MLWW_BanterChance Auto

string Property BANTER_FILE = "MantellaLivingWorld/banter.json" AutoReadOnly
string Property KEY_RECENT = "MLWW_BanterRecent" AutoReadOnly
float Property RADIUS = 1024.0 AutoReadOnly
float Property COOLDOWN = 120.0 AutoReadOnly
float Property MAX_TALK = 45.0 AutoReadOnly

Actor pendingA
Actor pendingB
string pendingSeed
bool talking
float pendingAt
int linesWanted
int linesSeen
float talkStarted

Function Register()
	RegisterForModEvent("MLWW_VoicedLine", "OnVoicedLine")
	RegisterForModEvent("MLWW_MantellaLine", "OnMantellaLine")
	RegisterForModEvent("MantellaConversation_Ended", "OnConversationEnded")
	RegisterForModEvent("MLW_ReportRequest", "OnReportRequest")
	; A load ends every talk.
	pendingA = None
	talking = false
	watchingFight = false  ; its check time is real seconds of the old session
	JsonUtil.SetIntValue(BANTER_FILE, "active", 0)
	JsonUtil.Save(BANTER_FILE)
EndFunction

; --- triggers --------------------------------------------------------------------------------------------------------

Event OnVoicedLine(string asEventName, string asText, float afDistance, Form akSpeaker)
	Actor speaker = akSpeaker as Actor
	If !speaker || speaker == PlayerRef || pendingA || talking
		Return
	EndIf
	Actor reactor = PickPartyMember(speaker)
	If reactor && Roll()
		Plan(reactor, speaker, reactor.GetDisplayName() + " heard " + speaker.GetDisplayName() + " say that. Only " + reactor.GetDisplayName() + " speaks now: one short sentence reacting to it.")
	EndIf
EndEvent

Function LocationChanged(Location akOldLoc, Location akNewLoc)
	Keyword inn = Game.GetFormFromFile(0x01CB87, "Skyrim.esm") as Keyword  ; LocTypeInn
	If !akNewLoc || !inn || !akNewLoc.HasKeyword(inn) || (akOldLoc && akOldLoc.HasKeyword(inn))
		Return
	EndIf
	TwoOfTheParty("The party just walked into " + akNewLoc.GetName() + ".")
EndFunction

; The player alias passes hits on; while a fight lasts the quest checks every 5 seconds whether it is over.
bool watchingFight
Function PlayerHit()
	If !watchingFight
		watchingFight = true
		fightCheckAt = Utility.GetCurrentRealTime() + 5.0
		Schedule()
	EndIf
EndFunction

Function FightOver()
	TwoOfTheParty("The fight just ended.")
EndFunction

Function TwoOfTheParty(string asWhat)
	If pendingA || talking
		Return
	EndIf
	Actor a = PickPartyMember(None)
	Actor b = PickPartyMember(a)
	If a && b && Roll()
		Plan(a, b, asWhat + " " + a.GetDisplayName() + " speaks to " + b.GetDisplayName() + " about it. Only " + a.GetDisplayName() + " speaks now: one short sentence.")
	EndIf
EndFunction

; --- planning and the delayed start ----------------------------------------------------------------------------------

bool Function Roll()
	If !MLWW_BanterOn || MLWW_BanterOn.GetValueInt() != 1 || !Calm()
		Return false
	EndIf
	Return Utility.RandomInt(1, 100) <= MLWW_BanterChance.GetValueInt()
EndFunction

Function Plan(Actor akA, Actor akB, string asSeed)
	pendingA = akA
	pendingB = akB
	pendingSeed = asSeed
	pendingAt = Utility.GetCurrentRealTime() + Utility.RandomFloat(4.0, 8.0)
	Schedule()
EndFunction

; One update timer serves the fight watch, the delayed reaction and the talk end: each update does what is due and
; asks for the next one.
float fightCheckAt
float talkCheckAt

Event OnUpdate()
	float now = Utility.GetCurrentRealTime()
	If watchingFight && now >= fightCheckAt
		If PlayerRef.IsInCombat()
			fightCheckAt = now + 5.0
		Else
			watchingFight = false
			FightOver()
		EndIf
	EndIf
	If talking && now >= talkCheckAt
		CheckTalk()
	ElseIf pendingA && now >= pendingAt
		Fire()
	EndIf
	Schedule()
EndEvent

Function Schedule()
	float now = Utility.GetCurrentRealTime()
	float nextAt = 0.0
	If watchingFight
		nextAt = fightCheckAt
	EndIf
	If talking && (nextAt == 0.0 || talkCheckAt < nextAt)
		nextAt = talkCheckAt
	ElseIf !talking && pendingA && (nextAt == 0.0 || pendingAt < nextAt)
		nextAt = pendingAt
	EndIf
	If nextAt > 0.0
		If nextAt - now < 0.2
			RegisterForSingleUpdate(0.2)
		Else
			RegisterForSingleUpdate(nextAt - now)
		EndIf
	EndIf
EndFunction

Function Fire()
	Actor a = pendingA
	Actor b = pendingB
	string seed = pendingSeed
	pendingA = None
	pendingB = None
	If !Calm() || !Near(a) || !Near(b) || a.IsInCombat() || b.IsInCombat()
		MLWW_Util.Log("banter dropped: no longer calm")
		Return
	EndIf
	If !MLW_Pace.TryClaim("banter", COOLDOWN)
		MLWW_Util.Log("banter dropped by pacing")
		Return
	EndIf
	MantellaConversation c = Game.GetFormFromFile(0x03D41A, "Mantella.esp") as MantellaConversation
	If !c || c.IsRunning()
		Return
	EndIf
	JsonUtil.SetStringValue(BANTER_FILE, "seed", seed)
	JsonUtil.SetIntValue(BANTER_FILE, "active", 1)
	JsonUtil.Save(BANTER_FILE)
	talking = true
	linesSeen = 0
	linesWanted = 1
	If Utility.RandomInt(1, 100) <= 20
		linesWanted = 2
	EndIf
	talkStarted = Utility.GetCurrentRealTime()
	Actor[] actors = new Actor[2]
	actors[0] = a
	actors[1] = b
	c.Start()
	c.StartConversation(actors)
	Remember(a.GetDisplayName() + " to " + b.GetDisplayName() + ": " + seed)
	MLWW_Util.Log("banter: " + seed)
	talkCheckAt = talkStarted + MAX_TALK
EndFunction

; --- ending the talk -------------------------------------------------------------------------------------------------

Event OnMantellaLine(string asEventName, string asText, float afSeconds, Form akSpeaker)
	If !talking
		Return
	EndIf
	linesSeen += 1
	If linesSeen >= linesWanted
		talkCheckAt = Utility.GetCurrentRealTime() + afSeconds + 0.5
		Schedule()
	EndIf
EndEvent

Function CheckTalk()
	If linesSeen >= linesWanted || Utility.GetCurrentRealTime() - talkStarted >= MAX_TALK
		EndTalk()
	Else
		talkCheckAt = talkStarted + MAX_TALK
	EndIf
EndFunction

Function EndTalk()
	talking = false
	JsonUtil.SetIntValue(BANTER_FILE, "active", 0)
	JsonUtil.Save(BANTER_FILE)
	MantellaConversation c = Game.GetFormFromFile(0x03D41A, "Mantella.esp") as MantellaConversation
	If c && c.IsRunning() && !c.IsPlayerInConversation()
		c.EndConversation()
	EndIf
EndFunction

Event OnConversationEnded()
	If talking
		talking = false
		JsonUtil.SetIntValue(BANTER_FILE, "active", 0)
		JsonUtil.Save(BANTER_FILE)
	EndIf
EndEvent

; --- helpers ---------------------------------------------------------------------------------------------------------

bool Function Calm()
	If PlayerRef.IsSneaking() || PlayerRef.IsInCombat() || Utility.IsInMenuMode()
		Return false
	EndIf
	Quest c = Game.GetFormFromFile(0x03D41A, "Mantella.esp") as Quest
	Return !(c && c.IsRunning())
EndFunction

bool Function Near(Actor akActor)
	Return akActor && !akActor.IsDead() && akActor.Is3DLoaded() && akActor.GetDistance(PlayerRef) <= RADIUS
EndFunction

; A random party member near the player that is not akNot, or None.
Actor Function PickPartyMember(Actor akNot)
	Actor[] near = MiscUtil.ScanCellNPCs(PlayerRef, RADIUS)
	Actor[] party = new Actor[16]
	int n = 0
	int i = 0
	While i < near.Length && n < 16
		Actor a = near[i]
		If a && a != PlayerRef && a != akNot && a.IsPlayerTeammate() && !a.IsInCombat() && Near(a)
			party[n] = a
			n += 1
		EndIf
		i += 1
	EndWhile
	If n == 0
		Return None
	EndIf
	Return party[Utility.RandomInt(0, n - 1)]
EndFunction

Function Remember(string asLine)
	StorageUtil.StringListAdd(None, KEY_RECENT, asLine)
	While StorageUtil.StringListCount(None, KEY_RECENT) > 5
		StorageUtil.StringListRemoveAt(None, KEY_RECENT, 0)
	EndWhile
EndFunction

Event OnReportRequest()
	MLW_Hub hub = MLWW_Util.Hub()
	If !hub
		Return
	EndIf
	hub.ReportAdd("world banter", "on " + MLWW_BanterOn.GetValueInt() + ", chance " + MLWW_BanterChance.GetValueInt() + "%, pace: " + MLW_Pace.ReportText())
	int i = 0
	While i < StorageUtil.StringListCount(None, KEY_RECENT)
		hub.ReportAdd("world banter", "recent: " + StorageUtil.StringListGet(None, KEY_RECENT, i))
		i += 1
	EndWhile
EndEvent

; Testing: plan a reaction now, skipping the chance roll (DevBench).
Function TestReact(Actor akReactor, Actor akSpeaker)
	Plan(akReactor, akSpeaker, akReactor.GetDisplayName() + " heard " + akSpeaker.GetDisplayName() + " say that. Only " + akReactor.GetDisplayName() + " speaks now: one short sentence reacting to it.")
EndFunction
