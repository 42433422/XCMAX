/** Minimal progress spool. Remove only after the server acknowledges the event. */
import { createHash, randomUUID } from 'node:crypto';
import { mkdirSync, readFileSync, readdirSync, renameSync, statSync, unlinkSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const canonical = (row) => JSON.stringify(row, (_key, value) => value && !Array.isArray(value) && typeof value === 'object'
  ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)) : value);
export function createReceiptOutbox({ directory, url, token, deviceId, fetcher = fetch }) {
  const links = new Map();
  let draining = false;
  let polling = false;
  const active = Boolean(directory && url && token && deviceId);
  if (active) mkdirSync(directory, { recursive: true, mode: 0o700 });
  const key = task => JSON.stringify([task.task_id, task.subtask_id]);
  const terminal = row => ['completed', 'failed', 'cancelled'].includes(row?.status);
  function bind(message) {
    const match = String(message.title || '').match(/^\[xcmax:([0-9a-f]{32}):([0-9a-f]{32})\]/);
    if (!active || !match || !message.task_id || !message.subtask_id) return;
    const identity = { correlation_id: match[1], attempt_id: match[2], device_id: deviceId,
      task_id: message.task_id, subtask_id: message.subtask_id };
    const previous = links.get(key(message));
    if (previous) {
      if (canonical(previous.identity) !== canonical(identity)) throw new Error('control_task_identity_changed');
      return;
    }
    links.set(key(message), { identity, controller: new AbortController(), closed: false });
    record({ ...message, type: 'task_progress', status: 'queued', progress: 0 });
  }
  function record(payload) {
    if (!active || payload.type !== 'task_progress') return;
    const link = links.get(key(payload));
    if (!link || !payload.subtask_id || !payload.status) return;
    const row = { ...link.identity, status: String(payload.status),
      progress: Math.max(0, Math.min(100, Math.round(Number(payload.progress) || 0))),
      ...(payload.cancellation ? { cancellation: payload.cancellation } : {}) };
    const event_id = createHash('sha256').update(canonical(row)).digest('hex');
    const temporary = join(directory, `.${randomUUID()}.pending`);
    writeFileSync(temporary, JSON.stringify({ ...row, event_id }), { mode: 0o600, flush: true });
    renameSync(temporary, join(directory, `${event_id}.json`));
    link.latest = { ...row, event_id };
    if (terminal(row)) link.closed = true;
  }
  async function deliver(row) {
    const response = await fetcher(url, { method: 'POST', headers: { 'Content-Type': 'application/json',
      Authorization: `Bearer ${token}` }, body: JSON.stringify(row), signal: AbortSignal.timeout(5000) });
    const result = response.ok ? await response.json() : null;
    if (result?.accepted !== true) throw new Error('control_receipt_unacknowledged');
    const link = links.get(key(row));
    const control = result.control;
    if (link && !link.closed && control?.action === 'cancel' && /^[0-9a-f]{64}$/.test(control.intent_id || '')
        && Object.entries(link.identity).every(([field, value]) => row[field] === value && control[field] === value)
        && (!link.control || link.control.intent_id === control.intent_id)) {
      link.control = Object.freeze({ ...control });
      link.controller.abort(new Error('control_cancel_requested'));
    }
    return true;
  }
  async function check(task) {
    const link = links.get(key(task));
    if (!active || !link || link.closed) return;
    // Repeat the same observed receipt to read current authority. Dedupe must
    // never cache a pre-cancel response or replay the original executor.
    await deliver(link.latest);
  }
  async function poll() {
    if (!active || polling) return;
    polling = true;
    try {
      await Promise.all([...links.values()].filter(link => !link.closed)
        .map(link => deliver(link.latest).catch(() => {})));
    } finally { polling = false; }
  }
  async function drain() {
    if (!active || draining) return;
    draining = true;
    try {
      for (const file of readdirSync(directory).filter((name) => /^[0-9a-f]{64}\.json$/.test(name)).slice(0, 20)) {
        const path = join(directory, file);
        try {
          await deliver(JSON.parse(readFileSync(path, 'utf8')));
          unlinkSync(path);
        } catch { break; }
      }
    } finally { draining = false; }
  }
  return { bind, record, drain, check, poll,
    signal: task => links.get(key(task))?.controller.signal,
    cancellation: task => links.get(key(task))?.control,
    finish: task => { const link = links.get(key(task)); if (link) link.closed = true; } };
}

/** Authoritative Para reports use a separate device-authenticated, idempotent endpoint. */
export function createParaReportOutbox({ directory, url, token, enabled, fetcher = fetch }) {
  const links = new Map();
  let draining = false;
  let sequence = 0;
  const active = Boolean(enabled && directory && url && token);
  if (active) {
    mkdirSync(directory, { recursive: true, mode: 0o700 });
    try { sequence = Number(readFileSync(join(directory, '.sequence'), 'utf8')) || 0; } catch { /* first start */ }
  }
  function bind(task) {
    if (/^\[xcmax:[0-9a-f]{32}:[0-9a-f]{32}\]/.test(String(task.title || ''))) {
      links.set(`${task.task_id}:${task.subtask_id}`, Number(task.attempt) || 1);
    }
  }
  function handles(task) { return active && links.has(`${task.task_id}:${task.subtask_id}`); }
  function claimExecution(task) {
    if (!handles(task)) return true;
    const key = createHash('sha256').update(`${task.task_id}:${task.subtask_id}:${links.get(`${task.task_id}:${task.subtask_id}`)}`).digest('hex');
    try {
      writeFileSync(join(directory, `.execution-${key}`), JSON.stringify({ task_id: task.task_id, subtask_id: task.subtask_id }),
        { flag: 'wx', mode: 0o600, flush: true });
      return true;
    } catch (error) { if (error.code === 'EEXIST') return false; throw error; }
  }
  function record(task, { status, progress, content = '' }) {
    if (!handles(task) || !['running', 'completed', 'failed'].includes(status)) return false;
    sequence = Math.max(sequence + 1, Date.now() * 1000);
    const report = String(content).replace(/(bearer\s+|(?:api[_-]?key|password|token|secret)\s*[:=]\s*)[^\s,;]+/gi, '$1[redacted]').slice(0, 12000);
    const row = { task_id: task.task_id, subtask_id: task.subtask_id,
      attempt: links.get(`${task.task_id}:${task.subtask_id}`), sequence, status,
      progress: Math.max(0, Math.min(100, Math.round(Number(progress) || 0))), report };
    const event_id = createHash('sha256').update(canonical(row)).digest('hex');
    const temporary = join(directory, `.${randomUUID()}.pending`);
    writeFileSync(join(directory, '.sequence'), String(sequence), { mode: 0o600, flush: true });
    writeFileSync(temporary, JSON.stringify({ ...row, event_id }), { mode: 0o600, flush: true });
    renameSync(temporary, join(directory, `${event_id}.json`));
    return true;
  }
  async function drain() {
    if (!active || draining) return;
    draining = true;
    try {
      const rows = readdirSync(directory).filter(name => /^[0-9a-f]{64}\.json$/.test(name))
        .map(name => ({ name, body: JSON.parse(readFileSync(join(directory, name), 'utf8')) }))
        .sort((a, b) => a.body.sequence - b.body.sequence).slice(0, 20);
      for (const { name, body } of rows) {
        try {
          const response = await fetcher(url, { method: 'POST', headers: { 'Content-Type': 'application/json',
            Authorization: `Bearer ${token}` }, body: JSON.stringify(body), signal: AbortSignal.timeout(5000) });
          if (response.ok && (await response.json()).accepted === true) unlinkSync(join(directory, name));
          else break;
        } catch { break; }
      }
    } finally { draining = false; }
  }
  return { bind, handles, record, drain, claimExecution };
}


/** Local managed login for legacy merge paths; credentials never enter model prompts. */
// 401 = 凭据文件里的 owner 密码与 Para users.password_hash 不一致（配置漂移，不是代码问题）。
// 只给文件路径与恢复手册，不输出任何凭据内容；修复后无需重启，下一轮轮询会重读文件。
export const PARA_AUTH_401_RUNBOOK = 'FHD/docs/autonomy/PARA_MANAGED_CREDENTIALS_401.md';
export function paraManagedAuthRejectedMessage(credentialFile) {
  return `para auth 401 managed_para_credentials_rejected: ${credentialFile} 的 owner 密码被 Para /api/auth/login 拒绝`
    + `（凭据与 Para users 表不一致）；auto_merge 合并队列与 request-merge 均不可用；恢复步骤见 ${PARA_AUTH_401_RUNBOOK}`;
}
export async function requestManagedParaSession({ apiBase, credentialFile, fetchImpl = fetch }) {
  let credentials;
  try {
    if (statSync(credentialFile).mode & 0o077) throw new Error('permissions');
    credentials = JSON.parse(readFileSync(credentialFile, 'utf8'));
    if (!credentials.email || !credentials.password || !credentials.owner_id) throw new Error('identity');
  } catch { throw new Error('managed_para_credentials_unavailable'); }
  const response = await fetchImpl(`${apiBase}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: credentials.email, password: credentials.password }),
  });
  if (response.status === 401) throw new Error(paraManagedAuthRejectedMessage(credentialFile));
  if (!response.ok) throw new Error(`para auth ${response.status}`);
  const body = await response.json();
  if (!body?.token || typeof body.token !== 'string' || body.user?.id !== credentials.owner_id) {
    throw new Error('para_session_identity_mismatch');
  }
  return body.token;
}
