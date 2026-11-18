"""Offline checks for World's game events, no game needed: every event the SKSE plugin sends has a Papyrus handler,
every native it registers is declared, the fact texts hold no dates or feelings (the Hub adds the date), and:
  - every task the plugin queues captures handles, form ids or plain values, never a raw reference pointer, and every
    task that takes a handle or a reference checks it before use;
  - no sink (and nothing a sink calls in the event itself) sends a Papyrus event, logs or writes a file, and the
    worker-thread callbacks only queue tasks;
  - every StorageUtil key a World script writes is read with the same type somewhere (World or another module), and
    every key read is written; the JsonUtil files World writes and reads match their readers and writers;
  - fact keys are unique, only written by MLWW_Facts.Sync, and Sync runs when an NPC joins a conversation, so a fact
    the loaded save has no numbers for is removed then.

usage: py -3 test/check_events.py
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODING = os.path.dirname(ROOT)
CPP_PATH = os.path.join(ROOT, 'plugin', 'src', 'Personal.cpp')
CPP = open(CPP_PATH, encoding='utf-8').read()
SCRIPTS = os.path.join(ROOT, 'Source', 'Scripts')
PSC = {f: open(os.path.join(SCRIPTS, f), encoding='utf-8').read() for f in os.listdir(SCRIPTS) if f.endswith('.psc')}
FACTS = PSC['MLWW_Facts.psc']
DATA = os.path.join(ROOT, 'SKSE', 'Plugins', 'StorageUtilData', 'MantellaLivingWorld')
fails = 0
warns = 0


def check(name, ok, detail=''):
    global fails
    print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else f': {detail}'))
    fails += not ok


def warn(name, detail):
    global warns
    print(f'WARN {name}: {detail}')
    warns += 1


handled = set(re.findall(r'RegisterForModEvent\("([^"]+)"', ''.join(PSC.values())))
sent = {e for call in re.findall(r'SendModEvent\(([^;]*)', CPP) for e in re.findall(r'"(MLWW_\w+)"', call)}
for event in sorted(sent):
    check(f'plugin event {event} has a handler', event in handled)

declared = set(re.findall(r'Function\s+(\w+)\([^)]*\)\s+global\s+native', PSC['MLWW_Native.psc'], re.I))
for name in re.findall(r'RegisterFunction\("(\w+)",\s*"MLWW_Native"', CPP):
    check(f'native {name} declared in MLWW_Native.psc', name in declared)

keys = re.findall(r'Put\(path, "([^"]+)"', FACTS)
check('fact keys start with fact_ and are unique', keys and all(k.startswith('fact_') for k in keys) and len(set(keys)) == len(keys), keys)

# Text pieces only: comments and the StorageUtil key names are not sent.
code = '\n'.join(line.split(';')[0] for line in FACTS.splitlines())
texts = [t for t in re.findall(r'"([^"]*)"', code) if not t.startswith(('MLWW_', 'fact_', 'MLW_', 'MantellaLivingWorld/'))]
banned = re.compile(r'\b(today|tonight|yesterday|tomorrow|ago|recently|lately|earlier|just now|soon|this (morning|week|month|year)|last '
                    r'(night|week|month|year)|grateful|thankful|angry|upset|proud|owes?|trusts?|loves?|hates?|feels?|felt|should|must|'
                    r'happy|sad|glad|sorry|afraid|scared|fond|resents?|admires?|respects?|deserves?|hero|betray\w*|loyal)\b', re.I)
hits = [t for t in texts if banned.search(t)]
check(f'{len(texts)} fact text pieces hold no relative date or feeling', not hits, hits)

# The value Put writes must be what the Hub parses ("day|expires|priority|text").
check('fact value is day|-1|priority|text', 'aiDay + "|-1|" + aiPriority + "|" + asText' in FACTS)
for key, priority in re.findall(r'Put\(path, "(fact_\w+)", [^,]+(?:\([^)]*\))?, ([0-9]),', FACTS):
    check(f'{key} priority 1-3', 1 <= int(priority) <= 3)


# ---------------------------------------------------------------------------------------------------------------------
# C++: what the queued tasks capture, and what runs in the event itself
# ---------------------------------------------------------------------------------------------------------------------

def strip_comments(src):
    return re.sub(r'//[^\n]*', lambda m: ' ' * len(m.group()), src)


SRC = strip_comments(CPP)


def match(src, i, open_ch, close_ch):
    """Index of the bracket closing the one at src[i]."""
    depth = 0
    in_str = None
    j = i
    while j < len(src):
        c = src[j]
        if in_str:
            if c == '\\':
                j += 1
            elif c == in_str:
                in_str = None
        elif c in '"\'':
            in_str = c
        elif c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return j
        j += 1
    raise ValueError(f'unbalanced {open_ch} at {i}')


def line_of(i):
    return SRC.count('\n', 0, i) + 1


# Functions: name -> (params, body start, body end)
FUNCS = {}
for m in re.finditer(r'\n\t*(?:template <[^>]*>\s*)?(?:[\w:<>\*&]+[ \t]+)+(\w+)\(([^;{}()]*(?:\([^)]*\)[^;{}()]*)*)\)\s*(?:const\s*)?\{', SRC):
    name = m.group(1)
    if name in ('if', 'for', 'while', 'switch', 'return'):
        continue
    start = m.end() - 1
    FUNCS.setdefault(name, (m.group(2), start, match(SRC, start, '{', '}')))

QUEUE_CALLS = ('Task', 'AddTask', 'RunLater')


def lambdas_in(a, b):
    """(kind, capture list, body start, body end, at) of every lambda passed to Task / AddTask / RunLater in SRC[a:b]."""
    out = []
    for m in re.finditer(r'\b(Task|AddTask|RunLater)\(', SRC[a:b]):
        at = a + m.end() - 1
        end = match(SRC, at, '(', ')')
        lb = SRC.find('[', at, end)
        if lb < 0:
            continue
        rb = match(SRC, lb, '[', ']')
        body = SRC.find('{', rb, end)
        if body < 0:
            continue
        out.append((m.group(1), SRC[lb + 1:rb], body, match(SRC, body, '{', '}'), at))
    return out


def without_lambdas(a, b):
    """SRC[a:b] with the bodies of queued lambdas blanked out: what runs right here."""
    text = list(SRC[a:b])
    for _, _, s, e, _ in lambdas_in(a, b):
        for i in range(s - a, min(e - a + 1, len(text))):
            if 0 <= i < len(text) and text[i] != '\n':
                text[i] = ' '
    return ''.join(text)


def enclosing(i):
    best = None
    for name, (_, s, e) in FUNCS.items():
        if s <= i <= e and (best is None or s > FUNCS[best][1]):
            best = name
    return best


def split_captures(caps):
    parts, depth, cur = [], 0, ''
    for c in caps:
        if c in '([{':
            depth += 1
        elif c in ')]}':
            depth -= 1
        if c == ',' and depth == 0:
            parts.append(cur.strip())
            cur = ''
        else:
            cur += c
    if cur.strip():
        parts.append(cur.strip())
    return parts


# Event fields, from CommonLibSSE-NG's headers: NiPointer keeps the reference alive, FormID / handle are looked up again.
EVENT_FIELDS = {}
for header in glob.glob(os.path.join(ROOT, 'plugin', 'lib', 'commonlibsse-ng', 'include', 'RE', '*', '*Event.h')):
    for typ, field in re.findall(r'^\s+((?:RE::)?(?:NiPointer<\w+>|FormID|std::u?int\d+_t|ObjectRefHandle|ActorHandle|bool|float|BSFixedString))\s+(\w+);', open(header, encoding='utf-8', errors='ignore').read(), re.M):
        EVENT_FIELDS.setdefault(field, set()).add(typ)
SAFE_TYPE = re.compile(r'NiPointer|FormID|int\d+_t|Handle|bool|float|std::string|BSFixedString|time_point|uint32_t')
RAW_REF = re.compile(r'\b(?:RE::)?(Actor|TESObjectREFR|PlayerCharacter|Character)\s*\*')


def capture_kind(name, expr, func_src):
    """'handle', 'id', 'value', 'nipointer', 'base-form' or 'raw:<why>' for one capture."""
    if expr is None:  # captured by name: find its declaration in the enclosing function
        if name in ('=', '&', 'this'):
            return 'value'  # [=] inside a worker callback: copies the outer lambda's captures, checked there
        decl = re.search(r'([\w:<>\*&]+(?:\s*\*)?)\s+' + re.escape(name) + r'\s*[=({;]', func_src)
        typ = decl.group(1) if decl else ''
        if RAW_REF.search(typ + ' *' if typ.endswith('*') else typ):
            return f'raw:{typ} {name}'
        if 'TESForm*' in typ.replace(' ', '') or typ == 'auto*':
            init = re.search(re.escape(name) + r'\s*=\s*([^;]+);', func_src)
            if init and 'OwnerOfTake' in init.group(1) and re.search(r'Is\(RE::FormType::NPC\)\s*\?\s*owner', SRC):
                return 'base-form'  # OwnerOfTake returns only NPC base forms, which are never unloaded
            return f'raw:{typ} {name}'
        return 'value'
    expr = expr.strip()
    if name == 'fn' and expr == 'std::forward<F>(a_fn)':
        return 'value'  # Task() wrapping the caller's lambda, whose own captures are checked where it is written
    if re.search(r'->GetHandle\(\)$|Handle\(\)$', expr):
        return 'handle'
    if re.search(r'GetFormID\(\)$', expr):
        return 'id'
    field = re.fullmatch(r'(?:e|a_event)\.(\w+)', expr)
    if field:
        types = EVENT_FIELDS.get(field.group(1), set())
        return 'nipointer' if any('NiPointer' in t for t in types) else 'id' if types and all(SAFE_TYPE.search(t) for t in types) else f'raw:event field {expr}'
    if re.fullmatch(r'Health\(.*\)|\w+->IsHostileToActor\(.*\)|Clock::now\(\)|g_epoch\.load\(\)|e\.\w+|a_\w+|\w+', expr) and not RAW_REF.search(expr):
        if re.fullmatch(r'\w+', expr):
            return capture_kind(expr, None, func_src)
        return 'value'
    return f'raw:{expr}'


task_count = 0
raw = []
for kind, caps, s, e, at in lambdas_in(0, len(SRC)):
    func = enclosing(at)
    fsrc = SRC[FUNCS[func][1]:FUNCS[func][2]] if func else SRC
    for cap in split_captures(caps):
        name, _, expr = cap.partition('=')
        if not cap or cap in ('=', '&'):
            continue
        k = capture_kind(name.strip(), expr if _ else None, fsrc)
        task_count += 1
        if k.startswith('raw'):
            raw.append(f'line {line_of(at)} {kind}: {cap} ({k})')
check(f'{task_count} captures of queued tasks are handles, form ids, NiPointers or values', not raw, raw)

# Every task target that takes a handle or a reference checks it before using it.
unchecked = []
for name, (params, s, e) in FUNCS.items():
    body = SRC[s:e]
    for typ, p in re.findall(r'(RE::ActorHandle|RE::NiPointer<[^>]+>|RE::ObjectRefHandle)\s+(\w+)', params):
        if 'Handle' in typ:
            ok = re.search(re.escape(p) + r'\.get\(\)', body) and re.search(r'if \(!\w+|if \(auto \w+ = ' + re.escape(p) + r'\.get\(\)|\w+ \? |&& \w+', body)
        else:  # LiveActor() returns nullptr for a null reference
            ok = re.search(re.escape(p) + r' \?|!' + re.escape(p) + r'\b|' + re.escape(p) + r' &&|LiveActor\(' + re.escape(p) + r'\.get\(\)\)', body)
        if not ok:
            unchecked.append(f'{name}({p})')
for kind, caps, s, e, at in lambdas_in(0, len(SRC)):
    body = SRC[s:e]
    captured = {c.partition('=')[0].strip() for c in split_captures(caps)}
    for h in [h for h in re.findall(r'(\w+)\.get\(\)', body) if h in captured]:
        if not re.search(r'if \((?:auto \w+ = )?!?\w*' + re.escape(h) + r'|if \(!\w+\)|if \(auto \w+ = ' + re.escape(h), body):
            unchecked.append(f'lambda at line {line_of(at)} ({h})')
check('every task checks its handles and references before use', not unchecked, unchecked)

# Globals must not keep raw reference pointers across frames.
globals_raw = [l.strip() for l in SRC.splitlines() if re.match(r'\s*(?:std::\w+<[^;]*>|[\w:]+\*?)\s+g_\w+', l) and RAW_REF.search(l)]
check('no global keeps a raw reference pointer', not globals_raw, globals_raw)

# What runs in the event itself: each sink and everything it calls outside queued lambdas.
FORBIDDEN = re.compile(r'\bSendModEvent\(|->SendEvent\(|Dispatch(?:Static|Method)Call|\blogger::|ofstream|Writer::Push|JsonUtil|WriteFile')
roots = []
reg = FUNCS['Register']
for m in re.finditer(r'static Sink<RE::(\w+)>\s+\w+\(', SRC[reg[1]:reg[2]]):
    at = reg[1] + m.end() - 1
    end = match(SRC, at, '(', ')')
    roots.append((m.group(1), at, end))


def called(text):
    return {c for c in re.findall(r'\b(\w+)\s*\(', text) if c in FUNCS and c not in QUEUE_CALLS}


bad_sinks, sink_funcs = [], set()
for event, a, b in roots:
    seen, todo = set(), [(f'Sink<{event}>', without_lambdas(a, b))]
    while todo:
        where, text = todo.pop()
        for hit in FORBIDDEN.findall(text):
            bad_sinks.append(f'{event} via {where}: {hit}')
        for fn in called(text) - seen:
            seen.add(fn)
            todo.append((fn, without_lambdas(FUNCS[fn][1], FUNCS[fn][2])))
    sink_funcs |= seen
check(f'{len(roots)} sinks ({len(sink_funcs)} functions run in the event) send no Papyrus event, log or write files', not bad_sinks, bad_sinks)

# Worker-thread callbacks (RunLater) must only queue main-thread tasks.
worker_bad = []
for kind, caps, s, e, at in lambdas_in(0, len(SRC)):
    if kind != 'RunLater':
        continue
    here = without_lambdas(s, e)
    for c in set(re.findall(r'\b(\w+)\s*\(', here)) - {'Task', 'AddTask', 'GetTaskInterface', 'PollCrime'}:
        worker_bad.append(f'line {line_of(at)}: {c}()')
check('worker-thread callbacks only queue tasks', not worker_bad, worker_bad)

# ResetFight forgets every piece of fight, crime and barter state the poll and the tasks keep.
reset = SRC[FUNCS['ResetFight'][1]:FUNCS['ResetFight'][2]]
# Not per-game: the crime factions and the quest index (editor id -> quest) are found once at kDataLoaded, and the
# outcome table's quests are the same in every save (MLWW_State hands them over again on each full scan).
state = set(re.findall(r'^\s*(?:std::[\w:]+<[^;]*>|[\w:]+)\s+(g_\w+)', SRC, re.M)) - {'g_crimeFactions', 'g_epoch', 'g_questsById', 'g_outcomeQuests'}
# Set before every use, behind a guard that ResetFight clears: g_barterGold whenever g_barterTarget is set (barter menu
# open), g_fightStart and g_lastCombat whenever g_inFight turns true.
GUARDED = {'g_barterGold': 'g_barterTarget', 'g_fightStart': 'g_inFight', 'g_lastCombat': 'g_inFight'}
missing = []
for g in sorted(state):
    if g in reset:
        continue
    guard = GUARDED.get(g)
    set_near = guard and re.search(re.escape(guard) + r'\s*=[^;]*;(?:[^;]*;){0,3}?[\s}]*' + re.escape(g) + r'\s*=', SRC)
    if not (guard and guard in reset and set_near):
        missing.append(g)
check(f'ResetFight resets all {len(state)} pieces of per-game state (or their guard) and raises the epoch', not missing and '++g_epoch' in reset, missing)


# ---------------------------------------------------------------------------------------------------------------------
# StorageUtil and JsonUtil keys
# ---------------------------------------------------------------------------------------------------------------------

def papyrus_code(text):
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


def props(text):
    return dict(re.findall(r'string Property (\w+) = "([^"]*)" AutoReadOnly', text))


def args_of(text, at):
    end = match(text, at, '(', ')')
    return split_captures(text[at + 1:end])


WRITE_OPS = re.compile(r'^(Set|Adjust|Unset|Pluck|Clear|Add|Insert|RemoveAt|Remove|Resize|Copy|Shift|Pop|Sort)')
FAMILY = re.compile(r'(Int|Float|String|Form)(Value|List)')


def storage_uses(files, module):
    """(module, file, op, family, key or prefix*, line) of every StorageUtil call with a key we can name."""
    uses = []
    for fname, text in files.items():
        code = papyrus_code(text)
        p = props(text)
        funcs = list(re.finditer(r'(?im)^\s*(?:\w+(?:\[\])?\s+)?Function\s+(\w+)\(([^)]*)\)', code))
        for m in re.finditer(r'StorageUtil\.(\w+)\(', code):
            fn = m.group(1)
            fam = FAMILY.search(fn)
            if not fam:
                continue
            args = args_of(code, m.end() - 1)
            if len(args) < 2:
                continue
            key = args[1].strip()
            line = code.count('\n', 0, m.start()) + 1
            op = 'write' if WRITE_OPS.search(fn.replace(fam.group(0), '')) else 'read'
            family = fam.group(1) + ('List' if fam.group(2) == 'List' else '')
            enc = [f for f in funcs if f.start() < m.start()]
            func = enc[-1] if enc else None
            resolved = resolve_key(key, p, code[func.start() if func else 0:m.start()], func, files, fname)
            for k in resolved:
                uses.append((module, fname, op, family, k, line))
    return uses


def resolve_key(key, p, before, func, files, fname):
    lit = re.fullmatch(r'"([^"]*)"', key)
    if lit:
        return [lit.group(1)]
    if key in p:
        return [p[key]]
    concat = re.fullmatch(r'(\w+|"[^"]*")\s*\+\s*.+', key)
    if concat:
        head = concat.group(1)
        return [(p.get(head) or head.strip('"')) + '*']
    local = re.findall(r'string\s+' + re.escape(key) + r'\s*=\s*([^\n]+)', before)
    if local:
        return resolve_key(local[-1].strip(), p, '', None, files, fname)
    if func is not None:  # a parameter: the keys every caller passes
        params = [x.split()[-1] for x in func.group(2).split(',') if x.strip()]
        params = [x.split('=')[0].strip() for x in func.group(2).split(',') if x.strip()]
        names = [x.split()[-1] for x in params]
        if key in names:
            idx = names.index(key)
            out = []
            script = fname[:-4]
            for other, text in files.items():
                code = papyrus_code(text)
                pat = (re.escape(script) + r'\.' if other != fname else r'(?<!Function )(?<![\w.])(?:' + re.escape(script) + r'\.)?') + re.escape(func.group(1)) + r'\('
                for c in re.finditer(pat, code):
                    a = args_of(code, c.end() - 1)
                    if idx < len(a):
                        out += resolve_key(a[idx].strip(), {**props(text)}, code[:c.start()], None, files, other)
            return out or [f'?{key}']
    return [f'?{key}']


world_uses = storage_uses(PSC, 'World')
other = {}
for path in glob.glob(os.path.join(CODING, 'Mantella-Living-World-*', 'Source', 'Scripts', '*.psc')):
    if os.sep + 'Mantella-Living-World-World' + os.sep not in path:
        other[os.path.basename(path)] = open(path, encoding='utf-8', errors='ignore').read()
other_uses = [u for u in storage_uses(other, 'other') if u[4].startswith('MLWW_')]
unresolved = sorted({f'{u[1]}:{u[5]} {u[4]}' for u in world_uses if u[4].startswith('?')})
check('every StorageUtil key in World scripts resolves to a name', not unresolved, unresolved)


def key_match(a, b):
    return a == b or (a.endswith('*') and b.startswith(a[:-1])) or (b.endswith('*') and a.startswith(b[:-1]))


own = [u for u in world_uses if not u[4].startswith('?') and u[4].startswith('MLWW_')]
alone, unread, mixed = [], [], []
for op, need in (('write', 'read'), ('read', 'write')):
    for u in own:
        if u[2] != op:
            continue
        partners = [v for v in own + other_uses if v[2] == need and key_match(u[4], v[4])]
        if not partners:
            (unread if op == 'write' else alone).append(f'{u[4]} ({u[3]}) {op} in {u[1]}:{u[5]}, never {need}')
        elif not any(v[3] == u[3] for v in partners):
            mixed.append(f'{u[4]}: {u[3]} {op} in {u[1]}:{u[5]}, {need} as ' + '/'.join(sorted({v[3] for v in partners})))
check(f'{len({u[4] for u in own})} StorageUtil keys: each one read is written', not alone, sorted(set(alone)))
for u in sorted({x.split(' in ')[0] for x in unread}):
    warn('StorageUtil key written but never read by any module', u)
check('StorageUtil writers and readers agree on the type', not mixed, sorted(set(mixed)))
outside = [u for u in other_uses if u[2] == 'read' and not any(v[2] == 'write' and key_match(v[4], u[4]) and v[3] == u[3] for v in own)]
check(f'{len(other_uses)} uses of World keys in other modules match what World writes', not outside, outside)

# JsonUtil: the facts (World -> the Hub), world.json (World -> the Hub and Knowledge), quest_outcomes.json (the table
# in this repo -> MLWW_State), knowledge_quests.json (Knowledge -> MLWW_State).
hub_state = open(os.path.join(CODING, 'Mantella-Living-World-Hub', 'server', 'living_world', 'lw_state.py'), encoding='utf-8').read()
check('the Hub reads every fact_ key as day|expires|priority|text',
      "startswith('fact_')" in hub_state and "split('|', 3)" in hub_state and 'len(parts) != 4' in hub_state)
other_fact_writes = [f'{f}:{code.count(chr(10), 0, m.start()) + 1}' for f, text in PSC.items()
                     for code in [papyrus_code(text)] for m in re.finditer(r'JsonUtil\.\w+\([^,]+,\s*"fact_', code)]
check('no World script writes a fact_ key except through MLWW_Facts.Put', not other_fact_writes, other_fact_writes)

state = papyrus_code(PSC['MLWW_State.psc'])
written = set(re.findall(r'JsonUtil\.Set(?:Raw)?Path\w*\(WORLD_FILE, "\.(\w+)"', state))
readers = {}
for path in [os.path.join(CODING, 'Mantella-Living-World-Hub', 'server', 'living_world', 'world_note.py'),
             os.path.join(CODING, 'Mantella-Living-World-Hub', 'server', 'living_world', 'lw_state.py')] + \
        glob.glob(os.path.join(CODING, 'Mantella-Living-World-Knowledge', 'server', '**', '*.py'), recursive=True):
    text = open(path, encoding='utf-8').read()
    for k in re.findall(r'\b(?:world|data)(?:\(\))?\.get\(["\'](\w+)', text):  # Knowledge's hookup names it data
        readers.setdefault(k, set()).add(os.path.relpath(path, CODING))
unread = sorted(written - set(readers) - {'version', 'day', 'mq_stage', 'guilds', 'thane', 'war_side', 'hold'})  # hold: the Hub dropped its fallback to it (EXP-9)
check(f'world.json: {len(written)} keys written, each read by the Hub or Knowledge (or kept for reports)', not unread, unread)
for k in sorted(set(readers) - written):
    warn('world.json key read but never written by World', f'"{k}" read in {", ".join(sorted(readers[k]))}')

rows = json.load(open(os.path.join(DATA, 'quest_outcomes.json'), encoding='utf-8'))['rows']
present = set()


def walk(o, path):
    if isinstance(o, dict):
        for k, v in o.items():
            present.add(path + '.' + k)
            walk(v, path + '.' + k)
    elif isinstance(o, list):
        for x in o:
            walk(x, path + '[]')


for r in rows:
    walk(r, '')
top = set(json.load(open(os.path.join(DATA, 'quest_outcomes.json'), encoding='utf-8')))
read_paths = set()
for m in re.finditer(r'JsonUtil\.(?:GetPath\w+|PathStringElements|PathCount|CanResolvePath)\(OUTCOMES,\s*([^)]*?)\)', state):
    expr = m.group(1)
    tail = ''.join(re.findall(r'"(\.[\w.]+)"', expr))
    if re.fullmatch(r'"\.(\w+)"', expr.strip()):
        if tail[1:] not in top:
            read_paths.add('top-level ' + tail)
    elif 'row' in expr:
        read_paths.add(tail)
    elif 'when' in expr or 'asPath' in expr:
        read_paths.add('.when' + tail)
        read_paths.add('.when.of[]' + tail)
cond = re.search(r'bool Function Condition\(string asPath.*?EndFunction', state, re.S).group(0)
cond_paths = set(re.findall(r'asPath \+ "(\.\w+)"', cond))
missing = sorted(p for p in read_paths if p.startswith('.') and p not in present and not p.startswith('.when'))
missing += sorted(f'.when{p} / .when.of[]{p}' for p in cond_paths if f'.when{p}' not in present and f'.when.of[]{p}' not in present)
check(f'quest_outcomes.json ({len(rows)} rows) has every path MLWW_State reads', not missing, missing)

kq = os.path.join(CODING, 'Mantella-Living-World-Knowledge', 'SKSE', 'Plugins', 'StorageUtilData', 'MantellaLivingWorld', 'knowledge_quests.json')
if os.path.isfile(kq):
    data = json.load(open(kq, encoding='utf-8'))
    ok = isinstance(data.get('stringList', {}).get('quests'), list)
    check('knowledge_quests.json holds the "quests" string list MLWW_State.ReadAllQuests reads', ok and 'JsonUtil.StringListToArray(QUESTS_WANTED, "quests")' in state)
else:
    warn('knowledge_quests.json', 'Knowledge not checked out next to World; reader not checked')

# Fact keys are cleared at join: every Put is inside Sync, Put removes a fact with no text, and joining runs Sync.
sync = re.search(r'Function Sync\(Actor akNpc\) global.*?EndFunction', FACTS, re.S).group(0)
check('every fact is written by MLWW_Facts.Sync', len(re.findall(r'Put\(path, "fact_', FACTS)) == len(re.findall(r'Put\(path, "fact_', sync)))
check('Put removes a fact whose text is empty', re.search(r'If value == ""\s+JsonUtil\.UnsetStringValue\(asPath, asKey\)', FACTS) is not None)
added = re.search(r'Event OnNpcAdded\(Form akActor\).*?EndEvent', PSC['MLWW_Personal.psc'], re.S).group(0)
check('joining a conversation runs Sync before the line is sent', added.find('MLWW_Facts.Sync(npc)') >= 0 and
      added.find('MLWW_Facts.Sync(npc)') < added.find('MLWW_Util.Send('))

# Harm to a Thalmor: words only. Witnesses and the report line name it; nothing touches bounties or crime gold.
UTIL_SRC, PERSONAL, CRIME_SRC = PSC['MLWW_Util.psc'], PSC['MLWW_Personal.psc'], PSC['MLWW_Crime.psc']
clause = re.search(r'string Function ThalmorClause\(.*?EndFunction', UTIL_SRC, re.S)
check('ThalmorFaction is 0x039F26, the Legion CWImperialFaction 0x02BF9A, the big cities LocTypeCity 0x013168',
      'GetFormFromFile(0x039F26, "Skyrim.esm") as Faction' in UTIL_SRC and 'GetFormFromFile(0x02BF9A, "Skyrim.esm") as Faction' in UTIL_SRC
      and 'GetFormFromFile(0x013168, "Skyrim.esm") as Keyword' in UTIL_SRC)
check('"folk here do not much care" only outside the big cities and Thalmor or Legion company', clause is not None
      and 'InCity(Game.GetPlayer().GetCurrentLocation()) || SidesWithThalmor(akNpc)' in clause.group(0)
      and 'If SidesWithThalmor(talk.GetActorInConversationByIndex(i))' in clause.group(0))
thalmor_code = clause.group(0) if clause else ''
for name in ('SawThalmor', 'ThalmorVictim'):
    m = re.search(r'Function ' + name + r'\(.*?EndFunction', PERSONAL + CRIME_SRC, re.S)
    thalmor_code += m.group(0) if m else ''
    check(f'{name} exists', m is not None)
check('the Thalmor code never changes crime gold', not re.search(r'CrimeGold|PayCrimeGold|SendAssaultAlarm|SendTrespassAlarm', thalmor_code))
check('murder and attack on a Thalmor tell the people close by', 'SawThalmor(akSender as Actor, true)' in PERSONAL and 'SawThalmor(akSender as Actor, false)' in PERSONAL)
check('a witness line names the Thalmor with the clause', 'MLWW_Util.ThalmorClause(akNpc)' in PERSONAL)
check('the report line names a Thalmor victim with the clause', 'MLWW_Util.ThalmorClause(akSpeaker)' in CRIME_SRC
      and 'If ThalmorVictim(asCrime, akSpeaker, akConversation)' in CRIME_SRC)
line_fn = re.search(r'string Function Line\(Actor akNpc\).*?EndFunction', PERSONAL, re.S).group(0)
slots = int(re.search(r'new string\[(\d+)\]', line_fn).group(1))
check(f'the line array has room for every item ({slots})', slots >= line_fn.count('n += 1'), line_fn.count('n += 1'))

# Live test 8: battles.json recorded the player harming his own follower with drain and slow magic he never cast (an
# aura, ability or enchantment he carries). The fight record keeps harmful magic only from a real cast: the active
# effect's spell is no ability, constant effect, enchantment, disease or addiction, and came from a hand or the voice.
BATTLE = open(os.path.join(ROOT, 'plugin', 'src', 'Battle.cpp'), encoding='utf-8').read()
is_cast = re.search(r'bool IsCast\(const RE::ActiveEffect& a_active\).*?\n\t\t}\n', BATTLE, re.S)
is_cast = is_cast.group(0) if is_cast else ''
check('Battle: IsCast turns away abilities, enchantments, diseases, addictions, constant effects and instant casts',
      all(t in is_cast for t in ('Type::kAbility', 'Type::kEnchantment', 'Type::kDisease', 'Type::kAddiction',
                                 'CastingType::kConstantEffect', 'CastingSource::kInstant', 'GetSpellType()')), is_cast[:200])
from_cast = re.search(r'bool FromCast\(.*?\n\t\t}\n', BATTLE, re.S)
from_cast = from_cast.group(0) if from_cast else ''
check("Battle: FromCast reads the target's active effects of that effect and that caster",
      'GetActiveEffectList()' in from_cast and 'active->GetBaseObject() != a_effect' in from_cast
      and 'active->caster.get().get() != a_caster' in from_cast and 'IsCast(*active)' in from_cast, from_cast[:200])
magic_task = re.search(r'void OnMagicTask\(.*?\n\t\t}\n', BATTLE, re.S)
magic_task = magic_task.group(0) if magic_task else ''
check('Battle: harmful magic is recorded only when FromCast says it was cast (helping magic as before)',
      '(harmful && !FromCast(target.get(), caster.get(), effect))' in magic_task
      and magic_task.find('FromCast') < magic_task.find('AddOnce(ft->harm[kind]'), magic_task[:200])

# B03: only fights read back from battles.json had a "player" tag; a fight recorded this session had none, passed
# Prune's default (the current player) and went on into another character's game loaded without a restart. ToJson
# now writes the player with every fight.
to_json = re.search(r'nlohmann::json ToJson\(double a_end\).*?\n\t\t}\n', BATTLE, re.S)
to_json = to_json.group(0) if to_json else ''
prune_fn = re.search(r'void Prune\(\).*?\n\t\t}\n', BATTLE, re.S)
prune_fn = prune_fn.group(0) if prune_fn else ''
check('Battle: every fight ToJson writes carries the player whose game it is from', '{ "player", PlayerName() }' in to_json, to_json[:300])
check('Battle: Prune drops fights of another player (an untagged fight counts as this player\'s)',
      'a_fight.value("player", player) != player' in prune_fn, prune_fn[:300])


def port_prune(fights, player, today):
    """Battle.cpp Prune on plain values."""
    return [f for f in fights if not (f.get('end', 0.0) > today + 0.001 or f.get('player', player) != player)]


ended = {'id': '1', 'end': 3.0, 'player': 'Player'}  # as End() now stores it (ToJson)
check('Battle rule: a fight of this session is dropped when another character is loaded', port_prune([ended], 'Jenassa', 4.0) == [])
check('Battle rule: and kept for the same character', port_prune([ended], 'Player', 4.0) == [ended])
check('Battle rule: a fight from after the loaded save is dropped', port_prune([ended], 'Player', 2.0) == [])


def port_is_cast(spell_type, casting_type, source):
    """Battle.cpp IsCast on plain values."""
    if spell_type in ('ability', 'enchantment', 'disease', 'addiction') or casting_type == 'constant':
        return False
    return source != 'instant'


for name, args, want in (("the player's Slow spell from his hand", ('spell', 'fire_and_forget', 'right'), True),
                         ('a shout (voice)', ('voice', 'fire_and_forget', 'other'), True),
                         ('a staff', ('staff', 'fire_and_forget', 'right'), True),
                         ('a slow aura from an ability he carries', ('ability', 'constant', 'instant'), False),
                         ('a drain from an enchanted armour', ('enchantment', 'constant', 'instant'), False),
                         ("a cloak's spell applied to those near him", ('spell', 'fire_and_forget', 'instant'), False),
                         ('a weapon enchantment on a hit', ('enchantment', 'fire_and_forget', 'right'), False)):
    check(f'Battle rule: {name} -> {"recorded" if want else "not his cast"}', port_is_cast(*args) == want)

# Live test 9: with the new DLL, battles.json still put drain and slow from the player on Jenassa and the wolf. FromCast
# counts an effect with no active effect left (an instant one, or one its conditions kept off) as a cast, so a perk or
# passive on the player still got through. The player's harmful magic now needs a cast of a spell carrying that effect
# (TESSpellCastEvent from the player) within a few seconds.
PERSONAL = open(os.path.join(ROOT, 'plugin', 'src', 'Personal.cpp'), encoding='utf-8').read()
player_cast = re.search(r'bool PlayerCast\(.*?\n\t\t}\n', BATTLE, re.S)
player_cast = player_cast.group(0) if player_cast else ''
cast_fn = re.search(r'\tvoid Cast\(const RE::TESSpellCastEvent& a_event\).*?\n\t}\n', BATTLE, re.S)
cast_fn = cast_fn.group(0) if cast_fn else ''
reset_fn = re.search(r'void Reset\(bool a_forget\).*?\n\t}', BATTLE, re.S)
check("Battle: the player's casts are sunk and kept (only the player's, a short capped list, cleared on load)",
      'holder->AddEventSink<RE::TESSpellCastEvent>(&cast)' in PERSONAL and 'Battle::Cast(e)' in PERSONAL
      and 'who != Player()' in cast_fn and 'g_playerCasts.emplace_back' in cast_fn and 'kMaxCasts' in cast_fn
      and bool(reset_fn) and 'g_playerCasts.clear();' in reset_fn.group(0))
check("Battle: PlayerCast matches the effect among the cast spell's effects within the window and keeps it fresh",
      'kCastWindow' in player_cast and 'a_e->baseEffect == a_effect' in player_cast and 'at = a_now' in player_cast
      and 'LookupByID<RE::MagicItem>' in player_cast)
check("Battle: the player's harmful magic is recorded only after PlayerCast (before Join and AddOnce)",
      '(harmful && caster->IsPlayerRef() && !PlayerCast(effect, now))' in magic_task
      and -1 < magic_task.find('PlayerCast') < magic_task.find('Join(caster.get()') < magic_task.find('AddOnce(ft->harm[kind]'))


def port_player_cast(casts, effect, now, window=5.0):
    """Battle.cpp PlayerCast on plain values: casts [[effects, time]]; a match refreshes the time."""
    casts[:] = [c for c in casts if now - c[1] <= window]
    for c in casts:
        if effect in c[0]:
            c[1] = now
            return True
    return False


casts = [[{'slow', 'frost'}, 10.0]]
check('Battle rule: an effect of a spell he just cast -> recorded', port_player_cast(casts, 'slow', 12.0))
check('Battle rule: a drain no cast of his carries (a perk, a passive) -> not his', not port_player_cast(casts, 'drain', 12.0))
check('Battle rule: a held concentration spell stays his past the window (each hit refreshes it)',
      port_player_cast(casts, 'frost', 16.0) and port_player_cast(casts, 'frost', 20.5))
check('Battle rule: long after the cast -> not his', not port_player_cast(casts, 'frost', 40.0))

# Live test 10: the player was put down for 23 damage and as the killer in three fights he never joined (a cloak or aura
# on him hits with the player as the cause, and the game gives him the kill). A hit of his counts only as a real attack:
# a weapon source (fists included), a spell carrying an effect of a cast of his (PlayerCast), or, with no source, a melee
# swing under way; a passive hit is no blow, no blame and no fight. A kill the game gives the player himself is his only
# after a real attack on that victim (or a real blow seen just after a one-shot death); else the killer stays unknown.
hit_task = re.search(r'void OnHitTask\(.*?\n\t\t}\n', BATTLE, re.S)
hit_task = hit_task.group(0) if hit_task else ''
death_task = re.search(r'void OnDeathTask\(.*?\n\t\t}\n', BATTLE, re.S)
death_task = death_task.group(0) if death_task else ''
player_blow = re.search(r'bool PlayerBlow\(RE::FormID a_source, bool a_swinging, Clock::time_point a_now\)\n\t\t{.*?\n\t\t}\n', BATTLE, re.S)
player_blow = player_blow.group(0) if player_blow else ''
hit_fn = re.search(r'\tvoid Hit\(const RE::TESHitEvent& a_event\).*?\n\t}\n', BATTLE, re.S)
hit_fn = hit_fn.group(0) if hit_fn else ''
check("Battle: PlayerBlow takes a weapon source, a spell with an effect of the player's cast, or a swing when no source",
      'form->Is(RE::FormType::Weapon)' in player_blow and 'PlayerCast(a_e->baseEffect, a_now)' in player_blow
      and 'return a_swinging;' in player_blow, player_blow[:200])
check("Battle: a hit of the player's that PlayerBlow turns away is dropped before any fighter, blow or blame is set",
      '(byPlayer && !PlayerBlow(a_source, a_swinging, Clock::now()))' in hit_task
      and -1 < hit_task.find('PlayerBlow') < hit_task.find('Begin()') < hit_task.find('ft->lastHitter = fc->id')
      and 'ft->byPlayer = true' in hit_task, hit_task[:300])
check("Battle: the hit sink passes the source and the player's swing, and notes a player's blow on someone already dead",
      'a_event.source' in hit_fn and 'GetAttackState()' in hit_fn and 'NotePlayerBlow(' in hit_fn
      and 'OnHitTask(targetHandle, causeHandle, source, swinging)' in hit_fn, hit_fn[:300])
check("Battle: a kill given to the player needs PlayerStruck, is looked at again once, then has no killer",
      'killer->IsPlayerRef()' in death_task and '!PlayerStruck(victim->GetFormID(), known, Clock::now())' in death_task
      and 'Writer::RunLater(kRecheck' in death_task and 'killer = nullptr;' in death_task
      and death_task.find('killer = nullptr;') < death_task.find('RE::NiPointer<RE::Actor> credit'), death_task[:300])
check("Battle: the player's real harmful cast marks the victim (passed PlayerCast), the JSON says who struck",
      'ft->byPlayer = true;  // passed PlayerCast' in magic_task and magic_task.find('PlayerCast(effect, now)') < magic_task.find('ft->byPlayer = true')
      and '{ "struck", f.struck ? 1 : 0 }' in BATTLE and 'g_playerBlows.clear();' in (reset_fn.group(0) if reset_fn else ''))


def port_player_blow(source, swinging, casts, now):
    """Battle.cpp PlayerBlow on plain values: source ('weapon', ('spell', effects), None)."""
    if source is None:
        return swinging
    if source == 'weapon':
        return True
    kind, effects = source
    return kind == 'spell' and any(port_player_cast(casts, e, now) for e in effects)


def port_fight(events):
    """Battle.cpp's blame and kill credit on plain values: events [(t, kind, who, target, source, swinging)] with kind hit,
    cast or death; a health loss as (t, 'loss', None, target, amount). Returns ({fighter: dealt}, {victim: killer})."""
    casts, last_hitter, by_player, dealt, killers, blows = [], {}, set(), {}, {}, []
    for t, kind, who, target, *rest in events:
        if kind == 'cast':
            casts.append([set(rest[0]), t])
        elif kind == 'hit':
            source, swinging = rest
            if who == 'player' and not port_player_blow(source, swinging, casts, t):
                continue
            last_hitter[target] = (who, t)
            if who == 'player':
                by_player.add(target)
                blows.append((target, t))
        elif kind == 'loss':
            hitter, at = last_hitter.get(target, (None, -99))
            if hitter and t - at <= 3:
                dealt[hitter] = dealt.get(hitter, 0) + rest[0]
        elif kind == 'death':
            killer = who
            if killer == 'player' and target not in by_player and not any(b == target and t - bt <= 5 for b, bt in blows):
                killer = ''
            killers[target] = killer
    return dealt, killers


# test 10's first fight: Jenassa strikes the wolf, the player's cloak spell touches it every second (no cast of his), the
# game names the player as the killer
cloak = ('spell', {'cloak damage'})
fight = [(0.0, 'hit', 'jenassa', 'wolf', 'weapon', False), (0.1, 'loss', None, 'wolf', 8), (0.5, 'hit', 'player', 'wolf', cloak, False),
         (1.0, 'hit', 'jenassa', 'wolf', 'weapon', False), (1.1, 'loss', None, 'wolf', 8), (1.5, 'hit', 'player', 'wolf', cloak, False),
         (2.0, 'hit', 'jenassa', 'wolf', 'weapon', False), (2.1, 'loss', None, 'wolf', 7), (2.2, 'death', 'player', 'wolf')]
dealt, killers = port_fight(fight)
check('Battle rule: a cloak on the player gives him no damage; the follower who struck gets it (test 10: he got 23)',
      dealt == {'jenassa': 23}, dealt)
check('Battle rule: the kill the game gives the player with no attack of his has no killer', killers == {'wolf': ''}, killers)
dealt, killers = port_fight([(0.0, 'hit', 'player', 'wolf', 'weapon', False), (0.1, 'loss', None, 'wolf', 23), (0.2, 'death', 'player', 'wolf')])
check("Battle rule: the player's own sword blow and kill stay his", dealt == {'player': 23} and killers == {'wolf': 'player'}, (dealt, killers))
dealt, killers = port_fight([(0.0, 'hit', 'player', 'wolf', None, True), (0.1, 'loss', None, 'wolf', 5), (3.0, 'death', 'player', 'wolf')])
check('Battle rule: a fist blow naming no source during his swing counts', dealt == {'player': 5} and killers == {'wolf': 'player'}, (dealt, killers))
dealt, killers = port_fight([(0.0, 'cast', 'player', None, ['fire']), (0.5, 'hit', 'player', 'wolf', ('spell', {'fire'}), False),
                             (0.6, 'loss', None, 'wolf', 23), (0.7, 'death', 'player', 'wolf')])
check('Battle rule: a fire bolt he cast by hand counts; the same spell from a script (no cast) does not',
      dealt == {'player': 23} and killers == {'wolf': 'player'}
      and port_fight([(0.5, 'hit', 'player', 'wolf', ('spell', {'fire'}), False), (0.7, 'death', 'player', 'wolf')])[1] == {'wolf': ''})
dealt, killers = port_fight([(0.0, 'hit', 'player', 'wolf', None, False), (0.2, 'death', 'player', 'wolf')])
check('Battle rule: no source and no swing (an aura with no spell named) is not his', killers == {'wolf': ''}, killers)

# Live session 12: menu dialogue spoken before Mantella's first talk of the session was lost (Mantella's own store); the
# listener heard it. Each line an NPC speaks in the dialogue menu with the player is kept per NPC from game load, with the
# topic the player chose, bounded, in menu_dialogue.json, which the Hub reads at a talk's first message.
LISTENER = open(os.path.join(ROOT, 'plugin', 'src', 'Listener.cpp'), encoding='utf-8').read()
handle = re.search(r'void HandleLine\(.*?\n\t\t}\n', LISTENER, re.S)
handle = handle.group(0) if handle else ''
keep = re.search(r'void KeepMenuLine\(.*?\n\t\t}\n', LISTENER, re.S)
keep = keep.group(0) if keep else ''
check('Listener: a line in the dialogue menu with that very NPC is kept, before the distance, combat, scene and length filters',
      'topics->menuOpen' in handle and 'speaker.get() == actor' in handle and -1 < handle.find('KeepMenuLine(') < handle.find('kMaxDistance'))
check("Listener: the player's chosen topic goes with the line; a vanilla greeting or short stock line nobody chose is left out",
      'chosen->parentTopic == a_info->parentTopic' in keep and 'chosen->topicText' in keep
      and 'FromBaseGame(a_info) && (said.empty() || WordCount(a_text) < 4)' in keep, keep[:200])
check("Listener: a mod's own line whose chosen entry is gone takes its topic's own name (live test 15: 8 of 11 had none)",
      'if (said.empty() && !FromBaseGame(a_info) && a_info->parentTopic)' in keep and 'a_info->parentTopic->GetFullName()' in keep
      and keep.find('a_info->parentTopic->GetFullName()') < keep.find('FromBaseGame(a_info) && (said.empty()'), keep[:200])
check('Listener: nothing expires (kept until the Hub made a memory of it); bounded at 60 per NPC and 200 NPCs; lines from a later '
      'time of another save kept aside under "later" (never in "npcs", which the Hub reads); when full a base game line goes '
      'first, then the oldest, counted as dropped',
      all(k in LISTENER for k in ('kMenuPerNpc = 60', 'kMenuNpcs = 200', 'if (InThisTime(*l, today))', '{ "later", MenuJson(later) }',
                                  'a_line.time >= g_loadReal ? a_today : g_loadDay', 'npc.dropped += 1',
                                  'std::ranges::find_if(npc.lines, [](const MenuLine& l) { return l.vanilla; })'))
      and 'kMenuDays' not in LISTENER)
check('Listener: each line keeps its plugin, place and game time (with the hour)',
      all(k in LISTENER for k in ('{ "plugin", l.plugin }', '{ "place", l.place }', '{ "day", l.day }', 'PlaceOf(a_actor)')))
HUB_MENU = os.path.join(CODING, 'Mantella-Living-World-Hub', 'server', 'living_world', 'menu_dialogue.py')
check("Listener: the file it writes is the one the Hub reads",
      'StorageUtilData/MantellaLivingWorld/menu_dialogue.json' in LISTENER
      and (not os.path.isfile(HUB_MENU) or "FILE = 'menu_dialogue.json'" in open(HUB_MENU, encoding='utf-8').read()))
check('Listener: the menu is read on the main thread (in the task), never in the sink',
      'KeepMenuLine' not in re.search(r'ProcessEvent\(const RE::TESTopicInfoEvent\*.*?\n\t\t\t}\n', LISTENER, re.S).group(0))

# Pairs: only the player's spouse (game or M.A.R.A.S married), adopted children and the steward are the household that
# "lives together as family"; Relationships' MRB_Close alone also covers the engaged, dating and lovers.
PAIRS = open(os.path.join(ROOT, 'Source', 'Scripts', 'MLWW_Pairs.psc'), encoding='utf-8').read()
house = re.search(r'(?m)^bool Function Household\(.*?^EndFunction', PAIRS, re.S)
house = house.group(0) if house else ''
check('Pairs: the household is the spouse, not anyone Relationships marks close',
      '0x0C6472' in house and '"maras", 0) >= 3' in house
      and re.search(r'If StorageUtil\.GetIntValue\(akActor, "MRB_Close"\) > 0\s*Return true', house) is None, house[:300])

# Plugin files and tasks: a refused rename never falls back to a truncating direct write and never sleeps on the worker;
# a wrong-typed field in battles.json or menu_dialogue.json never escapes a main-thread task; ended fights are not
# rewritten at the main menu or during a loading screen, and the root player is never "someone".
WRITER = open(os.path.join(ROOT, 'plugin', 'src', 'Writer.cpp'), encoding='utf-8').read()
write_text = re.search(r'void WriteText\(.*?\n\t\t}\n', WRITER, re.S)
write_text = write_text.group(0) if write_text else ''
check('Writer: a refused rename is retried later, never written in place', 'RetryRename(' in write_text
      and 'std::ofstream out(a_file' not in write_text and 'sleep_for' not in WRITER)
tick = re.search(r'\tvoid Tick\(\)\n\t\{.*?\n\t\}\n', BATTLE, re.S)
tick = tick.group(0) if tick else ''
check('Battle: Tick waits for a loaded game and skips loading screens', '!g_gameLoaded' in tick and 'LoadingMenu::MENU_NAME' in tick
      and 'g_gameLoaded = true' in BATTLE)
check('Battle: the root player name is never "someone"', re.search(r'std::string PlayerName\(\)\n\t\t\{[^}]*NameOf', BATTLE) is None)
check('Personal: Battle::Tick runs inside try/catch', re.search(r'try \{\s*Battle::Tick\(\);\s*\} catch', PERSONAL) is not None)
check('Listener: KeepMenuLine runs inside try/catch', re.search(r'try \{\s*KeepMenuLine\(', LISTENER) is not None)

# Menu dialogue store: one coalesced save per exchange, copied on the main thread when it runs, flushed on game save and
# before a load; the other character played longest ago goes first, not the alphabetically first.
save_menu = re.search(r'\t\tvoid SaveMenu\(\)\n\t\t\{.*?\n\t\t}\n', LISTENER, re.S)
save_menu = save_menu.group(0) if save_menu else ''
check('Listener: a captured line only marks the store dirty; one save runs later in a main-thread task',
      'g_menuDirty = true' in save_menu and 'Writer::RunLater(kMenuSaveDelay' in save_menu and 'AddTask(' in save_menu
      and 'menu = g_menu' not in save_menu, save_menu[:300])
MAIN = open(os.path.join(ROOT, 'plugin', 'src', 'main.cpp'), encoding='utf-8').read()
check('Listener: pending menu lines are written on a game save and before a load',
      re.search(r'kSaveGame \|\| a_msg->type == SKSE::MessagingInterface::kPreLoadGame\) \{\s*MLWW::Listener::FlushMenu\(\)', MAIN) is not None
      and 'MLWW::Listener::GameLoaded(' in MAIN)
check('Listener: the deferred save runs only through the guarded call (no exception leaves its task)',
      len(re.findall(r'\bSaveMenuNow\(\);', LISTENER)) == 2 and len(re.findall(r'try \{\s*SaveMenuNow\(\);', LISTENER)) == 2)
check('Listener: the other character played longest ago goes first', 'LastSeen(' in LISTENER
      and 'g_menuOthers.erase(g_menuOthers.begin())' not in LISTENER)

# Battle: a fight that was not kept and never written leaves battles.json alone; a sticking combat flag does not start
# the next fight on its own.
end = re.search(r'\t\tvoid End\(\)\n\t\t\{.*?\n\t\t}\n', BATTLE, re.S)
end = end.group(0) if end else ''
check('Battle: End writes only a kept fight, or one whose live account is in the file',
      re.search(r'if \(written\) \{\s*Write\(\);', end) is not None and 'g_fight.lastWrite != Clock::time_point{}' in end
      and 'g_waitNew = true' in end, end[-400:])
begin = re.search(r'\t\tvoid Begin\(\)\n\t\t\{.*?\n\t\t}\n', BATTLE, re.S)
check('Battle: after a fight ends, the combat flag alone starts no new one (a blow, a hostile combatant or leaving combat does)',
      '} else if (!g_waitNew || HostileCombatant()) {' in tick and begin is not None and 'g_waitNew = false' in begin.group(0))

# Papyrus: a load never keeps a full-scan time from before it; the initiative scan does nothing with nobody to bring over.
STATE = open(os.path.join(ROOT, 'Source', 'Scripts', 'MLWW_State.psc'), encoding='utf-8').read()
check('State: Register clears the full-scan due flag before the load scan is due',
      re.search(r'fullDue = false[^\n]*\n\s*DueFull\("load"', STATE) is not None)
INITIATIVE = open(os.path.join(ROOT, 'Source', 'Scripts', 'MLWW_Initiative.psc'), encoding='utf-8').read()
scan = re.search(r'(?m)^Actor Function Scan\(\).*?^EndFunction', INITIATIVE, re.S)
scan = scan.group(0) if scan else ''
check('Initiative: Scan returns before Calm() when nobody wants to tell anything',
      0 <= scan.find('If i == 0 ||') < scan.find('Calm(PlayerRef)'), scan[:300])
forget = re.search(r'(?m)^Function Forget\(.*?^EndFunction', INITIATIVE, re.S)
forget = forget.group(0) if forget else ''
outdated = re.search(r'(?m)^bool Function Outdated\(.*?^EndFunction', INITIATIVE, re.S)
outdated = outdated.group(0) if outdated else ''
check('Initiative: a reason whose quest stopped or moved on is forgotten before the NPC is brought over (no keys: no check)',
      '"MLWW_WantsToTellQuest"' in INITIATIVE and '"MLWW_WantsToTellStage"' in INITIATIVE
      and 'If !q\n\t\tReturn false' in outdated and '!q.IsRunning() || q.GetStage() != StorageUtil.GetIntValue(akNpc, KEY_STAGE)' in outdated
      and 'UnsetFormValue(akNpc, KEY_QUEST)' in forget and 'UnsetIntValue(akNpc, KEY_STAGE)' in forget
      and 0 <= scan.find('ElseIf Outdated(npc)') < scan.find('npc.Is3DLoaded()'), outdated[:300])

# Personal: a hit in a bar brawl (DGIntimidateFaction) is no assault.
PERSONAL_PSC = open(os.path.join(ROOT, 'Source', 'Scripts', 'MLWW_Personal.psc'), encoding='utf-8').read()
struck = re.search(r'(?m)^Event OnStruck\(.*?^EndEvent', PERSONAL_PSC, re.S)
struck = struck.group(0) if struck else ''
check('Personal: a struck NPC in a brawl (DGIntimidateFaction) logs no assault',
      'GetFormFromFile(0x04CFA6, "Skyrim.esm") as Faction' in struck
      and 0 <= struck.find('IsInFaction(brawl)') < struck.find('LogCrime('), struck[:300])

# Listener: the split by the loaded save's time runs soon after every load, not at the next line; merged lines are capped;
# the chosen dialogue entry is read only when the menu still lists it.
loaded = re.search(r'\tvoid GameLoaded\(bool a_newGame\)\n\t\{.*?\n\t}\n', LISTENER, re.S)
loaded = loaded.group(0) if loaded else ''
check('Listener: after a load the stored lines are loaded, switched to this character and saved (split) inside try/catch',
      re.search(r'try \{\s*if \(!g_menuLoaded\) \{\s*LoadMenu\(\);\s*\}\s*SwitchMenuPlayer\(\);\s*SaveMenu\(\);\s*\} catch', loaded) is not None
      and loaded.find('g_loadDay =') < loaded.find('SaveMenu();'), loaded[:400])
save_now = re.search(r'\t\tvoid SaveMenuNow\(\)\n\t\t\{.*?\n\t\t}\n', LISTENER, re.S)
save_now = save_now.group(0) if save_now else ''
merge = save_now[:save_now.find('g_menuLater.clear();')] if 'g_menuLater.clear();' in save_now else ''
check('Listener: lines merged back from the later store are capped at 60 per NPC, the oldest going first',
      'while (into.lines.size() > kMenuPerNpc)' in merge and 'into.lines.pop_front();' in merge, merge[-300:])
choice = re.search(r'ListedChoice\(RE::MenuTopicManager\* a_topics\)\n\t\t\{.*?\n\t\t}\n', LISTENER, re.S)
choice = choice.group(0) if choice else ''
check('Listener: the chosen menu entry is used only when found by address in the listed dialogue (never read before)',
      'a_topics->dialogueList' in choice and 'a_topics->dialogueListStack' in choice and 'entry == chosen' in choice
      and '->parentTopic' not in choice and 'ListedChoice(a_topics)' in LISTENER
      and 'a_topics->lastSelectedDialogue; chosen &&' not in LISTENER, choice[:300])
print(f'{fails} failed, {warns} warnings')
sys.exit(1 if fails else 0)
