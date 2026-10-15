import test from 'node:test';
import assert from 'node:assert/strict';
import './runtime_network.js';
test('runtime refuses GitHub and Cloudflare dependencies without network access',async()=>{
 for(const host of ['api.github.com','raw.githubusercontent.com','travian-defence.dmrylezfree.workers.dev']){
  await assert.rejects(fetch('https://'+host+'/'),/External state dependency disabled/);
 }
});
