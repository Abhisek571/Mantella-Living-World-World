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
state = set(re.findall(r'^\s*(?:std::[\w:]+<[^;]*>|[\w:]+)\s+(g_\w+)', SRC, re.M)) - {'g_crimeFactions', 'g_epoch'}
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
    check('knowledge_quests.json holds the "quests" string list MLWW_State.WriteQuests reads', ok and 'JsonUtil.StringListCount(QUESTS_WANTED, "quests")' in state)
else:
    warn('knowledge_quests.json', 'Knowledge not checked out next to World; reader not checked')

# Fact keys are cleared at join: every Put is inside Sync, Put removes a fact with no text, and joining runs Sync.
sync = re.search(r'Function Sync\(Actor akNpc\) global.*?EndFunction', FACTS, re.S).group(0)
check('every fact is written by MLWW_Facts.Sync', len(re.findall(r'Put\(path, "fact_', FACTS)) == len(re.findall(r'Put\(path, "fact_', sync)))
check('Put removes a fact whose text is empty', re.search(r'If value == ""\s+JsonUtil\.UnsetStringValue\(asPath, asKey\)', FACTS) is not None)
added = re.search(r'Event OnNpcAdded\(Form akActor\).*?EndEvent', PSC['MLWW_Personal.psc'], re.S).group(0)
check('joining a conversation runs Sync before the line is sent', added.find('MLWW_Facts.Sync(npc)') >= 0 and
      added.find('MLWW_Facts.Sync(npc)') < added.find('MLWW_Util.Send('))

print(f'{fails} failed, {warns} warnings')
sys.exit(1 if fails else 0)
