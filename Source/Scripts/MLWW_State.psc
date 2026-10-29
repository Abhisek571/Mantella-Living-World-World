Scriptname MLWW_State extends MLWW_Job
{Mantella Living World - World: writes the player's standing to StorageUtilData/MantellaLivingWorld/world.json for
the Mantella side (fame and bounty per hold, war side, Thane titles, guild ranks, main quest stage, dated events from
the quest outcome table). Refreshed when a conversation starts and on every location change, at most once per 30
real seconds; a refresh asked for inside that window runs when it ends. Every value is set through JsonUtil's parsed
setters and the file is only saved after all of them succeeded, so the file on disk is always valid JSON.

Other World quests read hold, fame, bounty and Thane state through the functions at the end.}

string Property WORLD_FILE = "MantellaLivingWorld/world.json" AutoReadOnly
string Property OUTCOMES = "MantellaLivingWorld/quest_outcomes.json" AutoReadOnly
float Property THROTTLE = 30.0 AutoReadOnly
int Property FAME_MAX = 10 AutoReadOnly
int Property MAX_EVENTS = 20 AutoReadOnly
string Property KEY_SCANNED = "MLWW_Scanned" AutoReadOnly
string Property KEY_SEEN = "MLWW_Seen_" AutoReadOnly

string[] holdNames
Location[] holdLocs
Faction[] crimeFacs
int[] fameByHold
int thaneBits = 0
string warSideName = ""
int mqStageNow = 0
float lastWrite = -1000.0
bool pending = false
bool busy = false
bool refreshed = false

Function Register()
	Setup()
	lastWrite = -1000.0  ; real time restarts at 0 on every launch
	pending = false
	busy = false
	RegisterForModEvent("MantellaConversation_Started", "OnConversationStarted")
	RegisterForModEvent("MLW_ReportRequest", "OnReportRequest")
	RequestRefresh()
EndFunction

Function LocationChanged(Location akOldLoc, Location akNewLoc)
	RequestRefresh()
EndFunction

Event OnConversationStarted()
	RequestRefresh()
EndEvent

Event OnReportRequest()
	MLW_Hub hub = MLWW_Util.Hub()
	If !hub
		Return
	EndIf
	EnsureFresh()
	string line = "war side " + warSideName + ", main quest stage " + mqStageNow + ", thane holds " + ThaneCount()
	hub.ReportAdd("world", line)
	string fames = ""
	string bounties = ""
	int i = 0
	While i < holdNames.Length
		If fameByHold[i] > 0
			fames += holdNames[i] + " " + fameByHold[i] + " "
		EndIf
		If crimeFacs[i] && crimeFacs[i].GetCrimeGold() > 0
			bounties += holdNames[i] + " " + crimeFacs[i].GetCrimeGoldNonViolent() + "/" + crimeFacs[i].GetCrimeGoldViolent() + " "
		EndIf
		i += 1
	EndWhile
	hub.ReportAdd("world", "fame: " + fames)
	hub.ReportAdd("world", "bounty (non-violent/violent): " + bounties)
	hub.ReportAdd("world", "world.json valid: " + JsonUtil.IsGood(WORLD_FILE) + ", outcome rows " + JsonUtil.PathCount(OUTCOMES, ".rows"))
	i = 0
	While i < StorageUtil.StringListCount(None, "MLWW_Sent")
		hub.ReportAdd("world", "sent " + StorageUtil.StringListGet(None, "MLWW_Sent", i))
		i += 1
	EndWhile
EndEvent

; ---------------------------------------------------------------------------
; Refresh with throttle
; ---------------------------------------------------------------------------

Function RequestRefresh()
	float wait = lastWrite + THROTTLE - Utility.GetCurrentRealTime()
	If wait > 0.0 && wait <= THROTTLE
		If !pending
			pending = true
			RegisterForSingleUpdate(wait + 0.1)
		EndIf
		Return
	EndIf
	Refresh()
EndFunction

Event OnUpdate()
	pending = false
	Refresh()
EndEvent

Function EnsureFresh()
	If !refreshed || !fameByHold
		Refresh()
	EndIf
EndFunction

Function Refresh()
	If busy
		Return
	EndIf
	busy = true
	Setup()
	lastWrite = Utility.GetCurrentRealTime()
	float now = Utility.GetCurrentGameTime()
	; Rows already true on the first scan of this save happened before the module was installed: day -1.
	bool firstScan = !StorageUtil.HasIntValue(None, KEY_SCANNED)

	int[] newFame = new int[9]
	int newThane = 0
	string newWar = ""
	int newMq = 0
	string[] guildNames = new string[16]
	string[] guildRanks = new string[16]
	int guilds = 0
	string[] ids = new string[128]
	bool[] truth = new bool[128]
	string[] evJson = new string[128]
	float[] evDay = new float[128]
	int events = 0
	string player = MLWW_Util.PlayerName()

	int n = JsonUtil.PathCount(OUTCOMES, ".rows")
	If n > 128
		n = 128
	EndIf
	int i = 0
	While i < n
		string row = ".rows[" + i + "]"
		ids[i] = JsonUtil.GetPathStringValue(OUTCOMES, row + ".id")
		truth[i] = RowTrue(row, ids, truth, i)
		If truth[i]
			string seenKey = KEY_SEEN + ids[i]
			If !StorageUtil.HasFloatValue(None, seenKey)
				If firstScan
					StorageUtil.SetFloatValue(None, seenKey, -1.0)
				Else
					StorageUtil.SetFloatValue(None, seenKey, now)
				EndIf
			EndIf
			string[] audience = JsonUtil.PathStringElements(OUTCOMES, row + ".audience.holds")
			AddFame(newFame, audience, JsonUtil.GetPathIntValue(OUTCOMES, row + ".fame"))
			string hold = JsonUtil.GetPathStringValue(OUTCOMES, row + ".hold")
			If JsonUtil.GetPathStringValue(OUTCOMES, row + ".category") == "thane" && holdNames.Find(hold) >= 0
				newThane = Math.LogicalOr(newThane, Math.LeftShift(1, holdNames.Find(hold)))
			EndIf
			If JsonUtil.CanResolvePath(OUTCOMES, row + ".sets.war_side")
				newWar = JsonUtil.GetPathStringValue(OUTCOMES, row + ".sets.war_side")
			EndIf
			int stage = JsonUtil.GetPathIntValue(OUTCOMES, row + ".sets.mq_stage")
			If stage > newMq
				newMq = stage
			EndIf
			string guild = JsonUtil.GetPathStringValue(OUTCOMES, row + ".sets.guild")
			If guild != ""
				int g = guildNames.Find(guild)
				If g < 0 && guilds < 16
					g = guilds
					guildNames[g] = guild
					guilds += 1
				EndIf
				If g >= 0
					guildRanks[g] = JsonUtil.GetPathStringValue(OUTCOMES, row + ".sets.rank")
				EndIf
			EndIf
			evDay[events] = StorageUtil.GetFloatValue(None, seenKey, -1.0)
			string text = MLWW_Util.Replace(JsonUtil.GetPathStringValue(OUTCOMES, row + ".text"), "{player}", player)
			evJson[events] = "{\"day\":" + evDay[events] + ",\"id\":" + MLWW_Util.Quote(ids[i]) + ",\"text\":" + MLWW_Util.Quote(text) + ",\"holds\":" + MLWW_Util.QuoteAll(audience) + ",\"factions\":" + MLWW_Util.QuoteAll(JsonUtil.PathStringElements(OUTCOMES, row + ".audience.factions")) + ",\"named\":" + MLWW_Util.QuoteAll(JsonUtil.PathStringElements(OUTCOMES, row + ".audience.named")) + "}"
			events += 1
		EndIf
		i += 1
	EndWhile
	StorageUtil.SetIntValue(None, KEY_SCANNED, 1)
	AddStatFame(newFame)

	fameByHold = newFame
	thaneBits = newThane
	warSideName = newWar
	mqStageNow = newMq
	refreshed = true

	bool ok = Write(now, player, guildNames, guildRanks, guilds, evJson, evDay, events) && WriteQuests()
	If ok
		JsonUtil.Save(WORLD_FILE)
	Else
		MLWW_Util.Log("world.json not saved: a value did not parse")
	EndIf
	busy = false
EndFunction

; True when the row's condition holds and every row it requires (earlier in the table) is true.
bool Function RowTrue(string asRow, string[] akIds, bool[] akTruth, int aiIndex)
	string[] requires = JsonUtil.PathStringElements(OUTCOMES, asRow + ".requires")
	int r = 0
	While requires && r < requires.Length
		int j = akIds.Find(requires[r])
		If j < 0 || j >= aiIndex || !akTruth[j]
			Return false
		EndIf
		r += 1
	EndWhile
	Quest q = Game.GetFormFromFile(JsonUtil.GetPathIntValue(OUTCOMES, asRow + ".form"), JsonUtil.GetPathStringValue(OUTCOMES, asRow + ".plugin")) as Quest
	string when = asRow + ".when"
	string kind = JsonUtil.GetPathStringValue(OUTCOMES, when + ".type")
	If kind == "any" || kind == "all"
		bool needAll = kind == "all"
		int k = 0
		int count = JsonUtil.PathCount(OUTCOMES, when + ".of")
		If count <= 0
			Return false
		EndIf
		While k < count
			bool ok = Condition(when + ".of[" + k + "]", q)
			If ok && !needAll
				Return true
			ElseIf !ok && needAll
				Return false
			EndIf
			k += 1
		EndWhile
		Return needAll
	EndIf
	Return Condition(when, q)
EndFunction

bool Function Condition(string asPath, Quest akQuest)
	string kind = JsonUtil.GetPathStringValue(OUTCOMES, asPath + ".type")
	If kind == "completed"
		Return akQuest && akQuest.IsCompleted()
	ElseIf kind == "stage"
		Return akQuest && akQuest.GetStageDone(JsonUtil.GetPathIntValue(OUTCOMES, asPath + ".stage"))
	ElseIf kind == "dead" || kind == "alive"
		Actor who = Game.GetFormFromFile(JsonUtil.GetPathIntValue(OUTCOMES, asPath + ".form"), JsonUtil.GetPathStringValue(OUTCOMES, asPath + ".plugin")) as Actor
		If !who
			Return false
		EndIf
		Return who.IsDead() == (kind == "dead")
	EndIf
	Return false
EndFunction

Function AddFame(int[] akFame, string[] akHolds, int aiFame)
	If aiFame <= 0 || !akHolds
		Return
	EndIf
	bool everywhere = akHolds.Find("all") >= 0
	int i = 0
	While i < holdNames.Length
		If everywhere || akHolds.Find(holdNames[i]) >= 0
			akFame[i] = akFame[i] + aiFame
		EndIf
		i += 1
	EndWhile
EndFunction

; Vanilla stats add to fameByHold everywhere: dragons slain and quests done.
Function AddStatFame(int[] akFame)
	int bonus = 0
	If Game.QueryStat("Dragon Souls Collected") >= 5
		bonus += 1
	EndIf
	If Game.QueryStat("Quests Completed") >= 30
		bonus += 1
	EndIf
	int i = 0
	While i < akFame.Length
		akFame[i] = akFame[i] + bonus
		If akFame[i] > FAME_MAX
			akFame[i] = FAME_MAX
		EndIf
		i += 1
	EndWhile
EndFunction

bool Function Write(float afNow, string asPlayer, string[] akGuildNames, string[] akGuildRanks, int aiGuilds, string[] akEvents, float[] akDays, int aiEvents)
	bool ok = true
	string fames = "{"
	string bountyJson = "{"
	string violent = "{"
	string[] thane = new string[9]
	int t = 0
	int i = 0
	While i < holdNames.Length
		If i > 0
			fames += ","
			bountyJson += ","
			violent += ","
		EndIf
		fames += MLWW_Util.Quote(holdNames[i]) + ":" + fameByHold[i]
		int nonViolentGold = 0
		int violentGold = 0
		If crimeFacs[i]
			nonViolentGold = crimeFacs[i].GetCrimeGoldNonViolent()
			violentGold = crimeFacs[i].GetCrimeGoldViolent()
		EndIf
		bountyJson += MLWW_Util.Quote(holdNames[i]) + ":" + (nonViolentGold + violentGold)
		violent += MLWW_Util.Quote(holdNames[i]) + ":" + violentGold
		If IsThane(i)
			thane[t] = holdNames[i]
			t += 1
		EndIf
		i += 1
	EndWhile
	string thaneJson = "["
	i = 0
	While i < t
		If i > 0
			thaneJson += ","
		EndIf
		thaneJson += MLWW_Util.Quote(thane[i])
		i += 1
	EndWhile
	string guildJson = "{"
	i = 0
	While i < aiGuilds
		If i > 0
			guildJson += ","
		EndIf
		guildJson += MLWW_Util.Quote(akGuildNames[i]) + ":" + MLWW_Util.Quote(akGuildRanks[i])
		i += 1
	EndWhile
	ok = ok && JsonUtil.SetRawPathValue(WORLD_FILE, ".fame", fames + "}")
	ok = ok && JsonUtil.SetRawPathValue(WORLD_FILE, ".bounty", bountyJson + "}")
	ok = ok && JsonUtil.SetRawPathValue(WORLD_FILE, ".bounty_violent", violent + "}")
	ok = ok && JsonUtil.SetRawPathValue(WORLD_FILE, ".thane", thaneJson + "]")
	ok = ok && JsonUtil.SetRawPathValue(WORLD_FILE, ".guilds", guildJson + "}")
	ok = ok && JsonUtil.SetRawPathValue(WORLD_FILE, ".events", NewestEvents(akEvents, akDays, aiEvents))
	ok = ok && JsonUtil.SetRawPathValue(WORLD_FILE, ".war_side", MLWW_Util.Quote(warSideName))
	ok = ok && JsonUtil.SetRawPathValue(WORLD_FILE, ".player", MLWW_Util.Quote(asPlayer))
	string here = ""
	int h = CurrentHold()
	If h >= 0
		here = holdNames[h]
	EndIf
	ok = ok && JsonUtil.SetRawPathValue(WORLD_FILE, ".hold", MLWW_Util.Quote(here))
	JsonUtil.SetPathIntValue(WORLD_FILE, ".version", 1)
	JsonUtil.SetPathIntValue(WORLD_FILE, ".mq_stage", mqStageNow)
	JsonUtil.SetPathFloatValue(WORLD_FILE, ".day", afNow)
	Return ok
EndFunction

; Progress of the quests other modules ask about (Knowledge lists them in knowledge_quests.json, the quests its NPC
; knowledge depends on): ".quests" = current stage, ".quest_state" = 0 not started, 1 running, 2 done.
string Property QUESTS_WANTED = "MantellaLivingWorld/knowledge_quests.json" AutoReadOnly

bool Function WriteQuests()
	string stages = "{"
	string states = "{"
	int n = JsonUtil.StringListCount(QUESTS_WANTED, "quests")
	int i = 0
	int written = 0
	While i < n
		string id = JsonUtil.StringListGet(QUESTS_WANTED, "quests", i)
		Quest q = Quest.GetQuest(id)
		If q
			int progress = 0
			If q.IsCompleted()
				progress = 2
			ElseIf q.IsRunning() || q.GetStage() > 0
				progress = 1
			EndIf
			If written > 0
				stages += ","
				states += ","
			EndIf
			stages += MLWW_Util.Quote(id) + ":" + q.GetStage()
			states += MLWW_Util.Quote(id) + ":" + progress
			written += 1
		EndIf
		i += 1
	EndWhile
	bool ok = JsonUtil.SetRawPathValue(WORLD_FILE, ".quests", stages + "}")
	Return ok && JsonUtil.SetRawPathValue(WORLD_FILE, ".quest_state", states + "}")
EndFunction

; The newest MAX_EVENTS events as a JSON array, newest first (events from before install, day -1, come last).
string Function NewestEvents(string[] akEvents, float[] akDays, int aiCount)
	bool[] used = new bool[128]
	string out = "["
	int written = 0
	While written < MAX_EVENTS && written < aiCount
		int best = -1
		int i = 0
		While i < aiCount
			If !used[i] && (best < 0 || akDays[i] > akDays[best])
				best = i
			EndIf
			i += 1
		EndWhile
		used[best] = true
		If written > 0
			out += ","
		EndIf
		out += akEvents[best]
		written += 1
	EndWhile
	Return out + "]"
EndFunction

; ---------------------------------------------------------------------------
; Holds and the player's standing (used by the other World quests)
; ---------------------------------------------------------------------------

Function Setup()
	If holdNames && holdNames.Length == 9 && holdLocs[0] && crimeFacs[0]
		Return
	EndIf
	holdNames = new string[9]
	holdLocs = new Location[9]
	crimeFacs = new Faction[9]
	SetHold(0, "Whiterun", 0x016772, 0x0267EA)
	SetHold(1, "Haafingar", 0x016770, 0x029DB0)
	SetHold(2, "Eastmarch", 0x01676A, 0x0267E3)
	SetHold(3, "Rift", 0x01676C, 0x02816B)
	SetHold(4, "Reach", 0x016769, 0x02816C)
	SetHold(5, "Pale", 0x01676D, 0x02816E)
	SetHold(6, "Falkreath", 0x01676F, 0x028170)
	SetHold(7, "Hjaalmarch", 0x01676E, 0x02816D)
	SetHold(8, "Winterhold", 0x01676B, 0x02816F)
	If !fameByHold
		fameByHold = new int[9]
	EndIf
EndFunction

Function SetHold(int aiIndex, string asName, int aiLocation, int aiCrimeFaction)
	holdNames[aiIndex] = asName
	holdLocs[aiIndex] = Game.GetFormFromFile(aiLocation, "Skyrim.esm") as Location
	crimeFacs[aiIndex] = Game.GetFormFromFile(aiCrimeFaction, "Skyrim.esm") as Faction
EndFunction

int Function HoldCount()
	Return 9
EndFunction

string Function HoldName(int aiHold)
	Setup()
	If aiHold < 0 || aiHold >= 9
		Return ""
	EndIf
	Return holdNames[aiHold]
EndFunction

; "the Reach", "Whiterun": the hold as it reads in a sentence.
string Function HoldText(int aiHold)
	string name = HoldName(aiHold)
	If name == "Reach" || name == "Pale" || name == "Rift"
		Return "the " + name
	EndIf
	Return name
EndFunction

int Function HoldOfLocation(Location akLocation)
	Setup()
	If !akLocation
		Return -1
	EndIf
	int i = 0
	While i < 9
		If holdLocs[i] && (akLocation == holdLocs[i] || holdLocs[i].IsChild(akLocation))
			Return i
		EndIf
		i += 1
	EndWhile
	Return -1
EndFunction

int Function HoldOfFaction(Faction akCrimeFaction)
	Setup()
	If !akCrimeFaction
		Return -1
	EndIf
	Return crimeFacs.Find(akCrimeFaction)
EndFunction

; The hold the player is in now (-1 in the wilds of no hold, or outside Skyrim).
int Function CurrentHold()
	Return HoldOfLocation(PlayerRef.GetCurrentLocation())
EndFunction

; Where an NPC belongs: their editor location's hold, else their crime faction's.
int Function ActorHold(Actor akActor)
	int h = HoldOfLocation(akActor.GetEditorLocation())
	If h < 0
		h = HoldOfFaction(akActor.GetCrimeFaction())
	EndIf
	Return h
EndFunction

Faction Function CrimeFaction(int aiHold)
	Setup()
	If aiHold < 0 || aiHold >= 9
		Return None
	EndIf
	Return crimeFacs[aiHold]
EndFunction

int Function Fame(int aiHold)
	EnsureFresh()
	If aiHold < 0 || aiHold >= 9
		Return 0
	EndIf
	Return fameByHold[aiHold]
EndFunction

; Total bountyJson (non-violent + violent) in a hold.
int Function Bounty(int aiHold)
	Faction f = CrimeFaction(aiHold)
	If !f
		Return 0
	EndIf
	Return f.GetCrimeGold()
EndFunction

bool Function IsThane(int aiHold)
	If aiHold < 0 || aiHold >= 9
		Return false
	EndIf
	Return Math.LogicalAnd(thaneBits, Math.LeftShift(1, aiHold)) != 0
EndFunction

int Function ThaneMask()
	EnsureFresh()
	Return thaneBits
EndFunction

int Function ThaneCount()
	int count = 0
	int i = 0
	While i < 9
		If IsThane(i)
			count += 1
		EndIf
		i += 1
	EndWhile
	Return count
EndFunction

; "Legion", "Stormcloaks" or "".
string Function WarSide()
	EnsureFresh()
	Return warSideName
EndFunction

int Function MainQuestStage()
	EnsureFresh()
	Return mqStageNow
EndFunction

; Testing: forces a refresh now, ignoring the throttle.
Function TestRefresh()
	lastWrite = -1000.0
	Refresh()
EndFunction
