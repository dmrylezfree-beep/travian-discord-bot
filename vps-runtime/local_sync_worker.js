import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
export function runTelegramSync() {
  return new Promise((resolve,reject)=>{
    const child=spawn(process.env.DEFENCE_PYTHON||'/opt/travian-discord-bot/.venv/bin/python',
      [fileURLToPath(new URL('./telegram_sync.py',import.meta.url))],
      {cwd:'/opt/travian-discord-bot',stdio:'ignore',env:{...process.env,DEFENCE_ENABLE_GIT_PERSIST:'0',DEFENCE_WORKER_URL:'http://127.0.0.1:18788'}});
    const timer=setTimeout(()=>child.kill('SIGKILL'),90000);
    child.on('error',()=>{clearTimeout(timer);reject(Error('Local sync failed'));});
    child.on('close',code=>{clearTimeout(timer);code===0?resolve():reject(Error('Local sync failed'));});
  });
}
export function localSyncWorker(worker,run=runTelegramSync) {
  return {async queue(batch,env){
    for(const message of batch.messages){
      if(message.body?.type==='telegram_sync'){
        try {await run();message.ack();}catch{message.retry({delaySeconds:60});}
      } else await worker.queue({messages:[message]},env);
    }
  }};
}
