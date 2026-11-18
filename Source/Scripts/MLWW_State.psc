Scriptname MLWW_State extends MLWW_Job
{Mantella Living World - World: writes the player's standing to StorageUtilData/MantellaLivingWorld/world.json for
the Mantella side (fame and bounty per hold, war side, Thane titles, guild ranks, main quest stage, dated events from
the quest outcome table, and the progress of the quests Knowledge asks about).

Three kinds of refresh, run one at a time (a refresh asked for while one runs is kept and runs right after it):
- full scan: the outcome table plus every asked-for quest, read in one call by World's SKSE plugin. Runs a short while
  after a save is loaded, after sleeping or waiting, and when a game day has passed since the last full scan (sleeping
  and the day check share one timer). One that becomes due during a Mantella talk or a fight waits until it ends.
- quest batch: the plugin hears quest stage and start/stop events; the changed quests are re-read at most once per
  QUEST_COOLDOWN real seconds, and changes in between are collected for the next batch. The outcome table is only
  looked at again when one of its quests changed or a named NPC died.
- cheap: fame, bounty, the hold the player is in, name and day. At a talk start and on location changes (at most once
  per THROTTLE real seconds there). Never a quest scan.
The values of the last scan are kept in the save, so world.json is written from them as soon as a save is loaded and
readers never have to skip it. Every value is set through JsonUtil's parsed setters and the file is saved once at the
end of a refresh, so the file on disk is always valid JSON.

Other World quests read hold, fame, bounty and Thane state through the functions at the end.}

string Property WORLD_FILE = "MantellaLivingWorld/world.json" AutoReadOnly
string Property OUTCOMES = "MantellaLivingWorld/quest_outcomes.json" AutoReadOnly
float Property THROTTLE = 30.0 AutoReadOnly        ; cheap refresh on location changes, at most once per this
float Property SETTLE = 15.0 AutoReadOnly          ; real seconds after a load before the full scan
float Property QUEST_COOLDOWN = 60.0 AutoReadOnly  ; quest batches at most once per this
float Property BUSY_RETRY = 10.0 AutoReadOnly      ; a full scan waiting for a talk or fight to end looks again after this
float Property TALK_FRESH = 5.0 AutoReadOnly       ; a talk start this soon after a cheap refresh does not repeat it
int Property FAME_MAX = 10 AutoReadOnly
int Property MAX_EVENTS = 128 AutoReadOnly  ; every true row; the Hub picks per audience
string Property KEY_SCANNED = "MLWW_Scanned" AutoReadOnly
; The long JSON (quest progress, outcome events) is kept in PapyrusUtil's storage, never in a script variable: a saved
; Papyrus string of several KB makes the save crash on load (the quest table alone is over 5 KB).
string Property KEY_EVENTS = "MLWW_EventJson" AutoReadOnly
string Property KEY_QUEST_STAGES = "MLWW_QuestStagesJson" AutoReadOnly
string Property KEY_QUEST_STATES = "MLWW_QuestStatesJson" AutoReadOnly
string Property KEY_SEEN = "MLWW_Seen_" AutoReadOnly
string Property KEY_DUNGEONS = "MLWW_DungeonsSeen" AutoReadOnly

string[] holdNames
Location[] holdLocs
Faction[] crimeFacs
int[] fameByHold
int thaneBits = 0
string warSideName = ""
int mqStageNow = 0
bool dungeonBusy = false

; What the last full scan or quest batch found (kept in the save: written again at once after a load).
bool cached = false
int[] rowFame          ; fame from the outcome table, before the stat bonus
string guildJson = "{}"
float lastFullDay = -1000.0  ; game time of the last full scan
string lastWhy = ""
float lastTook = 0.0
int questCount = 0
int batches = 0

; Scheduling (reset on every load: real time restarts at 0 on every launch).
bool busy = false
bool again = false
int pumpGen = 0  ; Register adds one: a Pump loop the save kept running from before the load stops
bool cheapDue = false
float cheapAt = 0.0
bool fullDue = false
float fullAt = 0.0
string fullWhy = ""
bool questDue = false
float questAt = 0.0
bool deathDue = false
float lastCheap = -1000.0
float menuFrom = -1.0
Quest[] watch          ; outcome-table quests met during a scan, handed to the plugin
int watchCount = 0

Function Register()
	Setup()
	pumpGen += 1
	busy = false
	again = false
	dungeonBusy = false
	cheapDue = false
	questDue = false
	questAt = 0.0
	lastCheap = -1000.0
	menuFrom = -1.0
	RegisterForModEvent("MantellaConversation_Started", "OnConversationStarted")
	RegisterForModEvent("MLW_ReportRequest", "OnReportRequest")
	RegisterForModEvent("MLWW_QuestChanged", "OnQuestChanged")
	RegisterForModEvent("MLWW_Died", "OnNamedDeath")
	RegisterForMenu("Sleep/Wait Menu")
	RegisterForSleep()
	If cached
		; this save's own values, written now (no game calls), so readers never skip world.json while the scan waits
		WriteOutcomes()
		WriteQuestJson()
		float left = (lastFullDay + 1.0 - Utility.GetCurrentGameTime()) * 24.0
		If left < 0.1
			left = 0.1
		EndIf
		RegisterForSingleUpdateGameTime(left)
	Else
		; a save from before this version, or a new game: nothing kept yet, so readers skip the file until the first scan
		JsonUtil.SetPathIntValue(WORLD_FILE, ".loading", 1)
	EndIf
	DueCheap(0.0)
	fullDue = false  ; a due time kept from before the load is not this load's: the full scan waits SETTLE seconds
	DueFull("load", Utility.GetCurrentRealTime() + SETTLE)
	Pump()
EndFunction

; The dungeon count is read first: a refresh is long, and a second location change during it must not read the count
; with the wrong place left.
Function LocationChanged(Location akOldLoc, Location akNewLoc)
	CheckDungeons(akOldLoc)
	DueCheap(lastCheap + THROTTLE)
	Pump()
EndFunction

; The vanilla count rises while the player is inside, so the place just left is the dungeon: everyone in the party now
; gets it. The first check on a save only takes the count. afWait: Party() only has followers who are loaded and close,
; and after a load door they arrive a moment after the player.
; dungeonBusy: two location changes close together (nested locations) would both read the old count before either
; writes it; the second check is skipped while the first one runs, its wait included.
Function CheckDungeons(Location akLeft, float afWait = 5.0)
	If dungeonBusy
		Return
	EndIf
	dungeonBusy = true
	int cleared = Game.QueryStat("Dungeons Cleared")
	int seen = StorageUtil.GetIntValue(None, KEY_DUNGEONS, -1)
	If cleared == seen
		dungeonBusy = false
		Return
	EndIf
	StorageUtil.SetIntValue(None, KEY_DUNGEONS, cleared)
	If seen < 0 || cleared < seen
		dungeonBusy = false
		Return
	EndIf
	string name = ""
	If akLeft
		name = akLeft.GetName()
	EndIf
	If afWait > 0.0
		Utility.Wait(afWait)
	EndIf
	Actor[] party = MLWW_Native.Party()
	int i = 0
	While party && i < party.Length
		MLWW_Facts.Dungeon(party[i], name, cleared - seen)
		MLWW_Facts.Score(party[i], "deeds", 2.0)
		MLWW_Facts.Sync(party[i])
		i += 1
	EndWhile
	dungeonBusy = false
EndFunction

; A talk start only gets the cheap refresh: no quest scan.
Event OnConversationStarted()
	If StorageUtil.GetIntValue(None, "MLW_TimingOn", 0) == 1  ; speed testing (off by default): one stage-time row
		MiscUtil.WriteToFile("Data/SKSE/Plugins/StorageUtilData/MantellaLivingWorld/timing_game.csv", StorageUtil.GetIntValue(None, "MLW_TimingTalk", 0) + "," + Utility.GetCurrentRealTime() + ",MLWW_State,OnConversationStarted_start,\n", true, false)
	EndIf
	If Utility.GetCurrentRealTime() - lastCheap >= TALK_FRESH
		DueCheap(0.0)
	EndIf
	Pump()
	If StorageUtil.GetIntValue(None, "MLW_TimingOn", 0) == 1  ; speed testing (off by default): one stage-time row
		MiscUtil.WriteToFile("Data/SKSE/Plugins/StorageUtilData/MantellaLivingWorld/timing_game.csv", StorageUtil.GetIntValue(None, "MLW_TimingTalk", 0) + "," + Utility.GetCurrentRealTime() + ",MLWW_State,OnConversationStarted_end,\n", true, false)
	EndIf
EndEvent

; Sent by the plugin once per batch of quest stage or start/stop changes (ReadChangedQuests takes them all).
Event OnQuestChanged(string asEventName, string asText, float afNum, Form akSender)
	DueQuests()
EndEvent

; A named NPC died: the outcome table's dead/alive rows are looked at with the next quest batch.
Event OnNamedDeath(string asEventName, string asText, float afNum, Form akSender)
	deathDue = true
	DueQuests()
EndEvent

Event OnMenuOpen(string asMenuName)
	menuFrom = Utility.GetCurrentGameTime()
EndEvent

Event OnSleepStart(float afSleepStartTime, float afDesiredSleepEndTime)
	menuFrom = afSleepStartTime
EndEvent

; Waiting (and sleeping) closes this menu after the hours passed. Sleep also sends OnSleepStop: both ask, one scan.
Event OnMenuClose(string asMenuName)
	Rested("sleep or wait")
	menuFrom = -1.0
EndEvent

Event OnSleepStop(bool abInterrupted)
	Rested("sleep")
EndEvent

; A full scan after a rest of about a quarter of an hour or more, unless one already ran since the rest began.
Function Rested(string asWhy)
	float now = Utility.GetCurrentGameTime()
	If menuFrom >= 0.0 && now - menuFrom > 0.01 && lastFullDay < menuFrom
		DueFull(asWhy, 0.0)
		Pump()
	EndIf
EndFunction

Event OnUpdate()
	Pump()
EndEvent

; The day check: armed for one game day after each full scan.
Event OnUpdateGameTime()
	Pump()
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
	hub.ReportAdd("world", "last full scan: game day " + lastFullDay + " (" + lastWhy + "), " + questCount + " quests, " + lastTook + " s; quest batches since load " + batches + "; full scan waiting " + fullDue)
	i = 0
	While i < StorageUtil.StringListCount(None, "MLWW_Sent")
		hub.ReportAdd("world", "sent " + StorageUtil.StringListGet(None, "MLWW_Sent", i))
		i += 1
	EndWhile
EndEvent

; ---------------------------------------------------------------------------
; Scheduling
; ---------------------------------------------------------------------------

Function DueCheap(float afAt)
	If !cheapDue || afAt < cheapAt
		cheapAt = afAt
	EndIf
	cheapDue = true
EndFunction

Function DueFull(string asWhy, float afAt)
	If !fullDue || afAt < fullAt
		fullAt = afAt
		fullWhy = asWhy
	EndIf
	fullDue = true
EndFunction

Function DueQuests()
	If !questDue
		questDue = true
		Pump()
	EndIf
EndFunction

; Runs whatever is due, one refresh at a time. A call while one runs sets again, and the running call goes round once
; more before it lets go, so no request is lost (it used to be dropped).
; Papyrus keeps running calls in the save: a save made during a Pump resumes that loop after loading, while Register
; clears busy and starts its own. The old loop sees pumpGen change and stops after its current step without touching
; busy, so only one loop runs.
Function Pump(bool abForce = false)
	If busy
		again = true
		Return
	EndIf
	busy = true
	again = true
	int gen = pumpGen
	While again && gen == pumpGen
		again = false
		Step(abForce)
	EndWhile
	If gen == pumpGen
		busy = false
		Schedule()
	EndIf
EndFunction

Function Step(bool abForce)
	float now = Utility.GetCurrentRealTime()
	bool wrote = false
	If questDue && now >= questAt
		questDue = false
		questAt = now + QUEST_COOLDOWN
		wrote = QuestBatch()
	EndIf
	If !fullDue && cached && Utility.GetCurrentGameTime() - lastFullDay >= 1.0
		DueFull("day", 0.0)
	EndIf
	If fullDue && now >= fullAt
		If !abForce && Occupied()
			fullAt = now + BUSY_RETRY
		Else
			fullDue = false
			FullScan(fullWhy)
			wrote = true
		EndIf
	EndIf
	If cheapDue && now >= cheapAt
		cheapDue = false
		Cheap()
		wrote = true
	EndIf
	If wrote
		JsonUtil.Save(WORLD_FILE)
	EndIf
EndFunction

; The next real-time wake-up for whatever is still due.
Function Schedule()
	float next = -1.0
	If questDue
		next = questAt
	EndIf
	If fullDue && (next < 0.0 || fullAt < next)
		next = fullAt
	EndIf
	If cheapDue && (next < 0.0 || cheapAt < next)
		next = cheapAt
	EndIf
	If next >= 0.0
		float wait = next - Utility.GetCurrentRealTime()
		If wait < 0.1
			wait = 0.1
		EndIf
		RegisterForSingleUpdate(wait)
	EndIf
EndFunction

; A Mantella talk is running or the player is fighting: a full scan waits.
bool Function Occupied()
	If PlayerRef.IsInCombat()
		Return true
	EndIf
	MantellaConversation talk = Game.GetFormFromFile(0x03D41A, "Mantella.esp") as MantellaConversation
	Return talk && talk.IsRunning()
EndFunction

; No scan of this save yet (a new game, the first load after install): one is asked for and runs from the scheduler, never
; inside the caller (a talk's NPC_Added handler would wait out the whole scan). Until then the getters give their
; defaults, and callers that would say something wrong from them check Ready first.
Function EnsureFresh()
	If !cached && !busy
		DueFull("asked", 0.0)
		Schedule()
	EndIf
EndFunction

; True once this save has had its first full scan: fame, Thane holds and the war side are real values.
bool Function Ready()
	EnsureFresh()
	Return cached
EndFunction

; ---------------------------------------------------------------------------
; The three refreshes (each only sets values; Step saves the file)
; ---------------------------------------------------------------------------

Function FullScan(string asWhy)
	float started = Utility.GetCurrentRealTime()
	lastFullDay = Utility.GetCurrentGameTime()  ; first: a rest event arriving while this runs needs no second scan
	EvalOutcomes()
	ReadAllQuests()
	cached = true  ; before Cheap: it clears loading only once there is something of this save's to show
	Cheap()
	cheapDue = false
	lastWhy = asWhy
	lastTook = Utility.GetCurrentRealTime() - started
	RegisterForSingleUpdateGameTime(24.0)
	MLWW_Util.Log("world.json: full scan (" + asWhy + "), " + questCount + " quests, " + lastTook + " s")
EndFunction

; Only the quests that changed since the last read; the outcome table only when one of its quests changed or a named
; NPC died. True when something was set.
bool Function QuestBatch()
	int changed = MLWW_Native.ReadChangedQuests()
	bool table = MLWW_Native.OutcomeQuestsChanged() || deathDue
	deathDue = false
	batches += 1
	If changed > 0
		KeepQuestJson()
		WriteQuestJson()
	EndIf
	If table
		EvalOutcomes()
		WriteFame()
	EndIf
	MLWW_Util.Log("world.json: quest batch, " + changed + " asked-for quests changed, outcome table " + table)
	Return changed > 0 || table
EndFunction

; Every quest Knowledge asks about (knowledge_quests.json; none when Knowledge is not installed), read by the plugin.
Function ReadAllQuests()
	string[] wanted = JsonUtil.StringListToArray(QUESTS_WANTED, "quests")
	questCount = MLWW_Native.ReadQuests(wanted)
	KeepQuestJson()
	WriteQuestJson()
EndFunction

; Fame, bounty, the hold the player is in, name and day: about 35 quick game calls.
Function Cheap()
	lastCheap = Utility.GetCurrentRealTime()
	Setup()
	bool ok = WriteFame()
	string bountyJson = "{"
	string violent = "{"
	int i = 0
	While i < holdNames.Length
		If i > 0
			bountyJson += ","
			violent += ","
		EndIf
		int nonViolentGold = 0
		int violentGold = 0
		If crimeFacs[i]
			nonViolentGold = crimeFacs[i].GetCrimeGoldNonViolent()
			violentGold = crimeFacs[i].GetCrimeGoldViolent()
		EndIf
		bountyJson += MLWW_Util.Quote(holdNames[i]) + ":" + (nonViolentGold + violentGold)
		violent += MLWW_Util.Quote(holdNames[i]) + ":" + violentGold
		i += 1
	EndWhile
	ok = ok && JsonUtil.SetRawPathValue(WORLD_FILE, ".bounty", bountyJson + "}")
	ok = ok && JsonUtil.SetRawPathValue(WORLD_FILE, ".bounty_violent", violent + "}")
	ok = ok && JsonUtil.SetRawPathValue(WORLD_FILE, ".player", MLWW_Util.Quote(MLWW_Util.PlayerName()))
	string here = ""
	int h = CurrentHold()
	If h >= 0
		here = holdNames[h]
	EndIf
	ok = ok && JsonUtil.SetRawPathValue(WORLD_FILE, ".hold", MLWW_Util.Quote(here))
	JsonUtil.SetPathIntValue(WORLD_FILE, ".version", 1)
	JsonUtil.SetPathFloatValue(WORLD_FILE, ".day", Utility.GetCurrentGameTime())
	If !ok
		MLWW_Util.Log("world.json: a value did not parse; that value keeps its last state")
	EndIf
	If cached
		; saved with loading 0 even when a value did not parse: the values that did are this game's, and a file left at
		; loading 1 would be skipped by every reader for the rest of the session
		JsonUtil.SetPathIntValue(WORLD_FILE, ".loading", 0)
	EndIf
EndFunction

; ---------------------------------------------------------------------------
; The outcome table
; ---------------------------------------------------------------------------

Function EvalOutcomes()
	Setup()
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
	string[] evId = new string[128]
	string[] gone = new string[128]  ; rows a later true row supersedes ("is the Harbinger" over "joined the Circle")
	int goneCount = 0
	int events = 0
	string player = MLWW_Util.PlayerName()
	watch = new Quest[128]
	watchCount = 0

	int n = JsonUtil.PathCount(OUTCOMES, ".rows")
	If n > 128
		MLWW_Util.Log("quest_outcomes.json: " + n + " rows, only the first 128 are read")
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
			string[] supersedes = JsonUtil.PathStringElements(OUTCOMES, row + ".supersedes")
			int s = 0
			While supersedes && s < supersedes.Length && goneCount < 128
				gone[goneCount] = supersedes[s]
				goneCount += 1
				s += 1
			EndWhile
			evId[events] = ids[i]
			evDay[events] = StorageUtil.GetFloatValue(None, seenKey, -1.0)
			string text = MLWW_Util.Replace(JsonUtil.GetPathStringValue(OUTCOMES, row + ".text"), "{player}", player)
			evJson[events] = "{\"day\":" + evDay[events] + ",\"id\":" + MLWW_Util.Quote(ids[i]) + ",\"text\":" + MLWW_Util.Quote(text) + ",\"holds\":" + MLWW_Util.QuoteAll(audience) + ",\"factions\":" + MLWW_Util.QuoteAll(JsonUtil.PathStringElements(OUTCOMES, row + ".audience.factions")) + ",\"named\":" + MLWW_Util.QuoteAll(JsonUtil.PathStringElements(OUTCOMES, row + ".audience.named")) + "}"
			events += 1
		EndIf
		i += 1
	EndWhile
	StorageUtil.SetIntValue(None, KEY_SCANNED, 1)
	MLWW_Native.WatchOutcomeQuests(watch)
	; Superseded rows keep their fame and sets (the later deed implies them) but are not told as events.
	int kept = 0
	i = 0
	While i < events
		If goneCount == 0 || gone.Find(evId[i]) < 0
			evJson[kept] = evJson[i]
			evDay[kept] = evDay[i]
			kept += 1
		EndIf
		i += 1
	EndWhile
	events = kept

	string guildsOut = "{"
	i = 0
	While i < guilds
		If i > 0
			guildsOut += ","
		EndIf
		guildsOut += MLWW_Util.Quote(guildNames[i]) + ":" + MLWW_Util.Quote(guildRanks[i])
		i += 1
	EndWhile

	rowFame = newFame
	thaneBits = newThane
	warSideName = newWar
	mqStageNow = newMq
	guildJson = guildsOut + "}"
	StorageUtil.SetStringValue(None, KEY_EVENTS, NewestEvents(evJson, evDay, events))
	WriteOutcomes()
EndFunction

; True when the row's condition holds and every row it requires (earlier in the table) is true. The row's quest goes on
; the watch list: only a quest whose row got this far can change the row (a required row changes with its own quest).
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
	If q && watchCount < 128
		watch[watchCount] = q
		watchCount += 1
	EndIf
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

; ---------------------------------------------------------------------------
; Writers (JsonUtil only; the file is saved by Step)
; ---------------------------------------------------------------------------

; Fame per hold: the outcome table's fame plus the vanilla stats (dragons slain, quests done) everywhere.
bool Function WriteFame()
	int bonus = 0
	If Game.QueryStat("Dragon Souls Collected") >= 5
		bonus += 1
	EndIf
	If Game.QueryStat("Quests Completed") >= 30
		bonus += 1
	EndIf
	int[] fame = new int[9]
	string fames = "{"
	int i = 0
	While i < 9
		If rowFame
			fame[i] = rowFame[i]
		EndIf
		fame[i] = fame[i] + bonus
		If fame[i] > FAME_MAX
			fame[i] = FAME_MAX
		EndIf
		If i > 0
			fames += ","
		EndIf
		fames += MLWW_Util.Quote(holdNames[i]) + ":" + fame[i]
		i += 1
	EndWhile
	fameByHold = fame
	Return JsonUtil.SetRawPathValue(WORLD_FILE, ".fame", fames + "}")
EndFunction

bool Function WriteOutcomes()
	Setup()
	string thaneJson = "["
	int t = 0
	int i = 0
	While i < 9
		If IsThane(i)
			If t > 0
				thaneJson += ","
			EndIf
			thaneJson += MLWW_Util.Quote(holdNames[i])
			t += 1
		EndIf
		i += 1
	EndWhile
	bool ok = JsonUtil.SetRawPathValue(WORLD_FILE, ".thane", thaneJson + "]")
	ok = JsonUtil.SetRawPathValue(WORLD_FILE, ".guilds", guildJson) && ok
	ok = JsonUtil.SetRawPathValue(WORLD_FILE, ".events", StorageUtil.GetStringValue(None, KEY_EVENTS, "[]")) && ok
	ok = JsonUtil.SetRawPathValue(WORLD_FILE, ".war_side", MLWW_Util.Quote(warSideName)) && ok
	JsonUtil.SetPathIntValue(WORLD_FILE, ".mq_stage", mqStageNow)
	If !ok
		MLWW_Util.Log("world.json: an outcome value did not parse; that value keeps its last state")
	EndIf
	Return ok
EndFunction

; Progress of the quests other modules ask about (Knowledge lists them in knowledge_quests.json, the quests its NPC
; knowledge depends on): ".quests" = current stage, ".quest_state" = 0 not started, 1 running, 2 done. Keyed by the ids
; as Knowledge lists them (the plugin writes the JSON).
string Property QUESTS_WANTED = "MantellaLivingWorld/knowledge_quests.json" AutoReadOnly

Function KeepQuestJson()
	StorageUtil.SetStringValue(None, KEY_QUEST_STAGES, MLWW_Native.QuestStagesJson())
	StorageUtil.SetStringValue(None, KEY_QUEST_STATES, MLWW_Native.QuestStatesJson())
EndFunction

bool Function WriteQuestJson()
	string questStages = StorageUtil.GetStringValue(None, KEY_QUEST_STAGES, "")
	string questStates = StorageUtil.GetStringValue(None, KEY_QUEST_STATES, "")
	If questStages == "" || questStates == ""
		Return true  ; nothing read yet (or the plugin is missing): the file keeps what it has
	EndIf
	bool ok = JsonUtil.SetRawPathValue(WORLD_FILE, ".quests", questStages)
	ok = JsonUtil.SetRawPathValue(WORLD_FILE, ".quest_state", questStates) && ok
	If !ok
		MLWW_Util.Log("world.json: the quest progress did not parse; it keeps its last state")
	EndIf
	Return ok
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
	If aiHold < 0 || aiHold >= 9 || !fameByHold
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

; Testing: a full scan now, ignoring a running talk or fight.
Function TestRefresh()
	DueFull("test", 0.0)
	Pump(true)
EndFunction
