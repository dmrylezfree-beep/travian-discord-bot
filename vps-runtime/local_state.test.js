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

test('Telegram request-sync retries preserve one committed request and its contributions',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'travian-confirm-'));const oldDir=process.env.DEFENCE_DATA_DIR;process.env.DEFENCE_DATA_DIR=dir;
 const oldFetch=globalThis.fetch;globalThis.fetch=async()=>{throw Error('fixture external calls disabled');};
 const env={TELEGRAM_BOT_TOKEN:'fixture',DEFENCE_REMINDERS:{send:async()=>{}}};const background=[];
 const ctx={waitUntil(p){background.push(Promise.resolve(p).catch(()=>{}));}};
 const incoming={id:null,submission_key:'telegram:-100:111:55',requester_id:55,target_x:15,target_y:3,attack_time:'2030-01-02 22:00:00',required_def:2000,status:'active'};
 const submit=async()=>{
  const response=await worker.fetch(new Request('http://127.0.0.1/discord/request-sync',{method:'POST',headers:{Authorization:'Bearer fixture','Content-Type':'application/json'},body:JSON.stringify({request:incoming})}),env,ctx);
  assert.equal(response.status,200);return response.json();
 };
 try{
  const first=await submit();const current=await readState('data/defence/requests.json');current.data[0].contributions=[{user_id:99,def_points:100}];current.data[0].collected_def=100;await saveState('data/defence/requests.json',current.data,current.sha);
  const second=await submit();assert.equal(first.request.id,second.request.id);assert.equal(second.request.collected_def,100);
  const saved=await readState('data/defence/requests.json');assert.equal(saved.data.length,1);assert.equal(saved.data[0].contributions.length,1);
  await Promise.allSettled(background);
 }finally{globalThis.fetch=oldFetch;if(oldDir===undefined)delete process.env.DEFENCE_DATA_DIR;else process.env.DEFENCE_DATA_DIR=oldDir;await rm(dir,{recursive:true,force:true});}
});

import {targetLink,defenceMentionRoles} from './defence-worker.js';
test('target links point to the current world and validate coordinates',()=>{
 assert.equal(targetLink({target_x:-15,target_y:3}),'[-15|3](https://ts8.x1.asia.travian.com/karte.php?x=-15&y=3)');
 for(const q of [{target_x:null,target_y:3},{target_x:201,target_y:0},{target_x:'[bad]',target_y:3}])assert.equal(targetLink(q),'—');
});
test('defence alerts select all four requested roles without unrelated mentions',()=>{
 const selected=defenceMentionRoles([{id:'4',name:'Defender'},{id:'5',name:'Everyone Else'},{id:'2',name:' MANAGER '},{id:'1',name:'Leader'},{id:'3',name:'attacker'}]);
 assert.deepEqual(selected.map(r=>r.id),['1','2','3','4']);
});
test('new request pings the four roles once; subsequent refreshes only update links',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'travian-mentions-'));const oldDir=process.env.DEFENCE_DATA_DIR,oldFetch=globalThis.fetch;process.env.DEFENCE_DATA_DIR=dir;
 let thread=false,card=false;const pings=[];let centre='',starter='',cardContent='';const author={id:'1555623257724682402'};
 const q={id:9,status:'active',target_x:-15,target_y:3,attack_time:'2031-01-02 12:00:00',required_def:1000,collected_def:0};
 globalThis.fetch=async(url,options={})=>{
  assert.ok(String(url).startsWith('https://discord.com/api/v10/'));const path=String(url).split('/api/v10')[1],method=options.method||'GET';const body=options.body?JSON.parse(options.body):{};let result;
  if(path.endsWith('/roles'))result=['Leader','Manager','Attacker','Defender','Other'].map((name,i)=>({id:String(i+1),name}));
  else if(path.endsWith('/threads/active'))result={threads:thread?[{id:'thread',name:'🛡 DEF #9 — -15|3',thread_metadata:{archived:false}}]:[]};
  else if(path.includes('/threads/archived/public'))result={threads:[]};
  else if(path.endsWith('/pins')&&method==='GET')result=[{id:'centre',author,content:'🛡 **WORLD Defence**'}];
  else if(path.endsWith('/messages/centre')&&method==='PATCH'){centre=body.content;result={id:'centre'};}
  else if(path.endsWith('/pins/centre')&&method==='PUT')result={};
  else if(path==='/channels/1430982180401578153/messages'&&method==='POST'){starter=body.content;result={id:'starter'};}
  else if(path.endsWith('/messages/starter/threads')&&method==='POST'){thread=true;result={id:'thread'};}
  else if(path==='/channels/thread/messages'&&method==='POST'){
   if(body.content.includes('<@&'))pings.push(body);else{card=true;cardContent=body.content;}result={id:'card'};
  }else if(path==='/channels/thread/messages?limit=50')result=card?[{id:'card',author,content:'🛡 **DEFENCE REQUEST #9'}]:[];
  else if(path==='/channels/thread/messages/card'&&method==='PATCH'){cardContent=body.content;result={id:'card'};}
  else throw Error('Unexpected external operation '+method+' '+path);
  return Response.json(result);
 };
 try{
  await saveState('data/defence/requests.json',[q],[]);const env={DISCORD_BOT_TOKEN:'fixture',LOCAL_SYNC:async()=>{}};
  const signature=await reconcileDefenceRequests(env);await reconcileDefenceRequests(env,signature);await reconcileDefenceRequests(env);
  assert.equal(pings.length,1);assert.deepEqual(pings[0].allowed_mentions,{parse:[],roles:['1','2','3','4']});
  assert.equal(pings[0].content.startsWith('<@&1> <@&2> <@&3> <@&4>'),true);
  for(const content of [centre,starter,cardContent])assert.ok(content.includes(targetLink(q)));
 }finally{globalThis.fetch=oldFetch;if(oldDir===undefined)delete process.env.DEFENCE_DATA_DIR;else process.env.DEFENCE_DATA_DIR=oldDir;await rm(dir,{recursive:true,force:true});}
});
