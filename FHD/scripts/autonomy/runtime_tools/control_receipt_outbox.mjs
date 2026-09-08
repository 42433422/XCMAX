/** Minimal progress spool. Remove only after the server acknowledges the event. */
import { createHash, randomUUID } from 'node:crypto';
import { mkdirSync, readFileSync, readdirSync, renameSync, unlinkSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const canonical = (row) => JSON.stringify(Object.fromEntries(Object.entries(row).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)));
export function createReceiptOutbox({ directory, url, token, deviceId, fetcher = fetch }) {
  const links = new Map();
  let draining = false;
  const active = Boolean(directory && url && token && deviceId);
  if (active) mkdirSync(directory, { recursive: true, mode: 0o700 });
  function bind(message) {
    const match = String(message.title || '').match(/\[xcmax:([0-9a-f]{32}):([0-9a-f]{32})\]/);
    if (match) links.set(message.task_id, { correlation_id: match[1], attempt_id: match[2] });
  }
  function record(payload) {
    if (!active || payload.type !== 'task_progress') return;
    const link = links.get(payload.task_id);
    if (!link || !payload.subtask_id || !payload.status) return;
    const row = { ...link, device_id: deviceId, task_id: payload.task_id, subtask_id: payload.subtask_id,
      status: String(payload.status), progress: Math.max(0, Math.min(100, Math.round(Number(payload.progress) || 0))) };
    const event_id = createHash('sha256').update(canonical(row)).digest('hex');
    const temporary = join(directory, `.${randomUUID()}.pending`);
    writeFileSync(temporary, JSON.stringify({ ...row, event_id }), { mode: 0o600, flush: true });
    renameSync(temporary, join(directory, `${event_id}.json`));
  }
  async function drain() {
    if (!active || draining) return;
    draining = true;
    try {
      for (const file of readdirSync(directory).filter((name) => /^[0-9a-f]{64}\.json$/.test(name)).slice(0, 20)) {
        const path = join(directory, file);
        try {
          const response = await fetcher(url, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: readFileSync(path, 'utf8'), signal: AbortSignal.timeout(5000) });
          if (response.ok && (await response.json()).accepted === true) unlinkSync(path);
          else break;
        } catch { break; }
      }
    } finally { draining = false; }
  }
  return { bind, record, drain };
}
