import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';
import { runCodexCli } from './cli_output_stream.mjs';

const started = [{ type: 'thread.started', thread_id: 'fixture-thread' }, { type: 'turn.started' }];
const completed = { type: 'turn.completed', usage: { input_tokens: 12, cached_input_tokens: 2, output_tokens: 3 } };
const answer = text => ({ type: 'item.completed', item: { id: 'answer', type: 'agent_message', text } });

function fixture(t, program) {
  const cwd = mkdtempSync(join(tmpdir(), 'codex-native-events-'));
  t.after(() => rmSync(cwd, { recursive: true, force: true }));
  writeFileSync(join(cwd, 'exec'), program);
  return { cwd, run: options => runCodexCli({ executable: process.execPath, cwd,
    prompt: 'A bounded fixture task', args: ['exec', '--sandbox', 'workspace-write', '-'],
    env: { PATH: process.env.PATH, SystemRoot: process.env.SystemRoot }, timeoutMs: 5000, ...options }) };
}

function transcript(events, exitCode = 0, suffix = '') {
  return `const fs = require('node:fs'); fs.readFileSync(0, 'utf8');
    fs.writeFileSync('partial.txt', 'a real workspace edit');
    if (!process.argv.includes('--json')) process.exit(99);
    for (const event of ${JSON.stringify(events)}) process.stdout.write(JSON.stringify(event) + '\\n');
    ${suffix}
    process.exitCode = ${exitCode};`;
}

test('native completed turn and exit 0 accept text which happens to contain the legacy failure marker', async t => {
  const { run } = fixture(t, transcript([...started, answer('[codex exit=1] is quoted source evidence'), completed]));
  const result = await run();
  assert.equal(result.ok, true);
  assert.equal(result.output, '[codex exit=1] is quoted source evidence');
  assert.equal(result.receipt.thread_id, 'fixture-thread');
  assert.deepEqual(result.receipt.usage, completed.usage);
  assert.equal(result.receipt.cli_version, null, 'an installed package pin is not the launched binary version');
});

for (const [name, events, exitCode, expected, suffix] of [
  ['turn.failed with exit 0', [...started, answer('I am done'), { type: 'turn.failed', error: { message: 'patch failed' } }], 0, 'failed'],
  ['fatal error without a terminal', [...started, { type: 'error', message: 'service disconnected' }], 0, 'unknown'],
  ['answer without completion', [...started, answer('I am done')], 0, 'unknown'],
  ['nonzero exit after completed turn', [...started, answer('done'), completed], 7, 'failed'],
  ['truncated JSONL', [...started, answer('done'), completed], 0, 'unknown', "process.stdout.write('{\"type\":');"],
  ['invalid native usage', [...started, { ...completed, usage: { ...completed.usage, input_tokens: '12' } }], 0, 'unknown'],
  ['unfinished native tool', [...started, { type: 'item.started', item: { id: 'shell', type: 'command_execution', status: 'in_progress' } }, completed], 0, 'unknown'],
]) {
  test(`${name} cannot turn a real file edit into success`, async t => {
    const { run, cwd } = fixture(t, transcript(events, exitCode, suffix));
    const result = await run();
    assert.equal(readFileSync(join(cwd, 'partial.txt'), 'utf8'), 'a real workspace edit');
    assert.equal(result.ok, false);
    assert.equal(result.receipt.status, expected);
    assert.equal(result.executionStarted, true);
  });
}

test('pinned CLI startup warnings, internally recovered errors and recovered tool failures do not veto a completed turn', async t => {
  const events = [
    { type: 'item.completed', item: { id: 'warning', type: 'error', message: 'deprecated configuration' } },
    ...started, { type: 'error', message: 'Reconnecting... 1/5' },
    { type: 'item.started', item: { id: 'shell', type: 'command_execution', status: 'in_progress' } },
    { type: 'item.completed', item: { id: 'shell', type: 'command_execution', status: 'failed', exit_code: 1 } },
    { type: 'item.started', item: { id: 'patch', type: 'file_change', status: 'in_progress' } },
    { type: 'item.completed', item: { id: 'patch', type: 'file_change', status: 'completed', changes: [] } },
    answer('recovered'), completed,
  ];
  const { run } = fixture(t, transcript(events));
  const result = await run({ cliVersion: '0.153.4', versionCheckedAt: '2026-11-21T00:00:00Z' });
  assert.equal(result.ok, true);
  assert.equal(result.receipt.tool_calls, 2);
  assert.equal(result.receipt.tool_failures, 1);
  assert.equal(result.receipt.cli_version, '0.153.4');
});

const stubborn = `const fs = require('node:fs'); fs.readFileSync(0, 'utf8');
  process.on('SIGTERM', () => fs.appendFileSync('signals', 'TERM\\n'));
  fs.writeFileSync('worker.pid', String(process.pid));
  console.log(JSON.stringify({type:'thread.started',thread_id:'fixture-thread'}));
  console.log(JSON.stringify({type:'turn.started'}));
  setInterval(() => fs.appendFileSync('heartbeat', '.'), 10);`;

test('timeout escalates to SIGKILL and waits for an actual process exit', { skip: process.platform === 'win32' }, async t => {
  const { run, cwd } = fixture(t, stubborn);
  const result = await run({ timeoutMs: 400, killGraceMs: 40 });
  assert.equal(result.ok, false);
  assert.equal(result.receipt.status, 'unknown');
  assert.equal(result.receipt.reason, 'codex_timeout');
  assert.equal(result.receipt.signal, 'SIGKILL');
  const pid = Number(readFileSync(join(cwd, 'worker.pid'), 'utf8'));
  assert.throws(() => process.kill(pid, 0), { code: 'ESRCH' });
  const heartbeat = readFileSync(join(cwd, 'heartbeat'), 'utf8');
  await delay(40);
  assert.equal(readFileSync(join(cwd, 'heartbeat'), 'utf8'), heartbeat);
});

test('abort cancels the actual child before returning an unknown receipt', { skip: process.platform === 'win32' }, async t => {
  const { run, cwd } = fixture(t, stubborn);
  const controller = new AbortController();
  const pending = run({ signal: controller.signal, killGraceMs: 40 });
  for (let attempts = 0; !existsSync(join(cwd, 'worker.pid')) && attempts < 100; attempts += 1) await delay(10);
  controller.abort();
  const result = await pending;
  assert.equal(result.receipt.reason, 'codex_cancelled');
  assert.equal(result.receipt.status, 'unknown');
  assert.throws(() => process.kill(Number(readFileSync(join(cwd, 'worker.pid'), 'utf8')), 0), { code: 'ESRCH' });
});

test('timeout also kills a tool descendant when the Codex parent exits first', { skip: process.platform === 'win32' }, async t => {
  const descendant = `const fs=require('node:fs'); process.on('SIGTERM',()=>{});
    fs.writeFileSync('descendant.pid',String(process.pid)); setInterval(()=>fs.appendFileSync('descendant-heartbeat','.'),10);`;
  const { run, cwd } = fixture(t, `const {spawn}=require('node:child_process');
    process.on('SIGTERM',()=>process.exit(0));
    spawn(process.execPath,['-e',${JSON.stringify(descendant)}],{stdio:'inherit'});
    setInterval(()=>{},1000);`);
  const startedAt = Date.now();
  const result = await run({ timeoutMs: 400, killGraceMs: 40 });
  assert.ok(Date.now() - startedAt < 3000, 'open descendant pipes must not leave the timeout hanging');
  assert.equal(result.receipt.reason, 'codex_timeout');
  const heartbeat = readFileSync(join(cwd, 'descendant-heartbeat'), 'utf8');
  await delay(40);
  assert.equal(readFileSync(join(cwd, 'descendant-heartbeat'), 'utf8'), heartbeat);
});

test('a missing binary records not_started rather than an executed failure', async t => {
  const { cwd, run } = fixture(t, '');
  const result = await run({ executable: join(cwd, 'missing-codex') });
  assert.equal(result.executionStarted, false);
  assert.equal(result.receipt.status, 'not_started');
  assert.equal(result.receipt.reason, 'ENOENT');
});
