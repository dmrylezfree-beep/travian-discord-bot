"""Shared durable JSON store for Python and Node; GitHub is never read at runtime."""
import copy
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
from contextlib import contextmanager

NAMES = {'players.json', 'discord_players.json', 'requests.json', 'state.json', 'settings.json'}
MISSING = object()
class Conflict(RuntimeError):
    pass


def merge(base, desired, current):
    """Merge disjoint changes; reject competing writes instead of losing updates."""
    if desired == base: return current
    if current == base or desired == current: return desired
    if all(isinstance(x, dict) for x in (base, desired, current)):
        out = {}
        for key in base.keys() | desired.keys() | current.keys():
            value = merge(base.get(key, MISSING), desired.get(key, MISSING), current.get(key, MISSING))
            if value is not MISSING: out[key] = value
        return out
    if all(isinstance(x, list) for x in (base, desired, current)):
        def indexed(items):
            if not all(isinstance(x, dict) and 'id' in x for x in items): return None
            result = {str(x['id']): x for x in items}
            return result if len(result) == len(items) else None
        maps = [indexed(x) for x in (base, desired, current)]
        if all(x is not None for x in maps):
            result = merge(*maps)
            keys = list(dict.fromkeys([str(x['id']) for x in current + desired]))
            return [result[k] for k in keys if k in result]
    raise Conflict('State changed concurrently; reload and retry')


def root():
    return Path(os.environ.get('DEFENCE_DATA_DIR', '/opt/travian-discord-bot/data/defence'))


def checked(name):
    if name not in NAMES: raise ValueError('Unsupported state document')
    return root() / name


@contextmanager
def locked():
    root().mkdir(parents=True, exist_ok=True)
    fd = os.open(root() / '.state.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally: os.close(fd)


def read_raw(name, default):
    try: return json.loads(checked(name).read_text(encoding='utf8'))
    except FileNotFoundError: return copy.deepcopy(default)
    # Invalid JSON is an error, never silently reset live state.


def atomic_write(path, value):
    fd, temp = tempfile.mkstemp(prefix='.'+path.name+'.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write('\n'); f.flush(); os.fsync(f.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(temp): os.unlink(temp)


class DocumentDict(dict): pass
class DocumentList(list): pass

def load(name, default):
    with locked(): data = read_raw(name, default)
    result = DocumentDict(data) if isinstance(data, dict) else DocumentList(data)
    result.baseline = copy.deepcopy(data)
    return result


def commit(name, desired, base):
    with locked():
        current = read_raw(name, [] if name == 'requests.json' else {})
        if name == 'requests.json':
            # An entire request is one business transaction: cancelling and
            # pledging cannot be merged as independent field changes.
            def index(rows):
                if not isinstance(rows, list) or not all(isinstance(row, dict) and 'id' in row for row in rows):
                    raise ValueError('Invalid request document')
                entries = {str(row['id']): row for row in rows}
                if len(entries) != len(rows): raise ValueError('Duplicate request ID')
                return entries
            before, proposed, latest = [index(rows) for rows in (base, desired, current)]
            for key in before.keys() | proposed.keys():
                old = before.get(key, MISSING)
                new = proposed.get(key, MISSING)
                now = latest.get(key, MISSING)
                if new != old and now != old and now != new:
                    raise Conflict('Request changed concurrently; reload and retry')
            result = merge(base, desired, current)
        else:
            result = merge(base, desired, current)
        atomic_write(checked(name), result)
    return result


def save(name, value):
    if not hasattr(value, 'baseline'):
        raise Conflict('State must be loaded before it can be saved')
    commit(name, value, value.baseline)
    value.baseline = json.loads(json.dumps(value))


if __name__ == '__main__':
    try:
        request = json.load(sys.stdin)
        name = request['name']
        if request['op'] == 'read':
            value = load(name, [] if name == 'requests.json' else {})
        elif request['op'] == 'write':
            value = commit(name, request['data'], request['base'])
        else: raise ValueError('Unknown operation')
        print(json.dumps({'ok': True, 'data': value}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': 'conflict' if isinstance(exc, Conflict) else 'state_error'}))
        sys.exit(1)
