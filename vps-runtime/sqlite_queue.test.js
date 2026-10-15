import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
import {makeSqliteQueue} from './sqlite_queue.js';

test('queue persists delayed jobs, retries failure and removes acknowledged jobs', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'travian-sqlite-'));
  const file = join(dir, 'jobs.db');
  let clock = 100000;
  let fail = true;
  let delivered = 0;
  const worker = {async queue(batch) {
    if (fail) throw Error('fake outage');
    delivered++; batch.messages[0].ack();
  }};
  let q = makeSqliteQueue(worker, {}, file, {now: () => clock});
  try {
    await q.binding.send({id: 1}, {delaySeconds: 10});
    await q.run(); assert.equal(delivered, 0);
    await q.stop();
    q = makeSqliteQueue(worker, {}, file, {now: () => clock});
    assert.equal(q.size, 1);
    clock += 10000; await q.run(); assert.equal(q.size, 1);
    fail = false; clock += 60000; await q.run();
    assert.equal(delivered, 1); assert.equal(q.size, 0);
  } finally { await q.stop(); await rm(dir, {recursive: true, force: true}); }
});

test('concurrent producers and consumers do not overwrite or simultaneously deliver jobs', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'travian-concurrent-'));
  const file = join(dir, 'jobs.db');
  const delivered = [];
  const worker = {async queue(batch) {
    await new Promise(r => setTimeout(r, 5));
    delivered.push(batch.messages[0].body.id); batch.messages[0].ack();
  }};
  const a = makeSqliteQueue(worker, {}, file), b = makeSqliteQueue(worker, {}, file);
  try {
    await Promise.all(Array.from({length: 20}, (_, id) => (id % 2 ? a : b).binding.send({id})));
    await Promise.all([a.run(), b.run(), a.run()]);
    assert.equal(new Set(delivered).size, 20); assert.equal(delivered.length, 20); assert.equal(a.size, 0);
  } finally { await a.stop(); await b.stop(); await rm(dir, {recursive: true, force: true}); }
});

test('invalid batch leaves no partially queued jobs', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'travian-batch-'));
  const q = makeSqliteQueue({}, {}, join(dir, 'jobs.db'));
  try {
    await assert.rejects(q.binding.sendBatch([{body: {id:1}}, {body: {id:2}, options: {delaySeconds: -1}}]));
    assert.equal(q.size, 0);
  } finally { await q.stop(); await rm(dir, {recursive: true, force: true}); }
});

test('lease from a crashed consumer is recovered after expiration', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'travian-crash-'));
  const file = join(dir, 'jobs.db');
  const module = new URL('./sqlite_queue.js', import.meta.url).href;
  const source = `import {makeSqliteQueue} from ${JSON.stringify(module)};
    const q=makeSqliteQueue({async queue(){process.exit(0)}},{},${JSON.stringify(file)},{now:()=>1000,leaseMs:10000});
    await q.binding.send({id:1}); await q.run();`;
  const result = spawnSync(process.execPath, ['--input-type=module', '-e', source], {timeout: 10000});
  assert.equal(result.status, 0);
  let clock = 5000, delivered = 0;
  const q = makeSqliteQueue({async queue(batch){delivered++;batch.messages[0].ack();}}, {}, file, {now:()=>clock});
  try {
    await q.run(); assert.equal(delivered, 0);
    clock = 12000; await q.run(); assert.equal(delivered, 1); assert.equal(q.size, 0);
  } finally { await q.stop(); await rm(dir, {recursive: true, force: true}); }
});
