import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createReceiptOutbox } from './control_receipt_outbox.mjs';
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
