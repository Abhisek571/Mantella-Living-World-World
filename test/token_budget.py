"""Worst-case size of one follower's World facts after a long playthrough, as the Integration Hub puts them in the
prompt. No game needed: the numbers are set the way MLWW_Facts keeps them, the texts come from the port of
MLWW_Facts.Sync (simulate_events.facts_of, checked here against MLWW_Facts.psc), and the Hub's own code parses,
dates and counts them (lw_state.game_facts, memory.facts_text and memory.tokens).

Fails when the worst case is above LIMIT tokens.

usage: py -3 test/token_budget.py [--player-name-length N]
"""
import argparse
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HUB = os.path.join(os.path.dirname(ROOT), 'Mantella-Living-World-Hub', 'server')
sys.path.insert(0, HERE)
sys.path.insert(0, HUB)
from simulate_events import facts_of  # noqa: E402
from living_world import lw_state, memory  # noqa: E402

LIMIT = 125  # about 120
FACTS = open(os.path.join(ROOT, 'Source', 'Scripts', 'MLWW_Facts.psc'), encoding='utf-8').read()
FOLLOWER = 1


def long_playthrough(worst):
    """A follower who has been along for everything (and trades), with long names and dates long ago. worst: every
    count at the widest it can reach in a long playthrough: rescues and friendly hits in the hundreds (each needs a
    rescue window or a hit that cost health), heals, fights and defences in the thousands (heals are counted once a
    minute), kills in the tens of thousands, dungeons in the hundreds, trade gold in the hundreds of thousands. Else
    counts in the tens."""
    s = {}
    for key, width in (('MLWW_SavedByPlayer', 3), ('MLWW_SavedPlayer', 3), ('MLWW_HealedByPlayer', 4), ('MLWW_HealedPlayer', 4),
                       ('MLWW_HitByPlayer', 3), ('MLWW_HitPlayer', 3), ('MLWW_Dungeons', 3), ('MLWW_KillsOwn', 5),
                       ('MLWW_KillsPlayer', 5), ('MLWW_Fought', 4), ('MLWW_Defended', 4)):
        s[(FOLLOWER, key)] = int('9' * (width if worst else 2))
    s[(FOLLOWER, 'MLWW_SpentTotal')] = s[(FOLLOWER, 'MLWW_SoldTotal')] = 249999 if worst else 2500
    s[(FOLLOWER, 'MLWW_Visits')] = 999 if worst else 40
    s[(FOLLOWER, 'MLWW_GoodsNames')], s[(FOLLOWER, 'MLWW_GoodsCounts')] = ['Flawless Amethyst'], [99]
    for key in ('MLWW_SavedDay', 'MLWW_HealedDay', 'MLWW_HitDay', 'MLWW_DungeonDay', 'MLWW_BestDay', 'MLWW_FoughtDay', 'MLWW_DefendedDay'):
        s[(FOLLOWER, key)] = 1
    s[(None, 'MLWW_BestDay')] = 1
    s[(FOLLOWER, 'MLWW_DungeonLast')] = 'Labyrinthian Thoroughfare'  # among the longest dungeon names, 25 characters
    s[(FOLLOWER, 'MLWW_BestName')], s[(FOLLOWER, 'MLWW_BestScore')] = 'Dragon Priest Konahrik', 1081  # a unique: no level
    s[(None, 'MLWW_BestName')], s[(None, 'MLWW_BestScore')] = 'Ancient Shrouded Dragon', 2090  # the player's, stronger
    return s


def hub_rows(store, player, merchant=True, today=999):
    """The World rows exactly as the Hub writes and budgets them: (row text, tokens charged)."""
    facts = facts_of(store, FOLLOWER, player, teammate=True)
    if not merchant:
        facts.pop('fact_customer', None)  # most followers are no merchants
    rows = lw_state.game_facts(facts, today)
    text = memory.facts_text({}, rows, today, player, 'Follower', budget_tokens=10 ** 6)
    lines = [l[2:] for l in text.splitlines() if l.startswith('- ')]
    return [(l, memory.tokens(l) + 1) for l in lines], memory.tokens('What you know for certain:')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--player-name-length', type=int, default=16)
    args = ap.parse_args()
    fails = 0

    # The port must say what MLWW_Facts.psc says: every fixed text piece of the port is in the script.
    tree = ast.parse(open(os.path.join(HERE, 'simulate_events.py'), encoding='utf-8').read())
    port = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'facts_of')
    pieces = {n.value.strip(' ,:') for n in ast.walk(port) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    pieces = {p for p in pieces if len(p) > 4 and not p.startswith(('MLWW_', 'fact_')) and '|' not in p}
    missing = sorted(p for p in pieces if p not in FACTS)
    print(('PASS' if not missing else 'FAIL') + f' {len(pieces)} text pieces of the port are in MLWW_Facts.psc' + (f': {missing}' if missing else ''))
    fails += bool(missing)

    player = 'P' * args.player_name_length
    for title, worst_case in (('long playthrough, counts in the tens', False), ('worst case, every count at its widest', True)):
        rows, heading = hub_rows(long_playthrough(worst_case), player)
        total = sum(t for _, t in rows)
        print(f'== {title}, player name {len(player)} characters: {len(rows)} facts, {total} tokens (+{heading} heading)')
        for line, t in rows:
            print(f'   {t:3}  {line}')
        if worst_case:
            worst = total
    plain_rows, _ = hub_rows(long_playthrough(True), player, merchant=False)
    print(f'   without the customer fact (a follower who is no merchant): {sum(t for _, t in plain_rows)} tokens')
    per_char = sum(line.count(player) for line, _ in rows) / 4
    print(f'   each extra character of the player name adds about {per_char:.1f} tokens')
    ok = worst <= LIMIT
    print(('PASS' if ok else 'FAIL') + f' worst case for one follower, customer fact included: {worst} tokens (limit {LIMIT}; the Hub gives all facts '
          f'{memory.FACT_TOKENS}, in a group at least {memory.MIN_GROUP_FACT_TOKENS} per NPC)')
    fails += not ok
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
