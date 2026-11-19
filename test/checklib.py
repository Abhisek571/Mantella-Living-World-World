"""Pass/fail reporting shared by the offline checks (check_*.py): one line per check, counts for the summary."""
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
