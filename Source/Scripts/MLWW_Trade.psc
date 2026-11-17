Scriptname MLWW_Trade extends MLWW_Job
{Mantella Living World - World: trading by talk. The model haggles in words; the game only acts when something really
moves, and every result goes back into the talk as an event line (and to the HUD, see MLWW_Util.Result) so the NPC
knows whether it worked.

One Mantella action, Trade(kind, amount, item, count, price), carries every kind (Trade below dispatches on kind):
give_gold, ask_gold, give_item, ask_item, offer_trade, take_gift. The six separate actions of 1.x (GiveGold and the
rest) stay registered for one version, so a talk running across the update still works.

GiveGold(amount)            the speaker hands the player gold they carry
AskGold(amount)             the player hands the speaker gold; a confirm box first
GiveItem(item, count)       the speaker hands over an item they carry (matched by name: exact, then contained), never
                            a quest item
AskItem(item, count)        the player hands over an item they carry, never a quest item; a confirm box first
OfferTrade(item, count, price)  a merchant sells from their vendor chest (or what they carry) for a price held to half
                            to one and a half times the barter menu's price; a confirm box first
TakeGift                    opens the game's gift menu so the player picks the gift; the speaker is told what it was

Who: followers, friends and lovers (the Hub's close or follower standing, a teammate, vanilla rank 1 or more) and an NPC
under an absolute command (MLW_CommandUntil) give and take freely. A stranger trades gold for goods or services only:
they pay gold or hand goods over only up to the value the player handed them in this talk (credit, cleared when a talk
starts). The confirm boxes are the player's consent; an NPC flagged "Trades without asking" skips them (TradesFree).
They show only when gold or goods leave the player: Yes, Not now and, when the UIExtensions text box is there, Custom
answer. A custom answer is what really moves and what the NPC is told: an amount of gold ("2000", "2,000", "2000 gold"),
for an item another count of it or gold instead ("50 gold"), for a purchase the price paid (never under half the shop
price). It is held to what the player has; anything else shows a short note and the box again.
Gold the player pays is first added to the NPC (or the merchant's chest) and checked there, and only then taken from the
player, without a destination: World's plugin would count gold handed to an NPC as a gift. Nothing leaves one side unless
it arrived on the other (MoveGold; items move in one engine step and are checked on arrival).

Also: the NPC's file gets what they carry (carry_gold, carry_items; a merchant also merchant=1 and stock) when they join
a talk and after every trade, for the Hub's line when the player talks about buying, selling or gold; and a barter menu
closed during a talk with that merchant is told to the talk.}

string Property ADVANCED = "MantellaConversation_Advanced_Action_" AutoReadOnly
string Property LEGACY = "MantellaConversation_Action_" AutoReadOnly
string Property ACTION_GIVE_GOLD = "mantella_mlww_give_gold" AutoReadOnly
string Property ACTION_ASK_GOLD = "mantella_mlww_ask_gold" AutoReadOnly
string Property ACTION_GIVE_ITEM = "mantella_mlww_give_item" AutoReadOnly
string Property ACTION_ASK_ITEM = "mantella_mlww_ask_item" AutoReadOnly
string Property ACTION_OFFER = "mantella_mlww_offer_trade" AutoReadOnly
string Property ACTION_GIFT = "mantella_mlww_take_gift" AutoReadOnly
string Property ACTION_TRADE = "mantella_mlww_trade" AutoReadOnly  ; the one action that carries every kind
string Property KEY_CREDIT = "MLWW_TradeCredit" AutoReadOnly   ; gold value the player handed this NPC in this talk, not paid back
string Property KEY_TALK = "MLWW_TradeTalk" AutoReadOnly       ; on this quest: the NPCs holding credit
string Property DIR = "MantellaLivingWorld/npc/" AutoReadOnly
string Property CUSTOM_ANSWER = "Custom answer" AutoReadOnly
float Property PRICE_MIN = 0.5 AutoReadOnly
float Property PRICE_MAX = 1.5 AutoReadOnly
int Property MAX_CARRY = 4 AutoReadOnly   ; items named in carry_items
int Property MAX_STOCK = 5 AutoReadOnly   ; items named in stock
int Property MAX_SCAN = 150 AutoReadOnly  ; inventory entries looked at, at most
int Property AMOUNT_MAX = 100000 AutoReadOnly  ; largest gold amount or price an action can name
int Property COUNT_MAX = 1000 AutoReadOnly  ; largest count an action can name (the action file's maximum)

bool giftOpen = false
Actor giftNpc = None
string giftItems = ""
int giftGold = 0
int giftCount = 0
int ownTrades = 0  ; MLWW_Trade events OfferTrade sent itself, not a barter menu

Function Register()
	RegisterForModEvent(ADVANCED + ACTION_TRADE, "OnTrade")
	RegisterForModEvent(LEGACY + ACTION_TRADE, "OnTradeLegacy")
	; the separate actions of an earlier version are gone (one Trade action); their registrations in older saves end here
	string[] gone = new string[6]
	gone[0] = ACTION_GIVE_GOLD
	gone[1] = ACTION_ASK_GOLD
	gone[2] = ACTION_GIVE_ITEM
	gone[3] = ACTION_ASK_ITEM
	gone[4] = ACTION_OFFER
	gone[5] = ACTION_GIFT
	int g = 0
	While g < gone.Length
		UnregisterForModEvent(ADVANCED + gone[g])
		UnregisterForModEvent(LEGACY + gone[g])
		g += 1
	EndWhile
	RegisterForModEvent("MantellaConversation_Started", "OnTalkStarted")
	RegisterForModEvent("MantellaConversation_NPC_Added", "OnNpcAdded")
	RegisterForModEvent("MLWW_GiftMenu", "OnGiftItem")
	RegisterForModEvent("MLWW_Trade", "OnBarterDone")
	giftOpen = false
	ownTrades = 0
EndFunction

; ---------------------------------------------------------------------------
; Action events
; ---------------------------------------------------------------------------

Event OnTrade(Form akSpeaker, Form akConversation, int aiArguments)
	Trade(akSpeaker as Actor, SKSE_HTTP.getString(aiArguments, "kind", ""), SKSE_HTTP.getString(aiArguments, "item", ""), Amount(aiArguments, "amount"), Amount(aiArguments, "count", COUNT_MAX), Amount(aiArguments, "price"))
	MLWW_Util.ActionDone(ACTION_TRADE)
EndEvent

; No arguments (Mantella's Advanced Actions off): the gift menu is the one kind that needs none, as TakeGift was.
Event OnTradeLegacy(Form akSpeaker)
	TakeGift(akSpeaker as Actor)
	MLWW_Util.ActionDone(ACTION_TRADE)
EndEvent

; The kind of trade -> the function that does it, with the asking box on. Returns the event line, for tests.
string Function Trade(Actor akNpc, string asKind, string asItem, int aiAmount, int aiCount, int aiPrice)
	If (aiAmount < 0 && (asKind == "give_gold" || asKind == "ask_gold")) \
		|| (aiCount < 0 && (asKind == "give_item" || asKind == "ask_item" || asKind == "offer_trade")) \
		|| (aiPrice < 0 && asKind == "offer_trade")
		Return Fail("Nothing traded: the number named was not a sensible amount", "the amount, count or price named was below one or over what can be traded at once")
	EndIf
	If asKind == "give_gold"
		Return GiveGold(akNpc, aiAmount)
	ElseIf asKind == "ask_gold"
		Return AskGold(akNpc, aiAmount, true)
	ElseIf asKind == "take_gift"
		Return TakeGift(akNpc)
	ElseIf asKind != "give_item" && asKind != "ask_item" && asKind != "offer_trade"
		Return Fail("Nothing traded: no kind of trade was named", "the game was not told which kind of trade (" + Named(asKind) + ")")
	ElseIf asItem == ""
		Return Fail("Nothing traded: no item was named", "no item was named")
	ElseIf asKind == "give_item"
		Return GiveItem(akNpc, asItem, aiCount)
	ElseIf asKind == "ask_item"
		Return AskItem(akNpc, asItem, aiCount, true)
	EndIf
	Return OfferTrade(akNpc, asItem, aiCount, aiPrice, true)
EndFunction

; A number argument (declared integer in the action file); 0 when missing or zero (a count then means one, a price the
; shop price, a gold amount is refused), -1 when negative or over aiMax (AMOUNT_MAX, COUNT_MAX for a count): Trade
; refuses it, never quietly turned into one item or into all they carry. Read with getInt only: SKSE_HTTP does no type
; check, and getString on a number crashes the game. The Hub turns a number sent as text into a number before it reaches the game.
int Function Amount(int aiArguments, string asKey, int aiMax = 100000)
	int n = SKSE_HTTP.getInt(aiArguments, asKey, 0)
	If n < 0 || n > aiMax
		Return -1
	EndIf
	Return n
EndFunction

; Mantella sent the action without its arguments (Advanced Actions off in Mantella).
string Function NoArguments(Actor akNpc, string asWhat)
	Return Fail("Nothing traded: the game was not told " + asWhat, "the game was not told " + asWhat + " (Mantella's Advanced Actions are off)")
EndFunction

; ---------------------------------------------------------------------------
; Gold
; ---------------------------------------------------------------------------

; NPC -> player. Returns the event line, for tests.
string Function GiveGold(Actor akNpc, int aiAmount)
	string why = Unusable(akNpc)
	If why != ""
		Return Fail("Nothing given: " + why, why)
	EndIf
	string who = akNpc.GetDisplayName()
	string player = MLWW_Util.PlayerName()
	If aiAmount <= 0
		Return Fail("Nothing given: no amount was named", "no amount of gold was named")
	EndIf
	int purse = akNpc.GetItemCount(Gold())
	If purse < aiAmount
		Return Fail(who + " has only " + purse + " gold", who + " carries only " + purse + " gold, not " + aiAmount)
	EndIf
	If !Free(akNpc)
		int credit = Credit(akNpc)
		If aiAmount > credit
			Return Fail(who + " will not give a stranger gold", StrangerPays(who, player, credit) + ", so " + who + " pays at most " + credit + " gold")
		EndIf
	EndIf
	int had = PlayerRef.GetItemCount(Gold())
	akNpc.RemoveItem(Gold(), aiAmount, true, PlayerRef)
	If PlayerRef.GetItemCount(Gold()) - had < aiAmount
		Return Fail("Nothing given: the gold did not arrive", "the " + aiAmount + " gold did not reach " + player)
	EndIf
	UseCredit(akNpc, aiAmount)
	WriteCarry(akNpc)
	Return Done(who + " gave you " + aiAmount + " gold", who + " handed " + player + " " + aiAmount + " gold; it was handed over")
EndFunction

; Player -> NPC, after a Yes/No (abAsk; tests call it without).
string Function AskGold(Actor akNpc, int aiAmount, bool abAsk = false)
	string why = Unusable(akNpc)
	If why != ""
		Return Fail("Nothing paid: " + why, why)
	EndIf
	string who = akNpc.GetDisplayName()
	string player = MLWW_Util.PlayerName()
	If aiAmount <= 0
		Return Fail("Nothing paid: no amount was named", "no amount of gold was named")
	EndIf
	int purse = PlayerRef.GetItemCount(Gold())
	If purse < aiAmount
		Return Fail("Not paid: you have only " + purse + " gold", player + " has only " + purse + " gold, not " + aiAmount)
	EndIf
	int amount = aiAmount
	bool chose = false
	string all = ""
	If abAsk && !TradesFree(akNpc)
		int answer = Confirm("Give " + who + " " + aiAmount + " gold? (you have " + purse + ")", "Give " + aiAmount + " gold", "Type an amount of gold, like 2000.")
		If answer < 0
			Return Fail("You kept your gold", player + " chose not to hand over the " + aiAmount + " gold")
		ElseIf answer > 0
			chose = true
			amount = Count(answer, PlayerRef.GetItemCount(Gold()))
			If amount < answer
				all = " (all " + player + " had)"
			EndIf
		EndIf
	EndIf
	If PlayerRef.GetItemCount(Gold()) < amount || PlayerRef.GetItemCount(Gold()) <= 0
		Return Fail("Not paid: you no longer have " + amount + " gold", player + " no longer has " + amount + " gold")
	EndIf
	If !PayGold(akNpc, amount)
		Return Fail("Not paid: the gold could not be handed over", "the gold could not be handed over to " + who + "; " + player + " kept it")
	EndIf
	WriteCarry(akNpc)
	Return Done("You gave " + who + " " + amount + " gold", player + " handed " + who + " " + amount + " gold" + all + Instead(chose, amount, aiAmount, aiAmount + " gold") + "; it was handed over")
EndFunction

; The player's gold to the NPC (MoveGold: added to them first, then taken from the player without a destination, as
; World's plugin would count gold handed over as a gift). False when nothing moved.
bool Function PayGold(Actor akNpc, int aiAmount)
	If !MoveGold(PlayerRef, akNpc, aiAmount)
		Return false
	EndIf
	AddCredit(akNpc, aiAmount)
	Return true
EndFunction

; aiAmount gold from akFrom to akTo. The add comes first and is checked: only when akTo really holds the gold is it taken
; from akFrom. False (and nothing moved) when akFrom lacks it or akTo did not take it. Never a destination on the remove:
; World's plugin would count gold handed to an NPC as a gift.
bool Function MoveGold(ObjectReference akFrom, ObjectReference akTo, int aiAmount)
	If !akFrom || !akTo || aiAmount <= 0 || akFrom.GetItemCount(Gold()) < aiAmount
		Return false
	EndIf
	int before = akTo.GetItemCount(Gold())
	akTo.AddItem(Gold(), aiAmount, true)
	int added = akTo.GetItemCount(Gold()) - before
	If added < aiAmount
		If added > 0
			akTo.RemoveItem(Gold(), added, true)  ; take back the part that did arrive: nothing moved
		EndIf
		Return false
	EndIf
	akFrom.RemoveItem(Gold(), aiAmount, true)
	Return true
EndFunction

; ---------------------------------------------------------------------------
; Items
; ---------------------------------------------------------------------------

; NPC -> player: something they carry, never a quest item.
string Function GiveItem(Actor akNpc, string asItem, int aiCount)
	string why = Unusable(akNpc)
	If why != ""
		Return Fail("Nothing given: " + why, why)
	EndIf
	string who = akNpc.GetDisplayName()
	string player = MLWW_Util.PlayerName()
	Form item = FindItem(akNpc, asItem)
	If !item
		Return Fail(who + " has no " + asItem, who + " carries nothing called " + Named(asItem) + " that can be handed over")
	EndIf
	int have = akNpc.GetItemCount(item)
	int count = Count(aiCount, have)
	int value = item.GetGoldValue() * count
	If !Free(akNpc)
		int credit = Credit(akNpc)
		If value > credit
			Return Fail(who + " will not give a stranger goods", StrangerPays(who, player, credit) + ", and " + Pieces(item, count) + " is worth " + value + " gold")
		EndIf
	EndIf
	int had = PlayerRef.GetItemCount(item)
	akNpc.RemoveItem(item, count, true, PlayerRef)
	If PlayerRef.GetItemCount(item) - had < count
		Return Fail("Nothing given: the " + item.GetName() + " did not arrive", Pieces(item, count) + " did not reach " + player)
	EndIf
	UseCredit(akNpc, value)
	WriteCarry(akNpc)
	Return Done(who + " gave you " + Pieces(item, count), who + " handed " + player + " " + Pieces(item, count) + Short(count, aiCount, have) + "; it was handed over")
EndFunction

; Player -> NPC: something the player carries, never a quest item; a Yes/No first. Handed over directly so enchanted
; or tempered items stay as they are (World records it as a gift, as it does for any item handed to an NPC).
string Function AskItem(Actor akNpc, string asItem, int aiCount, bool abAsk = false)
	string why = Unusable(akNpc)
	If why != ""
		Return Fail("Nothing handed over: " + why, why)
	EndIf
	string who = akNpc.GetDisplayName()
	string player = MLWW_Util.PlayerName()
	Form item = FindItem(PlayerRef, asItem)
	If !item
		Return Fail("You have no " + asItem, player + " carries nothing called " + Named(asItem) + " that can be handed over")
	EndIf
	int have = PlayerRef.GetItemCount(item)
	int count = Count(aiCount, have)
	int asked = count
	bool chose = false
	If abAsk && !TradesFree(akNpc)
		int answer = Confirm("Give " + who + " " + Pieces(item, count) + "? (you have " + have + ")", "Give it", "Type how many, like 3, or gold instead, like 50 gold.")
		If answer < 0
			Return Fail("You kept the " + item.GetName(), player + " chose not to hand over " + Pieces(item, count))
		ElseIf answer > 0 && typedGold
			int coins = Count(answer, PlayerRef.GetItemCount(Gold()))
			If PlayerRef.GetItemCount(Gold()) <= 0
				Return Fail("Nothing given: you have no gold", player + " offered gold instead of " + Pieces(item, asked) + " but has none")
			EndIf
			If !PayGold(akNpc, coins)
				Return Fail("Nothing given: the gold could not be handed over", "the gold could not be handed over to " + who + "; " + player + " kept it")
			EndIf
			WriteCarry(akNpc)
			Return Done("You gave " + who + " " + coins + " gold", player + " handed " + who + " " + coins + " gold instead of the " + Pieces(item, asked) + " asked for; it was handed over")
		ElseIf answer > 0
			chose = true
			count = answer
		EndIf
	EndIf
	count = Count(count, PlayerRef.GetItemCount(item))
	If count <= 0
		Return Fail("You no longer have the " + item.GetName(), player + " no longer has " + Named(item.GetName()))
	EndIf
	int had = akNpc.GetItemCount(item)
	PlayerRef.RemoveItem(item, count, true, akNpc)
	If akNpc.GetItemCount(item) - had < count
		Return Fail("Nothing handed over: the " + item.GetName() + " did not arrive", Pieces(item, count) + " did not reach " + who)
	EndIf
	AddCredit(akNpc, item.GetGoldValue() * count)
	WriteCarry(akNpc)
	Return Done("You gave " + who + " " + Pieces(item, count), player + " handed " + who + " " + Pieces(item, count) + Short(count, aiCount, have) + Instead(chose, count, asked, Pieces(item, asked)) + "; it was handed over")
EndFunction

; ---------------------------------------------------------------------------
; Merchants
; ---------------------------------------------------------------------------

; A merchant sells from their vendor chest (or what they carry) for aiPrice gold in all, held to PRICE_MIN..PRICE_MAX of
; the barter menu's price; a Yes/No first. The gold goes where the wares came from: the merchant chest Chest() found
; (where barter puts it, wherever the merchant stands), the NPC when the wares were his own or the chest did not take the
; gold. The gold is checked in its new place before it leaves the player, and the goods on arrival (else the gold goes
; back). The sale counts as trade with them (MLWW_Personal.OnTrade), as a barter menu would.
string Function OfferTrade(Actor akNpc, string asItem, int aiCount, int aiPrice, bool abAsk = false)
	string why = Unusable(akNpc)
	If why != ""
		Return Fail("No trade: " + why, why)
	EndIf
	string who = akNpc.GetDisplayName()
	string player = MLWW_Util.PlayerName()
	ObjectReference chest = Chest(akNpc)
	If !chest
		Return Fail("No trade: " + who + " is no merchant", who + " is no merchant and has no wares to sell")
	EndIf
	ObjectReference source = chest
	Form item = FindItem(chest, asItem)
	If !item
		source = akNpc
		item = FindItem(akNpc, asItem)
	EndIf
	If !item
		Return Fail("No trade: " + who + " has no " + asItem, who + " has nothing called " + Named(asItem) + " for sale")
	EndIf
	int have = source.GetItemCount(item)
	int count = Count(aiCount, have)
	int fair = MenuPrice(item) * count
	int low = Math.Ceiling(fair * PRICE_MIN)
	int high = Math.Floor(fair * PRICE_MAX)
	If high < 1
		high = 1
	EndIf
	If low > high
		low = high
	EndIf
	int price = aiPrice
	string held = ""
	If price <= 0
		price = fair
	ElseIf price < low
		price = low
		held = " (the price was raised to " + low + " gold, half the shop price)"
	ElseIf price > high
		price = high
		held = " (the price was lowered to " + high + " gold, one and a half times the shop price)"
	EndIf
	int purse = PlayerRef.GetItemCount(Gold())
	If purse < price
		Return Fail("Trade declined: you have only " + purse + " gold", player + " has only " + purse + " gold; " + Pieces(item, count) + " costs " + price)
	EndIf
	int offered = price
	bool chose = false
	If abAsk && !TradesFree(akNpc)
		int answer = Confirm(who + " sells you " + Pieces(item, count) + " for " + price + " gold (shop price " + fair + ", you have " + purse + "). Buy it?", "Buy for " + price + " gold", "Type the gold you pay, like " + price + ".")
		If answer < 0
			Return Fail("Trade declined", player + " declined to buy " + Pieces(item, count) + " for " + price + " gold")
		ElseIf answer > 0
			chose = true
			price = Count(answer, PlayerRef.GetItemCount(Gold()))
			held = ""
			If price < low
				price = low
				held = " (the price was raised to " + low + " gold, half the shop price)"
			EndIf
		EndIf
	EndIf
	count = Count(count, source.GetItemCount(item))
	If count <= 0 || PlayerRef.GetItemCount(Gold()) < price
		Return Fail("Trade declined: it is gone or you lack the gold", "the goods or the gold were no longer there")
	EndIf
	ObjectReference till = source
	If !MoveGold(PlayerRef, till, price)
		till = akNpc
		If source == akNpc || !MoveGold(PlayerRef, till, price)
			Return Fail("Trade declined: the gold could not be handed over", "the gold could not be handed over to " + who + "; " + player + " kept it")
		EndIf
	EndIf
	int had = PlayerRef.GetItemCount(item)
	source.RemoveItem(item, count, true, PlayerRef)
	If PlayerRef.GetItemCount(item) - had < count
		MoveGold(till, PlayerRef, price)  ; the goods did not arrive: the gold goes back
		Return Fail("Trade declined: the goods could not be handed over", Pieces(item, count) + " could not be handed over, so " + player + " got the gold back")
	EndIf
	ownTrades += 1
	akNpc.SendModEvent("MLWW_Trade", chest.GetItemCount(Gold()) + "|" + price + "|0", -price)  ; trade totals, as from the barter menu; the chest Chest() found, not po3's vendor faction (only there in the shop)
	WriteCarry(akNpc)
	Return Done("Bought " + Pieces(item, count) + " for " + price + " gold", player + " bought " + Pieces(item, count) + " from " + who + " for " + price + " gold" + Instead(chose, price, offered, offered + " gold") + held + "; the goods and the gold were handed over")
EndFunction

; The barter menu's price to buy aiItem, by the player's Speech (vanilla fBarterMax at Speech 0 to fBarterMin at 100;
; perks and the merchant's own settings left out).
int Function MenuPrice(Form akItem)
	int price = Math.Ceiling(akItem.GetGoldValue() * PriceFactor())
	If price < 1
		price = 1
	EndIf
	Return price
EndFunction

; The barter menu's buy factor for the player's Speech (MenuPrice, and once per chest for WriteWares).
float Function PriceFactor()
	float hi = Game.GetGameSettingFloat("fBarterMax")
	float lo = Game.GetGameSettingFloat("fBarterMin")
	If hi <= 0.0
		hi = 3.3
	EndIf
	If lo <= 0.0 || lo > hi
		lo = 2.0
	EndIf
	float speech = PapyrusUtil.ClampFloat(PlayerRef.GetActorValue("Speechcraft"), 0.0, 100.0)
	Return hi - (hi - lo) * speech / 100.0
EndFunction

; The merchant's vendor chest, None for anyone who is not a merchant: a faction the NPC is a member of (rank 0 or more)
; that has a merchant container (Lucan Valerius: Riverwood Trader Services 0005A665 -> chest 00078C0B; Alvor: Alvor
; Services 0005A666 -> 00078C10). Not Faction.IsVendor(): SKSE tests flag bit 0x1000, while the game's vendor-services
; factions carry 0x4000 and 0x1000 is set on a hold's crime faction (diag 2026-11-15). Wherever the NPC stands: po3's
; GetVendorFaction only answers while he is in his vendor location, so it is the last fallback. A merchant away from his
; shop still sells from his merchant chest by talk (the barter menu keeps the game's own place and hours).
ObjectReference Function Chest(Actor akNpc)
	Faction[] factions = akNpc.GetFactions(0, 127)
	int i = 0
	While factions && i < factions.Length
		Faction f = factions[i]
		If f
			ObjectReference box = f.GetMerchantContainer()
			If box
				Return box
			EndIf
		EndIf
		i += 1
	EndWhile
	Faction vendor = PO3_SKSEFunctions.GetVendorFaction(akNpc)
	If !vendor
		Return None
	EndIf
	Return PO3_SKSEFunctions.GetVendorFactionContainer(vendor)
EndFunction

; ---------------------------------------------------------------------------
; Gifts through the game's gift menu
; ---------------------------------------------------------------------------

; Opens the gift menu (no favor points); World's plugin sends MLWW_GiftMenu for each thing given, collected below.
string Function TakeGift(Actor akNpc)
	string why = Unusable(akNpc)
	If why != ""
		Return Fail("No gift menu: " + why, why)
	EndIf
	string who = akNpc.GetDisplayName()
	string player = MLWW_Util.PlayerName()
	giftNpc = akNpc
	giftItems = ""
	giftGold = 0
	giftCount = 0
	giftOpen = true
	akNpc.ShowGiftMenu(true, None, false, false)
	Utility.Wait(0.5)  ; the plugin's gift events come just after the menu closes
	giftOpen = false
	giftNpc = None
	WriteCarry(akNpc)
	If giftItems == ""
		Return Done("You gave " + who + " nothing", player + " opened the gift menu but gave " + who + " nothing")
	EndIf
	; The plugin remembers gift-menu gifts without scoring them (M.A.R.A.S scores its own); this menu is ours, so score.
	If giftGold >= 50
		MLWW_Facts.Score(akNpc, "gifts", PapyrusUtil.ClampFloat(giftGold / 100.0, 0.5, 5.0))
	EndIf
	If giftCount > 0
		MLWW_Facts.Score(akNpc, "gifts", PapyrusUtil.ClampFloat(giftCount as float, 1.0, 3.0))
	EndIf
	Return Done("You gave " + who + ": " + giftItems, player + " gave " + who + " " + giftItems + " as a gift")
EndFunction

Event OnGiftItem(string asEvent, string asItem, float afCount, Form akSender)
	If !giftOpen || akSender != giftNpc || asItem == ""
		Return
	EndIf
	int count = afCount as int
	If asItem == Gold().GetName()
		giftGold += count
	Else
		giftCount += 1
	EndIf
	string piece = asItem
	If count > 1
		piece = count + " " + asItem
	EndIf
	If giftItems != ""
		giftItems += ", "
	EndIf
	giftItems += piece
EndEvent

; ---------------------------------------------------------------------------
; Barter menu during a talk, credit, what the NPC carries
; ---------------------------------------------------------------------------

; asText: "<chest gold>|<gold the player paid>|<gold the player was paid>" (MLWW_Personal.OnTrade). Only told when the
; merchant is in the running talk (Mantella's Barter action, or the player opening it).
Event OnBarterDone(string asEvent, string asText, float afPlayerGold, Form akSender)
	If ownTrades > 0
		ownTrades -= 1
		Return
	EndIf
	Actor npc = akSender as Actor
	string[] parts = StringUtil.Split(asText, "|")
	If !npc || parts.Length != 3 || !InTalk(npc)
		Return
	EndIf
	string player = MLWW_Util.PlayerName()
	string line = player + " traded with " + npc.GetDisplayName() + " in the barter menu"
	If parts[1] as int > 0
		line += ", paying " + parts[1] + " gold"
	EndIf
	If parts[2] as int > 0
		line += ", and was paid " + parts[2] + " gold"
	EndIf
	WriteCarry(npc)
	MLWW_Util.Send("trade", "(" + line + ".)")
EndEvent

Event OnTalkStarted()
	If StorageUtil.GetIntValue(None, "MLW_TimingOn", 0) == 1  ; speed testing (off by default): one stage-time row
		MiscUtil.WriteToFile("Data/SKSE/Plugins/StorageUtilData/MantellaLivingWorld/timing_game.csv", StorageUtil.GetIntValue(None, "MLW_TimingTalk", 0) + "," + Utility.GetCurrentRealTime() + ",MLWW_Trade,OnTalkStarted_start,\n", true, false)
	EndIf
	int i = StorageUtil.FormListCount(self, KEY_TALK)
	While i > 0
		i -= 1
		StorageUtil.UnsetIntValue(StorageUtil.FormListGet(self, KEY_TALK, i), KEY_CREDIT)
	EndWhile
	StorageUtil.FormListClear(self, KEY_TALK)
	If StorageUtil.GetIntValue(None, "MLW_TimingOn", 0) == 1  ; speed testing (off by default): one stage-time row
		MiscUtil.WriteToFile("Data/SKSE/Plugins/StorageUtilData/MantellaLivingWorld/timing_game.csv", StorageUtil.GetIntValue(None, "MLW_TimingTalk", 0) + "," + Utility.GetCurrentRealTime() + ",MLWW_Trade,OnTalkStarted_end,\n", true, false)
	EndIf
EndEvent

Event OnNpcAdded(Form akActor)
	If StorageUtil.GetIntValue(None, "MLW_TimingOn", 0) == 1  ; speed testing (off by default): one stage-time row
		MiscUtil.WriteToFile("Data/SKSE/Plugins/StorageUtilData/MantellaLivingWorld/timing_game.csv", StorageUtil.GetIntValue(None, "MLW_TimingTalk", 0) + "," + Utility.GetCurrentRealTime() + ",MLWW_Trade,OnNpcAdded_start,\n", true, false)
	EndIf
	Actor npc = akActor as Actor
	If npc && npc != PlayerRef
		WriteCarry(npc)
	EndIf
	If StorageUtil.GetIntValue(None, "MLW_TimingOn", 0) == 1  ; speed testing (off by default): one stage-time row
		MiscUtil.WriteToFile("Data/SKSE/Plugins/StorageUtilData/MantellaLivingWorld/timing_game.csv", StorageUtil.GetIntValue(None, "MLW_TimingTalk", 0) + "," + Utility.GetCurrentRealTime() + ",MLWW_Trade,OnNpcAdded_end,\n", true, false)
	EndIf
EndEvent

int Function Credit(Actor akNpc)
	Return StorageUtil.GetIntValue(akNpc, KEY_CREDIT, 0)
EndFunction

Function AddCredit(Actor akNpc, int aiValue)
	If aiValue > 0
		StorageUtil.AdjustIntValue(akNpc, KEY_CREDIT, aiValue)
		StorageUtil.FormListAdd(self, KEY_TALK, akNpc, false)
	EndIf
EndFunction

Function UseCredit(Actor akNpc, int aiValue)
	int left = Credit(akNpc) - aiValue
	If left > 0
		StorageUtil.SetIntValue(akNpc, KEY_CREDIT, left)
	Else
		StorageUtil.UnsetIntValue(akNpc, KEY_CREDIT)
	EndIf
EndFunction

string Function StrangerPays(string asWho, string asPlayer, int aiCredit)
	If aiCredit <= 0
		Return asWho + " does not know " + asPlayer + " well and hands over gold or goods only as payment for what " + asPlayer + " gives first, and " + asPlayer + " has given nothing yet in this talk"
	EndIf
	Return asWho + " does not know " + asPlayer + " well and hands over gold or goods only as payment: " + asPlayer + " has handed over " + aiCredit + " gold's worth in this talk"
EndFunction

; What the NPC carries, for the Hub's trade line: gold, the most valuable things they could hand over (not worn), and for
; a merchant what the chest holds with the barter menu's prices.
Function WriteCarry(Actor akNpc)
	If !akNpc || akNpc == PlayerRef || !akNpc.GetActorBase().IsUnique()
		Return  ; a generic NPC shares the per-base file with others of its kind (as MLWW_Facts.Sync): never written
	EndIf
	string path = DIR + MLWW_Util.BaseId(akNpc) + ".json"
	JsonUtil.SetIntValue(path, "carry_gold", akNpc.GetItemCount(Gold()))
	JsonUtil.SetStringValue(path, "carry_items", Best(akNpc, akNpc, MAX_CARRY, false))
	ObjectReference chest = Chest(akNpc)
	JsonUtil.SetIntValue(path, "merchant", (chest != None) as int)
	JsonUtil.SetStringValue(path, "stock", WriteWares(path, chest))  ; one pass over the chest for both
	JsonUtil.Save(path)
EndFunction

; Every ware in the merchant's chest as "kind|count|price|name" (list "wares"), so the Hub can name a few of each kind and
; count the rest: with only the dearest five (stock), Lucan denied having the Oakflesh tome his chest held (live test 9).
; Cleared for anyone who is not a merchant. Returns the dearest MAX_STOCK with their barter prices (stock, as Best would),
; from the same pass: each item's count is asked once (each count waits for the game's frame).
; wares_complete is 1 only when the pass reached the chest's last entry: a bigger chest stops at MAX_SCAN, and the Hub
; then calls the list a sample, never the whole stock.
string Function WriteWares(string asPath, ObjectReference akChest)
	JsonUtil.StringListClear(asPath, "wares")
	JsonUtil.SetIntValue(asPath, "wares_complete", 0)
	If !akChest
		Return ""
	EndIf
	Form[] best = Utility.CreateFormArray(MAX_STOCK)
	int[] values = Utility.CreateIntArray(MAX_STOCK, -1)
	int[] counts = Utility.CreateIntArray(MAX_STOCK, 0)
	Form[] forms = akChest.GetContainerForms()
	Form[] questItems = PO3_SKSEFunctions.GetQuestItems(akChest)
	float factor = PriceFactor()
	int i = 0
	While forms && i < forms.Length && i < MAX_SCAN
		Form f = forms[i]
		; Handable's test with one item count per ware (each count waits for the game's frame)
		int count = 0
		If f && f != Gold() && f.GetName() != "" && f.IsPlayable() && (!questItems || questItems.Find(f) < 0)
			count = akChest.GetItemCount(f)
		EndIf
		If count > 0
			int price = Math.Ceiling(f.GetGoldValue() * factor)
			If price < 1
				price = 1
			EndIf
			JsonUtil.StringListAdd(asPath, "wares", WareKind(f) + "|" + count + "|" + price + "|" + f.GetName())
			int v = f.GetGoldValue()
			int at = MAX_STOCK
			While at > 0 && v > values[at - 1]
				at -= 1
			EndWhile
			If at < MAX_STOCK
				int j = MAX_STOCK - 1
				While j > at
					best[j] = best[j - 1]
					values[j] = values[j - 1]
					counts[j] = counts[j - 1]
					j -= 1
				EndWhile
				best[at] = f
				values[at] = v
				counts[at] = count
			EndIf
		EndIf
		i += 1
	EndWhile
	JsonUtil.SetIntValue(asPath, "wares_complete", (!forms || i >= forms.Length) as int)
	string out = ""
	i = 0
	While i < MAX_STOCK && best[i]
		If out != ""
			out += ", "
		EndIf
		out += Pieces(best[i], counts[i]) + " " + MenuPrice(best[i]) + " gold"
		i += 1
	EndWhile
	Return out
EndFunction

; The kind of a ware, as the Hub names them: spell tome, book, potion, poison, food, weapon, ammo, armor, clothing,
; jewelry, soul gem, ingredient, scroll, key, misc.
string Function WareKind(Form akItem)
	Book tome = akItem as Book
	If tome
		If tome.GetSpell()
			Return "spell tome"
		EndIf
		Return "book"
	EndIf
	Potion drink = akItem as Potion
	If drink
		If drink.IsFood()
			Return "food"
		ElseIf drink.IsPoison()
			Return "poison"
		EndIf
		Return "potion"
	EndIf
	If akItem as Weapon
		Return "weapon"
	ElseIf akItem as Ammo
		Return "ammo"
	EndIf
	Armor worn = akItem as Armor
	If worn
		If worn.IsJewelry()
			Return "jewelry"
		ElseIf worn.IsClothing()
			Return "clothing"
		EndIf
		Return "armor"
	EndIf
	If akItem as SoulGem
		Return "soul gem"
	ElseIf akItem as Ingredient
		Return "ingredient"
	ElseIf akItem as Scroll
		Return "scroll"
	ElseIf akItem as Key
		Return "key"
	EndIf
	Return "misc"
EndFunction

; Up to aiMax things in akFrom by value, most valuable first: "Steel Sword, 3 Bread". akWearer: leave out what they wear.
; abPrices: each with its barter menu price ("Steel Sword 150 gold").
string Function Best(ObjectReference akFrom, Actor akWearer, int aiMax, bool abPrices)
	Form[] forms = akFrom.GetContainerForms()
	Form[] questItems = PO3_SKSEFunctions.GetQuestItems(akFrom)
	Form[] best = Utility.CreateFormArray(aiMax)
	int[] values = Utility.CreateIntArray(aiMax, -1)
	int i = 0
	While forms && i < forms.Length && i < MAX_SCAN
		Form f = forms[i]
		If Handable(f, akFrom, questItems) && (!akWearer || !akWearer.IsEquipped(f))
			int v = f.GetGoldValue()
			int at = aiMax
			While at > 0 && v > values[at - 1]
				at -= 1
			EndWhile
			If at < aiMax
				int j = aiMax - 1
				While j > at
					best[j] = best[j - 1]
					values[j] = values[j - 1]
					j -= 1
				EndWhile
				best[at] = f
				values[at] = v
			EndIf
		EndIf
		i += 1
	EndWhile
	string out = ""
	i = 0
	While i < aiMax && best[i]
		If out != ""
			out += ", "
		EndIf
		out += Pieces(best[i], akFrom.GetItemCount(best[i]))
		If abPrices
			out += " " + MenuPrice(best[i]) + " gold"
		EndIf
		i += 1
	EndWhile
	Return out
EndFunction

; ---------------------------------------------------------------------------
; Helpers
; ---------------------------------------------------------------------------

MiscObject goldForm = None

MiscObject Function Gold()
	If !goldForm
		goldForm = Game.GetFormFromFile(0x00000F, "Skyrim.esm") as MiscObject
	EndIf
	Return goldForm
EndFunction

; Something in akIn that can change hands: named, playable, there, not gold and not a quest item.
bool Function Handable(Form akItem, ObjectReference akIn, Form[] akQuest)
	If !akItem || akItem == Gold() || akItem.GetName() == "" || !akItem.IsPlayable() || akIn.GetItemCount(akItem) <= 0
		Return false
	EndIf
	Return !akQuest || akQuest.Find(akItem) < 0
EndFunction

; The item in akIn the model meant by asName: the same name (any case), else the shortest name holding it, else the
; shortest name it holds ("a fine steel sword" -> Steel Sword). Never gold or a quest item. None when nothing fits.
Form Function FindItem(ObjectReference akIn, string asName)
	If !akIn || asName == ""
		Return None
	EndIf
	Form[] forms = akIn.GetContainerForms()
	Form[] questItems = PO3_SKSEFunctions.GetQuestItems(akIn)
	Form inside = None
	int insideLen = 0
	Form holds = None
	int holdsLen = 0
	int i = 0
	While forms && i < forms.Length && i < MAX_SCAN
		Form f = forms[i]
		If Handable(f, akIn, questItems)
			string name = f.GetName()
			If name == asName  ; Papyrus compares strings without case
				Return f
			EndIf
			int len = StringUtil.GetLength(name)
			If StringUtil.Find(name, asName) >= 0 && (!inside || len < insideLen)
				inside = f
				insideLen = len
			ElseIf StringUtil.Find(asName, name) >= 0 && (!holds || len > holdsLen)
				holds = f
				holdsLen = len
			EndIf
		EndIf
		i += 1
	EndWhile
	If inside
		Return inside
	EndIf
	Return holds
EndFunction

; The count to move: at least 1, at most what is there.
int Function Count(int aiWanted, int aiHave)
	int n = aiWanted
	If n < 1
		n = 1
	EndIf
	If n > aiHave
		n = aiHave
	EndIf
	Return n
EndFunction

; " (only 2 were there)" when fewer than asked moved.
string Function Short(int aiMoved, int aiWanted, int aiHave)
	If aiWanted > aiMoved && aiMoved == aiHave
		Return " (only " + aiHave + " were there)"
	EndIf
	Return ""
EndFunction

string Function Pieces(Form akItem, int aiCount)
	If aiCount > 1
		Return aiCount + " " + akItem.GetName()
	EndIf
	Return akItem.GetName()
EndFunction

string Function Named(string asName)
	Return "\"" + asName + "\""
EndFunction

; Why this NPC cannot trade now, "" when they can.
string Function Unusable(Actor akNpc)
	If !akNpc || akNpc == PlayerRef
		Return "nobody to trade with"
	ElseIf akNpc.IsDead()
		Return akNpc.GetDisplayName() + " is dead"
	EndIf
	Return ""
EndFunction

; Gives and takes freely: in the party, close (the Hub's standing in the NPC's file), a vanilla friend or better, or
; under an absolute command. Never a child: they count as strangers.
bool Function Free(Actor akNpc)
	If akNpc.IsChild()
		Return false
	EndIf
	If akNpc.IsPlayerTeammate() || akNpc.GetRelationshipRank(PlayerRef) >= 1
		Return true
	EndIf
	If StorageUtil.GetFloatValue(akNpc, "MLW_CommandUntil", 0.0) > Utility.GetCurrentGameTime()
		Return true
	EndIf
	string path = DIR + MLWW_Util.BaseId(akNpc) + ".json"
	Return JsonUtil.GetIntValue(path, "close", 0) > 0 || JsonUtil.GetIntValue(path, "follower", 0) > 0
EndFunction

; The per-NPC "Trades without asking" flag (set on the Integration Hub's side): no Yes/No box for this NPC. Read from any
; of the places a flag may be kept, so it works however the Hub stores it; off when none holds it.
bool Function TradesFree(Actor akNpc)
	If StorageUtil.GetIntValue(akNpc, "MLW_TradesFree", 0) > 0 || StorageUtil.GetIntValue(akNpc.GetActorBase(), "MLW_TradesFree", 0) > 0
		Return true
	EndIf
	string path = DIR + MLWW_Util.BaseId(akNpc) + ".json"
	If JsonUtil.GetIntValue(path, "trades_free", 0) > 0 || JsonUtil.GetIntValue(path, "trades_without_asking", 0) > 0
		Return true
	EndIf
	int i = JsonUtil.StringListCount(path, "flags")
	While i > 0
		i -= 1
		string flag = JsonUtil.StringListGet(path, "flags", i)
		If flag == "trades_free" || flag == "trades_without_asking" || flag == "Trades without asking"
			Return true
		EndIf
	EndWhile
	Return false
EndFunction

; The confirm box before gold or goods leave the player: asYes, "Not now", and "Custom answer" when the text box is
; there. -1: no; 0: yes; above 0: the number the player typed (typedGold: the answer said "gold"). An answer that is not
; a number shows a short note (asHint) and the box again; an empty text box goes back to the box.
bool typedGold = false

int Function Confirm(string asQuestion, string asYes, string asHint)
	typedGold = false
	string note = ""
	bool withText = TextBox()
	While true
		string pick
		If withText
			pick = SkyMessage.Show(note + asQuestion, asYes, "Not now", CUSTOM_ANSWER)
		Else
			pick = SkyMessage.Show(note + asQuestion, asYes, "Not now")
		EndIf
		If pick == asYes
			Return 0
		ElseIf pick != CUSTOM_ANSWER || !withText
			Return -1
		EndIf
		string text = TypedText()
		int n = TypedNumber(text)
		If n > 0
			typedGold = StringUtil.Find(text, "gold") >= 0
			Return n
		EndIf
		note = ""
		If text != ""
			note = "Not understood: " + Named(text) + ". " + asHint + "\n\n"
		EndIf
	EndWhile
	Return -1
EndFunction

; The UIExtensions text box (the one the Hub's Absolute Command uses) is installed. Without it there is no Custom answer.
bool Function TextBox()
	Return Game.GetModByName("UIExtensions.esp") != 255 || Game.GetLightModByName("UIExtensions.esp") != 65535
EndFunction

string Function TypedText()
	UIExtensions.InitMenu("UITextEntryMenu")
	UIExtensions.OpenMenu("UITextEntryMenu")
	Return UIExtensions.GetMenuResultString("UITextEntryMenu")
EndFunction

; A typed amount: digits, with commas, spaces and the word "gold" allowed ("2000", "2,000", "2000 gold"). -1 when the
; text is anything else, 0, or too long to be an amount.
int Function TypedNumber(string asText)
	string s = asText
	int at = StringUtil.Find(s, "gold")  ; any case
	If at >= 0
		string before = ""
		If at > 0
			before = StringUtil.Substring(s, 0, at)
		EndIf
		string after = ""
		If at + 4 < StringUtil.GetLength(s)
			after = StringUtil.Substring(s, at + 4)
		EndIf
		s = before + after
	EndIf
	int n = 0
	int digits = 0
	int i = 0
	int len = StringUtil.GetLength(s)
	While i < len
		string c = StringUtil.GetNthChar(s, i)
		If StringUtil.IsDigit(c)
			If digits >= 9
				Return -1
			EndIf
			n = n * 10 + (c as int)
			digits += 1
		ElseIf c != "," && c != " "
			Return -1
		EndIf
		i += 1
	EndWhile
	If digits == 0 || n <= 0
		Return -1
	EndIf
	Return n
EndFunction

; " instead of the <asAsked> asked for" when the player chose another amount in the box (abChose).
string Function Instead(bool abChose, int aiMoved, int aiAsked, string asAsked)
	If !abChose || aiMoved == aiAsked
		Return ""
	EndIf
	Return " instead of the " + asAsked + " asked for"
EndFunction

; True while akNpc is in the running Mantella conversation.
bool Function InTalk(Actor akNpc)
	MantellaConversation talk = Game.GetFormFromFile(0x03D41A, "Mantella.esp") as MantellaConversation
	If !talk || !talk.IsRunning()
		Return false
	EndIf
	int i = talk.CountActorsInConversation()
	While i > 0
		i -= 1
		If talk.GetActorInConversationByIndex(i) == akNpc
			Return true
		EndIf
	EndWhile
	Return false
EndFunction

string Function Done(string asHud, string asFact)
	string line = "(" + asFact + ".)"
	MLWW_Util.Result("trade", asHud, line)
	Return line
EndFunction

string Function Fail(string asHud, string asWhy)
	string line = "(Nothing happened: " + asWhy + ".)"
	MLWW_Util.Result("trade", asHud, line)
	Return line
EndFunction
