"""Refresh Telegram from local state; invoked by the persistent VPS queue."""
import fcntl
import os
import sys
sys.path.insert(0, '/opt/travian-discord-bot')
import defence_requests as defence
from defence_store import root

def main():
    with open(root() / '.telegram-sync.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = defence.load_state()
        if state.get('center_chat_id') and not defence.refresh_center(create_if_missing=True):
            raise RuntimeError('Telegram centre refresh failed')
        defence.refresh_optimal_plans(force=False)

if __name__ == '__main__':
    try: main()
    except Exception:
        print('Telegram local sync failed; will retry', file=sys.stderr)
        raise SystemExit(1)
