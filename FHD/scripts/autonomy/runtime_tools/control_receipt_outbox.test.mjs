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
    outbox.bind({ task_id: 'para', title: `[xcmax:${'a'.repeat(32)}:${'b'.repeat(32)}] check` });
    const event = { type: 'task_progress', task_id: 'para', subtask_id: 'sub', status: 'completed', progress: 100 };
    outbox.record(event); outbox.record(event);
    await outbox.drain();
    assert.equal(readdirSync(directory).length, 1);
    let delivered = 0;
    const restarted = createReceiptOutbox({ ...config, fetcher: async (_url, req) => {
      delivered++; assert.equal(JSON.parse(req.body).status, 'completed');
      return { ok: true, json: async () => ({ accepted: true }) };
    } });
    await restarted.drain();
    assert.equal(delivered, 1); assert.deepEqual(readdirSync(directory), []);
  } finally { rmSync(directory, { recursive: true, force: true }); }
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
