import test from 'node:test';
import assert from 'node:assert/strict';
import {once} from 'node:events';
import {createLocalService} from './local_service.js';

test('local API restricts routes, authentication and input before calling Worker', async () => {
  let calls = 0;
  const server = createLocalService({async fetch(request) {
    calls++; assert.equal(request.headers.get('authorization'), 'Bearer test');
    return Response.json({ok:true});
  }}, {TELEGRAM_BOT_TOKEN:'test'}, () => {});
  server.listen(0,'127.0.0.1'); await once(server,'listening');
  const url = `http://127.0.0.1:${server.address().port}`;
  const post = (path, body, auth = 'Bearer test') => fetch(url+path,{method:'POST',body,headers:{Authorization:auth}});
  try {
    assert.equal((await post('/schedule-reminders','{}','Bearer wrong')).status,401);
    assert.equal((await post('/setWebhook','{}')).status,404);
    assert.equal((await post('/discord','{}')).status,404);
    assert.equal((await post('/discord/request-sync','bad')).status,400);
    assert.equal((await post('/schedule-reminders','x'.repeat(1024*1024+1))).status,413);
    assert.equal(calls,0);
    assert.equal((await post('/discord/refresh','')).status,200);
    assert.equal((await post('/schedule-reminders','{"reminders":[]}')).status,200);
    assert.equal(calls,2);
  } finally {server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
});
