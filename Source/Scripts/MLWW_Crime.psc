Scriptname MLWW_Crime extends MLWW_Job
{Mantella Living World - World: settle crime by talking, and a gated crime report. Replaces Mantella's own
AbsolveCrime and ReportCrime actions (keep those two disabled; ours are named SettleCrime and ReportWitnessedCrime
so Mantella's Disabled Actions, which matches by name, never switches them off).

SettleCrime (only a guard, steward or Jarl; the bounty is the one in the speaker's crime faction):
  pay       the non-violent bounty is paid, stolen goods are taken (vanilla payment); the player confirms first
  bribe     the guard pockets bounty x 1.5 - Speech/100 x bounty x 0.5 gold; stolen goods are kept; the player
            confirms first
  persuade  free, only a non-violent bounty of 100 or less, once per game day per hold
  A Thane of the hold, or a player famous there, has a non-violent bounty of 40 or less waived for free.
  Violent crime gold (assault, murder) is never cleared by any of these.
ReportWitnessedCrime (only a guard, steward or Jarl): adds the vanilla bounty for the crime only when another NPC in
the conversation (not the player's teammate) is there as the witness who told them. Each crime counts once per
conversation and once per game day per hold, so reports never add more than one vanilla bounty per crime per day.}

MLWW_State Property World Auto

string Property ACTION_SETTLE = "mantella_mlww_settle_crime" AutoReadOnly
string Property ACTION_REPORT = "mantella_mlww_report_crime" AutoReadOnly
string Property ADVANCED = "MantellaConversation_Advanced_Action_" AutoReadOnly
string Property LEGACY = "MantellaConversation_Action_" AutoReadOnly
string Property KEY_PERSUADE = "MLWW_PersuadeDay_" AutoReadOnly
string Property KEY_REPORTED_TALK = "MLWW_ReportedThisTalk" AutoReadOnly
string Property KEY_REPORT_DAY = "MLWW_ReportDay_" AutoReadOnly
int Property PERSUADE_MAX = 100 AutoReadOnly
int Property WAIVE_MAX = 40 AutoReadOnly
int Property FAME_WAIVE = 5 AutoReadOnly

Function Register()
	RegisterForModEvent(ADVANCED + ACTION_SETTLE, "OnSettleAdvanced")
	RegisterForModEvent(LEGACY + ACTION_SETTLE, "OnSettleLegacy")
	RegisterForModEvent(ADVANCED + ACTION_REPORT, "OnReportAdvanced")
	RegisterForModEvent(LEGACY + ACTION_REPORT, "OnReportLegacy")
	RegisterForModEvent("MantellaConversation_Started", "OnTalkStarted")
EndFunction

; A new conversation: crimes reported in the last one may be reported again (still once per day per hold).
Event OnTalkStarted()
	StorageUtil.StringListClear(None, KEY_REPORTED_TALK)
EndEvent

; ---------------------------------------------------------------------------
; Settle
; ---------------------------------------------------------------------------

; Both paths come from the NPC's reply, which the player never chose, so pay and bribe ask the player before any
; gold or goods are taken.
Event OnSettleAdvanced(Form akSpeaker, Form akConversation, int aiArguments)
	Settle(akSpeaker as Actor, SKSE_HTTP.getString(aiArguments, "method", "pay"), true)
	MLWW_Util.ActionDone(ACTION_SETTLE)
EndEvent

; Mantella sent no arguments: treat it as paying.
Event OnSettleLegacy(Form akSpeaker)
	Settle(akSpeaker as Actor, "pay", true)
	MLWW_Util.ActionDone(ACTION_SETTLE)
EndEvent

; Yes/No before gold is taken. True when the player agreed.
bool Function PlayerAgrees(string asQuestion, string asYes)
	Return SkyMessage.Show(asQuestion, asYes, "Not now") == asYes
EndFunction

; Returns what happened (also sent to Mantella), for tests. abAsk: show the player a Yes/No before pay or bribe
; takes anything (the action events always ask; tests call it without).
string Function Settle(Actor akSpeaker, string asMethod, bool abAsk = false)
	string player = MLWW_Util.PlayerName()
	If !IsAuthority(akSpeaker) || !akSpeaker.GetCrimeFaction()
		Return Tell("Only a guard, steward or Jarl can settle " + player + "'s bounty; " + Name(akSpeaker) + " cannot.")
	EndIf
	string who = akSpeaker.GetDisplayName()
	Faction crime = akSpeaker.GetCrimeFaction()
	int hold = World.HoldOfFaction(crime)
	string where = HoldText(hold, crime)
	int nonViolent = crime.GetCrimeGoldNonViolent()
	int violent = crime.GetCrimeGoldViolent()
	If nonViolent <= 0
		If violent > 0
			Return Tell(player + "'s bounty in " + where + " is for violent crimes (" + violent + " gold); " + who + " cannot let that go.")
		EndIf
		Return Tell(player + " has no bounty in " + where + ".")
	EndIf
	string rest = ""
	If violent > 0
		rest = " The " + violent + " gold for violent crimes stands."
	EndIf
	If nonViolent <= WAIVE_MAX && (World.IsThane(hold) || World.Fame(hold) >= FAME_WAIVE)
		Clear(crime)
		string reason = "out of respect for a Thane of " + where
		If !World.IsThane(hold)
			reason = "because " + player + " is well known in " + where
		EndIf
		Debug.Notification("Bounty of " + nonViolent + " waived in " + where)
		Return Tell(who + " waived " + player + "'s " + nonViolent + " gold bounty in " + where + " " + reason + "." + rest)
	EndIf
	MiscObject gold = Game.GetFormFromFile(0x00000F, "Skyrim.esm") as MiscObject
	int purse = PlayerRef.GetItemCount(gold)
	If asMethod == "persuade"
		string persuadeKey = KEY_PERSUADE + HoldKey(hold, crime)
		If nonViolent > PERSUADE_MAX
			Return Tell(player + "'s bounty of " + nonViolent + " gold in " + where + " is too large to talk away; it must be paid.")
		ElseIf StorageUtil.GetIntValue(None, persuadeKey, -1) == MLWW_Util.Today()
			Return Tell(player + " already talked a bounty away in " + where + " today; " + who + " will not do it again.")
		EndIf
		StorageUtil.SetIntValue(None, persuadeKey, MLWW_Util.Today())
		Clear(crime)
		Debug.Notification("Bounty of " + nonViolent + " forgiven in " + where)
		Return Tell(who + " let " + player + "'s " + nonViolent + " gold bounty in " + where + " go." + rest)
	ElseIf asMethod == "bribe"
		int cost = BribeCost(nonViolent)
		If purse < cost
			Return Tell(player + " cannot afford the " + cost + " gold bribe for a " + nonViolent + " gold bounty in " + where + ".")
		EndIf
		If abAsk && !PlayerAgrees(who + " will forget your " + nonViolent + " gold bounty in " + where + " for a bribe of " + cost + " gold. You keep any stolen goods. Pay the bribe?", "Pay " + cost + " gold")
			Return Tell(player + " chose not to pay " + who + " a bribe now; the bounty in " + where + " stands.")
		EndIf
		PlayerRef.RemoveItem(gold, cost, true, akSpeaker)
		Clear(crime)
		Debug.Notification("Bribe of " + cost + " gold: bounty cleared in " + where)
		Return Tell(who + " took a " + cost + " gold bribe and cleared " + player + "'s " + nonViolent + " gold bounty in " + where + "." + rest)
	EndIf
	If purse < nonViolent
		Return Tell(player + " cannot afford to pay the " + nonViolent + " gold bounty in " + where + ".")
	EndIf
	If abAsk && !PlayerAgrees(who + " offers to settle your " + nonViolent + " gold bounty in " + where + ". Paying also hands over any stolen goods you carry. Pay it?", "Pay " + nonViolent + " gold")
		Return Tell(player + " chose not to pay the bounty in " + where + " now.")
	EndIf
	; Vanilla payment takes the gold and the stolen goods; violent gold is held aside so only the non-violent part
	; is charged, then put back.
	crime.SetCrimeGoldViolent(0)
	crime.PlayerPayCrimeGold(true, false)
	crime.SetCrimeGoldViolent(violent)
	Debug.Notification("Paid " + nonViolent + " gold bounty in " + where)
	Return Tell(player + " paid the " + nonViolent + " gold bounty in " + where + " to " + who + "; any stolen goods were taken." + rest)
EndFunction

; bounty x 1.5 - Speech/100 x bounty x 0.5, rounded up: 1.5x at Speech 0, 1x at Speech 100.
int Function BribeCost(int aiBounty)
	float speech = PlayerRef.GetActorValue("Speechcraft")
	If speech < 0.0
		speech = 0.0
	ElseIf speech > 100.0
		speech = 100.0
	EndIf
	Return Math.Ceiling(aiBounty * 1.5 - speech / 100.0 * aiBounty * 0.5)
EndFunction

; Non-violent gold only; SetCrimeGold leaves violent gold untouched.
Function Clear(Faction akCrime)
	akCrime.SetCrimeGold(0)
EndFunction

; ---------------------------------------------------------------------------
; Report
; ---------------------------------------------------------------------------

Event OnReportAdvanced(Form akSpeaker, Form akConversation, int aiArguments)
	Report(akSpeaker as Actor, akConversation as MantellaConversation, SKSE_HTTP.getString(aiArguments, "crime", ""))
	MLWW_Util.ActionDone(ACTION_REPORT)
EndEvent

Event OnReportLegacy(Form akSpeaker)
	Tell("The report did not say which crime; nothing was reported.")
	MLWW_Util.ActionDone(ACTION_REPORT)
EndEvent

string Function Report(Actor akSpeaker, MantellaConversation akConversation, string asCrime)
	string player = MLWW_Util.PlayerName()
	If !IsAuthority(akSpeaker) || !akSpeaker.GetCrimeFaction()
		Return Tell("Only a guard, steward or Jarl can take a crime report; " + Name(akSpeaker) + " cannot.")
	EndIf
	int gold = CrimeGold(asCrime)
	If gold <= 0
		Return Tell("The report named no crime a guard can act on; nothing was reported.")
	EndIf
	Actor witness = Witness(akSpeaker, akConversation)
	If !witness
		Return Tell(akSpeaker.GetDisplayName() + " has no witness to the " + asCrime + " here, so no bounty is added.")
	EndIf
	Faction crime = akSpeaker.GetCrimeFaction()
	int hold = World.HoldOfFaction(crime)
	string where = HoldText(hold, crime)
	; One report per crime per conversation, and at most one vanilla bounty per crime per hold per game day.
	string reportKey = HoldKey(hold, crime) + "_" + asCrime
	If StorageUtil.StringListHas(None, KEY_REPORTED_TALK, reportKey)
		Return Tell("The " + asCrime + " was already reported in " + where + " in this talk; no more bounty is added.")
	EndIf
	string dayKey = KEY_REPORT_DAY + reportKey
	If StorageUtil.GetIntValue(None, dayKey, -1) == MLWW_Util.Today()
		Return Tell(player + " was already reported for " + asCrime + " in " + where + " today; no more bounty is added.")
	EndIf
	StorageUtil.StringListAdd(None, KEY_REPORTED_TALK, reportKey, false)
	StorageUtil.SetIntValue(None, dayKey, MLWW_Util.Today())
	crime.ModCrimeGold(gold, asCrime == "assault" || asCrime == "murder")
	Debug.Notification(gold + " bounty added in " + where)
	Return Tell(witness.GetDisplayName() + " reported " + player + " for " + asCrime + "; " + akSpeaker.GetDisplayName() + " added " + gold + " gold to the bounty in " + where + ".")
EndFunction

; Vanilla bounty values (theft uses the flat 50 a typical stolen item costs; vanilla charges half the item's value).
int Function CrimeGold(string asCrime)
	If asCrime == "trespassing" || asCrime == "lockpicking"
		Return 5
	ElseIf asCrime == "pickpocketing"
		Return 25
	ElseIf asCrime == "theft"
		Return 50
	ElseIf asCrime == "assault"
		Return 40
	ElseIf asCrime == "murder"
		Return 1000
	EndIf
	Return 0
EndFunction

; Another living NPC in the conversation who is not a guard of the same hold and not the player's teammate: the one
; who saw it and told.
Actor Function Witness(Actor akGuard, MantellaConversation akConversation)
	If !akConversation
		Return None
	EndIf
	int i = 0
	int count = akConversation.CountActorsInConversation()
	While i < count
		Actor other = akConversation.GetActorInConversationByIndex(i)
		If other && other != akGuard && other != PlayerRef && !other.IsDead() && !IsAuthority(other) && !other.IsPlayerTeammate()
			Return other
		EndIf
		i += 1
	EndWhile
	Return None
EndFunction

; ---------------------------------------------------------------------------
; Helpers
; ---------------------------------------------------------------------------

bool Function IsAuthority(Actor akActor)
	If !akActor || akActor == PlayerRef || akActor.IsDead()
		Return false
	EndIf
	If akActor.IsGuard()
		Return true
	EndIf
	Faction jarl = Game.GetFormFromFile(0x050920, "Skyrim.esm") as Faction
	Faction steward = Game.GetFormFromFile(0x050922, "Skyrim.esm") as Faction
	Return (jarl && akActor.IsInFaction(jarl)) || (steward && akActor.IsInFaction(steward))
EndFunction

string Function HoldText(int aiHold, Faction akCrime)
	If aiHold >= 0
		Return World.HoldText(aiHold)
	EndIf
	Return akCrime.GetName()
EndFunction

string Function HoldKey(int aiHold, Faction akCrime)
	If aiHold >= 0
		Return World.HoldName(aiHold)
	EndIf
	Return MLWW_Util.Hex(akCrime.GetFormID(), 8)
EndFunction

string Function Name(Actor akActor)
	If !akActor
		Return "nobody"
	EndIf
	Return akActor.GetDisplayName()
EndFunction

string Function Tell(string asLine)
	MLWW_Util.Send("crime", asLine)
	Return asLine
EndFunction
