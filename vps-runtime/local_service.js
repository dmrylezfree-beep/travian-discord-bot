import http from 'node:http';
import {timingSafeEqual} from 'node:crypto';

const routes = new Set(['/schedule-reminders', '/discord/request-sync', '/discord/refresh', '/telegram/sync']);
export function createLocalService(worker, env, background) {
  if (!env.TELEGRAM_BOT_TOKEN) throw Error('Missing local service authentication');
  const expected = Buffer.from('Bearer ' + env.TELEGRAM_BOT_TOKEN);
  return http.createServer({requestTimeout: 15000, headersTimeout: 10000}, async (req, res) => {
    const reply = (status, body) => {
      res.writeHead(status, {'content-type': 'application/json'});
      res.end(JSON.stringify(body));
    };
    if (req.method !== 'POST' || !routes.has(req.url)) return reply(404, {error: 'not_found'});
    const received = Buffer.from(req.headers.authorization || '');
    if (received.length !== expected.length || !timingSafeEqual(received, expected)) return reply(401, {error: 'unauthorized'});
    try {
      const chunks = [];
      let length = 0;
      for await (const chunk of req) {
        length += chunk.length;
        if (length > 1024 * 1024) return reply(413, {error: 'too_large'});
        chunks.push(chunk);
      }
      let body = Buffer.concat(chunks);
      if (req.url === '/discord/refresh' && body.length === 0) body = Buffer.from('{}');
      try { JSON.parse(body.toString('utf8')); } catch { return reply(400, {error: 'invalid_json'}); }
      if (req.url === '/telegram/sync') { await env.LOCAL_SYNC(); return reply(202, {ok:true}); }
      const response = await worker.fetch(new Request('http://127.0.0.1' + req.url, {
        method: 'POST', headers: {Authorization: req.headers.authorization, 'Content-Type': 'application/json'}, body,
      }), env, {waitUntil: background});
      if (!response.ok) return reply(response.status, {error: 'handler_failed'});
      res.writeHead(response.status, {'content-type': 'application/json'});
      res.end(Buffer.from(await response.arrayBuffer()));
    } catch { if (!res.headersSent) reply(500, {error: 'internal_error'}); else res.end(); }
  });
}
