// Keep command/button/modal behavior in the existing Worker handler.
export function makeGatewayBridge({handleInteraction, env, callback}) {
  const inFlight = new Map();
  const seen = new Map();
  return async function receive(payload) {
    if (!payload?.id || !payload?.token) throw Error('Missing interaction identity');
    if (seen.has(payload.id)) return;
    if (inFlight.has(payload.id)) return inFlight.get(payload.id);
    const task = (async () => {
      const background = [];
      const ctx = {waitUntil(promise) {
        // Observe rejections immediately, without logging interaction tokens.
        background.push(Promise.resolve(promise).then(() => true, () => false));
      }};
      try {
        const response = await handleInteraction(payload, env, ctx);
        if (!response.ok) throw Error(`Handler status ${response.status}`);
        const body = await response.json();
        await callback(payload.id, payload.token, body);
        seen.set(payload.id, Date.now());
      } finally {
        await Promise.all(background);
      }
    })();
    inFlight.set(payload.id, task);
    try { await task; }
    finally {
      inFlight.delete(payload.id);
      const expiry = Date.now() - 15 * 60 * 1000;
      for (const [id, time] of seen) if (time < expiry) seen.delete(id);
    }
  };
}
