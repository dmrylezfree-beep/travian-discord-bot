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
