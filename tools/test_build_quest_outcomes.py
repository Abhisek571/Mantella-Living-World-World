"""Tests for build_quest_outcomes.py. Run: py -3 -m pytest tools  (or: py -3 tools/test_build_quest_outcomes.py)"""
import json, os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_quest_outcomes as B

CONDITIONS = {'completed', 'stage', 'any', 'dead'}


def fake_qjo(entries, types=None):
    """A Quest Journal Overhaul folder with one skyrim.json and the category mapping."""
    root = tempfile.mkdtemp()
    quests = os.path.join(root, 'interface', 'quests')
    os.makedirs(os.path.join(quests, 'categories'))
    data = {'Skyrim.esm': {q: dict({'location': loc}, **({'type': types[q]} if types and q in types else {}))
                           for q, loc in entries.items()}}
    json.dump(data, open(os.path.join(quests, 'skyrim.json'), 'w', encoding='utf-8'))
    json.dump({'main': [1, 10, 11, 13], 'faction': [2, 3, 4, 5, 9, 12]},
              open(os.path.join(quests, 'categories', 'mapping.json'), 'w', encoding='utf-8'))
    return root


def built(qjo_root=None):
    roots = [qjo_root] if qjo_root else []
    return B.build(B.load_qjo(roots))


def check_condition(c):
    assert c.get('type') in CONDITIONS, c
    if c['type'] == 'stage':
        assert isinstance(c.get('stage'), int) and c['stage'] >= 0, c
    if c['type'] == 'any':
        assert c.get('of'), c
        for sub in c['of']:
            assert sub.get('type') in CONDITIONS - {'any'}, sub
            check_condition(sub)
    if c['type'] == 'dead':
        assert isinstance(c.get('form'), int) and c.get('plugin'), c


def test_every_row_has_condition_text_audience():
    rows = built()['rows']
    assert rows
    for r in rows:
        check_condition(r['when'])
        assert r['text'].strip(), r['id']
        assert '{player}' in r['text'], r['id']
        assert len(r['text']) <= 160, r['id']
        a = r['audience']
        assert a.get('holds') or a.get('factions') or a.get('named'), r['id']
        for h in a.get('holds', []):
            assert h == 'all' or h in B.HOLDS, (r['id'], h)


def test_hold_from_qjo():
    root = fake_qjo({'MS13': 'whiterunHold', 'MQ104': 'whiterunHold', 'MG08': 'winterholdHold',
                     'CW01A': 'haafingarHold', 'MQ101': 'none', 'T03': 'whiterunHold'}, types={'CW01A': 9, 'T03': 1})
    data = built(root)
    by_id = {r['id']: r for r in data['rows']}
    assert by_id['ms13_golden_claw']['hold'] == 'Whiterun'
    assert 'Whiterun' in by_id['ms13_golden_claw']['audience']['holds']
    assert by_id['mg08_archmage']['hold'] == 'Winterhold'
    # A quest QJO places nowhere ("none") keeps no hold.
    assert by_id['mq101_helgen']['hold'] is None
    # Category: a hand-set category wins, then the QJO type (1 = main), then the editor-id prefix.
    assert by_id['cw_side_legion']['category'] == 'civil_war'
    assert by_id['t03_blessings']['category'] == 'main'
    assert by_id['ms08_time_of_need']['category'] == 'side'
    assert by_id['mq104_dragonborn']['category'] == 'main'


def test_hold_mapping_covers_qjo_hold_keys():
    for key in ['whiterunHold', 'haafingarHold', 'eastmarchHold', 'riftHold', 'reachHold', 'paleHold',
                'falkreathHold', 'hjaalmarchHold', 'winterholdHold']:
        assert B.hold_name(key) in B.HOLDS
    assert B.hold_name('redoranTerritories') is None
    assert B.hold_name('none') is None


def test_required_lines_covered():
    data = built()
    quests = {r['quest'] for r in data['rows']}
    # Main quest, Civil War, the four guild lines, all nine Thane titles, Riverwood/Whiterun side quests.
    for q in ['MQ101', 'MQ104', 'MQ105', 'MQ206', 'MQ305', 'CW01A', 'CW01B', 'CWFinale', 'C00', 'C06', 'MG01', 'MG08',
              'TG01', 'TG09', 'DB02', 'DB11', 'Favor250', 'Favor252', 'Favor253', 'Favor254', 'Favor255', 'Favor256',
              'Favor257', 'Favor258', 'FreeformRiftenThane', 'FavorJarlsMakeFriends', 'MS13', 'FreeformRiverwood01', 'MS08', 'MS09', 'T03', 'DA08',
              'CW03', 'MQ103']:
        assert q in quests, q
    cats = {r['category'] for r in data['rows']}
    assert {'main', 'civil_war', 'faction', 'thane', 'side'} <= cats


def test_rows_papyrus_ready():
    data = built()
    ids = [r['id'] for r in data['rows']]
    assert len(ids) == len(set(ids))
    for r in data['rows']:
        assert 0 < r['form'] < 0x01000000, r['id']
        assert r['plugin'].endswith(('.esm', '.esp', '.esl'))
        assert r['form_hex'] == '0x%06X' % r['form']
        assert isinstance(r['fame'], int) and 0 <= r['fame'] <= 3
        for req in r.get('requires', []):
            assert req in ids, (r['id'], req)
    # Papyrus walks .rows[i] and reads .count; both must match.
    assert data['count'] == len(data['rows'])
    json.loads(json.dumps(data))


def test_sets_feed_world_state():
    rows = built()['rows']
    # Later rows of a guild override earlier ones in game, so ranks must be in order within each guild.
    ranks = {}
    for r in rows:
        sets = r.get('sets', {})
        assert set(sets) <= {'guild', 'rank', 'war_side', 'mq_stage'}, r['id']
        if 'guild' in sets:
            assert sets.get('rank'), r['id']
            ranks.setdefault(sets['guild'], []).append(sets['rank'])
        if 'war_side' in sets:
            assert sets['war_side'] in ('Legion', 'Stormcloaks')
    assert ranks['Companions'][-1] == 'Harbinger' and ranks['College of Winterhold'][-1] == 'Arch-Mage'
    assert ranks['Thieves Guild'][-1] == 'Nightingale' and ranks['Dark Brotherhood'][-1] == 'Listener'
    stages = [r['sets']['mq_stage'] for r in rows if 'mq_stage' in r.get('sets', {})]
    assert stages == sorted(stages)
    thane = {r['hold'] for r in rows if r['category'] == 'thane' and r['hold']}
    assert thane == set(B.HOLDS)


def test_write_is_valid_json():
    out = os.path.join(tempfile.mkdtemp(), 'quest_outcomes.json')
    B.write(built(), out)
    data = json.load(open(out, encoding='utf-8'))
    assert data['rows'] and data['version'] == 1


def test_folder_with_glob_characters():
    # Mod folders are named like "[NoDelete] Quest Journal Overhaul": brackets must not act as a glob pattern.
    parent = tempfile.mkdtemp()
    src = fake_qjo({'MS13': 'whiterunHold'})
    dst = os.path.join(parent, '[NoDelete] QJO')
    os.rename(src, dst)
    assert B.load_qjo([dst])[('skyrim.esm', 'ms13')]['hold'] == 'Whiterun'


def test_real_qjo_if_installed():
    roots = [r for r in B.DEFAULT_QJO if os.path.isdir(r)]
    if not roots:
        return
    data = B.build(B.load_qjo(roots))
    by_quest = {r['quest']: r for r in data['rows']}
    assert by_quest['MS13']['hold'] == 'Whiterun'
    assert by_quest['MG08']['hold'] == 'Winterhold'
    assert by_quest['DB11']['hold'] == 'Haafingar'


if __name__ == '__main__':
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print('PASS', name)
            except Exception as e:  # report every failure, not just the first
                failed += 1
                print('FAIL', name, repr(e))
    sys.exit(1 if failed else 0)
