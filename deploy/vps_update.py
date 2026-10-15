"""Code-only GitHub updater. Never checks out, pulls or resets the live repository."""
import ast, fcntl, hashlib, json, os, pathlib, shutil, subprocess, sys, tempfile, time
STATE=pathlib.Path('/var/lib/travian-deploy')
APP=pathlib.Path('/opt/travian-discord-bot')
NODE=pathlib.Path('/opt/travian-discord-phase3')
REPO='https://github.com/dmrylezfree-beep/travian-discord-bot.git'

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def run(args,**kw):return subprocess.run(args,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=kw.pop('timeout',120),**kw)
def atomic(path,content):
 path.parent.mkdir(parents=True,exist_ok=True)
 fd,temp=tempfile.mkstemp(prefix='.deploy-',dir=path.parent)
 try:
  with os.fdopen(fd,'wb') as f:f.write(content);f.flush();os.fsync(f.fileno())
  os.chmod(temp,0o644);os.replace(temp,path)
 finally:
  if os.path.exists(temp):os.unlink(temp)
def write_record(path,obj):atomic(path,json.dumps(obj,indent=2).encode())
def service_state(service):
 text=run(['systemctl','show',service,'-p','ActiveState','-p','MainPID','-p','NRestarts']).stdout.decode()
 return dict(line.split('=',1) for line in text.splitlines() if '=' in line)
def healthy(services,seconds=60):
 initial={s:service_state(s) for s in services}
 for s,st in initial.items():
  if st['ActiveState']!='active' or st['MainPID']=='0':raise RuntimeError('Service not running: '+s)
 for _ in range(seconds//5):
  time.sleep(5)
  if any(service_state(s)!=initial[s] for s in services):raise RuntimeError('Service restarted or stopped')
def destination(item):
 prefix,relative=item['target'].split(':',1)
 if prefix not in ('app','node') or '/' in relative or relative.startswith('.') or not relative.endswith(('.py','.js','.json')):raise RuntimeError('Unsupported deployment target')
 return (APP if prefix=='app' else NODE)/relative

def restore_timers(record):
 for timer in record.get('timers',[]):run(['systemctl','start',timer])

def rollback(record):
 for service in record['services']:run(['systemctl','stop',service])
 for entry in record['files']:
  atomic(pathlib.Path(entry['target']),pathlib.Path(entry['backup']).read_bytes())
 for service in record['services']:run(['systemctl','start',service])
 healthy(record['services'],15)
 restore_timers(record)
 (STATE/'pending.json').unlink(missing_ok=True)

def validate(candidate,items):
 for item in items:
  path=candidate/item['source']
  if path.suffix=='.py':ast.parse(path.read_text(),filename=item['source'])
  elif path.suffix=='.js':run(['/usr/bin/node','--check',str(path)])
  elif path.suffix=='.json':json.loads(path.read_text())
 testroot=candidate/'test-state';testroot.mkdir()
 env={'PATH':'/usr/bin:/bin','DEFENCE_DATA_DIR':str(testroot),'DEFENCE_PYTHON':str(APP/'.venv/bin/python'), 'DEFENCE_STORE_HELPER':str(candidate/'defence_store.py')}
 tests=sorted(str(x) for x in (candidate/'vps-runtime').glob('*.test.js'))
 if not tests:raise RuntimeError('Missing runtime tests')
 run(['/usr/bin/node','--test',*tests],cwd=candidate/'vps-runtime',env=env,timeout=120)
 run([str(APP/'.venv/bin/python'),'-m','unittest','discover','-s',str(candidate),'-p','test_*.py'],env=env,timeout=60)

def apply(candidate,items,current,commit):
 changes=[i for i in items if sha(candidate/i['source'])!=current[i['target']]]
 for item in items:
  if sha(destination(item))!=current[item['target']]:raise RuntimeError('Local file changed; update refused')
 if not changes:return False
 services=sorted({s for i in changes for s in i['services']})
 for service in services:
  if service_state(service)['ActiveState']!='active':raise RuntimeError('Service already unhealthy; update refused')
 # Do not race scheduled jobs with replacement of their code.
 for unit in ['travian-daily-report','travian-crop-daily','travian-defence-settings-reminder','travian-defence-local-sync']:
  if service_state(unit)['ActiveState']=='active':raise RuntimeError('Scheduled job running; retry later')
 backup=pathlib.Path(tempfile.mkdtemp(prefix='backup-',dir=STATE))
 record={'commit':commit,'services':services,'files':[], 'timers':[]}
 for timer in ['travian-daily-report.timer','travian-crop-daily.timer','travian-defence-settings-reminder.timer','travian-defence-local-sync.timer']:
  if service_state(timer)['ActiveState']=='active':record['timers'].append(timer)
 for idx,item in enumerate(changes):
  target=destination(item);saved=backup/str(idx);shutil.copy2(target,saved)
  record['files'].append({'target':str(target),'backup':str(saved)})
 write_record(STATE/'pending.json',record)
 try:
  for timer in record['timers']:run(['systemctl','stop',timer])
  for unit in ['travian-daily-report','travian-crop-daily','travian-defence-settings-reminder','travian-defence-local-sync']:
   if service_state(unit)['ActiveState']=='active':raise RuntimeError('Scheduled job still running')
  for service in services:run(['systemctl','stop',service])
  for item in changes:atomic(destination(item),(candidate/item['source']).read_bytes())
  for service in services:run(['systemctl','start',service])
  healthy(services)
  restore_timers(record)
  write_record(STATE/'installed.json',{'commit':commit,'hashes':{i['target']:sha(destination(i)) for i in items}})
  (STATE/'pending.json').unlink()
 except BaseException:
  rollback(record)
  raise
 return True

def main():
 STATE.mkdir(mode=0o700,exist_ok=True)
 with open(STATE/'update.lock','w') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  if (STATE/'pending.json').exists():rollback(json.loads((STATE/'pending.json').read_text()))
  config=json.loads((STATE/'managed.json').read_text());items=config['files']
  if len({i['target'] for i in items})!=len(items):raise RuntimeError('Duplicate target')
  if '--initialize' in sys.argv:
   if (STATE/'installed.json').exists():raise RuntimeError('Already initialized')
   write_record(STATE/'installed.json',{'commit':config['commit'],'hashes':{i['target']:sha(destination(i)) for i in items}});return
  installed=json.loads((STATE/'installed.json').read_text())
  cache=STATE/'repository.git'
  if not cache.exists():run(['git','init','--bare',str(cache)])
  run(['git','-C',str(cache),'fetch','--depth=1',REPO,'refs/heads/main'],env={'PATH':'/usr/bin:/bin','GIT_TERMINAL_PROMPT':'0'})
  commit=run(['git','-C',str(cache),'rev-parse','FETCH_HEAD']).stdout.decode().strip()
  if commit==installed['commit']:print('Already current');return
  with tempfile.TemporaryDirectory(prefix='candidate-',dir=STATE) as directory:
   candidate=pathlib.Path(directory)
   for source in {i['source'] for i in items}|set(config['tests']):
    target=candidate/source;target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(run(['git','-C',str(cache),'show',commit+':'+source]).stdout)
   (candidate/'vps-runtime/node_modules').symlink_to(NODE/'node_modules')
   # Dependencies require a reviewed install, never an unattended npm operation.
   if (candidate/'vps-runtime/package-lock.json').read_bytes()!=(NODE/'package-lock.json').read_bytes():raise RuntimeError('Dependency update requires installation')
   validate(candidate,items)
   changed=apply(candidate,items,installed['hashes'],commit)
   if not changed:write_record(STATE/'installed.json',{'commit':commit,'hashes':installed['hashes']})
   print('Code update applied: '+commit if changed else 'No managed code changes')
if __name__=='__main__':
 try:main()
 except Exception as exc:
  print('Update failed safely: '+type(exc).__name__,file=sys.stderr);sys.exit(1)
