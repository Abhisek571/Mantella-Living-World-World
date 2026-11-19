"""Tests for make_records.py. Run: py -3 tools/test_make_records.py  (or: py -3 -m pytest tools)"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_records as M

BY_SCRIPT = {q[2]: q for q in M.QUESTS}
ACTIONS = {a['identifier']: a for a in M.ACTIONS}


def test_state_quest_has_no_world_property():
    yaml = M.quest_yaml(*BY_SCRIPT['MLWW_State'])
    assert 'Name: PlayerRef' in yaml and 'Name: World\n' not in yaml


def test_dependent_quest_points_at_the_state_quest():
    yaml = M.quest_yaml(*BY_SCRIPT['MLWW_Crime'])
    assert f'Name: World\n      Object: {M.STATE}:{M.E}\n' in yaml


def test_globals_go_only_to_their_script():
    banter = M.quest_yaml(*BY_SCRIPT['MLWW_Banter'])
    initiative = M.quest_yaml(*BY_SCRIPT['MLWW_Initiative'])
    assert 'Name: MLWW_BanterOn' in banter and 'Name: MLWW_BanterChance' in banter
    assert 'MLWW_InitiativeOn' not in banter and 'Name: MLWW_InitiativeOn' in initiative
    assert all('MLWW_Battle' not in M.quest_yaml(*q) for q in M.QUESTS)  # read by the SKSE plugin only


def test_only_banter_uses_the_hit_alias():
    for quest in M.QUESTS:
        alias = 'MLWW_BanterAlias' if quest[2] == 'MLWW_Banter' else 'MLWW_PlayerAlias'
        assert f'- Name: {alias}\n' in M.quest_yaml(*quest)


def test_crime_actions_never_repeat_trade_does():
    files = {k: json.loads(M.action_json(a)) for k, a in ACTIONS.items()}
    assert files['mantella_mlww_trade']['allow_repeat'] is True
    assert files['mantella_mlww_settle_crime']['allow_repeat'] is False
    assert files['mantella_mlww_report_crime']['allow_repeat'] is False


def test_gate_only_when_given():
    assert 'lw_gate' not in json.loads(M.action_json(ACTIONS['mantella_mlww_trade']))
    assert json.loads(M.action_json(ACTIONS['mantella_mlww_report_crime']))['lw_gate'] == 'authority'


def test_one_on_one_defaults_to_true():
    assert json.loads(M.action_json(ACTIONS['mantella_mlww_trade']))['one-on-one'] is True
    assert json.loads(M.action_json(ACTIONS['mantella_mlww_report_crime']))['one-on-one'] is False


def test_action_file_ends_with_one_newline():
    text = M.action_json(ACTIONS['mantella_mlww_trade'])
    assert text.endswith('}\n') and not text.endswith('\n\n')


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
