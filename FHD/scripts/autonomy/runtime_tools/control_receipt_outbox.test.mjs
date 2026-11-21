import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createReceiptOutbox, createParaReportOutbox } from './control_receipt_outbox.mjs';
import { probeTools } from './tool_preflight.mjs';

test('failed delivery stays on disk and replays after process recreation', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'xcmax-receipt-test-'));
  const config = { directory, url: 'https://server.invalid/receipts', token: 'fixture', deviceId: 'mac' };
  try {
    const outbox = createReceiptOutbox({ ...config, fetcher: async () => { throw new Error('offline'); } });
    outbox.bind({ task_id: 'para', subtask_id: 'sub', title: `[xcmax:${'a'.repeat(32)}:${'b'.repeat(32)}] check` });
    const event = { type: 'task_progress', task_id: 'para', subtask_id: 'sub', status: 'completed', progress: 100 };
    outbox.record(event); outbox.record(event);
    await outbox.drain();
    assert.equal(readdirSync(directory).length, 2);
    const delivered = [];
    const restarted = createReceiptOutbox({ ...config, fetcher: async (_url, req) => {
      delivered.push(JSON.parse(req.body).status);
      return { ok: true, json: async () => ({ accepted: true }) };
    } });
    await restarted.drain();
    assert.deepEqual(delivered.sort(), ['completed', 'queued']); assert.deepEqual(readdirSync(directory), []);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

const controlTask = id => ({ task_id: `para-${id}`, subtask_id: `sub-${id}`,
  title: `[xcmax:${id.repeat(32)}:${'c'.repeat(32)}] task` });
const cancel = row => ({ action: 'cancel', intent_id: 'd'.repeat(64),
  ...Object.fromEntries(['device_id', 'correlation_id', 'attempt_id', 'task_id', 'subtask_id']
    .map(field => [field, row[field]])) });
function controls(t, fetcher) {
  const directory = mkdtempSync(join(tmpdir(), 'xcmax-controls-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  return createReceiptOutbox({ directory, url: 'https://server.invalid/receipts', token: 'fixture',
    deviceId: 'mac', fetcher });
}

for (const [field, value] of Object.entries({ device_id: 'other', correlation_id: 'e'.repeat(32),
  attempt_id: 'e'.repeat(32), task_id: 'other', subtask_id: 'other', action: 'interrupt', intent_id: 'unknown' })) {
  test(`remote cancellation rejects a changed ${field}`, async t => {
    const outbox = controls(t, async (_url, request) => ({ ok: true,
      json: async () => ({ accepted: true, control: { ...cancel(JSON.parse(request.body)), [field]: value } }) }));
    const task = controlTask('a'); outbox.bind(task);
    await outbox.poll();
    assert.equal(outbox.signal(task).aborted, false);
  });
}

test('the original stop is read repeatedly, affects only A, and never aborts B', async t => {
  let requests = 0, aborts = 0;
  const outbox = controls(t, async (_url, request) => {
    const row = JSON.parse(request.body); requests++;
    return { ok: true, json: async () => ({ accepted: true, duplicate: true,
      control: row.task_id === 'para-a' ? cancel(row) : null }) };
  });
  const a = controlTask('a'), b = controlTask('b'); outbox.bind(a); outbox.bind(b);
  outbox.signal(a).addEventListener('abort', () => { aborts++; });
  await outbox.poll(); await outbox.poll();
  assert.equal(outbox.signal(a).aborted, true); assert.equal(outbox.signal(b).aborted, false);
  assert.equal(outbox.cancellation(a).intent_id, 'd'.repeat(64));
  assert.equal(requests, 4); assert.equal(aborts, 1);
});

test('late command cannot override a completed task even while its response is in flight', async t => {
  let reply;
  const outbox = controls(t, (_url, request) => new Promise(resolve => {
    reply = () => resolve({ ok: true, json: async () => ({ accepted: true, control: cancel(JSON.parse(request.body)) }) });
  }));
  const task = controlTask('a'); outbox.bind(task);
  const pending = outbox.check(task);
  outbox.record({ ...task, type: 'task_progress', status: 'completed', progress: 100 });
  reply(); await pending;
  assert.equal(outbox.signal(task).aborted, false);
  assert.equal(outbox.cancellation(task), undefined);
});

test('lost control response is retried as the same receipt, never as a new task', async t => {
  const sent = [];
  const outbox = controls(t, async (_url, request) => {
    const row = JSON.parse(request.body); sent.push(row);
    if (sent.length === 1) throw new Error('lost ACK');
    return { ok: true, json: async () => ({ accepted: true, duplicate: true, control: cancel(row) }) };
  });
  const task = controlTask('a'); outbox.bind(task);
  await assert.rejects(outbox.check(task), /lost ACK/);
  assert.equal(outbox.signal(task).aborted, false);
  await outbox.poll();
  assert.equal(outbox.signal(task).aborted, true);
  assert.deepEqual(sent[0], sent[1]);
  assert.throws(() => outbox.bind({ ...task, title: `[xcmax:${'a'.repeat(32)}:${'f'.repeat(32)}] changed` }),
    /control_task_identity_changed/);
});

test('preflight proves launch, records no stdout, treats missing tools as false', async () => {
  const result = await probeTools({ codex: 'ok', cursor: 'missing' }, async (cmd, args) => {
    assert.deepEqual(args, ['--version']);
    if (cmd === 'missing') throw new Error('not installed');
    return { stdout: 'never send me' };
  });
  assert.equal(result.codex.ok, true); assert.equal(result.cursor.ok, false);
  assert.equal(JSON.stringify(result).includes('never send me'), false);
});

test('Para reports survive restart in sequence and execution is never blindly repeated', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'xcmax-para-report-test-'));
  const config = { directory, url: 'http://localhost/report', token: 'fixture', enabled: true };
  const task = { task_id: 'task', subtask_id: 'sub', attempt: 1,
    title: `[xcmax:${'a'.repeat(32)}:${'b'.repeat(32)}] task` };
  try {
    const queue = createParaReportOutbox({ ...config, fetcher: async () => { throw new Error('offline'); } });
    queue.bind(task); assert.equal(queue.claimExecution(task), true);
    queue.record(task, { status: 'running', progress: 10 });
    queue.record(task, { status: 'completed', progress: 100, content: 'checked token=fixture-secret' });
    await queue.drain();
    assert.equal(readdirSync(directory).filter(name => !name.startsWith('.')).length, 2);
    const received = [];
    const restarted = createParaReportOutbox({ ...config, fetcher: async (_url, req) => {
      received.push(JSON.parse(req.body)); return { ok: true, json: async () => ({ accepted: true }) };
    } });
    restarted.bind(task); assert.equal(restarted.claimExecution(task), false);
    await restarted.drain();
    assert.deepEqual(received.map(row => row.status), ['running', 'completed']);
    assert.ok(received[1].sequence > received[0].sequence);
    assert.equal(received[1].report.includes('fixture-secret'), false);
    assert.equal(readdirSync(directory).filter(name => !name.startsWith('.')).length, 0);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
