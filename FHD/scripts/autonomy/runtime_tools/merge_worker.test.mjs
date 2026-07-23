import assert from 'node:assert/strict';
import test from 'node:test';

import {
  AUTO_PR_LABELS,
  CI_TIMEOUT_POLICY,
  CI_WAIT_MODE,
  CI_WAIT_TIMEOUT_MS,
  INITIAL_PR_LABELS,
  buildMergeConflictPayload,
  forbiddenAutoMergePaths,
  githubIssueLabelEndpoint,
  githubIssueLabelsEndpoint,
  isTransientMergeFailure,
  mergeRetryDelayMs,
  nextMergeRetryState,
  parseGithubRepo,
} from './merge_worker.mjs';


test('merge review veto uses the Para merge-conflict API contract', () => {
  assert.deepEqual(
    buildMergeConflictPayload(
      {
        subTasks: [{ branch_name: 'devfleet/codex/fix-1' }],
        workspace_path: '/tmp/task-1',
      },
      'REJECT: unsafe behavior',
      'ai-review-veto',
    ),
    {
      branch_name: 'devfleet/codex/fix-1',
      detail: 'REJECT: unsafe behavior',
      source: 'ai-review-veto',
      workspace_path: '/tmp/task-1',
    },
  );
});


test('veto labels use the issue labels REST endpoint', () => {
  assert.equal(
    githubIssueLabelsEndpoint('42433422/XCMAX', '555'),
    'repos/42433422/XCMAX/issues/555/labels',
  );
  assert.equal(
    githubIssueLabelEndpoint('42433422/XCMAX', '555', 'hold-merge'),
    'repos/42433422/XCMAX/issues/555/labels/hold-merge',
  );
});


test('loop-approved PRs use the immediate bot-gated lane', () => {
  assert.deepEqual(AUTO_PR_LABELS, ['risk:r0']);
  assert.deepEqual(INITIAL_PR_LABELS, ['hold-merge']);
  assert.equal(AUTO_PR_LABELS.includes('ai-generated'), false);
});


test('parseGithubRepo accepts SSH and HTTPS origins', () => {
  assert.equal(parseGithubRepo('git@github.com:owner/repo.git'), 'owner/repo');
  assert.equal(parseGithubRepo('https://github.com/owner/repo.git'), 'owner/repo');
});


test('forbiddenAutoMergePaths blocks governance and secret surfaces', () => {
  assert.deepEqual(
    forbiddenAutoMergePaths([
      'FHD/app/safe.py',
      '.github/workflows/release.yml',
      'service/.env.production',
      'service/alembic/versions/001.py',
      'frontend/package-lock.json',
    ]),
    [
      '.github/workflows/release.yml',
      'service/.env.production',
      'service/alembic/versions/001.py',
      'frontend/package-lock.json',
    ],
  );
});


test('ordinary implementation and tests remain auto-merge eligible', () => {
  assert.deepEqual(
    forbiddenAutoMergePaths(['FHD/app/service.py', 'FHD/tests/test_service.py']),
    [],
  );
});


test('merge retries use bounded exponential backoff', () => {
  assert.equal(mergeRetryDelayMs(1, 1_000, 8_000), 1_000);
  assert.equal(mergeRetryDelayMs(4, 1_000, 8_000), 8_000);
  assert.equal(mergeRetryDelayMs(8, 1_000, 8_000), 8_000);

  const retry = nextMergeRetryState({ attempts: 1 }, 'HTTP 503', 1_000);
  assert.equal(retry.status, 'retrying');
  assert.equal(retry.attempts, 2);
  assert.equal(retry.reason, 'HTTP 503');
  assert.ok(Date.parse(retry.next_retry_at) > 1_000);
});


test('operational failures retry but review and identity vetoes are terminal', () => {
  assert.equal(isTransientMergeFailure('HTTP 503 service unavailable'), true);
  assert.equal(isTransientMergeFailure('update-branch failed: network timeout'), true);
  assert.equal(isTransientMergeFailure('REJECT: unsafe behavior'), false);
  assert.equal(isTransientMergeFailure('GitHub actor mismatch: expected=bot actual=user'), false);
  assert.equal(isTransientMergeFailure('forbidden-auto-merge-paths: .env'), false);
  assert.equal(isTransientMergeFailure('ci-wait-timeout-fail: required checks'), false);
  assert.equal(isTransientMergeFailure('ci-wait-timeout-needs-human: escalate'), false);
  assert.equal(isTransientMergeFailure('required checks failed or unavailable'), false);
});


test('CI wait policy is explicit in code', () => {
  assert.equal(CI_WAIT_MODE, 'required');
  assert.equal(CI_WAIT_TIMEOUT_MS >= 60_000, true);
  assert.equal(['fail', 'human'].includes(CI_TIMEOUT_POLICY), true);
});
