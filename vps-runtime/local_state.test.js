import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {readState,saveState} from './local_state.js';
import {localSyncWorker} from './local_sync_worker.js';
import {makeSqliteQueue} from './sqlite_queue.js';
test('Node and Python share durable state; concurrent settings survive',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'travian-state-'));process.env.DEFENCE_DATA_DIR=dir;
 const path='data/defence/discord_players.json';
 try {
  const a=await readState(path),b=await readState(path);
  a.data.a={troops:1};b.data.b={troops:2};
  await Promise.all([saveState(path,a.data,a.sha),saveState(path,b.data,b.sha)]);
  assert.deepEqual((await readState(path)).data,{a:{troops:1},b:{troops:2}});
  await assert.rejects(()=>readState('../secret'));
 }finally{await rm(dir,{recursive:true,force:true});}
});
test('Telegram sync survives queue restart and retries failure',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'travian-sync-'));let now=0,attempts=0;
 const worker=localSyncWorker({},async()=>{if(++attempts===1)throw Error('offline');});
 let q=makeSqliteQueue(worker,{},join(dir,'q.sqlite'),{now:()=>now});
 try{
  await q.binding.send({type:'telegram_sync'});await q.stop();
  q=makeSqliteQueue(worker,{},join(dir,'q.sqlite'),{now:()=>now});
  await q.run();assert.equal(q.size,1);now=61000;await q.run();assert.equal(q.size,0);assert.equal(attempts,2);
 }finally{await q.stop();await rm(dir,{recursive:true,force:true});}
});
