import test from "node:test";
import assert from "node:assert/strict";
import {mkdtemp,rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {makeDefenceQueue} from "./discord_defence_queue_vps.js";

test("jobs survive restart and are acknowledged exactly once in normal execution", async () => {
  const dir = await mkdtemp(join(tmpdir(),"travian-defence-queue-"));
  const file = join(dir,"queue.json");
  const delivered = [];
  const worker = {
    async queue(batch) {
      for (const message of batch.messages) {
        delivered.push(message.body.id);
        message.ack();
      }
    }
  };
  try {
    const first = makeDefenceQueue(worker,{},file);
    await first.init();
    await first.binding.send({id:101},{delaySeconds:0});
    assert.equal(first.size,1);
    const second = makeDefenceQueue(worker,{},file);
    await second.init();
    assert.equal(second.size,1);
    await second.run();
    assert.deepEqual(delivered,[101]);
    assert.equal(second.size,0);
    const third = makeDefenceQueue(worker,{},file);
    await third.init();
    assert.equal(third.size,0);
  } finally {
    await rm(dir,{recursive:true,force:true});
  }
});

test("failed delivery is retained for retry", async () => {
  const dir = await mkdtemp(join(tmpdir(),"travian-defence-retry-"));
  const file = join(dir,"queue.json");
  const worker = {async queue(){throw Error("temporary outage");}};
  try {
    const queue = makeDefenceQueue(worker,{},file);
    await queue.init();
    await queue.binding.send({kind:"discord_request_expiry",request_id:5});
    await queue.run();
    assert.equal(queue.size,1);
    const restored = makeDefenceQueue(worker,{},file);
    await restored.init();
    assert.equal(restored.size,1);
  } finally {
    await rm(dir,{recursive:true,force:true});
  }
});
