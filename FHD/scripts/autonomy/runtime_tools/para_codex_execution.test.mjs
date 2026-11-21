import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { once } from 'node:events';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';

const directory = fileURLToPath(new URL('.', import.meta.url));
const native = { skip: process.platform === 'win32', timeout: 20000 };
const rows = file => existsSync(file) ? readFileSync(file, 'utf8').trim().split('\n').filter(Boolean).map(JSON.parse) : [];
const git = (cwd, ...args) => execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();

async function waitFor(check, diagnostics, timeout = 10000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) { const value = check(); if (value) return value; await delay(20); }
  assert.fail('Timed out awaiting native agent evidence: ' + diagnostics());
}

/** The device transport and model are local test doubles; the actual agent, CLI subprocess,
 * workspace clone, git publication, claim file and report outbox all run unmodified. */
async function worker(t, { mode, entry = 'para_e2e_agent.mjs', reportOnly = false, managed = false,
  control = false, cancelBeforeStart = false, env = {} }) {
  const root = mkdtempSync(join(tmpdir(), 'para-codex-contract-'));
  const source = join(root, 'source'), remote = join(root, 'remote.git'), workspaceRoot = join(root, 'workspaces');
  const callsFile = join(root, 'calls.jsonl'), transport = join(root, 'transport.jsonl'), taskFile = join(root, 'task.json');
  const modules = join(root, 'modules'), home = join(root, 'home'), codex = join(root, 'codex');
  for (const path of [source, home, join(modules, 'ws')]) mkdirSync(path, { recursive: true });
  git(source, 'init', '-q', '-b', 'main');
  git(source, 'config', 'user.name', 'Native Contract');
  git(source, 'config', 'user.email', 'contract@example.invalid');
  writeFileSync(join(source, 'target.txt'), 'original\n');
  git(source, 'add', 'target.txt'); git(source, 'commit', '-qm', 'Fixture base');
  git(root, 'clone', '--bare', source, remote);
  const base = git(source, 'rev-parse', 'HEAD'), id = randomUUID();
  const task = { type: 'execute_task', task_id: id, subtask_id: 'subtask-1', attempt: 1,
    tool: 'codex', work_branch: 'devfleet/codex/' + id, base_branch: 'main', repo_url: remote,
    title: (managed ? `[xcmax:${'a'.repeat(32)}:${'b'.repeat(32)}] ` : '') + 'Native protocol fixture',
    description: reportOnly ? 'MODSTORE_REPORT_ONLY=1\nReview the code.' : 'Apply the bounded fixture edit.' };
  writeFileSync(taskFile, JSON.stringify(task));
  writeFileSync(join(modules, 'ws', 'index.js'), `
    const fs=require('node:fs'), {EventEmitter}=require('node:events');
    module.exports=class WebSocket extends EventEmitter {
      static OPEN=1;
      constructor() { super(); this.readyState=1; let previous=fs.readFileSync(process.env.FIXTURE_TASK_FILE,'utf8');
        setImmediate(()=>{ this.emit('open'); setImmediate(()=>this.emit('message',previous)); });
        setInterval(()=>{ const next=fs.readFileSync(process.env.FIXTURE_TASK_FILE,'utf8');
          if(next!==previous) { previous=next; this.emit('message',next); } },25);
      }
      send(value) { fs.appendFileSync(process.env.FIXTURE_TRANSPORT,value+'\\n'); }
    };`);
  writeFileSync(codex, `#!/usr/bin/env node
    const fs=require('node:fs'), {spawn}=require('node:child_process');
    if(process.argv.includes('--version')) {
      if(${JSON.stringify(mode)}==='shutdown-before-start') {
        fs.writeFileSync(${JSON.stringify(join(root, 'version-wait'))},'waiting');
        setTimeout(()=>{ console.log('codex-cli 0.153.4'); process.exit(0); },1000);
      } else { console.log('codex-cli 0.153.4'); process.exit(0); }
      return;
    }
    const prompt=fs.readFileSync(0,'utf8'), probe=prompt.startsWith('Health check.');
    const model=process.argv[process.argv.indexOf('-m')+1], sandbox=process.argv[process.argv.indexOf('--sandbox')+1];
    const mode=${JSON.stringify(mode)}, emit=value=>console.log(JSON.stringify(value));
    fs.appendFileSync(${JSON.stringify(callsFile)},JSON.stringify({probe,model,sandbox,pid:process.pid,
      control_token_visible:Boolean(process.env.XCMAX_CONTROL_RECEIPT_TOKEN)})+'\\n');
    emit({type:'thread.started',thread_id:'original-fixture-thread'}); emit({type:'turn.started'});
    const done=()=>emit({type:'turn.completed',usage:{input_tokens:11,cached_input_tokens:1,output_tokens:4}});
    if(probe) {
      if(mode==='probe-selection' && model==='primary') { emit({type:'turn.failed',error:{message:'unsupported_model'}}); process.exit(1); }
      emit({type:'item.completed',item:{id:'answer',type:'agent_message',text:'OK'}}); done(); process.exit(0);
    }
    if(sandbox!=='read-only') fs.writeFileSync('target.txt','changed by '+model+'\\n');
    emit({type:'item.started',item:{id:'command-1',type:'command_execution',status:'in_progress',command:'node local-check.cjs'}});
    if(mode==='shutdown' || (mode==='remote-cancel' && process.cwd().includes(${JSON.stringify(id)}))) {
      process.on('SIGTERM',()=>{}); const beat=()=>fs.appendFileSync('heartbeat','.'); beat(); setInterval(beat,10);
    } else {
      emit({type:'item.completed',item:{id:'command-1',type:'command_execution',status:'completed',command:'node local-check.cjs',exit_code:0}});
      if(mode==='nonzero' || mode==='zero-failure' || mode==='quota') {
        emit({type:'turn.failed',error:{message:mode==='quota'?'insufficient_quota':'patch application failed'}});
        process.exit(mode==='zero-failure'?0:1);
      }
      emit({type:'item.completed',item:{id:'answer',type:'agent_message',text:'[codex exit=1] is quoted evidence; the native turn completed.'}});
      if(mode!=='incomplete') done();
    }
  `, { mode: 0o700 });
  const alternative = join(root, 'trae');
  writeFileSync(alternative, `#!/usr/bin/env node
    if(process.argv.includes('--version')) { console.log('trae 1.0.0'); process.exit(0); }
    require('node:fs').writeFileSync(${JSON.stringify(join(root, 'replayed'))},'alternative executor started');
    if(${JSON.stringify(mode)}==='override-cancel') setTimeout(()=>process.exit(1),6000);
    else process.exit(1);`, { mode: 0o700 });
  const reports = [];
  const controlReports = [];
  let cancelRequested = cancelBeforeStart, loseCancelAck = false;
  const server = createServer(async (request, response) => {
    if (request.url.includes('/pending-task')) { response.setHeader('content-type', 'application/json'); response.end('{"task":null}'); return; }
    let body = ''; for await (const chunk of request) body += chunk;
    if (request.url === '/control-receipts') {
      assert.equal(request.headers.authorization, 'Bearer fixture-control-token');
      const receipt = JSON.parse(body); controlReports.push(receipt);
      const command = cancelRequested && receipt.task_id === task.task_id ? {
        action: 'cancel', intent_id: 'd'.repeat(64),
        ...Object.fromEntries(['device_id', 'correlation_id', 'attempt_id', 'task_id', 'subtask_id']
          .map(field => [field, receipt[field]])),
      } : null;
      if (command && loseCancelAck) { loseCancelAck = false; response.destroy(); return; }
      response.setHeader('content-type', 'application/json');
      response.end(JSON.stringify({ accepted: true, control: command })); return;
    }
    assert.equal(request.headers.authorization, 'Bearer fixture-device-token');
    reports.push(JSON.parse(body));
    response.setHeader('content-type', 'application/json'); response.end('{"accepted":true}');
  });
  await once(server.listen(0, '127.0.0.1'), 'listening');
  let output = '', child;
  const childEnv = { PATH: process.env.PATH, HOME: home, SystemRoot: process.env.SystemRoot,
    NODE_PATH: modules, FIXTURE_TASK_FILE: taskFile, FIXTURE_TRANSPORT: transport,
    DEVFLEET_DEVICE_TOKEN: 'fixture-device-token', DEVFLEET_API_URL: `http://127.0.0.1:${server.address().port}`,
    DEVFLEET_WORKSPACE_ROOT: workspaceRoot, DEVFLEET_BARE_REPO: join(root, 'fallback.git'),
    DEVFLEET_CODEX_AGENT: codex, DEVFLEET_TRAE_AGENT: alternative,
    DEVFLEET_CURSOR_AGENT: join(root, 'missing-cursor'), DEVFLEET_CLAUDE_AGENT: join(root, 'missing-claude'),
    DEVFLEET_OPENCODE_AGENT: join(root, 'missing-opencode'),
    DEVFLEET_CODEX_MODEL_PROBE: '0', DEVFLEET_CODEX_MODEL_CANDIDATES: 'primary,backup',
    DEVFLEET_CODEX_TRAE_FAILOVER: '0', DEVFLEET_AI_AGENT_TIMEOUT_MS: '10000',
    XCMAX_CONTROL_REPORTS_ENABLED: managed ? '1' : '0',
    ...(control ? { XCMAX_CONTROL_RECEIPT_URL: `http://127.0.0.1:${server.address().port}/control-receipts`,
      XCMAX_CONTROL_RECEIPT_TOKEN: 'fixture-control-token', XCMAX_CONTROL_DEVICE_ID: 'mac',
      XCMAX_CONTROL_RECEIPT_DIR: join(root, 'control-receipts') } : {}), ...env };
  const start = () => {
    child = spawn(process.execPath, [join(directory, entry)], { cwd: root, env: childEnv, stdio: ['ignore', 'pipe', 'pipe'] });
    child.stdout.on('data', value => { output += value; }); child.stderr.on('data', value => { output += value; });
  };
  const stop = async () => {
    if (child.exitCode !== null || child.signalCode !== null) return;
    const ended = once(child, 'close'); child.kill('SIGTERM');
    const forced = setTimeout(() => child.kill('SIGKILL'), 8000);
    try { await ended; } finally { clearTimeout(forced); }
  };
  t.after(async () => { await stop(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); rmSync(root, { recursive: true, force: true }); });
  start();
  const workspace = join(managed ? join(home, 'XCMAX-runtime', 'control-workspaces') : workspaceRoot, id + '-subtask-1');
  const terminal = async (timeout = 10000) => {
    if (managed || reportOnly) return waitFor(() => reports.find(row => ['completed', 'failed'].includes(row.status)), () => output, timeout);
    const result = await waitFor(() => rows(transport).find(row => row.type === 'task_progress'
      && ['completed', 'failed'].includes(row.status)), () => output, timeout);
    if (result.status === 'failed') await waitFor(() => reports.some(row => row.status === 'failed'), () => output);
    return result;
  };
  const receipt = () => reports.map(row => {
    try { return JSON.parse(row.report || row.content || '{}'); } catch { return {}; }
  }).find(row => row.source === 'codex_exec_jsonl')?.codex_execution_receipt;
  const submitNext = () => {
    const next = { ...task, task_id: randomUUID(), subtask_id: 'subtask-2',
      title: `[xcmax:${'e'.repeat(32)}:${'f'.repeat(32)}] Second independent task` };
    next.work_branch = 'devfleet/codex/' + next.task_id;
    writeFileSync(taskFile, JSON.stringify(next)); return next;
  };
  return { root, task, base, remote, workspace, reports, receipt, terminal, stop, start, submitNext,
    controlReports, cancel: (loseAck = false) => { cancelRequested = true; loseCancelAck = loseAck; },
    calls: () => rows(callsFile), messages: () => rows(transport), diagnostics: () => output,
    signal: value => child.kill(value) };
}

for (const [mode, extra] of [
  ['nonzero', {}],
  ['zero-failure', { entry: 'e2e-agent.mjs', reportOnly: true, managed: true }],
  ['incomplete', { env: { DEVFLEET_TOOL_FALLBACK_ORDER: 'codex,trae', DEVFLEET_TOOL_FALLBACK_ON: 'any' } }],
  ['quota', {}],
]) {
  test(`native ${mode} never publishes or replays the original task`, native, async t => {
    const current = await worker(t, { mode, ...extra });
    assert.equal((await current.terminal()).status, 'failed');
    assert.equal(current.calls().filter(row => !row.probe).length, 1);
    assert.equal(existsSync(join(current.root, 'replayed')), false);
    assert.equal(git(current.remote, 'rev-parse', 'main'), current.base);
    assert.equal(git(current.remote, 'for-each-ref', '--format=%(refname)', 'refs/heads/devfleet'), '');
    assert.equal(git(current.workspace, 'rev-parse', 'HEAD'), current.base);
    assert.ok(existsSync(current.workspace), 'failed/unknown edits remain available for reconciliation');
    const receipt = current.receipt();
    assert.equal(receipt.status, mode === 'incomplete' ? 'unknown' : 'failed');
    assert.equal(receipt.cli_version, '0.153.4');
    if (extra.reportOnly) assert.equal(current.calls()[0].sandbox, 'read-only');
  });
}

test('native successful edit is pushed once and its original thread/tool/usage receipt is read back through the existing outbox', native, async t => {
  const current = await worker(t, { mode: 'success', managed: true });
  const report = await current.terminal();
  assert.equal(report.status, 'completed');
  const receipt = current.receipt();
  assert.equal(JSON.parse(report.report).source, 'executor_git_readback', 'the original delivery JSON stays parseable');
  assert.equal(receipt.thread_id, 'original-fixture-thread');
  assert.deepEqual(receipt.usage, { input_tokens: 11, cached_input_tokens: 1, output_tokens: 4 });
  assert.equal(receipt.tool_results[0].exit_code, 0);
  assert.match(receipt.tool_results[0].command_sha256, /^[a-f0-9]{64}$/);
  assert.equal(git(current.remote, 'show', current.task.work_branch + ':target.txt'), 'changed by primary');
  assert.equal(current.calls().filter(row => !row.probe).length, 1);
});

test('legacy startup entry shares successful report-only sandbox and native receipt handling', native, async t => {
  const current = await worker(t, { mode: 'success', entry: 'e2e-agent.mjs', reportOnly: true, managed: true });
  assert.equal((await current.terminal()).status, 'completed');
  assert.equal(current.calls()[0].sandbox, 'read-only');
  assert.equal(git(current.remote, 'for-each-ref', '--format=%(refname)', 'refs/heads/devfleet'), '');
});

test('only probes may select another model, then the selected real task executes once', native, async t => {
  const current = await worker(t, { mode: 'probe-selection', managed: true, env: { DEVFLEET_CODEX_MODEL_PROBE: '1' } });
  assert.equal((await current.terminal()).status, 'completed');
  assert.deepEqual(current.calls().map(({ probe, model }) => [probe, model]), [[true, 'primary'], [true, 'backup'], [false, 'backup']]);
});

test('worker SIGTERM waits for a stubborn Codex process and persists the unknown result before exiting', native, async t => {
  const current = await worker(t, { mode: 'shutdown', managed: true });
  const heartbeatPath = join(current.workspace, 'heartbeat');
  await waitFor(() => existsSync(heartbeatPath), current.diagnostics);
  current.signal('SIGTERM');
  assert.equal((await current.terminal()).status, 'failed');
  assert.equal(current.receipt().status, 'unknown');
  assert.equal(current.receipt().reason, 'codex_cancelled');
  const heartbeat = readFileSync(heartbeatPath, 'utf8');
  await delay(40);
  assert.equal(readFileSync(heartbeatPath, 'utf8'), heartbeat);
});

test('restarting an unmanaged original task preserves its failed workspace and refuses another model execution', native, async t => {
  const current = await worker(t, { mode: 'quota' });
  await current.terminal(); await current.stop();
  const reportCount = current.reports.length;
  current.start();
  await waitFor(() => current.reports.slice(reportCount).some(row => row.status === 'failed'
    && row.content.includes('workspace_reconciliation_required')), current.diagnostics);
  assert.equal(current.calls().filter(row => !row.probe).length, 1);
  assert.equal(readFileSync(join(current.workspace, 'target.txt'), 'utf8'), 'changed by primary\n');
});

test('shutdown during the version probe cannot fall through to an alternate executor', native, async t => {
  const current = await worker(t, { mode: 'shutdown-before-start', env: {
    DEVFLEET_TOOL_FALLBACK_ORDER: 'codex,trae', DEVFLEET_TOOL_FALLBACK_ON: 'any',
  } });
  await waitFor(() => existsSync(join(current.root, 'version-wait'))
    && current.messages().some(row => row.type === 'task_progress' && row.progress === 40), current.diagnostics);
  current.signal('SIGTERM');
  assert.equal((await current.terminal()).status, 'failed');
  assert.equal(current.calls().length, 0);
  assert.equal(existsSync(join(current.root, 'replayed')), false);
});

test('remote original stop waits for native process exit, keeps unknown usage, and allows independent task B', { ...native, timeout: 30000 }, async t => {
  // A lost response can require two 5s polls plus the 3s process-tree grace.
  // Keep the unrelated native execution deadline outside this cancellation race.
  const current = await worker(t, { mode: 'remote-cancel', managed: true, control: true,
    env: { DEVFLEET_AI_AGENT_TIMEOUT_MS: '30000' } });
  const heartbeatPath = join(current.workspace, 'heartbeat');
  await waitFor(() => existsSync(heartbeatPath), current.diagnostics);
  current.cancel(true); // One authenticated command response is lost.
  assert.equal((await current.terminal(18000)).status, 'failed');
  const proof = await waitFor(() => current.controlReports.find(row => row.cancellation), current.diagnostics);
  assert.equal(proof.task_id, current.task.task_id);
  assert.equal(proof.subtask_id, current.task.subtask_id);
  assert.equal(proof.cancellation.outcome, 'process_exited');
  assert.equal(proof.cancellation.usage_status, 'unknown');
  assert.equal(proof.cancellation.native.reason, 'codex_cancelled');
  assert.equal(proof.cancellation.native.usage, null);
  assert.equal(current.receipt().status, 'unknown');
  const heartbeat = readFileSync(heartbeatPath, 'utf8');
  await delay(50); assert.equal(readFileSync(heartbeatPath, 'utf8'), heartbeat);
  assert.equal(git(current.remote, 'for-each-ref', '--format=%(refname)', current.task.work_branch), '');
  const next = current.submitNext();
  await waitFor(() => current.reports.some(row => row.task_id === next.task_id && row.status === 'completed'), current.diagnostics);
  assert.equal(git(current.remote, 'show', next.work_branch + ':target.txt'), 'changed by primary');
  assert.equal(current.calls().filter(row => !row.probe).length, 2);
  assert.equal(current.calls().some(row => row.control_token_visible), false);
});

test('an approved stop already waiting on the original device queue launches no model or alternate tool', native, async t => {
  const current = await worker(t, { mode: 'success', managed: true, control: true, cancelBeforeStart: true,
    env: { DEVFLEET_TOOL_FALLBACK_ORDER: 'codex,trae', DEVFLEET_TOOL_FALLBACK_ON: 'any' } });
  assert.equal((await current.terminal()).status, 'failed');
  const proof = current.controlReports.find(row => row.cancellation);
  assert.equal(proof.cancellation.outcome, 'not_started');
  assert.equal(proof.cancellation.native, null);
  assert.equal(current.calls().length, 0);
  assert.equal(existsSync(current.workspace), false);
  assert.equal(existsSync(join(current.root, 'replayed')), false);
  assert.equal(git(current.remote, 'for-each-ref', '--format=%(refname)', 'refs/heads/devfleet'), '');
});

test('a non-Codex override cannot claim not_started or a native cancellation receipt', native, async t => {
  const current = await worker(t, { mode: 'override-cancel', managed: true, control: true,
    env: { DEVFLEET_FORCE_TRAE: '1' } });
  await waitFor(() => existsSync(join(current.root, 'replayed')), current.diagnostics);
  current.cancel();
  const report = await current.terminal();
  assert.equal(report.status, 'failed');
  const evidence = JSON.parse(report.report);
  assert.equal(evidence.source, 'mac_control_cancel');
  assert.equal(evidence.stop_confirmed, false);
  assert.equal(current.calls().length, 0);
  assert.equal(current.controlReports.some(row => row.cancellation), false);
  assert.equal(git(current.remote, 'for-each-ref', '--format=%(refname)', 'refs/heads/devfleet'), '');
});
