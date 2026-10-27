import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import {
  effectiveToolName,
  isToolFallbackEligible,
  removeOwnWorkspace,
  requestedToolName,
  resetWorkspaceForNextTool,
  toolAttemptPlan,
  toolFallbackMode,
  toolFallbackOrder,
  withFailureCleanup,
} from './e2e_agent_runtime_policy.mjs';

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
