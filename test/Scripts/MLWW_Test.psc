Scriptname MLWW_Test Hidden
{Test build only (never shipped): global functions DevBench calls to drive the World module's live tests.}

string Function PLUGIN() global
	Return "Mantella Living World - World.esp"
EndFunction

MLWW_State Function WorldState() global
	Return Game.GetFormFromFile(0x000800, PLUGIN()) as MLWW_State
EndFunction
MLWW_Meetings Function Meetings() global
	Return Game.GetFormFromFile(0x000801, PLUGIN()) as MLWW_Meetings
EndFunction
MLWW_Recognition Function Recognition() global
	Return Game.GetFormFromFile(0x000802, PLUGIN()) as MLWW_Recognition
EndFunction
MLWW_Pairs Function Pairs() global
	Return Game.GetFormFromFile(0x000803, PLUGIN()) as MLWW_Pairs
EndFunction
MLWW_Crime Function Crime() global
	Return Game.GetFormFromFile(0x000804, PLUGIN()) as MLWW_Crime
EndFunction

; Every quest running and its events registered.
string Function Status() global
	Return "state=" + WorldState().IsRunning() + " meetings=" + Meetings().IsRunning() + " recognition=" + Recognition().IsRunning() + " pairs=" + Pairs().IsRunning() + " crime=" + Crime().IsRunning() + " hold=" + WorldState().HoldName(WorldState().CurrentHold()) + " sent=" + StorageUtil.StringListCount(None, "MLWW_Sent")
EndFunction

; Re-runs every quest's registration, as a game load does.
string Function Reload() global
	WorldState().Register()
	Meetings().Register()
	Recognition().Register()
	Pairs().Register()
	Crime().Register()
	Return "registered"
EndFunction

; F1
string Function Refresh() global
	WorldState().TestRefresh()
	Return "saved good=" + JsonUtil.IsGood(WorldState().WORLD_FILE) + " errors=" + JsonUtil.GetErrors(WorldState().WORLD_FILE)
EndFunction

string Function SetBounty(int aiHold, int aiNonViolent, int aiViolent) global
	Faction f = WorldState().CrimeFaction(aiHold)
	f.SetCrimeGold(aiNonViolent)
	f.SetCrimeGoldViolent(aiViolent)
	Return Bounty(aiHold)
EndFunction

string Function Bounty(int aiHold) global
	Faction f = WorldState().CrimeFaction(aiHold)
	Return f.GetCrimeGoldNonViolent() + "/" + f.GetCrimeGoldViolent()
EndFunction

; Mantella conversation events, as Mantella sends them.
string Function Join(Actor akActor) global
	int handle = ModEvent.Create("MantellaConversation_NPC_Added")
	ModEvent.PushForm(handle, akActor)
	ModEvent.Send(handle)
	Return "sent"
EndFunction

string Function Leave(Actor akActor) global
	int handle = ModEvent.Create("MantellaConversation_NPC_Removed")
	ModEvent.PushForm(handle, akActor)
	ModEvent.Send(handle)
	Return "sent"
EndFunction

string Function EndConversation() global
	int handle = ModEvent.Create("MantellaConversation_Ended")
	ModEvent.Send(handle)
	Return "sent"
EndFunction

string Function LastSent() global
	int n = StorageUtil.StringListCount(None, "MLWW_Sent")
	If n == 0
		Return ""
	EndIf
	Return StorageUtil.StringListGet(None, "MLWW_Sent", n - 1)
EndFunction

int Function SentCount() global
	Return StorageUtil.StringListCount(None, "MLWW_Sent")
EndFunction

string Function ClearSent() global
	StorageUtil.StringListClear(None, "MLWW_Sent")
	Return "cleared"
EndFunction

; F3: pretend the last meeting was afDays earlier.
string Function AgeMeeting(Actor akActor, float afDays) global
	StorageUtil.AdjustFloatValue(akActor, "MLWW_LastMetDay", -afDays)
	Return "last met day " + StorageUtil.GetFloatValue(akActor, "MLWW_LastMetDay")
EndFunction

string Function ForgetMeeting(Actor akActor) global
	StorageUtil.UnsetFloatValue(akActor, "MLWW_LastMetDay")
	StorageUtil.IntListClear(akActor, "MLWW_LastMetSnapshot")
	Return "forgotten"
EndFunction

; F4: writes observation into the NPC's Knowledge file (npc/<baseid>.json).
string Function SetObservation(Actor akActor, int aiValue) global
	string file = "MantellaLivingWorld/npc/" + MLWW_Util.BaseId(akActor) + ".json"
	JsonUtil.SetPathIntValue(file, ".observation", aiValue)
	JsonUtil.Save(file)
	JsonUtil.Unload(file, false)
	Return file + " observation=" + aiValue
EndFunction

string Function Verdict(Actor akActor) global
	Return Recognition().Verdict(akActor)
EndFunction

; F5
int Function PairLevel(Actor akA, Actor akB) global
	Return Pairs().Level(akA, akB)
EndFunction

string Function PairLine(Actor akA, Actor akB) global
	Return Pairs().Line(akA, akB, Pairs().Level(akA, akB))
EndFunction

; F6
string Function Settle(Actor akSpeaker, string asMethod) global
	Return Crime().Settle(akSpeaker, asMethod)
EndFunction

string Function ReportNoWitness(Actor akSpeaker, string asCrime) global
	Return Crime().Report(akSpeaker, None, asCrime)
EndFunction

int Function BribeCost(int aiBounty) global
	Return Crime().BribeCost(aiBounty)
EndFunction

string Function ResetPersuade(int aiHold) global
	StorageUtil.UnsetIntValue(None, "MLWW_PersuadeDay_" + WorldState().HoldName(aiHold))
	Return "reset"
EndFunction

int Function Gold() global
	Return Game.GetPlayer().GetItemCount(Game.GetFormFromFile(0x00000F, "Skyrim.esm"))
EndFunction

string Function GiveGold(int aiAmount) global
	Game.GetPlayer().AddItem(Game.GetFormFromFile(0x00000F, "Skyrim.esm"), aiAmount, true)
	Return "gold " + Gold()
EndFunction

; Lines sent by one job ("meetings", "recognition", "pairs", "crime").
int Function SentCountOf(string asSource) global
	int count = 0
	int i = 0
	int n = StorageUtil.StringListCount(None, "MLWW_Sent")
	While i < n
		If StringUtil.Find(StorageUtil.StringListGet(None, "MLWW_Sent", i), asSource + ": ") == 0
			count += 1
		EndIf
		i += 1
	EndWhile
	Return count
EndFunction

; --- banter, initiative, pacing (F9-F10) ---
MLWW_Banter Function Banter() global
	Return Game.GetFormFromFile(0x000805, PLUGIN()) as MLWW_Banter
EndFunction
MLWW_Initiative Function Initiative() global
	Return Game.GetFormFromFile(0x000806, PLUGIN()) as MLWW_Initiative
EndFunction

; Sends the listener plugin's event as if akSpeaker had just said asText (sender = the speaker).
string Function FakeVoicedLine(Actor akSpeaker, string asText) global
	akSpeaker.SendModEvent("MLWW_VoicedLine", asText, akSpeaker.GetDistance(Game.GetPlayer()))
	Return "sent"
EndFunction

; Banter chance to 100 (or back) so a test does not depend on the roll.
string Function BanterChance(int aiPercent) global
	GlobalVariable g = Game.GetFormFromFile(0x000811, PLUGIN()) as GlobalVariable
	g.SetValueInt(aiPercent)
	Return "chance=" + g.GetValueInt()
EndFunction

string Function PaceReset() global
	MLW_Pace.Reset()
	Return MLW_Pace.ReportText()
EndFunction

string Function PaceText() global
	Return MLW_Pace.ReportText()
EndFunction

string Function BanterRecent() global
	Return StorageUtil.StringListCount(None, "MLWW_BanterRecent") + ": " + StorageUtil.StringListGet(None, "MLWW_BanterRecent", StorageUtil.StringListCount(None, "MLWW_BanterRecent") - 1)
EndFunction

string Function WantToTell(Actor akNpc, string asWhy) global
	Initiative().WantToTell(akNpc, asWhy)
	Return "wants=" + StorageUtil.FormListCount(None, "MLWW_WantsToTell")
EndFunction

; Runs the initiative scan now instead of waiting for the 30 s timer. Returns who came over, or "nobody".
string Function InitiativeScan() global
	Actor a = Initiative().Scan()
	If a
		Return a.GetDisplayName()
	EndIf
	Return "nobody"
EndFunction

string Function InitiativeRecent() global
	Return StorageUtil.StringListCount(None, "MLWW_InitiativeRecent") + ": " + StorageUtil.StringListGet(None, "MLWW_InitiativeRecent", StorageUtil.StringListCount(None, "MLWW_InitiativeRecent") - 1)
EndFunction

bool Function TalkRunning() global
	Return (Game.GetFormFromFile(0x03D41A, "Mantella.esp") as Quest).IsRunning()
EndFunction
