import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import vm from 'node:vm';

import {
  activeTaskId,
  enqueueByPriority,
  isSelfMaintenanceTask,
} from './para_queue_policy.mjs';

test('self-maintenance tasks move ahead of incident backlog', () => {
  const queue = [];
  enqueueByPriority(queue, { task: { task_id: 'incident', title: 'incident fix' } });
  enqueueByPriority(queue, {
    task: { task_id: 'maintenance-1', title: 'MODstore self-maintenance improvement' },
  });
  enqueueByPriority(queue, {
    task: { task_id: 'maintenance-2', title: 'second self-maintenance task' },
  });

  assert.equal(isSelfMaintenanceTask(queue[0].task), true);
  assert.deepEqual(
    queue.map((item) => item.task.task_id),
    ['maintenance-1', 'maintenance-2', 'incident'],
  );
});

test('active task claim survives queued work and advances to the next task', () => {
  const queue = [{ task: { task_id: 'next' } }];

  assert.equal(activeTaskId('running', queue), 'running');
  assert.equal(activeTaskId('', queue), 'next');
  assert.equal(activeTaskId('', []), '');
});

test('GitHub worker rejects recovery of a different dispatch on the same Para device', () => {
  const source = readFileSync(new URL('./para_e2e_agent.mjs', import.meta.url), 'utf8');
  const queue = [];
  const context = vm.createContext({ process: { env: { GITHUB_ACTIONS: 'true', PARA_GITHUB_REQUEST_ID: 'current' } },
    createHash, console: { error: () => {} }, knownSubtasks: new Set(), taskToolName: () => 'codex',
    taskQueuesByTool: new Map([['codex', queue]]), enqueueByPriority, publishToolStatus: () => {}, drainToolQueue: () => {},
  });
  vm.runInContext(source.slice(source.indexOf('function enqueueTask('), source.indexOf('async function recoverPendingTask(')), context);
  const title = `[xcmax:${createHash('sha256').update('current').digest('hex').slice(0, 32)}:${'a'.repeat(32)}] employee`;
  assert.equal(context.enqueueTask(null, { subtask_id: 'stale', title: 'old task' }), false);
  assert.equal(context.enqueueTask(null, { subtask_id: 'current', title }), true);
  assert.equal(context.enqueueTask(null, { subtask_id: 'current', title }), false);
  assert.equal(queue.length, 1);
});
