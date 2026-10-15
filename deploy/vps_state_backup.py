"""Public GitHub backup explicitly approved by owner; never imports into live state."""
import base64,datetime,fcntl,json,os,pathlib,sqlite3,tempfile,urllib.request,urllib.error
APP=pathlib.Path('/opt/travian-discord-bot')
FILES=['data/defence/'+x for x in ['players.json','discord_players.json','requests.json','state.json','settings.json']]
# Existing JSON documents only; no environment, tokens, logs or arbitrary files.
FILES += ['data/users/preferences.json', 'data/inactive_state.json', 'data/inactive_3d_state.json']
FILES += ['data/alliance_ops/'+name+'.json' for name in ['offers','operations','targets','states']]
FILES += ['data/attacks/'+name+'.json' for name in ['offers','scouts','attacks','important_villages','preferences','scout_villages']]
FILES += ['data/crop_fields/'+name+'.json' for name in ['state','reservations','crop_fields']]

QUEUE=pathlib.Path('/var/lib/travian-defence-local/jobs.sqlite')
URL='https://api.github.com/repos/dmrylezfree-beep/travian-discord-bot/contents/backups/vps-state/latest.json'

def collect():
 import sys
 sys.path.insert(0,str(APP))
 from defence_store import locked
 documents={}
 with locked():
  for path in FILES:
   full=APP/path
   if full.exists():documents[path]=json.loads(full.read_text())
 source=sqlite3.connect('file:'+str(QUEUE)+'?mode=ro',uri=True)
 with tempfile.TemporaryDirectory() as directory:
  target=sqlite3.connect(str(pathlib.Path(directory)/'queue.sqlite'))
  source.backup(target);target.close();source.close()
  queue=base64.b64encode((pathlib.Path(directory)/'queue.sqlite').read_bytes()).decode()
 return {'format':1,'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'documents':documents,'queue_sqlite_base64':queue}

def main():
 token=os.environ['GITHUB_TOKEN'];headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','Content-Type':'application/json','User-Agent':'travian-vps-backup'}
 data=collect();encoded=json.dumps(data,ensure_ascii=False,indent=2).encode()
 def request(method,body=None):
  req=urllib.request.Request(URL,data=None if body is None else json.dumps(body).encode(),method=method,headers=headers)
  with urllib.request.urlopen(req,timeout=60) as response:return json.load(response)
 for attempt in range(3):
  payload={'branch':'main','message':'Backup VPS bot state','content':base64.b64encode(encoded).decode()}
  try:payload['sha']=request('GET')['sha']
  except urllib.error.HTTPError as error:
   if error.code!=404:raise
  try:
   response=request('PUT',payload)
   print('VPS state backed up to GitHub: '+response['commit']['sha']);return
  except urllib.error.HTTPError as error:
   if error.code not in (409,422) or attempt==2:raise
if __name__=='__main__':
 try:main()
 except Exception as error:raise SystemExit('Backup failed; local data retained ('+type(error).__name__+')')
