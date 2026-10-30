Scriptname MLWW_Personal extends MLWW_Job
{Mantella Living World - World: what the player did to this NPC, seen first hand. World's SKSE plugin reports deaths,
hits, waking someone up, gifts, trade and being caught stealing; this keeps them on the NPC (StorageUtil) and, when
the NPC joins a conversation, sends one line with what still matters, at most four things:
  caught stealing or pickpocketing from them (30 days), wearing something stolen from them (now), woken up just
  now, struck by the player (30 days), gifts (30 days, the last three), trade today, and a merchant short of coin
  after the player sold to them (2 days, the time vanilla takes to restock).
Deaths are only recorded here (the day); Relationships uses them for grief.}

string Property KEY_DIED = "MLWW_DiedDay" AutoReadOnly
string Property KEY_DIED_BY_PLAYER = "MLWW_DiedByPlayer" AutoReadOnly
string Property KEY_STRUCK = "MLWW_StruckDay" AutoReadOnly
string Property KEY_WOKEN = "MLWW_WokenAt" AutoReadOnly
string Property KEY_WOKEN_HOUR = "MLWW_WokenHour" AutoReadOnly
string Property KEY_GIFTS = "MLWW_Gifts" AutoReadOnly          ; "day|count|name", newest last
string Property KEY_TRADE_DAY = "MLWW_TradeDay" AutoReadOnly
string Property KEY_BOUGHT = "MLWW_TradeBought" AutoReadOnly    ; gold the player paid them today
string Property KEY_SOLD = "MLWW_TradeSold" AutoReadOnly        ; gold they paid the player today
string Property KEY_CHEST = "MLWW_ChestGold" AutoReadOnly
string Property KEY_CHEST_DAY = "MLWW_ChestDay" AutoReadOnly
string Property KEY_CAUGHT = "MLWW_CaughtDay" AutoReadOnly      ; on the NPC's base: owners are bases
string Property KEY_CAUGHT_KIND = "MLWW_CaughtKind" AutoReadOnly

float Property MEMORY_DAYS = 30.0 AutoReadOnly
float Property WOKEN_DAYS = 0.05 AutoReadOnly    ; about an hour of game time
float Property RESTOCK_DAYS = 2.0 AutoReadOnly
int Property LOW_COIN = 100 AutoReadOnly
int Property MAX_GIFTS = 3 AutoReadOnly
int Property MAX_ITEMS = 4 AutoReadOnly

Function Register()
	RegisterForModEvent("MLWW_Died", "OnDied")
	RegisterForModEvent("MLWW_Struck", "OnStruck")
	RegisterForModEvent("MLWW_Woken", "OnWoken")
	RegisterForModEvent("MLWW_Gift", "OnGift")
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
	If !akSender || asItem == ""
		Return
	EndIf
	int today = MLWW_Util.Today()
	int count = afCount as int
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
EndEvent

Event OnTrade(string asName, string asChest, float afPlayerGold, Form akSender)
	If !akSender
		Return
	EndIf
	int today = MLWW_Util.Today()
	If StorageUtil.GetIntValue(akSender, KEY_TRADE_DAY, -1) != today
		StorageUtil.SetIntValue(akSender, KEY_TRADE_DAY, today)
		StorageUtil.SetIntValue(akSender, KEY_BOUGHT, 0)
		StorageUtil.SetIntValue(akSender, KEY_SOLD, 0)
	EndIf
	int gold = afPlayerGold as int
	If gold > 0
		StorageUtil.AdjustIntValue(akSender, KEY_SOLD, gold)
	Else
		StorageUtil.AdjustIntValue(akSender, KEY_BOUGHT, -gold)
	EndIf
	If asChest as int >= 0
		StorageUtil.SetIntValue(akSender, KEY_CHEST, asChest as int)
		StorageUtil.SetFloatValue(akSender, KEY_CHEST_DAY, Utility.GetCurrentGameTime())
	EndIf
EndEvent

Event OnCaught(string asName, string asKind, float afNum, Form akSender)
	Form owner = akSender
	Actor who = akSender as Actor
	If who
		owner = who.GetActorBase()
	EndIf
	If owner
		StorageUtil.SetFloatValue(owner, KEY_CAUGHT, Utility.GetCurrentGameTime())
		StorageUtil.SetStringValue(owner, KEY_CAUGHT_KIND, asKind)
	EndIf
EndEvent

; ---------------------------------------------------------------------------
; The line for Mantella
; ---------------------------------------------------------------------------

Event OnNpcAdded(Form akActor)
	Actor npc = akActor as Actor
	If !npc || npc == PlayerRef || npc.IsDead()
		Return
	EndIf
	MLWW_Util.Send("personal", Line(npc))
EndEvent

; One line with what the player did to this NPC; "" when nothing matters now.
string Function Line(Actor akNpc)
	float now = Utility.GetCurrentGameTime()
	string player = MLWW_Util.PlayerName()
	string name = akNpc.GetDisplayName()
	string[] items = new string[8]
	int n = 0

	ActorBase base = akNpc.GetActorBase()
	float caught = StorageUtil.GetFloatValue(base, KEY_CAUGHT, -1.0)
	If caught >= 0.0 && now - caught <= MEMORY_DAYS
		If StorageUtil.GetStringValue(base, KEY_CAUGHT_KIND) == "pickpocketing"
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
	If struck >= 0.0 && now - struck <= MEMORY_DAYS
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
	int chest = StorageUtil.GetIntValue(akNpc, KEY_CHEST, -1)
	If chest >= 0 && chest < LOW_COIN && now - StorageUtil.GetFloatValue(akNpc, KEY_CHEST_DAY) <= RESTOCK_DAYS
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
