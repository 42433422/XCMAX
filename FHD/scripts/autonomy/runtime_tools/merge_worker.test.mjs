import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  AI_REVIEW_CHUNK_MAX_CHARS,
  AI_REVIEW_MAX_CHUNKS,
  AUTO_PR_LABELS,
  CI_TIMEOUT_POLICY,
  CI_WAIT_MODE,
  CI_WAIT_TIMEOUT_MS,
  INITIAL_PR_LABELS,
  TASK_CONCURRENCY,
  buildMergeConflictPayload,
  blockingMergePollReason,
  chunkReviewDiff,
  forbiddenAutoMergePaths,
  extractSelfMaintenanceRunId,
  githubIssueLabelEndpoint,
  githubIssueLabelsEndpoint,
  isTransientMergeFailure,
  mergeRetryDelayMs,
  nextMergeRetryState,
  parseMergePollSnapshot,
  parseGithubRepo,
  parseReviewVerdict,
  reviewDiffInChunks,
  resolveReviewWithFallback,
  runTaskQueueFairly,
  selectMatchingWorkflowRun,
  selectTaskMergeBase,
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

test('merge task queue uses bounded concurrency without head-of-line blocking', async () => {
  let releaseFirst;
  const firstBlocked = new Promise((resolve) => {
    releaseFirst = resolve;
  });
  let firstStarted = false;
  let secondCompleted = false;

  const run = runTaskQueueFairly(
    ['first', 'second', 'third'],
    async (item) => {
      if (item === 'first') {
        firstStarted = true;
        await firstBlocked;
      }
      if (item === 'second') secondCompleted = true;
      return item;
    },
    2,
  );

  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(firstStarted, true);
  assert.equal(secondCompleted, true);
  releaseFirst();
  const results = await run;
  assert.deepEqual(results.map((result) => result.value), ['first', 'second', 'third']);
  assert.ok(TASK_CONCURRENCY >= 1 && TASK_CONCURRENCY <= 8);
});

test('merge task queue never exceeds the configured concurrency', async () => {
  let active = 0;
  let peak = 0;
  const results = await runTaskQueueFairly(
    [1, 2, 3, 4, 5],
    async (item) => {
      active += 1;
      peak = Math.max(peak, active);
      await new Promise((resolve) => setTimeout(resolve, 5));
      active -= 1;
      return item * 2;
    },
    2,
  );
  assert.equal(peak, 2);
  assert.deepEqual(results.map((result) => result.value), [2, 4, 6, 8, 10]);
});


test('operational failures retry but explicit review and identity vetoes are terminal', () => {
  assert.equal(isTransientMergeFailure('HTTP 503 service unavailable'), true);
  assert.equal(isTransientMergeFailure('update-branch failed: network timeout'), true);
  assert.equal(
    isTransientMergeFailure(
      'indeterminate-review: {"primary":"timeout","fallback":"minimax-key-unavailable"}',
    ),
    true,
  );
  assert.equal(isTransientMergeFailure('REJECT: unsafe behavior'), false);
  assert.equal(isTransientMergeFailure('GitHub actor mismatch: expected=bot actual=user'), false);
  assert.equal(isTransientMergeFailure('forbidden-auto-merge-paths: .env'), false);
  assert.equal(isTransientMergeFailure('manual-veto-active: PR #730 has hold-merge label'), false);
  assert.equal(isTransientMergeFailure('post-dispatch-check-failed: PR #730 checks=test'), false);
  assert.equal(isTransientMergeFailure('ci-wait-timeout-fail: required checks'), false);
  assert.equal(isTransientMergeFailure('ci-wait-timeout-needs-human: escalate'), false);
  assert.equal(isTransientMergeFailure('required checks failed or unavailable'), false);
});

test('merge polling stops for a restored human veto or terminal check failure', () => {
  assert.equal(
    blockingMergePollReason(
      {
        labels: [{ name: 'risk:r0' }, { name: 'hold-merge' }],
        statusCheckRollup: [],
      },
      730,
    ),
    'manual-veto-active: PR #730 has hold-merge label',
  );
  assert.equal(
    blockingMergePollReason(
      {
        labels: [{ name: 'risk:r0' }],
        statusCheckRollup: [
          { name: 'review', conclusion: 'SUCCESS' },
          { name: 'modstore-backend-test', conclusion: 'FAILURE' },
        ],
      },
      730,
    ),
    'post-dispatch-check-failed: PR #730 checks=modstore-backend-test',
  );
  assert.equal(
    blockingMergePollReason(
      {
        labels: [{ name: 'risk:r0' }],
        statusCheckRollup: [
          { name: 'review', conclusion: 'SUCCESS' },
          { name: 'backend-test', conclusion: '' },
        ],
      },
      730,
    ),
    '',
  );
});

test('merge polling preserves the parsed PR snapshot for post-fetch policy checks', () => {
  const snapshot = parseMergePollSnapshot(JSON.stringify({
    state: 'OPEN',
    mergeCommit: null,
    labels: [{ name: 'hold-merge' }],
    statusCheckRollup: [],
  }));
  assert.equal(snapshot.prState, 'OPEN');
  assert.equal(snapshot.mergeOid, '');
  assert.equal(
    blockingMergePollReason(snapshot.pr, 761),
    'manual-veto-active: PR #761 has hold-merge label',
  );
});

test('self-maintenance deployment correlation requires the explicit loop run marker', () => {
  assert.equal(
    extractSelfMaintenanceRunId({
      description: "task text LOOP_RUN_ID='02b3e3c8-1dc7-4449-a348-b375694be9a8'",
    }),
    '02b3e3c8-1dc7-4449-a348-b375694be9a8',
  );
  assert.equal(
    extractSelfMaintenanceRunId({
      description: 'unrelated uuid 02b3e3c8-1dc7-4449-a348-b375694be9a8',
    }),
    '',
  );
});

test('workflow correlation selects the newest run for the exact merge SHA', () => {
  assert.deepEqual(
    selectMatchingWorkflowRun(
      [
        {
          databaseId: 1,
          headSha: 'a'.repeat(40),
          createdAt: '2026-07-27T00:00:00Z',
        },
        {
          databaseId: 2,
          headSha: 'b'.repeat(40),
          createdAt: '2026-07-27T00:02:00Z',
        },
        {
          databaseId: 3,
          headSha: 'a'.repeat(40),
          createdAt: '2026-07-27T00:01:00Z',
        },
      ],
      'a'.repeat(40),
    )?.databaseId,
    3,
  );
});


test('CI wait policy is explicit in code', () => {
  assert.equal(CI_WAIT_MODE, 'required');
  assert.equal(CI_WAIT_TIMEOUT_MS >= 60_000, true);
  assert.equal(['fail', 'human'].includes(CI_TIMEOUT_POLICY), true);
});


test('review verdict parser accepts strict lines and structured JSON', () => {
  assert.equal(parseReviewVerdict('analysis\nAPPROVE')?.verdict, 'approve');
  assert.equal(parseReviewVerdict('VERDICT: APPROVE')?.verdict, 'approve');
  assert.equal(
    parseReviewVerdict('{"verdict":"reject","reason":"business_logic=data loss"}')?.reason,
    'REJECT: business_logic=data loss',
  );
  assert.equal(parseReviewVerdict('looks good but no protocol'), null);
});


test('indeterminate Trae review falls back to MiniMax', async () => {
  const result = await resolveReviewWithFallback({
    primary: async () => 'analysis without a verdict',
    fallback: async () => '{"verdict":"approve","reason":"all dimensions pass"}',
  });
  assert.equal(result.verdict, 'approve');
  assert.equal(result.provider, 'minimax');
});


test('review remains fail-closed when Trae and MiniMax are unavailable', async () => {
  const result = await resolveReviewWithFallback({
    primary: async () => { throw new Error('timeout'); },
    fallback: async () => { throw new Error('minimax-key-unavailable'); },
  });
  assert.equal(result.verdict, 'reject');
  assert.equal(result.reason, 'indeterminate-review');
  assert.match(result.diagnostics.primary, /timeout/);
  assert.match(result.diagnostics.fallback, /minimax-key-unavailable/);
});

test('large diffs are completely partitioned into bounded review chunks', () => {
  const diff = `${'a'.repeat(12_345)}\n${'b'.repeat(12_345)}\n${'c'.repeat(12_345)}`;
  const chunks = chunkReviewDiff(diff, 10_000);
  assert.equal(chunks.join(''), diff);
  assert.equal(chunks.length, 4);
  assert.equal(chunks.every((chunk) => chunk.length <= 10_000), true);
  assert.equal(AI_REVIEW_CHUNK_MAX_CHARS >= 8_000, true);
  assert.equal(AI_REVIEW_MAX_CHUNKS >= 1, true);
});


test('large diff approval requires every review chunk to approve', async () => {
  const reviewed = [];
  const result = await reviewDiffInChunks(
    'x'.repeat(31_435),
    async (chunk, position) => {
      reviewed.push({ length: chunk.length, ...position });
      return { verdict: 'approve', provider: 'test' };
    },
    { maxChars: 20_000, maxChunks: 3 },
  );
  assert.equal(result.verdict, 'approve');
  assert.equal(result.reviewed_chunks, 2);
  assert.deepEqual(reviewed.map((item) => item.number), [1, 2]);
  assert.equal(reviewed.reduce((total, item) => total + item.length, 0), 31_435);
});


test('one rejected review chunk vetoes the whole diff', async () => {
  const result = await reviewDiffInChunks(
    'x'.repeat(31_435),
    async (_chunk, position) => (
      position.number === 2
        ? { verdict: 'reject', reason: 'REJECT: security=unsafe input' }
        : { verdict: 'approve', provider: 'test' }
    ),
    { maxChars: 20_000, maxChunks: 3 },
  );
  assert.equal(result.verdict, 'reject');
  assert.equal(result.reason, 'chunk 2/2: REJECT: security=unsafe input');
});


test('review chunk count remains bounded and fail-closed', async () => {
  let calls = 0;
  const result = await reviewDiffInChunks(
    'x'.repeat(31),
    async () => {
      calls += 1;
      return { verdict: 'approve', provider: 'test' };
    },
    { maxChars: 10, maxChunks: 3 },
  );
  assert.equal(result.verdict, 'reject');
  assert.equal(result.reason, 'diff-too-large:31:chunks=4:limit=3');
  assert.equal(calls, 0);
});


test('review remediation branches are promoted to the rejected PR canonical base', () => {
  const task = {
    branch: 'devfleet/codex/rejected-candidate',
    description: 'context\n=== EXTERNAL MERGE REVIEW REMEDIATION ===\nexact findings',
  };
  assert.equal(selectTaskMergeBase(task, 'main'), 'main');
  assert.throws(
    () => selectTaskMergeBase(task, ''),
    /remediation-parent-base-unavailable/,
  );
  assert.equal(selectTaskMergeBase({ branch: 'release/1', description: 'ordinary' }), 'release/1');
});


test('self-maintenance continuation branches always merge to canonical main', () => {
  const task = {
    branch: 'devfleet/cursor/previous-remediation',
    description: (
      'Run a real MODstore self-maintenance improvement task. '
      + '=== SELF_MAINTENANCE_CANONICAL_MERGE_BASE:main ==='
    ),
  };
  assert.equal(selectTaskMergeBase(task, ''), 'main');
});


test('installer repairs stale Node paths and reloads the LaunchAgent definition', () => {
  const installer = readFileSync(
    new URL('./install_merge_worker.sh', import.meta.url),
    'utf8',
  );
  assert.match(installer, /configured_node=.*ProgramArguments:0/);
  assert.match(installer, /NODE_BIN=.*command -v node/);
  assert.match(installer, /Set :ProgramArguments:0 \$NODE_BIN/);
  assert.match(installer, /launchctl bootout "\$target"/);
  assert.match(installer, /bootstrap_agent\(\)/);
  assert.match(installer, /for attempt in 1 2 3/);
  assert.match(installer, /bootstrap_agent/);
  assert.match(installer, /trap .*EXIT/);
});
