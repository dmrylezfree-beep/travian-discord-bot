import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const helper=process.env.DEFENCE_STORE_HELPER || '/opt/travian-discord-bot/defence_store.py';
export function stateCall(request) {
  return new Promise((resolve,reject)=>{
    const child=spawn(process.env.DEFENCE_PYTHON || '/opt/travian-discord-bot/.venv/bin/python',[helper],{stdio:['pipe','pipe','pipe']});
    let output='',bytes=0;
    const timer=setTimeout(()=>{child.kill('SIGKILL');reject(Error('Local state timeout'));},10000);
    child.stdout.on('data',chunk=>{bytes+=chunk.length;if(bytes>16*1024*1024)child.kill('SIGKILL');else output+=chunk;});
    child.stderr.resume();
    child.on('error',()=>{clearTimeout(timer);reject(Error('Local state unavailable'));});
    child.on('close',code=>{
      clearTimeout(timer);
      try {const result=JSON.parse(output);if(code!==0||!result.ok)throw Error(result.error==='conflict'?'State conflict; reload and retry':'Local state failed');resolve(result.data);}
      catch(error){reject(error);}
    });
    child.stdin.on('error',()=>{});
    child.stdin.end(JSON.stringify(request));
  });
}
function name(path) {
  if(!/^data\/defence\/(players|discord_players|requests|state|settings)\.json$/.test(path))throw Error('Unsupported state document');
  return path.split('/').pop();
}
export async function readState(path) {
  const data=await stateCall({op:'read',name:name(path)});
  return {data,sha:structuredClone(data)};
}
export async function saveState(path,data,base) {
  return stateCall({op:'write',name:name(path),data,base});
}
export async function dispatchLocalSync(env) {
  if(env.LOCAL_SYNC)return env.LOCAL_SYNC();
  const response=await fetch('http://127.0.0.1:18788/telegram/sync',{
    method:'POST',headers:{Authorization:'Bearer '+env.TELEGRAM_BOT_TOKEN,'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(10000),
  });
  if(!response.ok)throw Error('Local sync scheduling failed');
}

// Gateway interactions and the local reconciler run in separate processes.
// Hold a kernel lock over the complete read/find/create/update sequence.
// The child releases it on stdin EOF, including when the Node parent exits.
export function withDiscordSyncLock(run) {
  const script = `import os,sys,fcntl
root=os.environ.get('DEFENCE_DATA_DIR','/opt/travian-discord-bot/data/defence')
with open(os.path.join(root,'.discord-sync.lock'),'a') as lock:
 os.chmod(lock.name,0o600)
 fcntl.flock(lock,fcntl.LOCK_EX)
 print('locked',flush=True)
 sys.stdin.buffer.read()
`;
  return new Promise((resolve,reject)=>{
    const child=spawn(process.env.DEFENCE_PYTHON || '/opt/travian-discord-bot/.venv/bin/python',
      ['-c',script],{stdio:['pipe','pipe','ignore']});
    let acquired=false,settled=false,result,failure,output='';
    const timer=setTimeout(()=>{failure=Error('Discord sync lock timeout');child.kill('SIGKILL');},120000);
    const finish=error=>{
      if(settled)return;
      settled=true;clearTimeout(timer);
      if(failure||error)reject(failure||error);else resolve(result);
    };
    child.stdin.on('error',()=>{});
    child.on('error',()=>finish(Error('Discord sync lock unavailable')));
    child.on('close',code=>finish(code===0&&acquired?null:Error('Discord sync lock failed')));
    child.stdout.on('data',chunk=>{
      output+=chunk;
      if(acquired||!output.includes('locked\n'))return;
      acquired=true;clearTimeout(timer);
      Promise.resolve().then(run).then(value=>{result=value;},error=>{failure=error;})
        .finally(()=>child.stdin.end());
    });
  });
}
