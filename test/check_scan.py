"""Offline checks for World's world.json refresh schedule (MLWW_State.psc + the quest natives in plugin/src/Personal.cpp),
no game needed.

1. Code checks: what each trigger is allowed to run (a talk start and a location change never scan quests), the quest
   reads go through the plugin, the scheduler keeps a request made while a refresh runs.
2. A model of Pump / Step / Schedule and the plugin's change set (every model function names the Papyrus it mirrors),
   with refreshes that take real time so events land while one runs, driven through:
     - a load: the cached values are written at once, the full scan waits SETTLE seconds
     - quest changes: batched at most once per QUEST_COOLDOWN, none lost
     - sleep across midnight and the day check: one shared timer, one scan
     - a full scan due during a talk or a fight waits until it ends
     - a request during a running refresh is run after it (the old Refresh() dropped it: the model must see that too)
     - talk starts and location changes: no full scan, no quest read

usage: py -3 test/check_scan.py
"""
import heapq
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import checklib  # noqa: E402
from checklib import check  # noqa: E402
PSC = open(os.path.join(ROOT, 'Source', 'Scripts', 'MLWW_State.psc'), encoding='utf-8').read()
CPP = open(os.path.join(ROOT, 'plugin', 'src', 'Personal.cpp'), encoding='utf-8').read()


def code(text):
    return '\n'.join(line.split(';')[0] for line in text.splitlines())


STATE = code(PSC)


def body(kind, name):
    m = re.search(rf'^(?:\w+(?:\[\])? )?{kind} {name}\(.*?^End{kind}', STATE, re.M | re.S)
    return m.group(0) if m else ''


def const(name):
    return float(re.search(rf'float Property {name} = ([\d.]+) AutoReadOnly', PSC).group(1))


THROTTLE, SETTLE, COOLDOWN, RETRY, TALK_FRESH = (const(n) for n in ('THROTTLE', 'SETTLE', 'QUEST_COOLDOWN', 'BUSY_RETRY', 'TALK_FRESH'))

# ---------------------------------------------------------------------------
# 1. Code checks
# ---------------------------------------------------------------------------
SCANS = ('DueFull', 'FullScan', 'ReadAllQuests', 'EvalOutcomes', 'QuestBatch', 'DueQuests', 'ReadQuests', 'GetQuest')
talk = body('Event', 'OnConversationStarted')
check('a talk start asks only for the cheap refresh (no quest scan, no outcome table)',
      talk and 'DueCheap(0.0)' in talk and not any(s in talk for s in SCANS), talk[:200])
loc = body('Function', 'LocationChanged')
check('a location change asks only for the cheap refresh, throttled', loc and 'DueCheap(lastCheap + THROTTLE)' in loc and not any(s in loc for s in SCANS))
reg = body('Function', 'Register')
check('a load writes the kept values at once and asks for the full scan SETTLE seconds later',
      'If cached' in reg and 'WriteOutcomes()' in reg and 'WriteQuestJson()' in reg and 'DueFull("load", Utility.GetCurrentRealTime() + SETTLE)' in reg)
check('a load no longer marks world.json loading while values of this save are kept (A03)',
      re.search(r'If cached.*?Else\s+JsonUtil\.SetPathIntValue\(WORLD_FILE, "\.loading", 1\)', reg, re.S) is not None)
step = body('Function', 'Step')
check('a full scan due during a talk or fight waits (Occupied) unless forced',
      re.search(r'If !abForce && Occupied\(\)\s+fullAt = now \+ BUSY_RETRY', step) is not None)
check('the day check asks for a full scan one game day after the last', 'Utility.GetCurrentGameTime() - lastFullDay >= 1.0' in step and 'DueFull("day", 0.0)' in step)
check('quest batches keep the cooldown', re.search(r'If questDue && now >= questAt\s+questDue = false\s+questAt = now \+ QUEST_COOLDOWN', step) is not None)
occ = body('Function', 'Occupied')
check('Occupied = fighting or a Mantella talk running', 'PlayerRef.IsInCombat()' in occ and 'talk.IsRunning()' in occ)
pump = body('Function', 'Pump')
check('a request while a refresh runs is kept and run after it (A07)',
      re.search(r'If busy\s+again = true\s+Return', pump) is not None and re.search(r'While again(?: && gen == pumpGen)?\s+again = false\s+Step', pump) is not None)
# B06: Papyrus keeps running calls in the save. A save made during a Pump resumed that loop after loading, while
# Register cleared busy and started a second one; the first to finish cleared busy under the other. Register now
# counts a generation and a loop from before it stops without touching busy.
check('Register starts a new Pump generation before it clears busy', re.search(r'pumpGen \+= 1\s+busy = false', reg) is not None, reg[:200])
check('a Pump loop stops when the generation changed, and only its own generation clears busy and schedules',
      'int gen = pumpGen' in pump and 'While again && gen == pumpGen' in pump
      and re.search(r'If gen == pumpGen\s+busy = false\s+Schedule\(\)\s+EndIf', pump) is not None, pump)


def port_pump_after_load(fixed=True):
    """A save made during a Pump: the restored loop goes on after Register's own loop started. Returns the most loops
    running at once and whether busy ended cleared."""
    state = {'busy': True, 'gen': 0, 'running': 1, 'most': 1, 'again': False}  # the restored loop, mid-step
    restored_gen = state['gen']
    # Register on load
    if fixed:
        state['gen'] += 1
    state['busy'] = False
    # Register's own Pump begins (its step yields; the restored loop resumes in between)
    state['busy'] = True
    state['running'] += 1
    state['most'] = max(state['most'], state['running'])
    own_gen = state['gen']
    # the restored loop finishes its step
    state['running'] -= 1
    if not fixed or restored_gen == state['gen']:
        state['busy'] = False  # cleared while Register's loop still runs
    busy_while_own_runs = state['busy']
    # Register's loop finishes
    state['running'] -= 1
    if not fixed or own_gen == state['gen']:
        state['busy'] = False
    return busy_while_own_runs, state['busy']


check('Pump model: after such a load, busy stays set while the new loop runs, and is cleared when it ends',
      port_pump_after_load(True) == (True, False))
check('Pump model: without the generation, the restored loop cleared busy under the new one (the old fault)',
      port_pump_after_load(False) == (False, False))
full = body('Function', 'FullScan')
check('a full scan re-arms the shared day timer', 'RegisterForSingleUpdateGameTime(24.0)' in full and 'lastFullDay = Utility.GetCurrentGameTime()' in full)

rested = body('Function', 'Rested')
check('sleeping and waiting ask for a full scan, once per rest (not again when one ran since the rest began)',
      'Rested("sleep or wait")' in body('Event', 'OnMenuClose') and 'Rested("sleep")' in body('Event', 'OnSleepStop')
      and 'lastFullDay < menuFrom' in rested and 'DueFull(asWhy, 0.0)' in rested
      and 'RegisterForMenu("Sleep/Wait Menu")' in reg and 'RegisterForSleep()' in reg)
check('a full scan notes its game time first, so a rest event during it asks for no second one',
      re.search(r'started = Utility\.GetCurrentRealTime\(\)\s+lastFullDay = Utility\.GetCurrentGameTime\(\)', full) is not None)
check('no quest is read one by one in Papyrus any more', 'Quest.GetQuest' not in STATE and 'GetStage()' not in STATE)
qb = body('Function', 'QuestBatch')
check('a quest batch re-reads only changed quests and looks at the outcome table only when needed',
      'MLWW_Native.ReadChangedQuests()' in qb and re.search(r'If changed > 0\s+KeepQuestJson\(\)', qb) is not None and 'MLWW_Native.OutcomeQuestsChanged() || deathDue' in qb)
# live test 18: a save holding these strings (over 5 KB each) crashed on load, in the engine's read of the save's string
# table; the long JSON lives in PapyrusUtil's storage, never in a script variable
script_vars = re.findall(r'^string\s+(\w+)\s*=', STATE, re.M)
check('no script variable keeps the quest or event JSON (kept in StorageUtil, out of the Papyrus string table)',
      not {'questStages', 'questStates', 'eventJson'} & set(script_vars)
      and 'StorageUtil.SetStringValue(None, KEY_QUEST_STAGES' in body('Function', 'KeepQuestJson')
      and 'StorageUtil.SetStringValue(None, KEY_EVENTS' in STATE, script_vars)
check('the quest JSON is never replaced by an empty read', re.search(r'If questStages == "" \|\| questStates == ""\s+Return true', body('Function', 'WriteQuestJson')) is not None)
check('World still works without Knowledge (the quest list is read through JsonUtil, no Knowledge script)', 'MLWK_' not in STATE)

# The plugin side.
check('the plugin hears quest stage and start/stop events',
      'AddEventSink<RE::TESQuestStageEvent>(&stage)' in CPP and 'AddEventSink<RE::TESQuestStartStopEvent>(&startStop)' in CPP)
onq = re.search(r'void OnQuestChanged\(RE::FormID a_quest\).*?\n\t\t}\n', CPP, re.S).group(0)
check('one MLWW_QuestChanged event per batch (only when the change set was empty)', 'first = g_questChanged.empty();' in onq and 'if (first)' in onq)
rq = re.search(r'std::int32_t ReadQuests\(.*?\n\t\t}\n', CPP, re.S).group(0)
check('a full read clears the change set', 'g_questChanged.clear();' in rq)
rc = re.search(r'std::int32_t ReadChangedQuests\(.*?\n\t\t}\n', CPP, re.S).group(0)
check('a batch re-reads only the changed quests and empties the change set',
      'if (g_questChanged.contains(row.quest->GetFormID()))' in rc and 'g_questChanged.clear();' in rc and 'return -1;' in rc)
reset = re.search(r'void ResetFight\(\).*?\n\t}\n', CPP, re.S).group(0)
check('a load forgets the quests read and the changes not taken', 'g_questRows.clear();' in reset and 'g_questChanged.clear();' in reset)

# ---------------------------------------------------------------------------
# 2. The model
# ---------------------------------------------------------------------------
CHEAP_TIME, FULL_TIME, BATCH_TIME = 1.0, 4.0, 0.2  # real seconds a refresh holds the script (frame-bound calls)


class Model:
    def __init__(self, fixed=True):
        self.fixed = fixed
        self.t = 0.0           # real seconds
        self.game = 10.0       # game days
        self.queue = []        # (time, seq, fn)
        self.seq = 0
        self.log = []          # (time, kind, why)
        self.talking = False
        self.fighting = False
        # MLWW_State variables
        self.cached = True
        self.last_full_day = self.game - 0.5
        self.busy = self.again = False
        self.cheap_due = self.full_due = self.quest_due = self.death_due = False
        self.cheap_at = self.full_at = self.quest_at = 0.0
        self.full_why = ''
        self.last_cheap = -1000.0
        self.update_at = None       # RegisterForSingleUpdate
        self.game_update_at = None  # RegisterForSingleUpdateGameTime, as a game day
        self.loading = 1
        # the plugin
        self.changed = set()
        self.read = []         # (time, ids) re-read by batches
        self.changes = []      # (time, id)
        # the old Refresh()
        self.old_pending = False
        self.rest_from = -1.0

    # -- event loop --------------------------------------------------------
    def at(self, t, fn):
        self.seq += 1
        heapq.heappush(self.queue, (t, self.seq, fn))

    def advance(self, d):
        """The script holds busy for d seconds; events due meanwhile run now (Papyrus lets other threads in during
        frame-bound calls)."""
        end = self.t + d
        while self.queue and self.queue[0][0] <= end:
            t, _, fn = heapq.heappop(self.queue)
            self.t = max(self.t, t)
            fn()
        self.t = end
        self.timers(end)

    def timers(self, upto):
        if self.update_at is not None and self.update_at <= upto:
            self.update_at = None
            self.at(self.t, self.on_update)
        if self.game_update_at is not None and self.game >= self.game_update_at:
            self.game_update_at = None
            self.at(self.t, self.on_update)

    def run(self, until):
        while True:
            nxt = [x for x in (self.queue[0][0] if self.queue else None, self.update_at) if x is not None]
            if not nxt or min(nxt) > until:
                break
            t = min(nxt)
            self.game += (t - self.t) / 86400.0 * 20  # timescale 20
            self.t = t
            if self.update_at is not None and self.update_at <= t:
                self.update_at = None
                self.on_update()
                continue
            _, _, fn = heapq.heappop(self.queue)
            fn()
            if self.game_update_at is not None and self.game >= self.game_update_at:
                self.game_update_at = None
                self.on_update()
        self.game += (until - self.t) / 86400.0 * 20
        self.t = until
        if self.game_update_at is not None and self.game >= self.game_update_at:
            self.game_update_at = None
            self.on_update()

    # -- the plugin (Personal.cpp OnQuestChanged / ReadChangedQuests / ReadQuests) --
    def quest_changed(self, qid):
        self.changes.append((self.t, qid))
        first = not self.changed
        self.changed.add(qid)
        if first:
            self.on_quest_changed()

    # -- MLWW_State --------------------------------------------------------
    def register(self):  # Register
        self.busy = self.again = self.cheap_due = self.quest_due = False
        self.quest_at = 0.0
        self.last_cheap = -1000.0
        self.changed = set()  # ResetFight on load
        if self.cached:
            self.loading = 0 if self.loading == 0 else self.loading  # kept values written at once
            self.game_update_at = max(self.last_full_day + 1.0, self.game + 0.1 / 24)
        else:
            self.loading = 1
        self.due_cheap(0.0)
        self.due_full('load', self.t + SETTLE)
        self.pump()

    def location_changed(self):  # LocationChanged
        if self.fixed:
            self.due_cheap(self.last_cheap + THROTTLE)
            self.pump()
        else:
            self.old_request()

    def conversation_started(self):  # OnConversationStarted
        if self.fixed:
            if self.t - self.last_cheap >= TALK_FRESH:
                self.due_cheap(0.0)
            self.pump()
        else:
            self.old_request()

    def on_quest_changed(self):  # OnQuestChanged
        self.due_quests()

    def named_death(self):  # OnNamedDeath
        self.death_due = True
        self.due_quests()

    def sleep_or_wait(self, hours, sleep_stop_after=1.0):
        """OnMenuOpen, the hours pass, OnMenuClose; OnSleepStop lands a moment later, while the scan the menu asked
        for is still running."""
        self.rest_from = self.game
        self.game += hours / 24.0
        self.at(self.t + sleep_stop_after, lambda: self.rested('sleep'))  # OnSleepStop
        self.rested('sleep or wait')  # OnMenuClose (its menuFrom = -1 is left out: the model checks the stronger guard)

    def rested(self, why):  # Rested
        if self.rest_from >= 0.0 and self.game - self.rest_from > 0.01 and self.last_full_day < self.rest_from:
            self.due_full(why, 0.0)
            self.pump()

    def on_update(self):  # OnUpdate / OnUpdateGameTime
        if self.fixed:
            self.pump()
        else:
            self.old_pending = False
            self.old_refresh('update')

    def due_cheap(self, at):
        if not self.cheap_due or at < self.cheap_at:
            self.cheap_at = at
        self.cheap_due = True

    def due_full(self, why, at):
        if not self.full_due or at < self.full_at:
            self.full_at, self.full_why = at, why
        self.full_due = True

    def due_quests(self):
        if not self.quest_due:
            self.quest_due = True
            self.pump()

    def pump(self, force=False):
        if self.busy:
            self.again = True
            return
        self.busy = True
        self.again = True
        while self.again:
            self.again = False
            self.step(force)
        self.busy = False
        self.schedule()

    def step(self, force):
        now = self.t
        if self.quest_due and now >= self.quest_at:
            self.quest_due = False
            self.quest_at = now + COOLDOWN
            self.quest_batch()
        if not self.full_due and self.cached and self.game - self.last_full_day >= 1.0:
            self.due_full('day', 0.0)
        if self.full_due and now >= self.full_at:
            if not force and (self.talking or self.fighting):
                self.full_at = now + RETRY
            else:
                self.full_due = False
                self.full_scan(self.full_why)
        if self.cheap_due and now >= self.cheap_at:
            self.cheap_due = False
            self.cheap()

    def schedule(self):
        nxt = [x for due, x in ((self.quest_due, self.quest_at), (self.full_due, self.full_at), (self.cheap_due, self.cheap_at)) if due]
        if nxt:
            self.update_at = max(min(nxt), self.t + 0.1)

    def full_scan(self, why):
        self.log.append((self.t, 'full', why))
        self.last_full_day = self.game  # first, as in FullScan
        self.changed = set()  # ReadQuests reads everything
        self.cached = True
        self.loading = 0
        self.advance(FULL_TIME)
        self.game_update_at = self.game + 1.0
        self.last_cheap = self.t

    def quest_batch(self):
        ids, self.changed = self.changed, set()
        self.log.append((self.t, 'batch', ''))
        if ids:
            self.read.append((self.t, ids))
        self.death_due = False
        self.advance(BATCH_TIME)

    def cheap(self):
        self.log.append((self.t, 'cheap', ''))
        self.last_cheap = self.t
        if self.cached:
            self.loading = 0
        self.advance(CHEAP_TIME)

    # -- the logic before this change (Refresh with busy return, every trigger scanning quests) --
    def old_request(self):
        wait = self.last_cheap + 30.0 - self.t
        if 0 < wait <= 30.0:
            if not self.old_pending:
                self.old_pending = True
                self.update_at = self.t + wait + 0.1
            return
        self.old_refresh('request')

    def old_refresh(self, why):
        if self.busy:
            self.log.append((self.t, 'dropped', why))
            return
        self.busy = True
        self.last_cheap = self.t
        self.log.append((self.t, 'full', why))
        self.advance(44.0)
        self.busy = False

    def count(self, kind, since=-1.0, until=1e18):
        return sum(1 for t, k, _ in self.log if k == kind and since <= t <= until)


def scenario_load():
    m = Model()
    m.at(0.0, m.register)
    m.run(SETTLE - 1.0)
    early = m.count('full')
    loading_early = m.loading
    m.run(SETTLE + FULL_TIME + 1.0)
    fulls = [t for t, k, _ in m.log if k == 'full']
    check('load: world.json readable at once from the kept values, full scan not before SETTLE, then exactly one',
          early == 0 and loading_early == 0 and len(fulls) == 1 and fulls[0] >= SETTLE, (early, loading_early, fulls))
    m2 = Model()
    m2.cached = False
    m2.at(0.0, m2.register)
    m2.run(SETTLE - 1.0)
    first = m2.loading
    m2.run(SETTLE + FULL_TIME + 1.0)
    check('load of a save with nothing kept (first load after the update): loading 1 until the first full scan, then 0',
          first == 1 and m2.loading == 0, (first, m2.loading))


def scenario_batching():
    m = Model()
    m.at(0.0, m.register)
    m.run(30.0)  # load settled
    m.log.clear()
    times = [100.0, 110.0, 130.0, 159.0, 161.0, 162.0, 300.0]
    for i, t in enumerate(times):
        m.at(t, lambda i=i: m.quest_changed(f'Q{i}'))
    m.run(500.0)
    batches = [t for t, ids in m.read]
    gaps = [b - a for a, b in zip(batches, batches[1:])]
    read_ids = set().union(*[ids for _, ids in m.read]) if m.read else set()
    check('quest changes: every batch at least QUEST_COOLDOWN after the one before',
          all(g >= COOLDOWN - 1e-6 for g in gaps), (batches, gaps))
    check('quest changes: none lost, each read within QUEST_COOLDOWN + 1 s', read_ids == {f'Q{i}' for i in range(len(times))}
          and all(any(rt >= ct and rt - ct <= COOLDOWN + 1.0 and f'Q{i}' in ids for rt, ids in m.read) for i, ct in enumerate(times)),
          m.read)
    check('quest changes: 7 changes in 4 batches (100, 160, 220 and 300)', len(m.read) == 4, batches)
    check('quest changes: no full scan for a quest change', m.count('full') == 0, m.log)


def scenario_timer():
    m = Model()
    m.game = 10.8  # evening
    m.last_full_day = 10.0
    m.at(0.0, m.register)
    m.run(30.0)
    m.log.clear()
    m.at(40.0, lambda: m.sleep_or_wait(8))  # across midnight, and a full day since the scan at 10.0
    m.run(60.0)
    check('sleep across midnight (day check also due): exactly one full scan', m.count('full') == 1, m.log)
    m.log.clear()
    start = m.game
    m.run(60.0 + 86400.0 / 20 * 1.05)  # a little over one game day of play, no sleep
    check('a game day passing: exactly one full scan (day)', m.count('full') == 1 and all(w == 'day' for _, k, w in m.log if k == 'full'),
          [x for x in m.log if x[1] == 'full'])
    m.log.clear()
    m.run(m.t + 86400.0 / 20 * 0.5)
    check('half a game day later: no full scan', m.count('full') == 0, m.log)


def scenario_talk_and_fight():
    m = Model()
    m.at(0.0, m.register)
    m.at(2.0, lambda: setattr(m, 'talking', True))
    m.at(3.0, m.conversation_started)
    m.at(80.0, lambda: setattr(m, 'talking', False))
    m.run(200.0)
    fulls = [t for t, k, _ in m.log if k == 'full']
    check('the load scan due during a talk waits until it ends (then within BUSY_RETRY)',
          len(fulls) == 1 and 80.0 <= fulls[0] <= 80.0 + RETRY + 0.2, fulls)
    m = Model()
    m.at(0.0, m.register)
    m.run(30.0)
    m.log.clear()
    m.at(40.0, lambda: setattr(m, 'fighting', True))
    m.at(41.0, lambda: m.sleep_or_wait(1))
    m.at(70.0, lambda: setattr(m, 'fighting', False))
    m.run(120.0)
    fulls = [t for t, k, _ in m.log if k == 'full']
    check('a full scan due during a fight waits until it ends', len(fulls) == 1 and 70.0 <= fulls[0] <= 70.0 + RETRY + 0.2, fulls)


def scenario_triggers():
    m = Model()
    m.at(0.0, m.register)
    m.run(30.0)
    m.log.clear()
    for t in (40.0, 43.0, 100.0, 300.0):
        m.at(t, m.conversation_started)
    for t in (50.0, 55.0, 60.0, 200.0):
        m.at(t, m.location_changed)
    m.run(400.0)
    check('talk starts and location changes: no full scan, no quest batch', m.count('full') == 0 and m.count('batch') == 0, m.log)
    cheap = [t for t, k, _ in m.log if k == 'cheap']
    check('talk starts get the cheap refresh at once (40, 100, 300; 43 is within TALK_FRESH)',
          all(any(abs(c - t) < 0.01 for c in cheap) for t in (40.0, 100.0, 300.0)) and not any(abs(c - 43.0) < 0.01 for c in cheap), cheap)
    loc_cheap = [c for c in cheap if 44.0 <= c <= 99.0]
    check('location changes 50/55/60: one cheap refresh at most every THROTTLE seconds', len(loc_cheap) == 1 and loc_cheap[0] >= 40.0 + THROTTLE - 0.01, loc_cheap)


def scenario_pending():
    m = Model()
    m.at(0.0, m.register)
    m.at(SETTLE + 1.0, m.location_changed)   # lands while the load scan runs
    m.run(SETTLE + 60.0)
    after = [t for t, k, _ in m.log if k == 'cheap' and t > SETTLE]
    check('a refresh asked for while the full scan runs is run after it (A07 fixed)', bool(after), m.log)
    old = Model(fixed=False)
    old.at(0.0, old.conversation_started)
    old.at(10.0, old.location_changed)  # within the 30 s window: queued as pending update at 30.1
    old.at(35.0, old.conversation_started)  # the 44 s refresh started at 30.1 is still running: dropped
    old.run(200.0)
    check('the model sees the old defect: a request during the 44 s refresh was dropped', old.count('dropped') >= 1, old.log)
    check('the model sees the old cost: every talk start scanned all quests', old.count('full') >= 2, old.log)


def scenario_not_ready():
    """A talk before this save's first scan: the getters never run the scan inside the caller (an NPC_Added handler waited
    the whole scan), and the hood and "since we last met" lines are skipped instead of built from zero values."""
    src = lambda n: open(os.path.join(ROOT, 'Source', 'Scripts', n), encoding='utf-8').read()
    state = src('MLWW_State.psc')
    fresh = re.search(r'(?m)^Function EnsureFresh\(\).*?^EndFunction', state, re.S)
    check('EnsureFresh only asks for a scan (no forced Pump in the caller)', fresh is not None and 'Pump(' not in fresh.group(0)
          and 'Schedule()' in fresh.group(0))
    check('State.Ready says whether the first scan is done', re.search(r'bool Function Ready\(\)\s*EnsureFresh\(\)\s*Return cached', state) is not None)
    check('Recognition gives no hood line before the first scan', '!World.Ready()' in src('MLWW_Recognition.psc'))
    face = re.search(r'(?m)^bool Function FaceHidden\(\).*?^EndFunction', src('MLWW_Recognition.psc'), re.S)
    face = face.group(0) if face else ''
    # live test 18: a wig in the hair slot made every NPC see "the hooded stranger"
    check('a hair-slot piece hides the face only as a hood (ArmorHelmet or ClothingHead), never a wig',
          'IsWig(hair)' in face and '0x06C0EE' in face and '0x10CD11' in face and 'IsWig(head)' in face
          and 'Return head != None' not in face)
    meet = re.search(r'(?m)^Event OnNpcAdded\(.*?^EndEvent', src('MLWW_Meetings.psc'), re.S)
    check('Meetings stores no snapshot before the first scan', meet is not None
          and 0 <= meet.group(0).find('!World.Ready()') < meet.group(0).find('Changes('))

scenario_load()
scenario_batching()
scenario_timer()
scenario_talk_and_fight()
scenario_triggers()
scenario_pending()
scenario_not_ready()

print(f'{"FAILED" if checklib.fails else "OK"}: {checklib.fails} failure(s)')
sys.exit(1 if checklib.fails else 0)
