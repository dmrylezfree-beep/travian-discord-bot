import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import worker from './defence-worker.js';
import {makeSqliteQueue} from './sqlite_queue.js';

test('Worker accepts entire reminder batch durably or rejects without partial insert', async () => {
  const dir=await mkdtemp(join(tmpdir(),'travian-integration-'));
  const env={TELEGRAM_BOT_TOKEN:'test'};
  const q=makeSqliteQueue(worker,env,join(dir,'jobs.sqlite'));
  env.DEFENCE_REMINDERS=q.binding;
  const send=reminders=>worker.fetch(new Request('http://localhost/schedule-reminders',{
    method:'POST',headers:{Authorization:'Bearer test','content-type':'application/json'},body:JSON.stringify({reminders}),
  }),env,{});
  try {
    const result=await send([{reminder_at:'2026-12-10 12:00:00'},{reminder_at:'bad-date'}]);
    assert.equal(result.status,400); assert.equal(q.size,0);
    const good=await send([{reminder_at:'2026-12-10 12:00:00'}]);
    assert.equal(good.status,200); assert.equal(q.size,1);
  } finally {await q.stop();await rm(dir,{recursive:true,force:true});}
});
