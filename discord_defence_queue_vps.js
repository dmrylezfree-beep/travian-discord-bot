import {mkdir,readFile,rename,writeFile} from "node:fs/promises";
import {dirname} from "node:path";
import {randomUUID} from "node:crypto";

// Durable queue adapter for the existing Worker's queue(batch, env) handler.
// Keep disabled until a full cutover rehearsal succeeds.
export function makeDefenceQueue(worker, env, file) {
  let jobs = [];
  let busy = false;
  let timer;
  let saving = Promise.resolve();
  const save = () => {
    const snapshot = JSON.stringify(jobs);
    saving = saving.then(async () => {
      await mkdir(dirname(file), {recursive:true});
      const temp = file + "." + randomUUID() + ".tmp";
      await writeFile(temp,snapshot,{mode:0o600});
      await rename(temp,file);
    });
    return saving;
  };
  async function init() {
    try {
      const value = JSON.parse(await readFile(file,"utf8"));
      if (!Array.isArray(value)) throw Error("Invalid queue file");
      jobs = value;
    } catch(e) {
      if(e.code !== "ENOENT") throw e;
      await save();
    }
  }
  const binding = {
    async send(body,options={}) {
      const delay = Number(options.delaySeconds||0);
      if(!Number.isFinite(delay)||delay<0)throw Error("Invalid queue delay");
      const job = {id:randomUUID(),body,due:Date.now()+delay*1000,tries:0};
      jobs.push(job);
      await save();
    }
  };
  async function run() {
    if(busy)return;
    busy=true;
    try {
      for(const job of jobs.filter(j=>j.due<=Date.now()).slice(0,10)) {
        let result="retry", delay=60;
        const message={
          body:job.body,
          ack(){result="ack";},
          retry(o={}){result="retry";delay=Math.max(1,Number(o.delaySeconds)||60);}
        };
        try {await worker.queue({messages:[message]},env);}
        catch(e){console.error("Defence queue delivery failed:",e);}
        if(result==="ack")jobs=jobs.filter(j=>j.id!==job.id);
        else {job.tries++;job.due=Date.now()+delay*1000;}
        await save();
      }
    }finally{busy=false;}
  }
  function start(){
    if(timer)throw Error("Queue already running");
    timer=setInterval(()=>run().catch(console.error),5000);
  }
  async function stop(){
    if(timer)clearInterval(timer);
    timer=null;
    while(busy)await new Promise(r=>setTimeout(r,25));
    await saving;
  }
  return {init,binding,run,start,stop,get size(){return jobs.length;}};
}
