import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import {
  effectiveToolName,
  isToolFallbackEligible,
  pausedByOpenCodePolicy,
  removeOwnWorkspace,
  requestedToolName,
  resetWorkspaceForNextTool,
  toolAttemptPlan,
  toolFallbackMode,
  toolFallbackOrder,
  withFailureCleanup,
} from './e2e_agent_runtime_policy.mjs';
import { openCodePlatformConfig, runOpenCodeAgent } from './opencode_agent.mjs';

test('OpenCode-only policy pauses the other CLIs and scopes native config to the XCMAX gateway', () => {
  const env = { DEVFLEET_FORCE_OPENCODE: '1', DEVFLEET_FORCE_CODEX: '1',
    PARA_PLATFORM_GATEWAY_URL: 'https://xiu-ci.com/v1', PARA_OPENCODE_MODEL: 'xcmax-para-coding',
    OPENCODE_API_KEY: 'test-only-placeholder' };
  assert.equal(effectiveToolName({ env, fallback: 'codex' }), 'opencode');
  assert.equal(pausedByOpenCodePolicy('codex', env), true);
  assert.equal(pausedByOpenCodePolicy('opencode', env), false);
  const config = openCodePlatformConfig(env);
  assert.equal(config.provider.xcmax.npm, '@ai-sdk/openai');
  assert.equal(config.model, 'xcmax/xcmax-para-coding');
  assert.equal(config.provider.xcmax.models['xcmax-para-coding'].id, 'xcmax-para-coding');
  assert.deepEqual(config.provider.xcmax.whitelist, ['xcmax-para-coding']);
  assert.deepEqual(config.enabled_providers, ['xcmax']);
  assert.ok(!JSON.stringify(config).includes(env.OPENCODE_API_KEY));
  assert.throws(() => openCodePlatformConfig({ ...env, OPENCODE_API_KEY: '' }), /专用密钥/);
  assert.equal(openCodePlatformConfig({ ...env, PARA_OPENCODE_MODEL: 'vendor/model:variant' }).model, 'xcmax/vendor/model:variant');
  assert.throws(() => openCodePlatformConfig({ ...env, PARA_PLATFORM_POOL: '1', PARA_PLATFORM_MODEL: 'other' }), /专用密钥/);
});

test('OpenCode report-only sessions deny unknown tools even when no log callback is supplied', async () => {
  const root = mkdtempSync(join(tmpdir(), 'opencode-native-api-'));
  const executable = join(root, 'opencode');
  writeFileSync(executable, `#!${process.execPath}\n` + String.raw`
const http = require('node:http');
let session;
const server = http.createServer(async (req, res) => {
  if (req.headers.authorization !== 'Basic ' + Buffer.from('opencode:' + process.env.OPENCODE_SERVER_PASSWORD).toString('base64')) {
    res.writeHead(401).end(); return;
  }
  let raw = ''; for await (const chunk of req) raw += chunk;
  if (req.url === '/event') { res.writeHead(200, {'content-type': 'text/event-stream'}); res.flushHeaders(); return; }
  res.setHeader('content-type', 'application/json');
  if (req.url === '/config') {
    const config = JSON.parse(process.env.OPENCODE_CONFIG_CONTENT);
    config.provider.xcmax.options.apiKey = process.env.OPENCODE_API_KEY;
    if (process.env.FIXTURE_CONFIG_OVERRIDE === 'headers') config.provider.xcmax.models['vendor/model:variant'].headers = {aUtHoRiZaTiOn:'fixture-other-key'};
    if (process.env.FIXTURE_CONFIG_OVERRIDE === 'endpoint') config.provider.xcmax.options.baseURL = 'https://other.example.test/v1';
    if (process.env.FIXTURE_CONFIG_OVERRIDE === 'key') config.provider.xcmax.options.apiKey = 'fixture-other-key';
    if (process.env.FIXTURE_CONFIG_OVERRIDE === 'model') config.provider.xcmax.models['vendor/model:variant'].id = 'other';
    res.end(JSON.stringify(config)); return;
  }
  if (req.url === '/session') { session = JSON.parse(raw); res.end(JSON.stringify({id:'fixture-session'})); return; }
  const message = JSON.parse(raw);
  res.end(JSON.stringify({info:{tokens:{input:1,output:2}},parts:[{type:'text',text:JSON.stringify({session,message})}]}));
});
server.listen(0, '127.0.0.1', () => console.log('http://127.0.0.1:' + server.address().port));
`, { mode: 0o700 });
  try {
    const env = { DEVFLEET_FORCE_OPENCODE: '1', PARA_PLATFORM_POOL: '1',
      PARA_OPENCODE_MODEL: 'vendor/model:variant', PARA_PLATFORM_MODEL: 'vendor/model:variant',
      PARA_PLATFORM_GATEWAY_URL: 'https://gateway.example.test/v1', OPENCODE_API_KEY: 'fixture-granted-key' };
    for (const log of [() => {}, undefined]) {
      const output = JSON.parse(await runOpenCodeAgent(root, 'Review the existing files', {
        executable, env, timeoutMs: 5000, reportOnly: true, log,
      }));
      assert.equal(output.message.agent, 'plan');
      assert.equal(output.message.parts[0].text, 'Review the existing files');
      assert.deepEqual(output.message.model, { providerID: 'xcmax', modelID: 'vendor/model:variant' });
      assert.deepEqual(output.session.permission, [
        { permission: '*', pattern: '*', action: 'deny' },
        ...['read', 'glob', 'grep', 'list'].map(permission => ({ permission, pattern: '*', action: 'allow' })),
      ]);
    }
    for (const override of ['headers', 'endpoint', 'key', 'model']) {
      await assert.rejects(runOpenCodeAgent(root, 'Do not launch a model', {
        executable, env: { ...env, FIXTURE_CONFIG_OVERRIDE: override }, timeoutMs: 5000, reportOnly: false,
      }), /opencode_platform_binding_mismatch/);
    }
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('forced Codex overrides an explicit Cursor task assignment', () => {
  assert.equal(
    effectiveToolName({
      task: { tool: 'cursor' },
      env: { DEVFLEET_FORCE_CODEX: '1' },
    }),
    'codex',
  );
});

test('task assignment wins over device config when no force policy is active', () => {
  assert.equal(
    effectiveToolName({
      task: { tool: 'trae' },
      agentConfig: { devTool: 'cursor' },
      env: {},
    }),
    'trae',
  );
  assert.equal(requestedToolName({}, { devTool: 'cursor' }), 'cursor');
  assert.equal(effectiveToolName({ task: { tool_name: 'opencode' }, env: {} }), 'opencode');
});

test('queue callers can choose a supported fallback tool', () => {
  assert.equal(effectiveToolName({ task: {}, env: {}, fallback: 'codex' }), 'codex');
  assert.equal(effectiveToolName({ task: {}, env: {}, fallback: 'invalid' }), '');
});

test('failed workspace preparation always invokes bounded cleanup', async () => {
  const cleaned = [];
  await assert.rejects(
    withFailureCleanup(
      '/safe/workspace/task-id',
      async () => {
        throw new Error('clone failed');
      },
      (path) => cleaned.push(path),
    ),
    /clone failed/,
  );
  assert.deepEqual(cleaned, ['/safe/workspace/task-id']);
});

test('successful workspace preparation is not cleaned early', async () => {
  const cleaned = [];
  const result = await withFailureCleanup(
    '/safe/workspace/task-id',
    async () => 'ready',
    (path) => cleaned.push(path),
  );
  assert.equal(result, 'ready');
  assert.deepEqual(cleaned, []);
});

test('clone fallback removes only this task workspace directly under the root', () => {
  const root = mkdtempSync(join(tmpdir(), 'ws-')), own = join(root, 'task-a'), other = join(root, 'task-b');
  for (const dir of [own, other]) mkdirSync(join(dir, '.git'), { recursive: true });
  for (const bad of [root, `${other}/../task-a`, join(other, 'x'), join(root, '..'), 'task-a', '']) assert.equal(removeOwnWorkspace(bad, root), false);
  assert.equal(removeOwnWorkspace(own, root), true);
  assert.deepEqual([existsSync(own), existsSync(other)], [false, true]);
  rmSync(root, { recursive: true });
});

const CHAIN = { DEVFLEET_TOOL_FALLBACK_ORDER: 'codex,cursor,claude_code,trae' };

test('fallback order parses, normalises and de-duplicates supported tools only', () => {
  assert.deepEqual(toolFallbackOrder({ DEVFLEET_TOOL_FALLBACK_ORDER: ' Codex, cursor,claude-code,bogus,codex,trae ' }), ['codex', 'cursor', 'claude_code', 'trae']);
  assert.deepEqual(toolFallbackOrder({}), []);
});

test('no fallback order keeps the legacy single-tool path', () => {
  assert.equal(toolAttemptPlan({ task: { tool: 'cursor' }, env: {} }), null);
});

test('requested tool runs first, then the rest of the chain in order without repeats', () => {
  assert.deepEqual(toolAttemptPlan({ task: { tool: 'cursor' }, env: CHAIN }), ['cursor', 'codex', 'claude_code', 'trae']);
  assert.deepEqual(toolAttemptPlan({ task: { tool: 'opencode' }, env: CHAIN }), ['opencode', 'codex', 'cursor', 'claude_code', 'trae']);
  assert.deepEqual(toolAttemptPlan({ task: {}, env: CHAIN }), ['codex', 'cursor', 'claude_code', 'trae']);
  assert.deepEqual(toolAttemptPlan({ task: { tool: 'codex' }, env: CHAIN }), ['codex', 'cursor', 'claude_code', 'trae']);
});

test('tools that are not installed are skipped', () => {
  const installed = new Set(['codex', 'trae']);
  assert.deepEqual(
    toolAttemptPlan({ task: { tool: 'cursor' }, env: CHAIN, isAvailable: (tool) => installed.has(tool) }),
    ['codex', 'trae'],
  );
  assert.deepEqual(toolAttemptPlan({ task: {}, env: CHAIN, isAvailable: () => false }), []);
});

test('a DEVFLEET_FORCE_* switch still overrides the chain', () => {
  assert.equal(toolAttemptPlan({ task: { tool: 'codex' }, env: { ...CHAIN, DEVFLEET_FORCE_CURSOR: '1' } }), null);
  assert.equal(effectiveToolName({ task: { tool: 'codex' }, env: { ...CHAIN, DEVFLEET_FORCE_CURSOR: '1' } }), 'cursor');
});

test('provider mode falls back only on quota, login, billing, rate-limit, timeout or provider errors', () => {
  assert.equal(toolFallbackMode({}), 'provider');
  assert.equal(toolFallbackMode({ DEVFLEET_TOOL_FALLBACK_ON: 'ANY' }), 'any');
  for (const text of [
    'You have an unpaid invoice. Please update your payment method.',
    "ERROR: You've hit your usage limit. Try again later.",
    'Error: not logged in. Please run codex login',
    'HTTP 401 Unauthorized',
    '429 Too Many Requests',
    'request timed out',
    'cursor exited with code null (timed out)\ntimed out',
    'trae 失败: failed to create agent: failed to create agent: Models is required',
  ]) assert.equal(isToolFallbackEligible(text, 'provider'), true, text);
  for (const text of [
    'AssertionError: expected 2 to equal 3',
    'SyntaxError: Unexpected token',
    'safety policy violation: unauthorized content',
    'failed to create agent: Models is required; permission denied',
    '',
  ]) assert.equal(isToolFallbackEligible(text, 'provider'), false, text);
  assert.equal(isToolFallbackEligible('AssertionError: expected 2 to equal 3', 'any'), true);
});

test('workspace is reset in place to the task base between tool attempts', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'chain-'));
  const run = (args) => execFileSync('git', ['-c', 'user.name=t', '-c', 'user.email=t@t', ...args], { cwd: dir, encoding: 'utf8' }).trim();
  try {
    run(['init', '-q', '-b', 'main']);
    run(['config', 'core.autocrlf', 'false']);
    writeFileSync(join(dir, 'a.txt'), 'base\n');
    run(['add', 'a.txt']);
    run(['commit', '-q', '-m', 'base']);
    const baseHead = run(['rev-parse', 'HEAD']);
    run(['checkout', '-q', '-b', 'devfleet/work']);
    mkdirSync(join(dir, '.devfleet'));
    writeFileSync(join(dir, '.devfleet', 'TASK.md'), 'task\n');
    writeFileSync(join(dir, '.git', 'info', 'exclude'), '.devfleet/\n');
    // 上一个工具留下的半成品：一个提交 + 未提交改动 + 新文件
    writeFileSync(join(dir, 'a.txt'), 'tool commit\n');
    run(['commit', '-q', '-am', 'half done']);
    writeFileSync(join(dir, 'a.txt'), 'dirty\n');
    writeFileSync(join(dir, 'new.txt'), 'untracked\n');

    await resetWorkspaceForNextTool(async (cwd, args) => execFileSync('git', args, { cwd, encoding: 'utf8' }), dir, { work_branch: 'devfleet/work' }, baseHead);

    assert.equal(run(['rev-parse', 'HEAD']), baseHead);
    assert.equal(run(['rev-parse', '--abbrev-ref', 'HEAD']), 'devfleet/work');
    assert.equal(run(['status', '--porcelain']), '');
    assert.equal(readFileSync(join(dir, 'a.txt'), 'utf8'), 'base\n');
    assert.equal(existsSync(join(dir, 'new.txt')), false);
    assert.equal(existsSync(join(dir, '.devfleet', 'TASK.md')), true);
    await assert.rejects(resetWorkspaceForNextTool(async () => '', dir, { work_branch: 'x' }, ''), /no task base/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
