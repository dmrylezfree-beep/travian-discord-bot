// New reminders are durably accepted by the local VPS service.
export function makeCloudflareQueue(env, request = fetch) {
  if (!env.TELEGRAM_BOT_TOKEN) throw Error('Missing queue authentication');
  return {async send(body) {
    if (!body || typeof body.reminder_at !== 'string') throw Error('Missing reminder_at');
    // Local service computes delay from the original reminder_at.
    const response = await request('http://127.0.0.1:18788/schedule-reminders', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', Authorization: `Bearer ${env.TELEGRAM_BOT_TOKEN}`},
      body: JSON.stringify({reminders: [body]}), signal: AbortSignal.timeout(15000),
    });
    if (!response.ok) throw Error(`Queue HTTP ${response.status}`);
    const result = await response.json();
    if (result.ok !== true || result.scheduled !== 1) throw Error('Queue did not confirm scheduling');
  }};
}
