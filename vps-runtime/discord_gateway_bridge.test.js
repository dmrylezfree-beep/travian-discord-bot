import test from 'node:test';
import assert from 'node:assert/strict';
import {makeGatewayBridge} from './discord_gateway_bridge.js';
import {handleDiscordInteraction} from './defence-worker.js';

test('gateway preserves command, component and modal payloads and responses', async () => {
  for (const [type, responseType] of [[2, 4], [3, 9], [5, 5]]) {
    let count = 0;
    const payload = {id: String(type), token: 'test-token', type, data: {custom_id: 'original'}};
    const expected = {type: responseType, data: {content: 'response', flags: 64}};
    const receive = makeGatewayBridge({env: {}, handleInteraction: async input => {
      count++;
      assert.equal(input, payload);
      return Response.json(expected);
    }, callback: async (id, token, body) => {
      assert.equal(id, payload.id);
      assert.equal(token, payload.token);
      assert.deepEqual(body, expected);
    }});
    await Promise.all([receive(payload), receive(payload)]);
    await receive(payload);
    assert.equal(count, 1);
  }
});

test('real Worker rejects an unrelated guild through Gateway without external calls', async () => {
  const result = await handleDiscordInteraction({type: 2, guild_id: 'unrelated'}, {}, {waitUntil() { throw Error('Unexpected task'); }});
  const body = await result.json();
  assert.equal(body.type, 4);
  assert.match(body.data.content, /WORLD/);
});

test('callback failure is reported and does not mark delivery successful', async () => {
  let attempts = 0;
  const receive = makeGatewayBridge({env: {}, handleInteraction: async () => Response.json({type: 5}),
    callback: async () => { if (++attempts === 1) throw Error('offline'); }});
  const payload = {id: 'retry-test', token: 'test-token'};
  await assert.rejects(receive(payload), /offline/);
  await receive(payload);
  assert.equal(attempts, 2);
});
