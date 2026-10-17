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

import worker,{parseServerTime,formatServerTime,queueDiscordExpiry,reconcileDefenceRequests} from './defence-worker.js';
test('game time is UTC in both summer and winter; expiry has no extra delay',async()=>{
 const oldNow=Date.now;Date.now=()=>Date.parse('2026-10-17T11:59:00Z');
 try{
  for(const value of ['2026-01-17 12:00:00','2026-10-17 12:00:00']){
   assert.equal(parseServerTime(value),Date.parse(value.replace(' ','T')+'Z'));
   assert.equal(formatServerTime(parseServerTime(value)),value);
  }
  const sent=[];await queueDiscordExpiry({DEFENCE_REMINDERS:{send:async(...args)=>sent.push(args)}},{id:13,attack_time:'2026-10-17 12:00:00'});
  assert.equal(sent[0][0].reminder_at,'2026-10-17 12:00:00');assert.equal(sent[0][1].delaySeconds,60);
 }finally{Date.now=oldNow;}
});
test('expiry reconciles existing Discord threads, retries committed expiry, and retains future Telegram requests',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'travian-expiry-'));const oldDir=process.env.DEFENCE_DATA_DIR;
 const oldFetch=globalThis.fetch,oldNow=Date.now;process.env.DEFENCE_DATA_DIR=dir;
 let now=Date.parse('2026-10-17T11:30:00Z'),archived=false,failArchive=false,syncs=0,acks=0,retries=0;
 let centre='',calls=0,cardBody;Date.now=()=>now;
 const q={id:13,status:'active',attack_time:'2026-10-17 12:00:00',target_x:13,target_y:3,required_def:1000,collected_def:0};
 const author={id:'1555623257724682402'};
 const env={DISCORD_BOT_TOKEN:'fixture',LOCAL_SYNC:async()=>{syncs++;}};
 globalThis.fetch=async(url,options={})=>{
  calls++;assert.ok(String(url).startsWith('https://discord.com/api/v10/'));
  const path=String(url).split('/api/v10')[1],method=options.method||'GET';
  const thread={id:'thread',name:'🛡 DEF #13 — 13|3',thread_metadata:{archived}};
  let data;
  if(path.endsWith('/roles'))data=[];
  else if(path.endsWith('/threads/active'))data={threads:archived?[]:[thread]};
  else if(path.includes('/threads/archived/public'))data={threads:archived?[thread]:[]};
  else if(path.endsWith('/pins')&&method==='GET')data=[{id:'centre',author,content:'🛡 **WORLD Defence**'}];
  else if(path.endsWith('/messages/centre')&&method==='PATCH'){centre=JSON.parse(options.body).content;data={id:'centre'};}
  else if(path.endsWith('/pins/centre')&&method==='PUT')data={};
  else if(path==='/channels/thread/messages?limit=50')data=[{id:'card',author,content:'🛡 **DEFENCE REQUEST #13'}];
  else if(path==='/channels/thread/messages/card'&&method==='PATCH'){cardBody=JSON.parse(options.body);data={id:'card'};}
  else if(path==='/channels/thread'&&method==='PATCH'){
   if(failArchive)return new Response('fixture unavailable',{status:503});
   archived=JSON.parse(options.body).archived;data={id:'thread'};
  }else throw Error('Unexpected external request: '+method+' '+path);
  return Response.json(data);
 };
 const message=()=>({body:{kind:'discord_request_expiry',request_id:13},ack(){acks++;},retry(){retries++;}});
 try{
  await saveState('data/defence/requests.json',[q],[]);
  let signature=await reconcileDefenceRequests(env);
  assert.match(centre,/#13/);assert.equal((await readState('data/defence/requests.json')).data[0].status,'active');
  const previousCalls=calls;signature=await reconcileDefenceRequests(env,signature);assert.equal(calls,previousCalls);
  now=Date.parse('2026-10-17T12:00:00Z');failArchive=true;
  await assert.rejects(()=>reconcileDefenceRequests(env,signature));
  assert.equal((await readState('data/defence/requests.json')).data[0].status,'expired');assert.equal(archived,false);
  await worker.queue({messages:[message()]},env);assert.equal(retries,1);assert.equal(acks,0);
  failArchive=false;await worker.queue({messages:[message()]},env);
  assert.equal(acks,1);assert.equal(archived,true);assert.deepEqual(cardBody.components,[]);assert.match(cardBody.content,/EXPIRED/);
  signature=await reconcileDefenceRequests(env,signature);assert.ok(syncs>0);assert.doesNotMatch(centre,/#13/);
  const doneCalls=calls;await reconcileDefenceRequests(env,signature);assert.equal(calls,doneCalls);
  // Missing queue job: periodic reconciliation alone expires and archives.
  const state=await readState('data/defence/requests.json');state.data[0].status='active';await saveState('data/defence/requests.json',state.data,state.sha);archived=false;
  await reconcileDefenceRequests(env);assert.equal(archived,true);assert.equal((await readState('data/defence/requests.json')).data[0].status,'expired');
 }finally{
  globalThis.fetch=oldFetch;Date.now=oldNow;
  if(oldDir===undefined)delete process.env.DEFENCE_DATA_DIR;else process.env.DEFENCE_DATA_DIR=oldDir;
  await rm(dir,{recursive:true,force:true});
 }
});
