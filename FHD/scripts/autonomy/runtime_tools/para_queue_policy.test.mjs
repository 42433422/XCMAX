import assert from 'node:assert/strict';
import test from 'node:test';

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
