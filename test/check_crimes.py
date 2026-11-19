"""Offline checks for crimes.json (MLWW_Personal.LogCrime / LogDeath -> the Integration Hub's world log), no game needed:
  - the row texts of LogCrime, LogDeath, PlaceJson and WitnessJson are run as written (a small port of the Papyrus string
    expressions) with awkward names (quotes, backslashes) and must give valid JSON in the shape the Hub reads;
  - the file is one JSON object (the Hub's reader only takes objects) with "crimes" and "deaths" lists, kept bounded and
    shared by every save (each row names the player character);
  - children are never victims, and a child witness is listed without a name;
  - the rows go through the Hub's own worldlog.from_crime / from_death (when the Hub is checked out next to World): a
    murder with witnesses names the player, place / town / hold are kept, a death row gives a death event.
usage: py -3 test/check_crimes.py
"""
import json
import os
import re
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import checklib  # noqa: E402
from checklib import check  # noqa: E402
HUB = os.path.join(os.path.dirname(ROOT), 'Mantella-Living-World-Hub', 'server')
PERSONAL = open(os.path.join(ROOT, 'Source', 'Scripts', 'MLWW_Personal.psc'), encoding='utf-8').read()


def func(name):
    m = re.search(r'(?m)^(?:\w+ )?Function ' + name + r'\(.*?^EndFunction', PERSONAL, re.S)
    return m.group(0) if m else ''


def expr_after(src, start):
    """The Papyrus expression that starts after `start`, joined over its line continuations."""
    i = src.find(start)
    if i < 0:
        return ''
    lines = []
    for line in src[i + len(start):].splitlines():
        line = line.split(' ;')[0].rstrip()
        lines.append(line.rstrip('\\').strip())
        if not line.endswith('\\'):
            break
    return ' '.join(lines)


class Num(float):
    """A Papyrus float: numbers in maths, Papyrus' text when added to a string."""
    def __radd__(self, other):
        return other + ('%f' % self)

    def __add__(self, other):
        return ('%f' % self) + other if isinstance(other, str) else Num(float(self) + other)

    def __mul__(self, other):
        return Num(float(self) * other)


class Actor:
    def __init__(self, name, base, ref, child=False, thalmor=False):
        self.name, self.base, self.ref, self.child, self.thalmor = name, base, ref, child, thalmor

    def GetFormID(self):
        return self.ref

    def GetDisplayName(self):
        return self.name


def quote(text):  # MLWW_Util.Quote
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


def to_python(expr):
    expr = re.sub(r'\(MLWW_Util\.IsThalmor\((\w+)\) as int\)', r'pint(\1.thalmor)', expr)
    expr = re.sub(r'\(\(now \* 1000\.0\) as int\)', 'pint(now * 1000.0)', expr)
    expr = expr.replace('MLWW_Util.', '').replace('.GetFormID()', '.GetFormID()')
    return expr


ENV = {'Quote': quote, 'BaseId': lambda a: a.base, 'Hex': lambda v, n: format(v, '0%dX' % n)[-n:],
       'PlayerName': lambda: 'Ulfric "the Bold" \\ Jr', 'pint': lambda v: str(int(v))}


def run(expr, **names):
    return eval(to_python(expr), dict(ENV), names)  # noqa: S307 - our own source, ported


# --- the pieces as written ---------------------------------------------------------------------------------------------
crime_fn, death_fn, place_fn, wit_fn, append_fn = (func(n) for n in ('LogCrime', 'LogDeath', 'PlaceJson', 'WitnessJson', 'AppendRow'))
check('LogCrime, LogDeath, PlaceJson, WitnessJson and AppendRow exist', all((crime_fn, death_fn, place_fn, wit_fn, append_fn)))
_waits = [float(w) for w in re.findall(r'Utility\.WaitMenuMode\(\s*(\d*\.?\d+)\s*\)', append_fn or '')]
check('AppendRow waits for the other writer in steps of at least 0.1 s (shorter Papyrus waits are not reliable)',
      _waits and min(_waits) >= 0.1, _waits)
place_expr = expr_after(place_fn, 'Return ')
wit_head = expr_after(wit_fn, 'out += "{')
wit_minor = expr_after(wit_fn, 'If a.IsChild()\n\t\t\t\tout += ')
wit_name = expr_after(wit_fn, 'Else\n\t\t\t\tout += ')
crime_expr = expr_after(crime_fn, 'string row = ')
death_expr = expr_after(death_fn, 'string row = ')
id_expr = expr_after(crime_fn, 'string id = ')


def place_json(actor, hold, place='Bannered Mare "Inn"', town='Whiterun', hold_name='Whiterun'):
    return run(place_expr, place=place, town=town, hold=hold_name)


def witness_json(people):
    out = '['
    for i, a in enumerate(people):
        if i:
            out += ','
        out += run('"{' + wit_head, a=a)
        out += run(wit_minor) if a.child else run(wit_name, a=a)
    return out + ']'


nazeem = Actor('Nazeem', '013BB9', 0x00013BBA)
elf = Actor('Ondolemar', '013B76', 0xFE001803, thalmor=True)
adult = Actor('Ysolda "Y"', '013BAB', 0x00013BAC)
child = Actor('Lars Battle-Born', '013B9F', 0x00013BA0, child=True)
ENV.update(PlaceJson=place_json, WitnessJson=lambda v: witness_json(people), Masked=lambda: '0')  # Papyrus adds an int to a string as its digits
now = Num(52.25)

rows = {}
for kind, victim, people in (('murder', nazeem, [adult, child]), ('assault', elf, [])):
    rid = run(id_expr, asCrime=kind, ref=format(victim.ref, '08X'), now=now)
    text = run(crime_expr, id=rid, asCrime=kind, now=now, akVictim=victim, aiHold=0, ref=format(victim.ref, '08X'))
    try:
        rows[kind] = json.loads(text)
        check(f'{kind} row is valid JSON', True)
    except ValueError as e:
        check(f'{kind} row is valid JSON', False, f'{e}: {text}')
people = [adult]
dtext = run(death_expr, now=now, akDead=Actor('Hulda', '013BA3', 0x00013BA4), ref='00013BA4')
try:
    death = json.loads(dtext)
    check('death row is valid JSON', True)
except ValueError as e:
    death = {}
    check('death row is valid JSON', False, f'{e}: {dtext}')

murder = rows.get('murder', {})
want = {'id', 'crime', 'day', 'place', 'town', 'hold', 'victim', 'witnesses', 'by_player', 'player'}
check('a crime row has every field the Hub reads', want <= set(murder), sorted(want - set(murder)))
check('the victim: 6-hex base id as npc/<base>.json, name, Thalmor flag',
      murder.get('victim', {}).get('base') == '013BB9' and murder['victim'].get('name') == 'Nazeem' and murder['victim'].get('thalmor') == 0
      and rows.get('assault', {}).get('victim', {}).get('thalmor') == 1)
check('names with quotes and backslashes survive', murder.get('player') == 'Ulfric "the Bold" \\ Jr' and murder.get('place') == 'Bannered Mare "Inn"')
check('the crime kind is one the Hub takes', {r.get('crime') for r in rows.values()} == {'murder', 'assault'})
wits = murder.get('witnesses', [])
check('witnesses carry base and ref id; a child is listed without a name',
      len(wits) == 2 and wits[0] == {'base': '013BAB', 'ref_id': '00013BAC', 'name': 'Ysolda "Y"'}
      and wits[1].get('minor') == 1 and 'name' not in wits[1], wits)
check('a row id is the kind, the reference and the time', murder.get('id') == 'murder-00013BBA-52250', murder.get('id'))
dwant = {'id', 'base', 'ref_id', 'name', 'day', 'place', 'town', 'hold', 'by_player', 'unique', 'witnesses', 'player'}
check('a death row has every field from_death takes', dwant <= set(death) and death.get('by_player') is False, sorted(dwant - set(death)))

# --- rules in the code -------------------------------------------------------------------------------------------------
check('a child is never a victim', 'akVictim.IsChild()' in crime_fn and 'akDead.IsChild()' in death_fn)
check('the party, creatures and the player are not victims', 'akVictim.IsPlayerTeammate()' in crime_fn and '"ActorTypeNPC"' in crime_fn
      and 'akVictim == PlayerRef' in crime_fn)
check('one attack row per person per day, replaced by a murder that day',
      'If attackedToday\n\t\t\tReturn' in crime_fn and 'replace = StorageUtil.GetStringValue(akVictim, KEY_ASSAULT_ROW)' in crime_fn)
check('murders, attacks and deaths not by the player are logged', 'LogCrime(akSender as Actor, "murder", hold)' in PERSONAL
      and 'LogCrime(akSender as Actor, "assault", -1)' in PERSONAL and re.search(r'If afByPlayer <= 0\.0\s+LogDeath\(akSender as Actor\)', PERSONAL))
check('the file is MantellaLivingWorld/crimes.json', 'string Property CRIMES_FILE = "MantellaLivingWorld/crimes.json"' in PERSONAL)
cap = re.search(r'MAX_CRIME_ROWS = (\d+)', PERSONAL)
check('each list is bounded (oldest dropped first)', cap and 50 <= int(cap.group(1)) <= 500
      and 'JsonUtil.ClearPathIndex(CRIMES_FILE, path, 0)' in append_fn and 'While JsonUtil.PathCount(CRIMES_FILE, path) > MAX_CRIME_ROWS' in append_fn)
check('rows are appended to a list in a JSON object, with the last player at the top',
      'JsonUtil.SetRawPathValue(CRIMES_FILE, path, "[]")' in append_fn and 'path + "[" + at + "]"' in append_fn
      and 'JsonUtil.SetRawPathValue(CRIMES_FILE, ".player"' in append_fn and 'JsonUtil.Save(CRIMES_FILE)' in append_fn)
check('witnesses are capped', 'seen < MAX_CRIME_WITNESSES' in wit_fn)
ENV['Masked'] = lambda: '1'
masked_row = json.loads(run(crime_expr, id='m-1', asCrime='murder', now=now, akVictim=nazeem, aiHold=0, ref=format(nazeem.ref, '08X')))
ENV['Masked'] = lambda: '0'
check('a hood that hides the player marks the crime row (masked, as the Hub reads it)', masked_row.get('masked') == 1
      and murder.get('masked') == 0
      and 'Function Masked()' in PERSONAL and 'world.Fame(hold) >= 3 || world.IsThane(hold)' in PERSONAL)
check("the player's followers are never witnesses (teammate or current follower faction, also when waiting)",
      '!InParty(a)' in wit_fn and 'Function InParty(Actor akActor)' in PERSONAL and 'GetFactionRank(current) >= 0' in PERSONAL
      and '!a.IsPlayerTeammate()' not in wit_fn)
check('the town is a city, town or settlement location (LocTypeCity/Town/Settlement)',
      all(f'GetFormFromFile({k}, "Skyrim.esm") as Keyword' in place_fn for k in ('0x013168', '0x013166', '0x013167')))

# --- through the Hub's adapters ----------------------------------------------------------------------------------------
if os.path.isdir(os.path.join(HUB, 'living_world')):
    sys.path.insert(0, HUB)
    tmp = tempfile.mkdtemp()
    try:
        from living_world import embed, lw_state, memory, worldlog as W
        embed.use(None)
        lw_state.DATA_DIR = os.path.join(tmp, 'channel')
        os.makedirs(lw_state.DATA_DIR)
        W.KNOWLEDGE_DIRS[:] = [os.path.join(tmp, 'knowledge')]
        store = memory.MemoryStore(os.path.join(tmp, 'conv'), 'save1')
        doc = {'player': murder.get('player'), 'crimes': list(rows.values()), 'deaths': [death]}
        path = os.path.join(lw_state.DATA_DIR, 'crimes.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(doc, f)
        read = lw_state._read('crimes.json')
        check("the Hub's channel reader takes the file", read.get('crimes') and read.get('deaths'))
        player = read['player']
        ev = W.from_crime(store, read['crimes'][0], player)
        check('from_crime logs the murder, naming the player before witnesses',
              ev is not None and ev['kind'] == 'killing' and 'Ulfric' in ev['public_text'] and 'Nazeem' in ev['true_text'], ev)
        check('from_crime keeps place, town and hold', ev and ev['place'] == {'location': 'Bannered Mare "Inn"', 'town': 'Whiterun', 'hold': 'Whiterun'},
              ev and ev['place'])
        check('from_crime keeps the witnesses (the child by base id only)', ev and len(ev['present']) == 2
              and ev['present'][0]['base'] == '013BAB' and ev['present'][1]['base'] == '013B9F' and not ev['present'][1]['name'], ev and ev['present'])
        ev2 = W.from_crime(store, read['crimes'][1], player)
        check('an attack without witnesses does not name the player in public', ev2 is not None and ev2['kind'] == 'crime'
              and 'Ulfric' not in ev2['public_text'], ev2)
        d = read['deaths'][0]
        ev3 = W.from_death(store, base=d['base'], name=d['name'], day=d['day'], place_name=d['place'], by_player=d['by_player'],
                           unique=d['unique'], witnesses=d['witnesses'])
        check('from_death logs the death row', ev3 is not None and ev3['kind'] == 'death' and 'Hulda' in ev3['true_text'], ev3)
    except Exception as e:  # a Hub change that breaks the adapters
        check('the Hub adapters run', False, repr(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
else:
    print('WARN the Hub is not checked out next to World: adapters not run')

# Settle: the free paths (Thane/fame waiver, persuade) take stolen goods like a payment, so the player is asked first
# when the action asks (abAsk); a bribe promises "You keep any stolen goods".
CRIME = open(os.path.join(ROOT, 'Source', 'Scripts', 'MLWW_Crime.psc'), encoding='utf-8').read()
m = re.search(r'(?m)^string Function Settle\(.*?^EndFunction', CRIME, re.S)
settle = m.group(0) if m else ''
takes = [i.start() for i in re.finditer(r'ClearTakingGoods\(crime', settle)]
check('Settle: two free paths take stolen goods', len(takes) == 2, takes)
for at in takes:
    before = settle[max(0, settle.rfind('If nonViolent <= WAIVE_MAX', 0, at), settle.rfind('If asMethod == "persuade"', 0, at)):at]
    check('Settle: a free path asks before taking stolen goods', 'PlayerAgrees(' in before and 'stolen goods' in before and 'abAsk' in before, before[-200:])

# tools/make_records.py writes the plugin and these action files: regenerating must give the shipped action files back
# (a hand edit to the output alone is undone by the next run, as the guard-only gate once nearly was).
import subprocess
gen = tempfile.mkdtemp()
try:
    subprocess.run([sys.executable, '-B', os.path.join(ROOT, 'tools', 'make_records.py')], cwd=gen, check=True, capture_output=True)
    actions = os.path.join('SKSE', 'Plugins', 'MantellaSoftware', 'data', 'actions')
    for fn in sorted(os.listdir(os.path.join(gen, actions))):
        made = open(os.path.join(gen, actions, fn), encoding='utf-8').read()  # text mode reads either line end the same
        shipped = open(os.path.join(ROOT, actions, fn), encoding='utf-8').read()  # text mode reads either line end the same
        check(f'make_records.py regenerates {fn} as shipped', made == shipped)
finally:
    shutil.rmtree(gen, ignore_errors=True)

print(f'{checklib.fails} failed')
sys.exit(1 if checklib.fails else 0)
