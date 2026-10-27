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
    fd, temp = tempfile.mkstemp(prefix='.push-', dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.chmod(temp,0o600);os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def main():
    if os.geteuid()!=0 or not sys.stdin.isatty():
        print('Запустите эту команду под root в интерактивном Терминале.');return 1
    token=getpass.getpass('Вставьте токен Push_travian_bot (ввод скрыт): ').strip()
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
    if str(me.get('username','')).lower()!='push_travian_bot':
        print('Это токен другого бота. Ничего не сохранено.');return 1
    if api('getWebhookInfo').get('url'):
        print('У Push-бота уже настроен webhook. Ничего не изменено; сообщите об этом Codex.');return 1
    membership=requests.post('https://api.telegram.org/bot'+token+'/getChatMember',json={'chat_id':-1002493230303,'user_id':me['id']},proxies=proxies,timeout=25)
    membership.raise_for_status()
    if membership.json().get('result',{}).get('status') not in ('administrator','creator'):
        print('Добавьте @Push_travian_bot в группу и назначьте администратором для проверки участников. Затем повторите настройку. Ничего не сохранено.');return 1
    state=pathlib.Path('/var/lib/travian-deploy')
    with (state/'update.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if (state/'pending.json').exists():
            print('Идёт обновление VPS. Повторите команду после его завершения.');return 1
        config=json.loads((state/'managed.json').read_text())
        entries=[i for i in config['files'] if i['source']=='push_bot.py']
        if len(entries)!=1:raise RuntimeError('Push deployment not registered')
        def quote(value):return '"'+value.replace('\\','\\\\').replace('"','\\"')+'"'
        env='PUSH_TELEGRAM_TOKEN='+quote(token)+'\n'
        if proxy:env+='TELEGRAM_PROXY_URL='+quote(proxy)+'\n'
        atomic(pathlib.Path('/etc/travian-push-token.env'),env)
        # Only the new bot is enabled/restarted. Existing bot services are untouched.
        subprocess.run(['systemctl','enable','travian-push.service'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        subprocess.run(['systemctl','restart','travian-push.service'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        import time
        invocation=subprocess.check_output(['systemctl','show','travian-push.service','-p','InvocationID','--value'],text=True).strip()
        ready=False
        for _ in range(45):
            log=subprocess.check_output(['journalctl','_SYSTEMD_INVOCATION_ID='+invocation,'--no-pager','-o','cat'],text=True)
            if 'Push ledger ready.' in log:
                ready=True;break
            time.sleep(1)
        if not ready:raise RuntimeError('Push startup not confirmed')
        status=subprocess.check_output(['systemctl','is-active','travian-push.service'],text=True).strip()
        if status!='active':raise RuntimeError('Push service did not start')
        entries[0]['services']=['travian-push.service']
        atomic(state/'managed.json',json.dumps(config,indent=2))
    print('Токен сохранён. Push_travian_bot запущен. В ветке пуша отправьте /push@Push_travian_bot.')
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except KeyboardInterrupt:print('\nВвод отменён.');raise SystemExit(1)
    except Exception:print('Настройка не завершена. Секреты скрыты. Сообщите Codex, что команда завершилась ошибкой.');raise SystemExit(1)
