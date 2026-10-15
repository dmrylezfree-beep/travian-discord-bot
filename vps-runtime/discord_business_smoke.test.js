import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import assert from 'node:assert/strict';
import {handleDiscordInteraction} from './defence-worker.js';

test('existing handler preserves registration, modal permissions and validation without external writes', async () => {
  const original = globalThis.fetch;
  const dir=await mkdtemp(join(tmpdir(),'travian-smoke-'));
  process.env.DEFENCE_DATA_DIR=dir;
  globalThis.fetch=async()=>{throw Error('Unexpected external dependency');};
  const base = {id: 'test', token: 'test-token', application_id: '1555623257724682402',
    guild_id: '1430982178074005507', channel_id: '1430982180401578153',
    member: {user: {id: 'test-user'}, permissions: '8192'}};
  const ctx = {waitUntil() {throw Error('Unexpected background mutation');}};
  const run = async patch => (await handleDiscordInteraction({...base, ...patch}, {}, ctx)).json();
  try {
    const def = await run({type: 2, data: {name: 'def'}});
    assert.equal(def.type, 4);
    assert.ok(def.data.components.length);
    for (const language of ['en', 'ja']) {
      const modal = await run({type: 3, data: {custom_id: `def_register_${language}`}});
      assert.equal(modal.type, 9);
      assert.equal(modal.data.custom_id, `def_coords_${language}`);
    }
    const create = await run({type: 3, data: {custom_id: 'def_create_en'}});
    assert.equal(create.type, 9);
    const denied = await run({type: 3, data: {custom_id: 'def_create_en'}, member: {...base.member, permissions: '0'}});
    assert.equal(denied.type, 4);
    assert.match(denied.data.content, /permission/i);
    const invalid = await run({type: 5, data: {custom_id: 'def_createval_en', components: []}});
    assert.equal(invalid.type, 4);
    assert.match(invalid.data.content, /Check coordinates/);

  } finally { globalThis.fetch = original; await rm(dir,{recursive:true,force:true}); }
});
