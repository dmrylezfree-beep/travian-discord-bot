import {DatabaseSync} from 'node:sqlite';
import {mkdirSync, chmodSync} from 'node:fs';
import {dirname} from 'node:path';
import {randomUUID} from 'node:crypto';

// At-least-once delivery. External messaging APIs cannot share our transaction.
export function makeSqliteQueue(worker, env, file, {now = Date.now, leaseMs = 120000} = {}) {
  mkdirSync(dirname(file), {recursive: true, mode: 0o700});
  const db = new DatabaseSync(file, {timeout: 5000});
  chmodSync(file, 0o600);
  db.exec(`PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
    CREATE TABLE IF NOT EXISTS jobs (
      id TEXT PRIMARY KEY, body TEXT NOT NULL, due INTEGER NOT NULL,
      tries INTEGER NOT NULL DEFAULT 0, owner TEXT, lease_until INTEGER NOT NULL DEFAULT 0
    ); CREATE INDEX IF NOT EXISTS jobs_due ON jobs(due,lease_until);`);
  const owner = randomUUID();
  let active;
  let timer;
  let closed = false;
  let stopping = false;
  const insert = db.prepare('INSERT INTO jobs(id,body,due) VALUES(?,?,?)');
  function prepare(body, options = {}) {
    if (closed || stopping) throw Error('Queue is stopping');
    const delay = Number(options.delaySeconds ?? 0);
    if (!Number.isFinite(delay) || delay < 0 || delay > 86400) throw Error('Invalid delay');
    const encoded = JSON.stringify(body);
    if (encoded === undefined || Buffer.byteLength(encoded) > 65536) throw Error('Invalid job body');
    return [randomUUID(), encoded, now() + Math.ceil(delay * 1000)];
  }
  const binding = {
    async send(body, options = {}) { insert.run(...prepare(body, options)); },
    async sendBatch(items) {
      const prepared = items.map(item => prepare(item.body, item.options));
      db.exec('BEGIN IMMEDIATE');
      try {
        for (const args of prepared) insert.run(...args);
        db.exec('COMMIT');
      } catch (error) { db.exec('ROLLBACK'); throw error; }
    },
  };
  function claim() {
    db.exec('BEGIN IMMEDIATE');
    try {
      const job = db.prepare('SELECT * FROM jobs WHERE due<=? AND lease_until<=? ORDER BY due,id LIMIT 1').get(now(), now());
      if (job) db.prepare('UPDATE jobs SET owner=?,lease_until=? WHERE id=?').run(owner, now() + leaseMs, job.id);
      db.exec('COMMIT');
      return job;
    } catch (error) { db.exec('ROLLBACK'); throw error; }
  }
  async function deliver() {
    for (let count = 0; count < 10 && !stopping; count++) {
      const job = claim();
      if (!job) return;
      let ack = false;
      let delay = 60;
      const heartbeat = setInterval(() => {
        try { db.prepare('UPDATE jobs SET lease_until=? WHERE id=? AND owner=?').run(now()+leaseMs, job.id, owner); }
        catch { console.error('Queue lease renewal failed'); }
      }, Math.max(100, Math.floor(leaseMs / 3)));
      try {
        await worker.queue({messages: [{body: JSON.parse(job.body),
          ack() { ack = true; },
          retry(options = {}) {
            ack = false;
            const value = Number(options.delaySeconds ?? 60);
            delay = Number.isFinite(value) && value > 0 ? Math.min(value, 86400) : 60;
          },
        }]}, env);
      } catch { ack = false; }
      finally { clearInterval(heartbeat); }
      if (ack) db.prepare('DELETE FROM jobs WHERE id=? AND owner=?').run(job.id, owner);
      else db.prepare('UPDATE jobs SET tries=tries+1,due=?,owner=NULL,lease_until=0 WHERE id=? AND owner=?')
        .run(now() + delay * 1000, job.id, owner);
    }
  }
  function run() {
    if (closed || stopping) return Promise.resolve();
    if (active) return active;
    active = deliver().finally(() => {active = undefined;});
    return active;
  }
  function start() {
    if (timer || closed || stopping) throw Error('Queue cannot start');
    timer = setInterval(() => run().catch(() => console.error('Queue processing failed')), 1000);
  }
  async function stop() {
    stopping = true;
    clearInterval(timer);
    if (active) await active;
    if (!closed) { db.close(); closed = true; }
  }
  return {binding, run, start, stop,
    get size() { return db.prepare('SELECT count(*) AS total FROM jobs').get().total; }};
}
