#!/opt/travian-discord-bot/.venv/bin/python
"""Interactive credential entry. Never accepts a token in command arguments."""
import fcntl
import getpass
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import tempfile
import requests


def atomic(path, data):
    fd, temp = tempfile.mkstemp(prefix='.scout-', dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.chmod(temp,0o600);os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def main():
    if os.geteuid()!=0 or not sys.stdin.isatty():
        print('Запустите эту команду под root в интерактивном Терминале.');return 1
    token=getpass.getpass('Вставьте токен Scout_travian_bot (ввод скрыт): ').strip()
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{20,}',token):
        print('Формат токена не распознан. Ничего не сохранено.');return 1
    proxy=None
    for line in pathlib.Path('/etc/travian-bots.env').read_text().splitlines():
        if line.startswith('TELEGRAM_PROXY_URL='):
            values=shlex.split(line.split('=',1)[1]);proxy=values[0] if values else None
    proxies={'https':proxy} if proxy else None
    def api(method):
        r=requests.post('https://api.telegram.org/bot'+token+'/'+method,json={},proxies=proxies,timeout=25)
        r.raise_for_status();result=r.json()
        if not result.get('ok'):raise RuntimeError('API unavailable')
        return result['result']
    me=api('getMe')
    if str(me.get('username','')).lower()!='scout_travian_bot':
        print('Это токен другого бота. Ничего не сохранено.');return 1
    if api('getWebhookInfo').get('url'):
        print('У Scout-бота уже настроен webhook. Ничего не изменено; сообщите об этом Codex.');return 1
    state=pathlib.Path('/var/lib/travian-deploy')
    with (state/'update.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if (state/'pending.json').exists():
            print('Идёт обновление VPS. Повторите команду после его завершения.');return 1
        config=json.loads((state/'managed.json').read_text())
        entries=[i for i in config['files'] if i['source']=='scout_bot.py']
        if len(entries)!=1:raise RuntimeError('Scout deployment not registered')
        def quote(value):return '"'+value.replace('\\','\\\\').replace('"','\\"')+'"'
        env='SCOUT_TELEGRAM_TOKEN='+quote(token)+'\n'
        if proxy:env+='TELEGRAM_PROXY_URL='+quote(proxy)+'\n'
        atomic(pathlib.Path('/etc/travian-scout-token.env'),env)
        # Only the new bot is enabled/restarted. Existing bot services are untouched.
        subprocess.run(['systemctl','enable','travian-scout.service'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        subprocess.run(['systemctl','restart','travian-scout.service'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        import time
        invocation=subprocess.check_output(['systemctl','show','travian-scout.service','-p','InvocationID','--value'],text=True).strip()
        ready=False
        for _ in range(45):
            log=subprocess.check_output(['journalctl','_SYSTEMD_INVOCATION_ID='+invocation,'--no-pager','-o','cat'],text=True)
            if 'Scout calculator ready.' in log:
                ready=True;break
            time.sleep(1)
        if not ready:raise RuntimeError('Scout startup not confirmed')
        status=subprocess.check_output(['systemctl','is-active','travian-scout.service'],text=True).strip()
        if status!='active':raise RuntimeError('Scout service did not start')
        entries[0]['services']=['travian-scout.service']
        atomic(state/'managed.json',json.dumps(config,indent=2))
    print('Токен сохранён. Scout_travian_bot запущен. Откройте его в Telegram и нажмите /start.')
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except KeyboardInterrupt:print('\nВвод отменён.');raise SystemExit(1)
    except Exception:print('Настройка не завершена. Секреты скрыты. Сообщите Codex, что команда завершилась ошибкой.');raise SystemExit(1)
