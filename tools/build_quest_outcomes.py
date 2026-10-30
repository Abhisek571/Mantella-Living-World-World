"""Builds quest_outcomes.json: what the world knows about the player's finished quests.

Each row says when it is true (quest completed, quest stage done, any or all of several, an actor dead or alive), the line NPCs
are told ("{player}" is replaced by the player's name in game), who knows it (holds, factions, named NPCs) and how
much fame it adds in those holds. The hold and category of each quest come from Quest Journal Overhaul's JSON
files (read-only); the outcome rows themselves are written by hand below.

usage: py -3 tools/build_quest_outcomes.py [--qjo <mod folder> ...] [--out <file>]
"""
import argparse, glob, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'SKSE', 'Plugins', 'StorageUtilData', 'MantellaLivingWorld', 'quest_outcomes.json')
# Local folders: the environment (MLW_MO2, MLW_GAME) or the untracked tools/local-paths.json of the Integration Hub
# repository ({"mo2": "<Mod Organizer 2 instance>", "game": "<Skyrim Special Edition folder>"}).
def _local(key, env):
    if os.environ.get(env):
        return os.environ[env]
    f = os.path.join(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'Mantella-Living-World-Hub'), 'tools', 'local-paths.json')
    value = json.load(open(f, encoding='utf-8')).get(key, '') if os.path.isfile(f) else ''
    if not value:
        raise SystemExit(f'Set {env}, or "{key}" in {f}')
    return value


MODS = os.path.join(_local('mo2', 'MLW_MO2'), 'mods')
# Later folders win when two files place the same quest.
DEFAULT_QJO = [os.path.join(MODS, d) for d in ('[NoDelete] Quest Journal Overhaul',
                                               '[NoDelete] Quest Journal Overhaul - More Mod Support',
                                               '[NoDelete] Quest Journal Overhaul - Unofficial Mods Support')]

HOLDS = ['Whiterun', 'Haafingar', 'Eastmarch', 'Rift', 'Reach', 'Pale', 'Falkreath', 'Hjaalmarch', 'Winterhold']
_QJO_HOLD = {h.lower() + 'hold': h for h in HOLDS}

# Quest editor id -> (form id inside its plugin, plugin). Read from Skyrim.esm.
QUESTS = {
    'MQ101': 0x03372B, 'MQ103': 0x0D0800, 'MQ104': 0x02610C, 'MQ105': 0x0242BA, 'MQ106': 0x032926,
    'MQ201': 0x035D5F, 'MQ206': 0x036193, 'MQ302': 0x045923, 'MQ304': 0x046EF1, 'MQ305': 0x046EF2,
    'MQPaarthurnax': 0x03FA16,
    'CW01A': 0x0D517A, 'CW01B': 0x0E2D29, 'CW03': 0x0D661C, 'CWFinale': 0x0D1444,
    'C00': 0x04B2D9, 'C03': 0x01CEF4, 'C06': 0x01CEF6,
    'MG01': 0x01F251, 'MG08': 0x01F258,
    'TG01': 0x01F326, 'TG09': 0x021555,
    'DB02': 0x01EA51, 'DB11': 0x01EA59,
    'Favor250': 0x0A2C86, 'Favor252': 0x0A2C9B, 'Favor253': 0x0A2C9E, 'Favor254': 0x0A2CA6, 'Favor255': 0x0A34CE,
    'Favor256': 0x0A34D4, 'Favor257': 0x0A34D7, 'Favor258': 0x0A34DE, 'FreeformRiftenThane': 0x065BDF,
    'FavorJarlsMakeFriends': 0x087E24,
    'MS13': 0x039645, 'FreeformRiverwood01': 0x074A83, 'MS08': 0x01CF25, 'MS09': 0x01CF26, 'T03': 0x01C48E,
    'DA08': 0x04A37B,
}
PLUGIN = 'Skyrim.esm'
THANE = {'Favor250': 'Reach', 'Favor252': 'Haafingar', 'Favor253': 'Whiterun', 'Favor254': 'Eastmarch',
         'Favor255': 'Hjaalmarch', 'Favor256': 'Pale', 'Favor257': 'Winterhold', 'Favor258': 'Falkreath',
         'FreeformRiftenThane': 'Rift'}


def done(quest):
    return {'type': 'completed'}


def stage(n):
    return {'type': 'stage', 'stage': n}


# PaarthurnaxREF, the placed actor (persistent). The base NPC 0x03C57C is not an Actor in Papyrus.
PAARTHURNAX_REF = 0x03C57D


def dead(ref, plugin=PLUGIN):
    return {'type': 'dead', 'form': ref, 'plugin': plugin}


def alive(ref, plugin=PLUGIN):
    return {'type': 'alive', 'form': ref, 'plugin': plugin}


def holds(*h):
    return {'holds': list(h)}


# id, quest, when, text, audience, fame (0-3 per audience hold), optional extras.
OUTCOMES = [
    # Main quest
    ('mq101_helgen', 'MQ101', done, '{player} survived the dragon attack on Helgen.', holds('Falkreath', 'Whiterun'), 0, {'sets': {'mq_stage': 1}}),
    ('mq103_dragonstone', 'MQ103', done, '{player} brought the Dragonstone back from Bleak Falls Barrow.', holds('Whiterun'), 1, {}),
    ('mq104_dragonborn', 'MQ104', done, '{player} killed a dragon at the Western Watchtower and absorbed its soul: people call them Dragonborn.', holds('all'), 2, {'sets': {'mq_stage': 2}}),
    ('mq105_greybeards', 'MQ105', done, 'The Greybeards summoned {player} to High Hrothgar and trained them in the Voice.', holds('all'), 1, {'sets': {'mq_stage': 3}}),
    ('mq106_blades', 'MQ106', done, '{player} learned the dragons are coming back to life and joined Delphine of the Blades.', {'named': ['Delphine', 'Esbern'], 'factions': ['Blades']}, 0, {}),
    ('mq201_embassy', 'MQ201', done, '{player} broke into the Thalmor Embassy.', {'holds': ['Haafingar'], 'factions': ['Thalmor', 'Blades']}, 0, {}),
    ('mq206_alduins_bane', 'MQ206', done, '{player} read an Elder Scroll and learned Dragonrend.', {'factions': ['Greybeards', 'Blades']}, 0, {}),
    ('mq302_truce', 'MQ302', done, '{player} called a peace council at High Hrothgar between the Jarls.', holds('all'), 1, {}),
    ('mq305_alduin', 'MQ305', done, '{player} defeated Alduin, the World-Eater, in Sovngarde.', holds('all'), 3, {'sets': {'mq_stage': 4}}),
    # The Paarthurnax Dilemma completes MQPaarthurnax (stage 100) when the Blades accept sparing him, so completion
    # alone does not mean he died: check the actor.
    ('mq_paarthurnax_dead', 'MQPaarthurnax', lambda q: dead(PAARTHURNAX_REF), '{player} killed Paarthurnax at the Blades\' demand.', {'factions': ['Greybeards', 'Blades']}, 0, {}),
    ('mq_paarthurnax_spared', 'MQPaarthurnax', lambda q: {'type': 'all', 'of': [{'type': 'completed'}, alive(PAARTHURNAX_REF)]},
     '{player} spared Paarthurnax and talked the Blades into letting him live.', {'factions': ['Greybeards', 'Blades']}, 0, {}),
    # Civil War
    ('cw_side_legion', 'CW01A', lambda q: stage(200), '{player} joined the Imperial Legion.', {'holds': ['Haafingar'], 'factions': ['Legion', 'Stormcloaks']}, 1, {'category': 'civil_war', 'sets': {'war_side': 'Legion'}}),
    ('cw_side_stormcloak', 'CW01B', lambda q: stage(200), '{player} joined the Stormcloaks.', {'holds': ['Eastmarch'], 'factions': ['Stormcloaks', 'Legion']}, 1, {'category': 'civil_war', 'sets': {'war_side': 'Stormcloaks'}}),
    ('cw03_whiterun_message', 'CW03', done, '{player} carried a war message to Jarl Balgruuf of Whiterun.', holds('Whiterun'), 0, {}),
    ('cw_finale_legion', 'CWFinale', done, '{player} helped the Legion take Windhelm; Ulfric Stormcloak is dead and the rebellion is over.', holds('all'), 3, {'requires': ['cw_side_legion']}),
    ('cw_finale_stormcloak', 'CWFinale', done, '{player} helped the Stormcloaks take Solitude; General Tullius is dead and Ulfric rules Skyrim.', holds('all'), 3, {'requires': ['cw_side_stormcloak']}),
    # Companions
    ('c00_companions', 'C00', done, '{player} is a member of the Companions of Jorrvaskr.', {'holds': ['Whiterun'], 'factions': ['Companions']}, 1, {'sets': {'guild': 'Companions', 'rank': 'member'}}),
    ('c03_circle', 'C03', done, '{player} joined the Circle of the Companions.', {'factions': ['Companions']}, 0, {'sets': {'guild': 'Companions', 'rank': 'Circle'}}),
    ('c06_harbinger', 'C06', done, '{player} is the Harbinger of the Companions.', {'holds': ['Whiterun'], 'factions': ['Companions']}, 2, {'sets': {'guild': 'Companions', 'rank': 'Harbinger'}}),
    # College of Winterhold
    ('mg01_college', 'MG01', done, '{player} studies at the College of Winterhold.', {'holds': ['Winterhold'], 'factions': ['College of Winterhold']}, 0, {'sets': {'guild': 'College of Winterhold', 'rank': 'apprentice'}}),
    ('mg08_archmage', 'MG08', done, '{player} is the Arch-Mage of the College of Winterhold.', {'holds': ['Winterhold'], 'factions': ['College of Winterhold']}, 2, {'sets': {'guild': 'College of Winterhold', 'rank': 'Arch-Mage'}}),
    # Thieves Guild (a secret: only its members know)
    ('tg01_thieves_guild', 'TG01', done, '{player} works for the Thieves Guild in Riften.', {'factions': ['Thieves Guild']}, 0, {'sets': {'guild': 'Thieves Guild', 'rank': 'member'}}),
    ('tg09_nightingale', 'TG09', done, '{player} is a Nightingale and restored the Thieves Guild.', {'factions': ['Thieves Guild']}, 0, {'sets': {'guild': 'Thieves Guild', 'rank': 'Nightingale'}}),
    # Dark Brotherhood (a secret)
    # Stage 200 is the join; killing Astrid instead sets stage 220 (FailQuest).
    ('db02_brotherhood', 'DB02', lambda q: stage(200), '{player} joined the Dark Brotherhood.', {'factions': ['Dark Brotherhood']}, 0, {'sets': {'guild': 'Dark Brotherhood', 'rank': 'member'}}),
    ('db11_listener', 'DB11', done, '{player} is the Listener of the Dark Brotherhood; the Emperor was assassinated.', {'factions': ['Dark Brotherhood']}, 0, {'sets': {'guild': 'Dark Brotherhood', 'rank': 'Listener'}}),
    # Thane titles (stage 200 is the title; completed covers patched versions)
    *[(f'thane_{h.lower()}', q, lambda q: {'type': 'any', 'of': [{'type': 'completed'}, stage(200)]},
       f'{{player}} is Thane of {"the " + h if h in ("Reach", "Pale", "Rift") else h}.', holds(h), 2, {'category': 'thane', 'hold': h})
      for q, h in THANE.items()],
    ('thane_all', 'FavorJarlsMakeFriends', done, '{player} is Thane of every hold in Skyrim.', holds('all'), 1, {'category': 'thane'}),
    # Riverwood and Whiterun side quests
    ('ms13_golden_claw', 'MS13', done, '{player} brought the golden claw back to Lucan Valerius in Riverwood.', {'holds': ['Whiterun'], 'named': ['Lucan Valerius', 'Camilla Valerius']}, 1, {}),
    ('riverwood_letter', 'FreeformRiverwood01', done, '{player} carried the love-letter business between Faendal, Sven and Camilla in Riverwood.', {'named': ['Faendal', 'Sven', 'Camilla Valerius']}, 0, {'hold': 'Whiterun'}),
    ('ms08_time_of_need', 'MS08', done, '{player} settled the matter of Saadia and the Alik\'r warriors in Whiterun.', holds('Whiterun'), 1, {}),
    ('ms09_missing_in_action', 'MS09', done, '{player} found out what happened to Thorald Gray-Mane.', {'named': ['Fralia Gray-Mane', 'Avulstein Gray-Mane', 'Olfina Gray-Mane'], 'holds': ['Whiterun']}, 1, {}),
    ('t03_blessings', 'T03', done, '{player} helped Danica Pure-Spring revive the Gildergreen.', holds('Whiterun'), 1, {}),
    ('da08_whispering_door', 'DA08', done, '{player} opened the Whispering Door in Dragonsreach.', {'named': ['Balgruuf the Greater', 'Farengar Secret-Fire', 'Nelkir']}, 0, {'hold': 'Whiterun'}),
]

PREFIX_CATEGORY = [('MQ', 'main'), ('CW', 'civil_war'), ('Favor', 'thane'), ('DA', 'daedric'),
                   ('C0', 'faction'), ('MG', 'faction'), ('TG', 'faction'), ('DB', 'faction')]


def hold_name(qjo_location):
    """QJO location key -> one of HOLDS, or None for non-holds ("none", Morrowind, Cyrodiil...)."""
    return _QJO_HOLD.get((qjo_location or '').lower())


def load_qjo(roots):
    """(plugin, editor id) -> {'hold': str|None, 'type': int|None}, plus category type lists under '_mapping'."""
    out, mapping = {}, {'main': [], 'faction': []}
    for root in roots:
        folder = os.path.join(root, 'interface', 'quests')
        for f in sorted(glob.glob(os.path.join(glob.escape(folder), '*.json'))):
            try:
                data = json.load(open(f, encoding='utf-8-sig'))
            except (OSError, ValueError):
                continue
            for plugin, quests in data.items():
                if not isinstance(quests, dict):
                    continue
                for q, v in quests.items():
                    if isinstance(v, dict):
                        out[(plugin.lower(), q.lower())] = {'hold': hold_name(v.get('location')), 'type': v.get('type')}
        m = os.path.join(folder, 'categories', 'mapping.json')
        if os.path.isfile(m):
            try:
                mapping = json.load(open(m, encoding='utf-8-sig'))
            except ValueError:
                pass
    out['_mapping'] = mapping
    return out


def category(quest, qjo_type, mapping):
    if qjo_type is not None:
        if qjo_type in mapping.get('main', []):
            return 'main'
        if qjo_type in mapping.get('faction', []):
            return 'faction'
    for prefix, cat in PREFIX_CATEGORY:
        if quest.startswith(prefix):
            return cat
    return 'side'


def build(qjo):
    mapping = qjo.get('_mapping', {})
    rows = []
    for rid, quest, when, text, audience, fame, extra in OUTCOMES:
        info = qjo.get((PLUGIN.lower(), quest.lower()), {})
        hold = extra.get('hold', info.get('hold'))
        aud = {k: list(v) for k, v in audience.items()}
        if hold and aud.get('holds') and 'all' not in aud['holds'] and hold not in aud['holds']:
            aud['holds'].append(hold)
        row = {'id': rid, 'quest': quest, 'plugin': PLUGIN, 'form': QUESTS[quest], 'form_hex': '0x%06X' % QUESTS[quest],
               'when': when(quest), 'text': text, 'audience': aud, 'fame': fame, 'hold': hold,
               'category': extra.get('category') or category(quest, info.get('type'), mapping)}
        if 'sets' in extra:
            row['sets'] = extra['sets']
        if 'requires' in extra:
            row['requires'] = extra['requires']
        rows.append(row)
    return {'version': 1, 'note': 'Generated by tools/build_quest_outcomes.py; edit OUTCOMES there.',
            'holds': HOLDS, 'count': len(rows), 'rows': rows}


def write(data, path=OUT):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write('\n')
    json.load(open(tmp, encoding='utf-8'))
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--qjo', nargs='*', default=DEFAULT_QJO)
    ap.add_argument('--out', default=OUT)
    a = ap.parse_args()
    roots = [r for r in a.qjo if os.path.isdir(r)]
    data = build(load_qjo(roots))
    write(data, a.out)
    missing = [r['quest'] for r in data['rows'] if r['hold'] is None]
    print(f"{data['count']} outcome rows from {len(roots)} QJO folder(s) -> {a.out}")
    if missing:
        print('no hold from QJO:', ', '.join(sorted(set(missing))))


if __name__ == '__main__':
    main()
