"""Offline checks for trading by talk (Source/Scripts/MLWW_Trade.psc and its action files), no game needed:
  - the one trade action file (Trade, the kind inside) is well formed (key = name, only kind required, numbers bounded,
    no stock Mantella name), every kind is dispatched to its function, and the Trade handlers and the separate handlers
    of the previous version (kept one version) tell Mantella the action is done;
  - every result of a trade function goes back to the talk through Done or Fail (one event line, in parentheses, and the
    HUD line), so the NPC always learns whether it worked; a refusal starts "(Nothing happened: ";
  - the player's gold never goes straight into an NPC (World's plugin would count it as a gift), every confirm box is
    followed by a re-check of what it is about, and the HUD lines of World and the Hub obey the one MCM switch;
  - the confirm box's Custom answer: shown only with the UIExtensions text box, a port of the typed-amount parser run on
    cases, and the event line telling the NPC what they really got;
  - a port of the item matching, counts, price limits and the stranger rule, run on cases.
usage: py -3 test/check_trade.py
"""
import json
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODING = os.path.dirname(ROOT)
HUB = os.path.join(CODING, 'Mantella-Living-World-Hub')
TRADE = open(os.path.join(ROOT, 'Source', 'Scripts', 'MLWW_Trade.psc'), encoding='utf-8').read()
UTIL = open(os.path.join(ROOT, 'Source', 'Scripts', 'MLWW_Util.psc'), encoding='utf-8').read()
CRIME = open(os.path.join(ROOT, 'Source', 'Scripts', 'MLWW_Crime.psc'), encoding='utf-8').read()
ACTIONS = os.path.join(ROOT, 'SKSE', 'Plugins', 'MantellaSoftware', 'data', 'actions')
STOCK = {'AbsolveCrime', 'AddToConversation', 'Attack', 'Barter', 'Brawl', 'CancelTravel', 'CastSpell', 'CheckDirections',
         'CollectIngredients', 'Emote', 'EndConversation', 'Flee', 'Follow', 'Inventory', 'LeadTo', 'Listen', 'Look', 'Loot',
         'MoveTo', 'ReportCrime', 'ShareConversation', 'StandDown', 'Teleport', 'TravelTo', 'Unfollow', 'Wait'}
fails = 0


def check(name, ok, detail=''):
    global fails
    print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else f': {detail}'))
    fails += not ok


def code(text):
    """Papyrus without comments (strings kept)."""
    out = []
    for line in text.splitlines():
        cut, q = '', False
        for c in line:
            if c == '"':
                q = not q
            if c == ';' and not q:
                break
            cut += c
        out.append(cut)
    return '\n'.join(out)


SRC = code(TRADE)
props = dict(re.findall(r'string Property (\w+) = "([^"]*)" AutoReadOnly', TRADE))


def block(kind, name):
    m = re.search(r'(?im)^\s*(?:\w+\s+)?' + kind + r'\s+' + name + r'\(.*?^\s*End' + kind, SRC, re.S | re.M)
    return m.group(0) if m else ''


# ---------------------------------------------------------------------------------------------------------------------
# Action files and handlers
# ---------------------------------------------------------------------------------------------------------------------
trade_files = {}
for f in sorted(os.listdir(ACTIONS)):
    data = json.load(open(os.path.join(ACTIONS, f), encoding='utf-8'))
    if data['identifier'] in props.values():
        trade_files[data['identifier']] = data
check('one trade action file (Trade, the kind inside)', list(trade_files) == [props['ACTION_TRADE']], sorted(trade_files))
data = trade_files.get(props['ACTION_TRADE'], {})
params = data.get('parameters', {})
check('Trade: not a stock Mantella action name', data.get('name') == 'Trade' and data['name'] not in STOCK, data.get('name'))
check('Trade: key = name, file name = identifier', data.get('key') == data.get('name') and os.path.isfile(os.path.join(ACTIONS, props['ACTION_TRADE'] + '.json')))
check('Trade: only kind is required', data.get('required') == ['kind'], data.get('required'))
check('Trade: numbers have bounds', all(p.get('minimum', 0) >= 1 and p.get('maximum') for p in params.values() if p['type'] == 'integer'))
check('Trade: needs a response (the result comes back to the talk)', data.get('requires_response') is True)
# Live test 8: "I'd like to buy X" always went to stock Barter. The Hub sends only the first sentence of a description.
first = re.split(r'(?<=[.!?])\s+', data.get('description', '').strip(), maxsplit=1)[0]
check('Trade: its first sentence tells offer_trade (a named item for a talked price) from Barter (the shop menu)',
      'offer_trade' in first and 'Barter' in first and 'price' in first, first)
# Live test 15: "once agreed (a named item at a price agreed in talk is offer_trade ...)" kept "I'd like to buy a Potion
# of Minor Healing" (no price said) on Barter. A ware asked for by name is offer_trade, at the shop price when none is agreed.
check('Trade: a ware asked for by name is offer_trade with no price agreed (shop price); no "once agreed" condition',
      'asks to buy by name' in first and 'shop price' in first and 'once agreed' not in first and 'price agreed in talk' not in first, first)
check('Trade: no gate (offer_trade is refused by the game for anyone who is no merchant)', not data.get('lw_gate'), data.get('lw_gate'))
KINDS = {'give_gold': 'GiveGold(akNpc, aiAmount)', 'ask_gold': 'AskGold(akNpc, aiAmount, true)', 'give_item': 'GiveItem(akNpc, asItem, aiCount)',
         'ask_item': 'AskItem(akNpc, asItem, aiCount, true)', 'offer_trade': 'OfferTrade(akNpc, asItem, aiCount, aiPrice, true)',
         'take_gift': 'TakeGift(akNpc)'}
check('Trade: the kind enum is the six kinds', params.get('kind', {}).get('enum') == list(KINDS), params.get('kind', {}).get('enum'))
dispatch = block('Function', 'Trade')
for kind, call in KINDS.items():
    check(f'Trade kind {kind}: dispatched to {call.split("(")[0]} (asking box on where gold or goods leave the player)',
          f'"{kind}"' in dispatch and call in dispatch and (kind in params['kind']['description'] or kind.split('_')[0] + '_*' in params['kind']['description']), kind)
check('Trade: an unknown kind and a missing item are refused with a line', 'no kind of trade was named' in dispatch and 'no item was named' in dispatch)
for p in params:
    check(f'Trade: handler reads "{p}"', f'getString(aiArguments, "{p}"' in block('Event', 'OnTrade') or f'Amount(aiArguments, "{p}"' in block('Event', 'OnTrade'), p)
amount = block('Function', 'Amount')
check('Amount reads a number only with getInt (getString on a number crashes the game); negative or over AMOUNT_MAX is -1',
      'SKSE_HTTP.getInt(aiArguments, asKey, 0)' in amount and 'getString' not in amount
      and 'If n < 0 || n > aiMax\n\t\tReturn -1' in amount.replace('\r\n', '\n') and 'Return AMOUNT_MAX' not in amount, amount)


def trade_refuses(amount, count, price, kind):
    """A port of Trade's first test: which out-of-range numbers it refuses before anything moves, per kind."""
    first = dispatch.replace('\r\n', '\n').split('\tEndIf\n', 1)[0]
    gold, items = ('give_gold', 'ask_gold'), ('give_item', 'ask_item', 'offer_trade')
    return 'Fail(' in first and ((amount < 0 and kind in gold) or (count < 0 and kind in items) or (price < 0 and kind == 'offer_trade'))


check('Trade refuses a negative or absurd number for its kind before anything moves (bounds in the source)',
      all(s in dispatch for s in ('aiAmount < 0 && (asKind == "give_gold" || asKind == "ask_gold")',
                                   'aiCount < 0 && (asKind == "give_item" || asKind == "ask_item" || asKind == "offer_trade")',
                                   'aiPrice < 0 && asKind == "offer_trade"'))
      and dispatch.find('the amount, count or price named') < dispatch.find('GiveGold(akNpc, aiAmount)'), dispatch[:600])
for case, want in (((-1, 0, 0, 'give_gold'), True), ((-1, 0, 0, 'give_item'), False), ((0, -1, 0, 'give_item'), True),
                   ((0, 0, -1, 'offer_trade'), True), ((0, 0, -1, 'ask_item'), False), ((0, 0, 0, 'offer_trade'), False)):
    check(f'Trade bounds: amount/count/price {case[:3]} for {case[3]} {"refused" if want else "goes on"}', trade_refuses(*case) == want, case)
_limits = {k: int(v) for k, v in re.findall(r'int Property (AMOUNT_MAX|COUNT_MAX) = (\d+)', TRADE)}
_reads = block('Event', 'OnTrade')
for _p, _const in (('amount', 'AMOUNT_MAX'), ('count', 'COUNT_MAX'), ('price', 'AMOUNT_MAX')):
    _read_max = _limits.get('COUNT_MAX') if f'Amount(aiArguments, "{_p}", COUNT_MAX)' in _reads else \
        (int(re.search(r'int aiMax = (\d+)', amount).group(1)) if f'Amount(aiArguments, "{_p}")' in _reads else None)
    check(f"Trade {_p}: the action file's maximum is what the game accepts ({_const})",
          params[_p].get('maximum') == _limits.get(_const) == _read_max and params[_p].get('minimum') == 1,
          (params[_p].get('maximum'), _limits.get(_const), _read_max))
sys.path.insert(0, os.path.join(HUB, 'tools'))
try:
    import check_action_getters
    found = check_action_getters.check_repo(ROOT)
    check('every action argument is read with one getter of its declared type', not found, found)
except ImportError:
    check('the Hub getter check (tools/check_action_getters.py) is next to this repo', False)
registered = dict(re.findall(r'RegisterForModEvent\((\w+ \+ \w+), "(\w+)"\)', SRC))
check('the separate actions of an earlier version are no longer registered, and older saves drop them',
      all(f'{p} + ACTION_{a}' not in registered for p in ('ADVANCED', 'LEGACY') for a in ('GIVE_GOLD', 'ASK_GOLD', 'GIVE_ITEM', 'ASK_ITEM', 'OFFER', 'GIFT'))
      and 'UnregisterForModEvent(ADVANCED + gone[g])' in SRC and 'UnregisterForModEvent(LEGACY + gone[g])' in SRC)
for prop in ('ACTION_TRADE',):
    for path in ('ADVANCED', 'LEGACY'):
        handler = registered.get(f'{path} + {prop}')
        body = block('Event', handler) if handler else ''
        check(f'{prop}: {path.lower()} handler {handler} tells Mantella it is done',
              bool(body) and f'MLWW_Util.ActionDone({prop})' in body, handler)
check('legacy Trade (no arguments) opens the gift menu, as TakeGift did', 'TakeGift(akSpeaker as Actor)' in block('Event', 'OnTradeLegacy'))
check('offer_trade for someone who is no merchant: refused with a line', '" is no merchant and has no wares to sell"' in block('Function', 'OfferTrade'))
check('World still writes the merchant field (the Hub line about wares)', 'JsonUtil.SetIntValue(path, "merchant"' in SRC)
# Live test 6: Lucan Valerius (owner of the Riverwood Trader) was "no merchant": po3's GetVendorFaction reads the actor's
# cached vendor faction, only there while he stands in his vendor location. Diag 2026-11-15 measured why the faction loop
# never matched either: SKSE's Faction.IsVendor() tests flag bit 0x1000, set on the hold's crime faction (Whiterun
# 000267EA: 0x40, 0x1000, 0x8000, no container), while the services factions carry 0x4000 (and 0x8000) and the merchant
# container. A merchant is a member (rank 0+) of a faction with a merchant container, wherever he stands.
chest = block('Function', 'Chest')
check("merchant test: the actor's own factions (rank 0+) and their merchant container, before po3's fallback",
      'akNpc.GetFactions(0, 127)' in chest and 'f.GetMerchantContainer()' in chest
      and chest.find('GetFactions') < chest.find('GetVendorFaction'), chest)
check('merchant test: never Faction.IsVendor() (it tests bit 0x1000, the wrong bit on the game data)', 'IsVendor()' not in chest, chest)
check("merchant test: never the actor's own inventory", 'GetItemCount' not in chest and 'GetContainerForms' not in chest)

VENDOR_BIT_SKSE = 0x1000  # what SKSE's Faction.IsVendor() tests


def port_chest(factions, use_is_vendor=False):
    """factions: [(form id, rank, flag bits, merchant container)] as measured in the game. The script's rule; with
    use_is_vendor the old rule (IsVendor() and a container), which must fail on the real data."""
    for form, rank, flags, box in factions:
        if 0 <= rank <= 127 and box and (not use_is_vendor or flags & VENDOR_BIT_SKSE):
            return box
    return None


# measured 2026-11-15 (GetFactions(-128, 127), IsFactionFlagSet over bits 0..16, GetMerchantContainer)
LUCAN = [(0x00013481, 0, 0, None), (0x000267EA, 0, 0x40 | 0x1000 | 0x8000, None),  # crime faction Whiterun
         (0x00035D42, 0, 0x8000, None),  # Riverwood Trader Faction
         (0x00051596, 0, 0, None), (0x00051599, 0, 0, None),
         (0x0005A665, 0, 0x4000 | 0x8000, 0x00078C0B),  # Riverwood Trader Services -> the chest (10 torches, 750 gold)
         (0x0009E0E5, 0, 0, None),  # TG No Pickpocketing
         (0x000AB87A, 0, 0x4000 | 0x8000, 0x00078C0B),  # Riverwood Trader Services
         (0x0001365B, 0, 0, None)]
ALVOR = [(0x000267EA, 0, 0x40 | 0x1000 | 0x8000, None), (0x0005A666, 0, 0x4000, 0x00078C10)]  # Alvor Services
check('Lucan Valerius (measured factions) is a merchant with chest 00078C0B, wherever he stands', port_chest(LUCAN) == 0x00078C0B)
check('Alvor (measured, at home) is a merchant with chest 00078C10', port_chest(ALVOR) == 0x00078C10)
check('the IsVendor() rule finds neither of them on the real data (it is wrong)',
      port_chest(LUCAN, True) is None and port_chest(ALVOR, True) is None)
check('Hod (no faction with a merchant container) is no merchant', port_chest([(1, 0, 0x8000, None), (2, 0, 0x1000, None)]) is None)
check('a vendor faction the NPC was taken out of (rank -1) does not count', port_chest([(3, -1, 0x4000, 'Box')]) is None)

# ---------------------------------------------------------------------------------------------------------------------
# Every result reaches the talk and the HUD
# ---------------------------------------------------------------------------------------------------------------------
for fn in ('Trade', 'GiveGold', 'AskGold', 'GiveItem', 'AskItem', 'OfferTrade', 'TakeGift', 'NoArguments'):
    body = block('Function', fn)
    returns = re.findall(r'\bReturn\b([^\n]*)', body)
    # Trade only hands on what the kind's function returns (each checked here too)
    bad = [r.strip() for r in returns if not re.match(r'\s*(Done|Fail)\(', r) and not (fn == 'Trade' and re.match(r'\s*(GiveGold|AskGold|GiveItem|AskItem|OfferTrade|TakeGift)\(', r))]
    check(f'{fn}: all {len(returns)} results go through Done or Fail', returns and not bad, bad)
done, fail = block('Function', 'Done'), block('Function', 'Fail')
check('Done: one event line in parentheses, plus the HUD line', '"(" + asFact + ".)"' in done and 'MLWW_Util.Result("trade", asHud, line)' in done)
check('Fail: "(Nothing happened: <why>.)", plus the HUD line', '"(Nothing happened: " + asWhy + ".)"' in fail and 'MLWW_Util.Result("trade", asHud, line)' in fail)
result = re.search(r'Function Result\(.*?EndFunction', UTIL, re.S).group(0)
check('MLWW_Util.Result shows the HUD line and sends the event line', 'Hud(asHud)' in result and 'Send(asSource, asFact)' in result)
hud = re.search(r'Function Hud\(.*?EndFunction', UTIL, re.S).group(0)
check('World HUD lines obey the Hub switch MLW_ActionHud (0x80D), on when missing', '0x00080D' in hud and '!on || on.GetValueInt() != 0' in hud)
notify = open(os.path.join(HUB, 'Source', 'Scripts', 'MLW_Notify.psc'), encoding='utf-8').read()
check('the Hub MLW_Notify reads the same switch', '0x00080D' in notify and '!on || on.GetValueInt() != 0' in notify)
glob_yaml = os.path.join(HUB, 'esp', 'Globals', 'MLW_ActionHud - 00080D_Mantella Living World - Integration Hub.esp.yaml')
check('the switch is a Hub global, on by default', os.path.isfile(glob_yaml) and 'Data: 1' in open(glob_yaml, encoding='utf-8').read())
mcm = json.load(open(os.path.join(HUB, 'MCM', 'Config', 'Mantella Living World - Integration Hub', 'config.json'), encoding='utf-8'))
toggles = [c for p in mcm['pages'] for c in p['content'] if c.get('valueOptions', {}).get('sourceForm', '').endswith('|80D')]
check('the MCM has an "Action notifications" toggle for it', len(toggles) == 1 and toggles[0]['type'] == 'toggle', toggles)
raw = [f for f, t in (('MLWW_Trade', code(TRADE)), ('MLWW_Crime', code(CRIME))) if 'Debug.Notification' in t]
check('trade and crime show HUD lines only through the switch', not raw, raw)
check('crime refusals reach the HUD too (Tell shows the line when no HUD line was set)',
      re.search(r'If !notified\s+MLWW_Util\.Hud\(asLine\)', CRIME) is not None)

# ---------------------------------------------------------------------------------------------------------------------
# Money paths and consent
# ---------------------------------------------------------------------------------------------------------------------
check('player gold never goes straight to an NPC (the plugin would count a gift)',
      not re.search(r'PlayerRef\.RemoveItem\(Gold\(\),[^)]*,[^)]*,', SRC))
move_gold = block('Function', 'MoveGold')
check('player gold paid: added to the NPC or chest first and checked there, then taken without a destination',
      'akTo.AddItem(Gold(), aiAmount, true)' in move_gold and 'akFrom.RemoveItem(Gold(), aiAmount, true)' in move_gold
      and move_gold.find('akTo.AddItem') < move_gold.find('akTo.GetItemCount(Gold()) - before') < move_gold.find('akFrom.RemoveItem')
      and 'MoveGold(PlayerRef, akNpc, aiAmount)' in block('Function', 'PayGold'))


def calls(body, method):
    """(receiver, [top-level arguments]) of every <receiver>.<method>(...) in body."""
    out = []
    for m in re.finditer(r'(\w+)\.' + method + r'\(', body):
        depth, i, args, cur = 1, m.end(), [], ''
        while i < len(body) and depth:
            c = body[i]
            depth += (c == '(') - (c == ')')
            if depth == 1 and c == ',':
                args.append(cur.strip())
                cur = ''
            elif depth:
                cur += c
            i += 1
        args.append(cur.strip())
        out.append((m.group(1), args, m.start()))
    return out


# Live test 8: a sale with Lucan away from his shop took 152 gold from the player and the gold reached neither the chest
# nor Lucan (the old order: PlayerRef.RemoveItem first, then source.AddItem, never checked). Every transfer path: nothing
# may leave one side unless it arrived on the other.
FUNCS = re.findall(r'(?im)^\s*(?:\w+\s+)?Function\s+(\w+)\(', SRC)
pairing = []
for fn in FUNCS:
    body = block('Function', fn)
    for recv, args, at in calls(body, 'RemoveItem'):
        item = args[0]
        dest = args[3] if len(args) > 3 and args[3] not in ('None', '') else ''
        if dest:  # one engine move: the destination's count must be checked after it
            if not re.search(re.escape(dest) + r'\.GetItemCount\(' + re.escape(item) + r'\) - \w+ <', body[at:]):
                pairing.append(f'{fn}: {recv}.RemoveItem({item}) to {dest} is not checked on arrival')
        else:  # a remove with nowhere to go: an add of the same thing must come first on this path, and be checked
            adds = [a for a in calls(body[:at], 'AddItem') if a[1][0] == item]
            if not adds or not re.search(r'GetItemCount\(' + re.escape(item) + r'\) - \w+', body[adds[-1][2]:at]):
                pairing.append(f'{fn}: {recv}.RemoveItem({item}) removes before a checked add of it')
check('every RemoveItem on every trade path has its matching add (checked) or is a move checked on arrival', not pairing, pairing)
moved = {fn for fn in ('GiveGold', 'AskGold', 'GiveItem', 'AskItem', 'OfferTrade')
         if 'RemoveItem(' in block('Function', fn) or 'PayGold(' in block('Function', fn) or 'MoveGold(' in block('Function', fn)}
check("all five kinds that move gold or goods go through checked transfers (take_gift: the game's own gift menu)",
      moved == {'GiveGold', 'AskGold', 'GiveItem', 'AskItem', 'OfferTrade'} and 'RemoveItem' not in block('Function', 'TakeGift'), moved)
for fn in ('AskGold', 'AskItem'):
    body = block('Function', fn)
    check(f'{fn}: a payment that did not move is told as nothing happened (also the Custom answer paths)',
          body.count('If !PayGold(') == body.count('PayGold(') and body.count('PayGold(') >= 1, body.count('PayGold('))
offer = block('Function', 'OfferTrade')
check('OfferTrade: the gold goes where the wares came from (the chest Chest() found), the NPC if the chest did not take it',
      'ObjectReference till = source' in offer and 'MoveGold(PlayerRef, till, price)' in offer and 'till = akNpc' in offer)
check('OfferTrade: goods that did not arrive send the gold back', 'MoveGold(till, PlayerRef, price)' in offer)
check("OfferTrade: never po3's vendor faction for the gold (only there while he stands in the shop)",
      'ChestGold(akNpc)' not in offer and 'GetVendorFaction' not in offer)


class Box:
    def __init__(self, gold, takes=True):
        self.gold, self.takes = gold, takes


def port_move_gold(src, dst, n):
    """MLWW_Trade.MoveGold: add first, check, then remove."""
    if n <= 0 or src.gold < n:
        return False
    before = dst.gold
    if dst.takes:
        dst.gold += n
    added = dst.gold - before
    if added < n:
        dst.gold -= max(added, 0)
        return False
    src.gold -= n
    return True


def port_offer(player, chest, npc, price):
    till = chest
    if not port_move_gold(player, till, price):
        till = npc
        if not port_move_gold(player, till, price):
            return None
    return till


for name, chest_takes in (('in his shop', True), ('away from his shop, chest refusing the gold', False)):
    p, c, n = Box(348), Box(1652, chest_takes), Box(41)
    total = p.gold + c.gold + n.gold
    till = port_offer(p, c, n, 152)
    check(f'sale {name}: 152 gold left the player and arrived ({"chest" if till is c else "NPC"}), none lost',
          p.gold == 196 and p.gold + c.gold + n.gold == total and till is not None, (p.gold, c.gold, n.gold))
p, c, n = Box(348, True), Box(0, False), Box(0, False)
check('sale where nobody can take the gold: nothing leaves the player', port_offer(p, c, n, 152) is None and p.gold == 348)
for fn, recheck in (('AskGold', 'PlayerRef.GetItemCount(Gold()) < amount'), ('AskItem', 'Count(count, PlayerRef.GetItemCount(item))'),
                    ('OfferTrade', 'Count(count, source.GetItemCount(item))')):
    body = block('Function', fn)
    ask = body.find('Confirm(')
    check(f'{fn}: confirm box unless "Trades without asking", then a re-check before anything moves',
          ask > 0 and '!TradesFree(akNpc)' in body[:ask + 200] and body.find(recheck, ask) > ask)
check('GiveGold and GiveItem never ask (the NPC hands over its own things)', 'Confirm(' not in block('Function', 'GiveGold') + block('Function', 'GiveItem'))

# ---------------------------------------------------------------------------------------------------------------------
# Custom answer
# ---------------------------------------------------------------------------------------------------------------------
confirm = block('Function', 'Confirm')
check('Custom answer is shown only when the text box is there', 'bool withText = TextBox()' in confirm
      and re.search(r'If withText\s+pick = SkyMessage\.Show\([^\n]*CUSTOM_ANSWER\)\s+Else\s+pick = SkyMessage\.Show\(note \+ asQuestion, asYes, "Not now"\)', confirm) is not None)
check('the text box is the UIExtensions one the Hub uses, checked by its plugin',
      'UIExtensions.esp' in block('Function', 'TextBox') and 'UIExtensions.OpenMenu("UITextEntryMenu")' in block('Function', 'TypedText')
      and 'UIExtensions.OpenMenu("UITextEntryMenu")' in open(os.path.join(HUB, 'Source', 'Scripts', 'MLW_Command.psc'), encoding='utf-8').read())
check('World has the UIExtensions compile stub', os.path.isfile(os.path.join(ROOT, 'build', 'stubs', 'UIExtensions.psc')))
check('an answer not understood shows a note and the box again', 'note = "Not understood: "' in confirm and 'While true' in confirm)
for fn, moved in (('AskGold', 'PayGold(akNpc, amount)'), ('AskItem', 'PlayerRef.RemoveItem(item, count, true, akNpc)'), ('OfferTrade', 'MoveGold(PlayerRef, till, price)')):
    body = block('Function', fn)
    check(f'{fn}: the custom answer is what moves, held to what the player has', moved in body and 'Count(answer, PlayerRef.GetItemCount(' in body)
check('AskItem: gold instead of the item goes through PayGold and says so', 'PayGold(akNpc, coins)' in block('Function', 'AskItem')
      and 'gold instead of the " + Pieces(item, asked) + " asked for' in block('Function', 'AskItem'))
check('the event lines name the amount that really moved', '" handed " + who + " " + amount + " gold"' in block('Function', 'AskGold')
      and 'Instead(chose, amount, aiAmount' in block('Function', 'AskGold') and 'Instead(chose, price, offered' in block('Function', 'OfferTrade'))
check('a typed price is never under half the shop price', re.search(r'price = Count\(answer, PlayerRef\.GetItemCount\(Gold\(\)\)\)\s+held = ""\s+If price < low', block('Function', 'OfferTrade')) is not None)


def typed_number(text):
    """MLWW_Trade.TypedNumber: digits with commas, spaces and the word gold (any case); -1 otherwise."""
    s = text
    at = s.lower().find('gold')
    if at >= 0:
        s = s[:at] + s[at + 4:]
    n = digits = 0
    for c in s:
        if c.isdigit():
            if digits >= 9:
                return -1
            n, digits = n * 10 + int(c), digits + 1
        elif c not in ', ':
            return -1
    return n if digits and n > 0 else -1


for text, want in (('2000', 2000), ('2,000', 2000), ('2000 gold', 2000), (' 50 Gold ', 50), ('gold 75', 75), ('3', 3), ('0', -1), ('', -1),
                   ('lots', -1), ('2.5', -1), ('-5', -1), ('two hundred', -1), ('1234567890', -1), ('gold', -1), ('50 gold coins', -1)):
    check(f'typed {text!r} -> {want}', typed_number(text) == want, typed_number(text))
check('TypedNumber in the script allows only digits, commas and spaces', 'If StringUtil.IsDigit(c)' in block('Function', 'TypedNumber')
      and 'ElseIf c != "," && c != " "' in block('Function', 'TypedNumber'))
check('credit is cleared when a talk starts', 'StorageUtil.UnsetIntValue(StorageUtil.FormListGet(self, KEY_TALK, i), KEY_CREDIT)' in block('Event', 'OnTalkStarted'))
check("OfferTrade's own trade event is not told again as a barter menu", 'ownTrades += 1' in block('Function', 'OfferTrade') and 'ownTrades -= 1' in block('Event', 'OnBarterDone'))
check('the carry keys World writes are the ones the Hub reads',
      all(f'"{k}"' in SRC for k in ('carry_gold', 'carry_items', 'merchant', 'stock'))
      and all(f"'{k}'" in open(os.path.join(HUB, 'server', 'living_world', 'trade.py'), encoding='utf-8').read() for k in ('carry_gold', 'carry_items', 'merchant', 'stock')))
# live test 9: stock named only the dearest five wares and Lucan denied having the Oakflesh tome his chest held. Every
# ware now goes into the "wares" list with its kind; the Hub names a few of each kind and counts the rest.
hub_trade = open(os.path.join(HUB, 'server', 'living_world', 'trade.py'), encoding='utf-8').read()
write_wares = block('Function', 'WriteWares')
check('WriteCarry writes the wares list (cleared for a non-merchant)', 'WriteWares(path, chest)' in block('Function', 'WriteCarry')
      and 'JsonUtil.StringListClear(asPath, "wares")' in write_wares and write_wares.index('StringListClear') < write_wares.index('If !akChest'))
check('wares: "kind|count|price|name", at most MAX_SCAN entries, quest items and gold left out, one count per ware',
      '"|" + count + "|" + price + "|" + f.GetName()' in write_wares and 'i < MAX_SCAN' in write_wares
      and 'questItems.Find(f) < 0' in write_wares and 'f != Gold()' in write_wares and write_wares.count('GetItemCount') == 1)
check('wares: the price is the barter menu price (the same factor as MenuPrice)', 'PriceFactor()' in write_wares
      and 'PriceFactor()' in block('Function', 'MenuPrice'))
kinds = set(re.findall(r'Return "([a-z ]+)"', block('Function', 'WareKind')))
hub_kinds = set(re.findall(r"'([a-z ]+)': \('", hub_trade))
check(f'every kind World writes is one the Hub names ({len(kinds)})', kinds and kinds <= hub_kinds, kinds - hub_kinds)
check('the Hub reads the wares list', "npc.get('wares')" in hub_trade)
# B04: a chest of more than MAX_SCAN entries was cut off without a word, and the Hub called the list the whole stock.
# wares_complete is 0 until the pass reaches the chest's last entry; the Hub needs it for the whole-stock wording.
check('wares: wares_complete is reset first and set to 1 only when the pass read the chest to its end',
      write_wares.index('JsonUtil.SetIntValue(asPath, "wares_complete", 0)') < write_wares.index('If !akChest')
      and 'JsonUtil.SetIntValue(asPath, "wares_complete", (!forms || i >= forms.Length) as int)' in write_wares
      and write_wares.index('"wares_complete", (!forms') > write_wares.index('EndWhile'))
check("the Hub calls the list the whole stock only with wares_complete", "_int(npc.get('wares_complete')) == 1" in hub_trade)


def port_complete(entries, max_scan=150):
    """WriteWares' loop end on plain values: True when the chest was read to its end."""
    i = 0
    while entries and i < len(entries) and i < max_scan:
        i += 1
    return not entries or i >= len(entries)


check('wares rule: 150 entries read whole, 151 not, an empty chest is complete',
      port_complete(list(range(150))) and not port_complete(list(range(151))) and port_complete([]))
rules = open(os.path.join(ROOT, 'SKSE', 'Plugins', 'MantellaSoftware', 'data', 'prompt_rules', '20_world.txt'), encoding='utf-8').read()
check('the World rule no longer says gold moves only in the barter menu', 'trade actions' in rules and 'Nothing happened' in rules)
records = open(os.path.join(ROOT, 'tools', 'make_records.py'), encoding='utf-8').read()
check('the trade quest is in the plugin', "'MLWW_Trade'" in records and os.path.isfile(os.path.join(ROOT, 'esp', 'Quests', 'MLWW_QuestTrade - 000808_Mantella Living World - World.esp.yaml')))


# ---------------------------------------------------------------------------------------------------------------------
# Port of the rules, run on cases
# ---------------------------------------------------------------------------------------------------------------------
def find_item(items, wanted):
    """MLWW_Trade.FindItem: items = [(name, playable, quest, count)]. Papyrus == and StringUtil.Find ignore case."""
    if not wanted:
        return None
    inside = holds = None
    for name, playable, quest, count in items:
        if name == 'Gold' or not name or not playable or count <= 0 or quest:
            continue
        if name.lower() == wanted.lower():
            return name
        if wanted.lower() in name.lower() and (inside is None or len(name) < len(inside)):
            inside = name
        elif name.lower() in wanted.lower() and (holds is None or len(name) > len(holds)):
            holds = name
    return inside or holds


def count(wanted, have):
    return min(max(wanted, 1), have)


def price_limits(value, speech, wanted, hi=3.3, lo=2.0, n=1):
    menu = max(1, math.ceil(value * (hi - (hi - lo) * min(max(speech, 0), 100) / 100)))
    fair = menu * n
    low, high = math.ceil(fair * 0.5), max(1, math.floor(fair * 1.5))
    low = min(low, high)
    return fair if wanted <= 0 else min(max(wanted, low), high)


bag = [('Gold', True, False, 300), ('Steel Sword', True, False, 1), ('Steel Sword of Fire', True, False, 1), ('Bread', True, False, 3),
       ('Amulet of Mara', True, True, 1), ('Skin', False, False, 1), ('Iron Dagger', True, False, 0), ('Sweetroll', True, False, 2)]
for wanted, want in (('steel sword', 'Steel Sword'), ('sword', 'Steel Sword'), ('a fine steel sword', 'Steel Sword'), ('bread loaf', 'Bread'),
                     ('Amulet of Mara', None), ('gold', None), ('skin', None), ('Iron Dagger', None), ('', None), ('apple', None),
                     ('SWEETROLL', 'Sweetroll'), ('roll', 'Sweetroll')):
    check(f'item {wanted!r} -> {want}', find_item(bag, wanted) == want, find_item(bag, wanted))
check('count: at least 1, at most what is there', (count(0, 3), count(5, 3), count(2, 3)) == (1, 3, 2))
check('FindItem in the script: exact first, then contained, then containing', re.search(r'If name == asName\s+Return f', block('Function', 'FindItem'))
      and 'StringUtil.Find(name, asName) >= 0' in SRC and 'StringUtil.Find(asName, name) >= 0' in SRC)
# Prices: a Steel Sword (value 45) at Speech 15 -> menu 3.105x = 140
check('price: none named -> the shop price', price_limits(45, 15, 0) == 140, price_limits(45, 15, 0))
check('price: too low -> half the shop price', price_limits(45, 15, 10) == 70, price_limits(45, 15, 10))
check('price: too high -> one and a half times', price_limits(45, 15, 1000) == 210, price_limits(45, 15, 1000))
check('price: haggled within limits stays', price_limits(45, 15, 100) == 100)
check('price: Speech 100 makes the shop price 2x', price_limits(45, 100, 0) == 90)
check('price: a worthless item still costs 1', price_limits(0, 50, 0) == 1 and price_limits(0, 50, 5) == 1)
check('price limits in the script are 0.5 and 1.5', 'float Property PRICE_MIN = 0.5' in TRADE and 'float Property PRICE_MAX = 1.5' in TRADE)


class Talk:
    """The stranger rule: a stranger pays gold or hands goods over only up to the credit the player built in this talk."""
    def __init__(self, free):
        self.free, self.credit, self.npc_gold, self.player_gold = free, 0, 500, 500

    def ask_gold(self, n, yes=True):
        if n <= 0 or self.player_gold < n or not yes:
            return False
        self.player_gold -= n
        self.npc_gold += n
        self.credit += n
        return True

    def give_gold(self, n):
        if n <= 0 or self.npc_gold < n or (not self.free and n > self.credit):
            return False
        self.npc_gold -= n
        self.player_gold += n
        self.credit = max(0, self.credit - n)
        return True

    def give_item(self, value):
        if not self.free and value > self.credit:
            return False
        self.credit = max(0, self.credit - value)
        return True


s = Talk(free=False)
check('stranger: no free gold', not s.give_gold(10))
check('stranger: no free goods', not s.give_item(5))
check('stranger: paid 50, hands over goods worth 40', s.ask_gold(50) and s.give_item(40))
check('stranger: then 10 change at most', not s.give_gold(11) and s.give_gold(10) and s.credit == 0)
check('stranger: declined box moves nothing', not s.ask_gold(30, yes=False) and s.credit == 0)
f = Talk(free=True)
check('follower: gives freely, but only what they carry', f.give_gold(200) and not f.give_gold(400) and f.give_item(999))
stranger_rule = block('Function', 'GiveGold') + block('Function', 'GiveItem')
check('script: the stranger rule is in GiveGold and GiveItem', stranger_rule.count('If !Free(akNpc)') == 2 and stranger_rule.count('> credit') == 2)
check('script: a child is never free, an absolute command is', 'If akNpc.IsChild()' in block('Function', 'Free') and 'MLW_CommandUntil' in block('Function', 'Free'))

# live test 11: the Hub now tells a merchant to try any ware asked for with offer_trade and let the result decide; the
# game must refuse a ware the chest (and the merchant) lacks with a told-back line, and nothing else
offer = block('Function', 'OfferTrade')
check('script: offer_trade for a ware that is not there is refused with a told-back line before anything moves',
      'Form item = FindItem(chest, asItem)' in offer and 'item = FindItem(akNpc, asItem)' in offer
      and 'has nothing called " + Named(asItem) + " for sale")' in offer
      and offer.find('has nothing called') < offer.find('GetItemCount(item)'), offer[:300])

# Values: an item the player hands over is credited at the barter sell price (base value / PriceFactor), a stranger's
# goods cost the barter buy price (MenuPrice); and the hand-over is marked so MLWW_Personal.OnGift does not score it as a
# gift (an ask_item / give_item loop once raised the gift score for free).
ask_item = block('Function', 'AskItem')
check('script: AskItem credits the barter sell price, not the base value',
      'AddCredit(akNpc, Math.Floor(item.GetGoldValue() * count / PriceFactor()))' in ask_item and 'AddCredit(akNpc, item.GetGoldValue() * count)' not in ask_item)
check('script: GiveItem charges a stranger the barter menu price', 'int value = MenuPrice(item) * count' in block('Function', 'GiveItem'))
mark = ask_item.find('"MLWW_TradeHanded"')
check('script: AskItem marks the hand-over before it moves', 0 <= mark < ask_item.find('PlayerRef.RemoveItem(item, count, true, akNpc)'))
personal = open(os.path.join(ROOT, 'Source', 'Scripts', 'MLWW_Personal.psc'), encoding='utf-8').read()
on_gift = re.search(r'(?m)^Event OnGift\(.*?^EndEvent', personal, re.S)
check('script: OnGift skips a Trade hand-over', on_gift is not None and on_gift.group(0).find('TradeHandOver(') >= 0
      and on_gift.group(0).find('TradeHandOver(') < on_gift.group(0).find('RecordGift('))

print(f'{fails} failed')
sys.exit(1 if fails else 0)
