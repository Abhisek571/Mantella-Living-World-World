Scriptname MLWW_Personal extends MLWW_Job
{Mantella Living World - World: what the player did to this NPC, seen first hand. World's SKSE plugin reports deaths,
hits, waking someone up, gifts, trade and being caught stealing; this keeps them on the NPC (StorageUtil) and, when
the NPC joins a conversation, sends one line with what still matters, at most four things:
  caught stealing or pickpocketing from them (30 days), wearing something stolen from them (now), woken up just
  now, struck by the player (30 days), gifts (30 days, the last three), trade today, and a merchant short of coin
  after the player sold to them (2 days, the time vanilla takes to restock).
Deaths are only recorded here (the day); Relationships uses them for grief. A murder (a person who was no enemy, killed by
the player) is stamped with its day and hold for MLWW_Crime's murder report.
A murder of, or an attack on, a Thalmor: the people close by (not the party) saw it, and for 3 days their line says so,
with MLWW_Util.ThalmorClause (folk outside the big walled cities do not much care). Only words: no bounty changes.
What lasts (lifetime trade, heals, rescues, kills, fights, friendly fire) is kept by MLWW_Facts and written to the NPC's
file as facts: when they join a conversation and otherwise at most once per FACT_DELAY.
Murders and attacks by the player, and deaths of named people the player did not kill, are also added to
MantellaLivingWorld/crimes.json for the Hub's world log (see LogCrime).}

string Property KEY_DIED = "MLWW_DiedDay" AutoReadOnly
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
string Property KEY_THALMOR = "MLWW_SawThalmorAt" AutoReadOnly         ; on a witness: when the player harmed a Thalmor
string Property KEY_THALMOR_KILLED = "MLWW_SawThalmorKilled" AutoReadOnly  ; 1 killed, 0 attacked
string Property KEY_THALMOR_NAME = "MLWW_SawThalmorName" AutoReadOnly
float Property THALMOR_DAYS = 3.0 AutoReadOnly
float Property WITNESS_RANGE = 3072.0 AutoReadOnly  ; as the battle record's bystanders
int Property MAX_WITNESSES = 40 AutoReadOnly
string Property CRIMES_FILE = "MantellaLivingWorld/crimes.json" AutoReadOnly
int Property MAX_CRIME_ROWS = 200 AutoReadOnly       ; per list; the oldest rows go first
int Property MAX_CRIME_WITNESSES = 12 AutoReadOnly
string Property KEY_ASSAULT_DAY = "MLWW_AssaultLoggedDay" AutoReadOnly  ; on the victim: the day an attack row was written
string Property KEY_ASSAULT_ROW = "MLWW_AssaultRowId" AutoReadOnly      ; that row's id, replaced if they are killed that day

float Property MEMORY_DAYS = 30.0 AutoReadOnly
float Property WOKEN_DAYS = 0.05 AutoReadOnly    ; about an hour of game time
float Property RESTOCK_DAYS = 2.0 AutoReadOnly
int Property LOW_COIN = 100 AutoReadOnly
int Property MAX_GIFTS = 3 AutoReadOnly
int Property MAX_ITEMS = 4 AutoReadOnly
string Property KEY_STALE = "MLWW_StaleFacts" AutoReadOnly     ; NPCs whose facts wait to be written
float Property FACT_DELAY = 30.0 AutoReadOnly

bool factWritePending = false
bool crimeLogging = false

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
		If afByPlayer <= 0.0
			LogDeath(akSender as Actor)  ; a killing by the player is a murder row (OnMurder) or a fight's
		EndIf
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
	; Whether that murder was of a Thalmor, kept beside each day for MLWW_Crime's report line.
	int thalmor = MLWW_Util.IsThalmor(akSender as Actor) as int
	If hold >= 0
		StorageUtil.SetIntValue(None, "MLWW_MurderThalmor_" + hold, thalmor)
	EndIf
	If crime
		StorageUtil.SetIntValue(crime, "MLWW_MurderThalmor", thalmor)
	EndIf
	If thalmor
		SawThalmor(akSender as Actor, true)
	EndIf
	LogCrime(akSender as Actor, "murder", hold)
EndEvent

Event OnStruck(string asEvent, string asText, float afNum, Form akSender)
	If akSender
		StorageUtil.SetFloatValue(akSender, KEY_STRUCK, Utility.GetCurrentGameTime())
		If MLWW_Util.IsThalmor(akSender as Actor)
			SawThalmor(akSender as Actor, false)
		EndIf
		LogCrime(akSender as Actor, "assault", -1)
	EndIf
EndEvent

; ---------------------------------------------------------------------------
; crimes.json: what the Hub's world log reads (worldlog.from_crime / from_death). One JSON object shared by every save:
;   {"player": <last writer>, "crimes": [row...], "deaths": [row...]}, each list append-only, at most MAX_CRIME_ROWS.
; A crime row: {id, crime: murder/assault, day, place, town, hold, victim: {base, ref_id, name, thalmor},
;   witnesses: [{base, ref_id, name}], by_player: true, player}. A death row: {id, base, ref_id, name, day, place, town,
;   hold, by_player: false, unique: true, witnesses, player}. Children are never victims here, and a child witness is
;   listed without a name ({base, ref_id, minor: 1}). A crime row has "masked":1 when a hood hid the player's face where
;   that hides who they are (as MLWW_Recognition): the Hub names "a hooded stranger" to those who do not know the player.
;   The player's followers are never witnesses (InParty): they were with the player, not onlookers who spread it.
; ---------------------------------------------------------------------------

; A murder or an attack by the player on a person (not the party). One attack row per person per day; a murder the same
; day replaces that attack row. aiHold: the hold of the victim's crime faction, used when the place has none.
Function LogCrime(Actor akVictim, string asCrime, int aiHold)
	If !akVictim || akVictim == PlayerRef || akVictim.IsChild() || akVictim.IsPlayerTeammate() || !akVictim.HasKeyword(Keyword.GetKeyword("ActorTypeNPC"))
		Return
	EndIf
	float now = Utility.GetCurrentGameTime()
	string ref = MLWW_Util.Hex(akVictim.GetFormID(), 8)
	string id = asCrime + "-" + ref + "-" + ((now * 1000.0) as int)
	string replace = ""
	bool attackedToday = StorageUtil.GetIntValue(akVictim, KEY_ASSAULT_DAY, -1) == now as int
	If asCrime == "assault"
		If attackedToday
			Return
		EndIf
		StorageUtil.SetIntValue(akVictim, KEY_ASSAULT_DAY, now as int)
		StorageUtil.SetStringValue(akVictim, KEY_ASSAULT_ROW, id)
	ElseIf attackedToday
		replace = StorageUtil.GetStringValue(akVictim, KEY_ASSAULT_ROW)
	EndIf
	string row = "{\"id\":" + MLWW_Util.Quote(id) + ",\"crime\":\"" + asCrime + "\",\"day\":" + now + PlaceJson(akVictim, aiHold) \
		+ ",\"victim\":{\"base\":\"" + MLWW_Util.BaseId(akVictim) + "\",\"ref_id\":\"" + ref + "\",\"name\":" \
		+ MLWW_Util.Quote(akVictim.GetDisplayName()) + ",\"thalmor\":" + (MLWW_Util.IsThalmor(akVictim) as int) + "}" \
		+ ",\"witnesses\":" + WitnessJson(akVictim) + ",\"by_player\":true,\"masked\":" + Masked() \
		+ ",\"player\":" + MLWW_Util.Quote(MLWW_Util.PlayerName()) + "}"
	AppendRow("crimes", row, replace)
EndFunction

; A named person who died, not by the player's hand (MLWW_Died only reports named people).
Function LogDeath(Actor akDead)
	If !akDead || akDead.IsChild()
		Return
	EndIf
	float now = Utility.GetCurrentGameTime()
	string ref = MLWW_Util.Hex(akDead.GetFormID(), 8)
	string row = "{\"id\":\"death-" + ref + "-" + ((now * 1000.0) as int) + "\",\"base\":\"" + MLWW_Util.BaseId(akDead) \
		+ "\",\"ref_id\":\"" + ref + "\",\"name\":" + MLWW_Util.Quote(akDead.GetDisplayName()) + ",\"day\":" + now \
		+ PlaceJson(akDead, -1) + ",\"by_player\":false,\"unique\":true,\"witnesses\":" + WitnessJson(akDead) \
		+ ",\"player\":" + MLWW_Util.Quote(MLWW_Util.PlayerName()) + "}"
	AppendRow("deaths", row, "")
EndFunction

; ,"place":..,"town":..,"hold":.. for where akActor is: the location's name (else the cell's, as the battle record does),
; the city, town or settlement it lies in, and its hold (else aiHold).
string Function PlaceJson(Actor akActor, int aiHold)
	Location here = akActor.GetCurrentLocation()
	string place = ""
	If here
		place = here.GetName()
	EndIf
	If place == "" && akActor.GetParentCell()
		place = akActor.GetParentCell().GetName()
	EndIf
	string town = ""
	Keyword city = Game.GetFormFromFile(0x013168, "Skyrim.esm") as Keyword        ; LocTypeCity
	Keyword townType = Game.GetFormFromFile(0x013166, "Skyrim.esm") as Keyword    ; LocTypeTown
	Keyword settlement = Game.GetFormFromFile(0x013167, "Skyrim.esm") as Keyword  ; LocTypeSettlement
	Location loc = here
	int depth = 0
	While loc && town == "" && depth < 8
		If loc.HasKeyword(city) || loc.HasKeyword(townType) || loc.HasKeyword(settlement)
			town = loc.GetName()
		EndIf
		loc = PO3_SKSEFunctions.GetParentLocation(loc)
		depth += 1
	EndWhile
	string hold = ""
	MLWW_State world = Game.GetFormFromFile(0x000800, "Mantella Living World - World.esp") as MLWW_State
	If world
		int h = world.HoldOfLocation(here)
		If h < 0
			h = aiHold
		EndIf
		hold = world.HoldName(h)
	EndIf
	Return ",\"place\":" + MLWW_Util.Quote(place) + ",\"town\":" + MLWW_Util.Quote(town) + ",\"hold\":" + MLWW_Util.Quote(hold)
EndFunction

; The people close to akAt (as SawThalmor: not the player's party), at most MAX_CRIME_WITNESSES, as a JSON array.
string Function WitnessJson(Actor akAt)
	ObjectReference[] near = PO3_SKSEFunctions.FindAllReferencesOfFormType(akAt, 62, WITNESS_RANGE)
	Keyword npc = Keyword.GetKeyword("ActorTypeNPC")
	string out = "["
	int i = 0
	int seen = 0
	While near && i < near.Length && seen < MAX_CRIME_WITNESSES
		Actor a = near[i] as Actor
		If a && a != PlayerRef && a != akAt && !a.IsDead() && !InParty(a) && a.HasKeyword(npc)
			If seen > 0
				out += ","
			EndIf
			out += "{\"base\":\"" + MLWW_Util.BaseId(a) + "\",\"ref_id\":\"" + MLWW_Util.Hex(a.GetFormID(), 8) + "\""
			If a.IsChild()
				out += ",\"minor\":1}"
			Else
				out += ",\"name\":" + MLWW_Util.Quote(a.GetDisplayName()) + "}"
			EndIf
			seen += 1
		EndIf
		i += 1
	EndWhile
	Return out + "]"
EndFunction

; One of the player's followers: a teammate, or in the current follower faction (rank 0 or more; dismissed is -1),
; which vanilla, NFF and the Followers module all use, also for a follower who is waiting or not set as a teammate.
bool Function InParty(Actor akActor)
	If akActor.IsPlayerTeammate()
		Return true
	EndIf
	Faction current = Game.GetFormFromFile(0x05C84E, "Skyrim.esm") as Faction  ; CurrentFollowerFaction
	Return current && akActor.GetFactionRank(current) >= 0
EndFunction

; 1 when a hood or helmet hides the player's face where that hides who they are: inside a hold where the player is not
; famous (fame 3+) and not Thane, as MLWW_Recognition.Verdict decides; else 0.
int Function Masked()
	Armor head = PlayerRef.GetWornForm(0x00000001) as Armor
	If !head
		head = PlayerRef.GetWornForm(0x00000002) as Armor
	EndIf
	MLWW_State world = Game.GetFormFromFile(0x000800, "Mantella Living World - World.esp") as MLWW_State
	If !head || !world
		Return 0
	EndIf
	int hold = world.CurrentHold()
	If hold < 0 || world.Fame(hold) >= 3 || world.IsThane(hold)
		Return 0
	EndIf
	Return 1
EndFunction

; Adds asRow to the list (or puts it in place of the row with id asReplaceId among the last 20), drops the oldest rows
; beyond MAX_CRIME_ROWS and saves. One writer at a time, as Relationships' marriages.json.
Function AppendRow(string asList, string asRow, string asReplaceId)
	int tries = 0
	While crimeLogging && tries < 40
		Utility.WaitMenuMode(0.1)
		tries += 1
	EndWhile
	crimeLogging = true
	string path = "." + asList
	If !JsonUtil.IsPathArray(CRIMES_FILE, path)
		JsonUtil.SetRawPathValue(CRIMES_FILE, path, "[]")
	EndIf
	int n = JsonUtil.PathCount(CRIMES_FILE, path)
	If n < 0
		n = 0
	EndIf
	int at = n
	If asReplaceId != ""
		int i = n - 1
		While i >= 0 && i >= n - 20
			If JsonUtil.GetPathStringValue(CRIMES_FILE, path + "[" + i + "].id") == asReplaceId
				at = i
				i = 0
			EndIf
			i -= 1
		EndWhile
	EndIf
	If JsonUtil.SetRawPathValue(CRIMES_FILE, path + "[" + at + "]", asRow)
		While JsonUtil.PathCount(CRIMES_FILE, path) > MAX_CRIME_ROWS
			JsonUtil.ClearPathIndex(CRIMES_FILE, path, 0)
		EndWhile
		JsonUtil.SetRawPathValue(CRIMES_FILE, ".player", MLWW_Util.Quote(MLWW_Util.PlayerName()))
		JsonUtil.Save(CRIMES_FILE)
	EndIf
	crimeLogging = false
EndFunction

; The people near akVictim (not the player's party) saw the player kill or attack this Thalmor. A killing is not
; overwritten by a later attack on the same day.
Function SawThalmor(Actor akVictim, bool abKilled)
	float now = Utility.GetCurrentGameTime()
	string victim = akVictim.GetDisplayName()
	ObjectReference[] near = PO3_SKSEFunctions.FindAllReferencesOfFormType(akVictim, 62, WITNESS_RANGE)  ; not MiscUtil.ScanCellNPCs: VR
	int i = 0
	int seen = 0
	Keyword npc = Keyword.GetKeyword("ActorTypeNPC")
	While near && i < near.Length && seen < MAX_WITNESSES
		Actor a = near[i] as Actor
		If a && a != PlayerRef && a != akVictim && !a.IsDead() && !InParty(a) && a.HasKeyword(npc)
			bool killedLately = StorageUtil.GetIntValue(a, KEY_THALMOR_KILLED) > 0 && now - StorageUtil.GetFloatValue(a, KEY_THALMOR, -9.0) < 1.0
			If abKilled || !killedLately
				StorageUtil.SetFloatValue(a, KEY_THALMOR, now)
				StorageUtil.SetIntValue(a, KEY_THALMOR_KILLED, abKilled as int)
				StorageUtil.SetStringValue(a, KEY_THALMOR_NAME, victim)
			EndIf
			seen += 1
		EndIf
		i += 1
	EndWhile
EndFunction

Event OnWoken(string asEvent, string asText, float afHour, Form akSender)
	If akSender
		StorageUtil.SetFloatValue(akSender, KEY_WOKEN, Utility.GetCurrentGameTime())
		StorageUtil.SetFloatValue(akSender, KEY_WOKEN_HOUR, afHour)
	EndIf
EndEvent

Event OnGift(string asName, string asItem, float afCount, Form akSender)
	If TradeHandOver(akSender, asItem)
		Return
	EndIf
	RecordGift(akSender, asItem, afCount as int, true)
EndEvent

; An item the player handed over through the Trade action (MLWW_Trade.AskItem marks it just before): a sale or a payment,
; told to the talk by Trade itself, never scored or remembered as a gift. The mark is used once and lasts 10 seconds.
bool Function TradeHandOver(Form akSender, string asItem)
	If !akSender || StorageUtil.GetStringValue(akSender, "MLWW_TradeHanded", "") != asItem
		Return false
	EndIf
	float at = StorageUtil.GetFloatValue(akSender, "MLWW_TradeHandedAt", -100.0)
	float now = Utility.GetCurrentRealTime()
	StorageUtil.UnsetStringValue(akSender, "MLWW_TradeHanded")
	StorageUtil.UnsetFloatValue(akSender, "MLWW_TradeHandedAt")
	Return now >= at && now - at < 10.0
EndFunction

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
	If StorageUtil.GetIntValue(None, "MLW_TimingOn", 0) == 1  ; speed testing (off by default): one stage-time row
		MiscUtil.WriteToFile("Data/SKSE/Plugins/StorageUtilData/MantellaLivingWorld/timing_game.csv", StorageUtil.GetIntValue(None, "MLW_TimingTalk", 0) + "," + Utility.GetCurrentRealTime() + ",MLWW_Personal,OnNpcAdded_start,\n", true, false)
	EndIf
	Actor npc = akActor as Actor
	If !npc || npc == PlayerRef || npc.IsDead()
		Return
	EndIf
	MLWW_Facts.Sync(npc)
	MLWW_Util.Send("personal", Line(npc))
	If StorageUtil.GetIntValue(None, "MLW_TimingOn", 0) == 1  ; speed testing (off by default): one stage-time row
		MiscUtil.WriteToFile("Data/SKSE/Plugins/StorageUtilData/MantellaLivingWorld/timing_game.csv", StorageUtil.GetIntValue(None, "MLW_TimingTalk", 0) + "," + Utility.GetCurrentRealTime() + ",MLWW_Personal,OnNpcAdded_end,\n", true, false)
	EndIf
EndEvent

; One line with what the player did to this NPC; "" when nothing matters now.
string Function Line(Actor akNpc)
	float now = Utility.GetCurrentGameTime()
	string player = MLWW_Util.PlayerName()
	string name = akNpc.GetDisplayName()
	string[] items = new string[10]
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

	float sawThalmor = StorageUtil.GetFloatValue(akNpc, KEY_THALMOR, -1.0)
	If sawThalmor >= 0.0 && now - sawThalmor <= THALMOR_DAYS
		string verb = " attack "
		If StorageUtil.GetIntValue(akNpc, KEY_THALMOR_KILLED) > 0
			verb = " kill "
		EndIf
		items[n] = name + " saw " + player + verb + StorageUtil.GetStringValue(akNpc, KEY_THALMOR_NAME) + " " + When(sawThalmor, now) + " (" + MLWW_Util.ThalmorClause(akNpc) + ")"
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
