Scriptname MLWW_Personal extends MLWW_Job
{Mantella Living World - World: what the player did to this NPC, seen first hand. World's SKSE plugin reports deaths,
hits, waking someone up, gifts, trade and being caught stealing; this keeps them on the NPC (StorageUtil) and, when
the NPC joins a conversation, sends one line with what still matters, at most four things:
  caught stealing or pickpocketing from them (30 days), wearing something stolen from them (now), woken up just
  now, struck by the player (30 days), gifts (30 days, the last three), trade today, and a merchant short of coin
  after the player sold to them (2 days, the time vanilla takes to restock).
Deaths are only recorded here (the day); Relationships uses them for grief. A murder (a person who was no enemy, killed by
the player) is stamped with its day and hold for MLWW_Crime's murder report.
What lasts (lifetime trade, heals, rescues, kills, fights, friendly fire) is kept by MLWW_Facts and written to the NPC's
file as facts: when they join a conversation and otherwise at most once per FACT_DELAY.}

string Property KEY_DIED = "MLWW_DiedDay" AutoReadOnly
string Property KEY_DIED_BY_PLAYER = "MLWW_DiedByPlayer" AutoReadOnly
string Property KEY_STRUCK = "MLWW_StruckDay" AutoReadOnly
string Property KEY_WOKEN = "MLWW_WokenAt" AutoReadOnly
string Property KEY_WOKEN_HOUR = "MLWW_WokenHour" AutoReadOnly
string Property KEY_GIFTS = "MLWW_Gifts" AutoReadOnly          ; "day|count|name", newest last
string Property KEY_TRADE_DAY = "MLWW_TradeDay" AutoReadOnly
string Property KEY_BOUGHT = "MLWW_TradeBought" AutoReadOnly    ; gold the player paid them today
string Property KEY_SOLD = "MLWW_TradeSold" AutoReadOnly        ; gold they paid the player today
string Property KEY_CHEST_DAY = "MLWW_ChestDay" AutoReadOnly
string Property KEY_CAUGHT = "MLWW_CaughtDay" AutoReadOnly      ; on CaughtKey: a named NPC's base, else the actor
string Property KEY_CAUGHT_KIND = "MLWW_CaughtKind" AutoReadOnly

float Property MEMORY_DAYS = 30.0 AutoReadOnly
float Property WOKEN_DAYS = 0.05 AutoReadOnly    ; about an hour of game time
float Property RESTOCK_DAYS = 2.0 AutoReadOnly
int Property LOW_COIN = 100 AutoReadOnly
int Property MAX_GIFTS = 3 AutoReadOnly
int Property MAX_ITEMS = 4 AutoReadOnly
string Property KEY_STALE = "MLWW_StaleFacts" AutoReadOnly     ; NPCs whose facts wait to be written
float Property FACT_DELAY = 30.0 AutoReadOnly

bool factWritePending = false

Function Register()
	RegisterForModEvent("MLWW_Healed", "OnHealed")
	RegisterForModEvent("MLWW_Saved", "OnSaved")
	RegisterForModEvent("MLWW_Kill", "OnKill")
	RegisterForModEvent("MLWW_FriendlyFire", "OnFriendlyFire")
	RegisterForModEvent("MLWW_Fought", "OnFought")
	RegisterForModEvent("MLWW_Defended", "OnDefended")
	RegisterForModEvent("MLWW_TradeGoods", "OnTradeGoods")
	factWritePending = false
	If StorageUtil.FormListCount(self, KEY_STALE) > 0
		QueueFacts(None)
	EndIf
	RegisterForModEvent("MLWW_Died", "OnDied")
	RegisterForModEvent("MLWW_Murder", "OnMurder")
	RegisterForModEvent("MLWW_Struck", "OnStruck")
	RegisterForModEvent("MLWW_Woken", "OnWoken")
	RegisterForModEvent("MLWW_Gift", "OnGift")
	RegisterForModEvent("MLWW_GiftMenu", "OnGiftMenu")
	RegisterForModEvent("MLWW_Trade", "OnTrade")
	RegisterForModEvent("MLWW_Caught", "OnCaught")
	RegisterForModEvent("MantellaConversation_NPC_Added", "OnNpcAdded")
EndFunction

; ---------------------------------------------------------------------------
; Records (from MLWW_Listener.dll)
; ---------------------------------------------------------------------------

Event OnDied(string asEvent, string asText, float afByPlayer, Form akSender)
	If akSender
		StorageUtil.SetFloatValue(akSender, KEY_DIED, Utility.GetCurrentGameTime())
		StorageUtil.SetIntValue(akSender, KEY_DIED_BY_PLAYER, afByPlayer as int)
	EndIf
EndEvent

; A person who was not hostile, killed by the player (named or not). asCrime: the victim's crime faction form id as a
; signed number, "" when they had none. MLWW_Crime.NoEvidence backs a murder report only in that hold.
Event OnMurder(string asEvent, string asCrime, float afNum, Form akSender)
	Faction crime = None
	If asCrime != ""
		crime = Game.GetFormEx(asCrime as int) as Faction
	EndIf
	MLWW_State world = Game.GetFormFromFile(0x000800, "Mantella Living World - World.esp") as MLWW_State
	int hold = -1
	If world && crime
		hold = world.HoldOfFaction(crime)
	EndIf
	float today = Utility.GetCurrentGameTime()
	StorageUtil.SetFloatValue(None, "MLWW_LastMurderDay", today)
	StorageUtil.SetIntValue(None, "MLWW_LastMurderHold", hold)
	StorageUtil.SetFormValue(None, "MLWW_LastMurderFaction", crime)
	; Per hold and per crime faction too, so a later killing elsewhere does not hide this one from that hold's guards.
	If hold >= 0
		StorageUtil.SetFloatValue(None, "MLWW_MurderDay_" + hold, today)
	EndIf
	If crime
		StorageUtil.SetFloatValue(crime, "MLWW_MurderDay", today)
	EndIf
EndEvent

Event OnStruck(string asEvent, string asText, float afNum, Form akSender)
	If akSender
		StorageUtil.SetFloatValue(akSender, KEY_STRUCK, Utility.GetCurrentGameTime())
	EndIf
EndEvent

Event OnWoken(string asEvent, string asText, float afHour, Form akSender)
	If akSender
		StorageUtil.SetFloatValue(akSender, KEY_WOKEN, Utility.GetCurrentGameTime())
		StorageUtil.SetFloatValue(akSender, KEY_WOKEN_HOUR, afHour)
	EndIf
EndEvent

Event OnGift(string asName, string asItem, float afCount, Form akSender)
	RecordGift(akSender, asItem, afCount as int, true)
EndEvent

; Given through the gift menu: remembered the same, no score event (M.A.R.A.S scores its own gifts).
Event OnGiftMenu(string asName, string asItem, float afCount, Form akSender)
	RecordGift(akSender, asItem, afCount as int, false)
EndEvent

Function RecordGift(Form akSender, string asItem, int count, bool abScore)
	If !akSender || asItem == ""
		Return
	EndIf
	If abScore && asItem == "Gold"
		; Small change is remembered but not scored: handing a coin back and forth is no gift.
		If count >= 50
			MLWW_Facts.Score(akSender, "gifts", PapyrusUtil.ClampFloat(count / 100.0, 0.5, 5.0))
		EndIf
	ElseIf abScore
		MLWW_Facts.Score(akSender, "gifts", 1.0)
	EndIf
	int today = MLWW_Util.Today()
	int last = StorageUtil.StringListCount(akSender, KEY_GIFTS) - 1
	If last >= 0
		; The same item again today adds up ("100 gold" twice is "200 gold").
		string prev = StorageUtil.StringListGet(akSender, KEY_GIFTS, last)
		string[] parts = StringUtil.Split(prev, "|")
		If parts.Length == 3 && parts[0] as int == today && parts[2] == asItem
			StorageUtil.StringListSet(akSender, KEY_GIFTS, last, today + "|" + (parts[1] as int + count) + "|" + asItem)
			Return
		EndIf
	EndIf
	StorageUtil.StringListAdd(akSender, KEY_GIFTS, today + "|" + count + "|" + asItem)
	While StorageUtil.StringListCount(akSender, KEY_GIFTS) > MAX_GIFTS
		StorageUtil.StringListRemoveAt(akSender, KEY_GIFTS, 0)
	EndWhile
EndFunction

; asText: "<chest gold>|<gold the player paid>|<gold the player was paid>" (an old plugin sends only the chest gold, and
; afPlayerGold the net change).
Event OnTrade(string asName, string asText, float afPlayerGold, Form akSender)
	If !akSender
		Return
	EndIf
	string[] parts = StringUtil.Split(asText, "|")
	int spent = 0
	int earned = 0
	If parts.Length == 3
		spent = parts[1] as int
		earned = parts[2] as int
	ElseIf afPlayerGold > 0.0
		earned = afPlayerGold as int
	Else
		spent = -(afPlayerGold as int)
	EndIf
	If spent <= 0 && earned <= 0
		Return
	EndIf
	int today = MLWW_Util.Today()
	bool newDay = StorageUtil.GetIntValue(akSender, KEY_TRADE_DAY, -1) != today
	If newDay
		StorageUtil.SetIntValue(akSender, KEY_TRADE_DAY, today)
		StorageUtil.SetIntValue(akSender, KEY_BOUGHT, 0)
		StorageUtil.SetIntValue(akSender, KEY_SOLD, 0)
	EndIf
	MLWW_Facts.Trade(akSender, spent, earned, newDay)  ; one visit per day, however often the barter menu opens
	QueueFacts(akSender as Actor)
	StorageUtil.AdjustIntValue(akSender, KEY_SOLD, earned)
	StorageUtil.AdjustIntValue(akSender, KEY_BOUGHT, spent)
	; Line() reads the chest as it is now; this only dates the trade.
	StorageUtil.SetFloatValue(akSender, KEY_CHEST_DAY, Utility.GetCurrentGameTime())
EndEvent

Event OnCaught(string asName, string asKind, float afNum, Form akSender)
	Form owner = akSender  ; an owner from item ownership is already a base
	Actor who = akSender as Actor
	If who
		owner = CaughtKey(who)
	EndIf
	If owner
		StorageUtil.SetFloatValue(owner, KEY_CAUGHT, Utility.GetCurrentGameTime())
		StorageUtil.SetStringValue(owner, KEY_CAUGHT_KIND, asKind)
	EndIf
EndEvent

; Where "caught stealing" is kept for an actor: a named NPC's base (item owners are bases), anyone else's own reference,
; so one guard catching the player is not every guard of that base.
Form Function CaughtKey(Actor akNpc) global
	ActorBase base = akNpc.GetActorBase()
	If base && base.IsUnique()
		Return base
	EndIf
	Return akNpc
EndFunction

Event OnTradeGoods(string asName, string asItem, float afCount, Form akSender)
	If akSender && asItem != ""
		MLWW_Facts.Goods(akSender, asItem, afCount as int)
		QueueFacts(akSender as Actor)
	EndIf
EndEvent

; afByPlayer 1: the player healed this NPC; 0: this NPC healed the player.
Event OnHealed(string asName, string asText, float afByPlayer, Form akSender)
	Actor npc = akSender as Actor
	If !npc
		Return
	EndIf
	If afByPlayer > 0.0
		MLWW_Facts.Count(npc, "MLWW_HealedByPlayer", "MLWW_HealedDay")
		MLWW_Facts.Score(npc, "care", 1.0)
	Else
		MLWW_Facts.Count(npc, "MLWW_HealedPlayer", "MLWW_HealedDay")
	EndIf
	QueueFacts(npc)
EndEvent

; afByPlayer 1: the player got this NPC out of bleedout; 0: this NPC killed what had the player nearly dead.
Event OnSaved(string asName, string asHow, float afByPlayer, Form akSender)
	Actor npc = akSender as Actor
	If !npc
		Return
	EndIf
	If afByPlayer > 0.0
		MLWW_Facts.Count(npc, "MLWW_SavedByPlayer", "MLWW_SavedDay")
		MLWW_Facts.Score(npc, "deeds", 5.0)
	Else
		MLWW_Facts.Count(npc, "MLWW_SavedPlayer", "MLWW_SavedDay")
	EndIf
	QueueFacts(npc)
EndEvent

; An enemy killed by the player or a party member: counts for everyone in the party who is here.
Event OnKill(string asName, string asEnemy, float afScore, Form akKiller)
	int score = afScore as int
	MLWW_Facts.Best(None, asEnemy, score)
	Actor[] party = MLWW_Native.Party()
	int i = 0
	While party && i < party.Length
		MLWW_Facts.Kill(party[i], party[i] == akKiller, akKiller == PlayerRef, asEnemy, score)
		QueueFacts(party[i])
		i += 1
	EndWhile
EndEvent

; afByPlayer 1: the player hit this NPC; 0: this NPC hit the player. Sent only when health was lost.
Event OnFriendlyFire(string asName, string asText, float afByPlayer, Form akSender)
	Actor npc = akSender as Actor
	If !npc
		Return
	EndIf
	If afByPlayer > 0.0
		MLWW_Facts.Count(npc, "MLWW_HitByPlayer", "MLWW_HitDay")
	Else
		MLWW_Facts.Count(npc, "MLWW_HitPlayer", "MLWW_HitDay")
	EndIf
	QueueFacts(npc)
EndEvent

Event OnFought(string asName, string asText, float afNum, Form akSender)
	Actor npc = akSender as Actor
	If npc
		MLWW_Facts.Count(npc, "MLWW_Fought", "MLWW_FoughtDay")
		MLWW_Facts.Score(npc, "deeds", 0.5)
		QueueFacts(npc)
	EndIf
EndEvent

Event OnDefended(string asName, string asText, float afNum, Form akSender)
	Actor npc = akSender as Actor
	If npc
		MLWW_Facts.Count(npc, "MLWW_Defended", "MLWW_DefendedDay")
		QueueFacts(npc)
	EndIf
EndEvent

; Facts are written together, FACT_DELAY after the first change, however many events came in between.
Function QueueFacts(Actor akNpc)
	If akNpc
		StorageUtil.FormListAdd(self, KEY_STALE, akNpc, false)
	EndIf
	If !factWritePending
		factWritePending = true
		RegisterForSingleUpdate(FACT_DELAY)
	EndIf
EndFunction

Event OnUpdate()
	factWritePending = false
	WriteQueuedFacts()
EndEvent

Function WriteQueuedFacts()
	int i = StorageUtil.FormListCount(self, KEY_STALE)
	While i > 0
		i -= 1
		Actor npc = StorageUtil.FormListGet(self, KEY_STALE, i) as Actor
		StorageUtil.FormListRemoveAt(self, KEY_STALE, i)
		MLWW_Facts.Sync(npc)
	EndWhile
EndFunction

; ---------------------------------------------------------------------------
; The line for Mantella
; ---------------------------------------------------------------------------

Event OnNpcAdded(Form akActor)
	Actor npc = akActor as Actor
	If !npc || npc == PlayerRef || npc.IsDead()
		Return
	EndIf
	MLWW_Facts.Sync(npc)
	MLWW_Util.Send("personal", Line(npc))
EndEvent

; One line with what the player did to this NPC; "" when nothing matters now.
string Function Line(Actor akNpc)
	float now = Utility.GetCurrentGameTime()
	string player = MLWW_Util.PlayerName()
	string name = akNpc.GetDisplayName()
	string[] items = new string[8]
	int n = 0

	Form caughtBy = CaughtKey(akNpc)
	float caught = StorageUtil.GetFloatValue(caughtBy, KEY_CAUGHT, -1.0)
	If caught >= 0.0 && now - caught <= MEMORY_DAYS
		If StorageUtil.GetStringValue(caughtBy, KEY_CAUGHT_KIND) == "pickpocketing"
			items[n] = name + " caught " + player + " picking their pocket " + When(caught, now)
		Else
			items[n] = player + " was caught stealing from " + name + " " + When(caught, now)
		EndIf
		n += 1
	EndIf

	string worn = MLWW_Native.WornStolenFrom(akNpc)
	If worn != ""
		items[n] = player + " is wearing " + worn + ", stolen from " + name
		n += 1
	EndIf

	float woken = StorageUtil.GetFloatValue(akNpc, KEY_WOKEN, -1.0)
	If woken >= 0.0 && now - woken <= WOKEN_DAYS
		float hour = StorageUtil.GetFloatValue(akNpc, KEY_WOKEN_HOUR, 12.0)
		If hour >= 22.0 || hour < 5.0
			items[n] = player + " just woke " + name + " up in the middle of the night"
		Else
			items[n] = player + " just woke " + name + " up"
		EndIf
		n += 1
	EndIf

	float struck = StorageUtil.GetFloatValue(akNpc, KEY_STRUCK, -1.0)
	; With the Hub, a party member the player has hurt already has it as a fact (MLWW_Facts, friendly fire).
	bool hitFact = StorageUtil.GetIntValue(akNpc, "MLWW_HitByPlayer") > 0 && MLWW_Util.Hub()
	If struck >= 0.0 && now - struck <= MEMORY_DAYS && !hitFact
		items[n] = player + " struck " + name + " " + When(struck, now)
		n += 1
	EndIf

	string gifts = Gifts(akNpc, now)
	If gifts != ""
		items[n] = player + " gave " + name + " " + gifts
		n += 1
	EndIf

	If StorageUtil.GetIntValue(akNpc, KEY_TRADE_DAY, -1) == now as int
		int bought = StorageUtil.GetIntValue(akNpc, KEY_BOUGHT)
		int sold = StorageUtil.GetIntValue(akNpc, KEY_SOLD)
		If bought > 0
			items[n] = player + " bought " + bought + " gold worth of goods from " + name + " today"
			n += 1
		EndIf
		If sold > 0
			items[n] = name + " paid " + player + " " + sold + " gold for goods today"
			n += 1
		EndIf
	EndIf
	; Only after the player traded with them lately; the chest as it is now (restocked, or spent down by others).
	float chestDay = StorageUtil.GetFloatValue(akNpc, KEY_CHEST_DAY, -1.0)
	int chest = -1
	If chestDay >= 0.0 && now - chestDay <= RESTOCK_DAYS
		chest = MLWW_Native.ChestGold(akNpc)
	EndIf
	If chest >= 0 && chest < LOW_COIN
		items[n] = name + " is short of coin, with only " + chest + " gold left to trade"
		n += 1
	EndIf

	If n == 0
		Return ""
	EndIf
	string line = ""
	int i = 0
	While i < n && i < MAX_ITEMS
		If i > 0
			line += "; "
		EndIf
		line += items[i]
		i += 1
	EndWhile
	Return line + "."
EndFunction

; "a Silver Ring and 100 septims today, 2 Apples 3 days ago" for the gifts of the last MEMORY_DAYS, newest first.
; Gold is written as septims: Papyrus strings ignore case, so "Gold" cannot be turned into "gold".
string Function Gifts(Actor akNpc, float afNow)
	string out = ""
	string run = ""      ; the gifts of one day, waiting for their "today" / "N days ago"
	int runDay = -1
	int i = StorageUtil.StringListCount(akNpc, KEY_GIFTS) - 1
	While i >= -1
		string[] parts
		If i >= 0
			parts = StringUtil.Split(StorageUtil.StringListGet(akNpc, KEY_GIFTS, i), "|")
		EndIf
		bool ok = i >= 0 && parts.Length == 3 && afNow - (parts[0] as float) <= MEMORY_DAYS + 1.0
		If run != "" && (!ok || parts[0] as int != runDay)
			If out != ""
				out += ", "
			EndIf
			out += run + " " + WhenDay(runDay, afNow as int)
			run = ""
		EndIf
		If ok
			string what = parts[2]
			If what == "Gold"
				what = parts[1] + " septims"
			ElseIf parts[1] as int > 1
				what = parts[1] + " " + what
			EndIf
			If run != ""
				run += " and "
			EndIf
			run += what
			runDay = parts[0] as int
		EndIf
		i -= 1
	EndWhile
	Return out
EndFunction

string Function When(float afDay, float afNow)
	Return WhenDay(afDay as int, afNow as int)
EndFunction

string Function WhenDay(int aiDay, int aiToday)
	int days = aiToday - aiDay
	If days <= 0
		Return "today"
	ElseIf days == 1
		Return "yesterday"
	EndIf
	Return days + " days ago"
EndFunction
