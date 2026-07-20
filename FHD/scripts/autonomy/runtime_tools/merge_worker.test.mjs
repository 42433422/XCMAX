import assert from 'node:assert/strict';
import test from 'node:test';

import {
  AUTO_PR_LABELS,
  forbiddenAutoMergePaths,
  isTransientMergeFailure,
  mergeRetryDelayMs,
  nextMergeRetryState,
  parseGithubRepo,
} from './merge_worker.mjs';


test('loop-approved PRs use the immediate bot-gated lane', () => {
  assert.deepEqual(AUTO_PR_LABELS, ['risk:r0']);
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
});
