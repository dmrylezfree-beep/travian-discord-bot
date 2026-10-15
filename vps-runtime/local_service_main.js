import './runtime_network.js';
import worker from './defence-worker.js';
import {localSyncWorker} from './local_sync_worker.js';
import {makeSqliteQueue} from './sqlite_queue.js';
import {createLocalService} from './local_service.js';
import {once} from 'node:events';

if (process.env.DEFENCE_LOCAL_ENABLE !== 'approved') throw Error('Local service activation required');
process.umask(0o077);
const env = {DISCORD_BOT_TOKEN:process.env.DISCORD_BOT_TOKEN,
  TELEGRAM_BOT_TOKEN:process.env.DEFENCE_TELEGRAM_TOKEN};
for (const [key,value] of Object.entries(env)) if (!value) throw Error(`Missing ${key}`);
console.error = (...args) => {
  if (args.some(value => typeof value === 'string' && value.includes('ExperimentalWarning: SQLite'))) {
    process.stderr.write('Node.js marks SQLite experimental; queue initialization continues.\n');
  } else {
    process.stderr.write('Local defence operation failed; sensitive details suppressed.\n');
  }
};
// Bound requests so shutdown/retries cannot hang indefinitely on an external API.
const nativeFetch = globalThis.fetch;
globalThis.fetch = (url, options = {}) => nativeFetch(url, {...options,
  signal: options.signal ? AbortSignal.any([options.signal,AbortSignal.timeout(20000)]) : AbortSignal.timeout(20000)});
const tasks = new Set();
function background(promise) {
  const task=Promise.resolve(promise).catch(()=>console.error());
  tasks.add(task); task.finally(()=>tasks.delete(task));
}
const queue = makeSqliteQueue(localSyncWorker(worker),env,'/var/lib/travian-defence-local/jobs.sqlite');
env.DEFENCE_REMINDERS = queue.binding;
env.LOCAL_SYNC = () => queue.binding.send({type:"telegram_sync"});
const server = createLocalService(worker,env,background);
let stopping = false;
async function stop() {
  if (stopping) return;
  stopping = true;
  const deadline=setTimeout(()=>process.exit(1),23000); deadline.unref();
  await new Promise(resolve=>server.close(resolve));
  await Promise.allSettled([...tasks]);
  await queue.stop();
  clearTimeout(deadline);
}
try {
  server.listen(18788,'127.0.0.1');
  await once(server,'listening');
  queue.start();
  console.log('Local defence API and persistent queue ready on 127.0.0.1:18788.');
} catch {console.error();process.exitCode=1;await stop();}
for (const signal of ['SIGTERM','SIGINT']) process.on(signal,stop);
