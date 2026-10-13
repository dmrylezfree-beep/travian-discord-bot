// STAGING_SYNC_CHECK_20261013: harmless marker to verify automatic VPS refresh.
import test from "node:test";
import assert from "node:assert/strict";
import { generateKeyPairSync, sign } from "node:crypto";
import { verifyDiscordRequest } from "./defence-worker.js";

test("valid Ed25519 Discord signature is accepted", async () => {
  const { publicKey, privateKey } = generateKeyPairSync("ed25519");
  const publicKeyHex = publicKey.export({format:"der",type:"spki"}).subarray(-32).toString("hex");
  const timestamp = String(Math.floor(Date.now()/1000));
  const body = '{"type":1}';
  const signature = sign(null,Buffer.from(timestamp+body),privateKey).toString("hex");
  const request = new Request("http://localhost/discord",{
    method:"POST",
    headers:{"X-Signature-Ed25519":signature,"X-Signature-Timestamp":timestamp},
    body
  });
  assert.equal(await verifyDiscordRequest(request,body,publicKeyHex),true);
  assert.equal(await verifyDiscordRequest(request,'{"type":2}',publicKeyHex),false);
});

test("missing signature is rejected", async () => {
  const request = new Request("http://localhost/discord",{method:"POST",body:'{"type":1}'});
  assert.equal(await verifyDiscordRequest(request,'{"type":1}'),false);
});
