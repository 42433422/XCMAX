import assert from 'node:assert/strict';
import test from 'node:test';

import {
  effectiveToolName,
  requestedToolName,
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
