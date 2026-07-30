#!/usr/bin/env node
// Para /api/tasks/merge-queue 消费者：把已完成子任务的工作分支 merge 回 base branch，
// 然后把 merge_commit_sha 回传给 Para。解决了「任务 completed 后无 merge 消费者」断点。
//
// 触发条件：任务 auto_merge=true 且 workspace_path 非空（由 FHD invoke 在派工时设置）。
// 安全：缺 diff、审查异常、结论不明确或高风险路径一律 fail-closed。
// 冲突：保留 PR + hold-merge veto，并写入 merge-conflict 供后续自治修复。

import { execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import {
  chmodSync,
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  statSync,
  unlinkSync,
  writeFileSync,
} from 'node:fs';
import { dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { promisify } from 'node:util';

const execFileAsync = promisify(execFile);

const API_BASE = process.env.PARA_API_BASE || 'http://127.0.0.1:3001';
const POLL_SEC = Number.parseInt(process.env.MERGE_WORKER_POLL_SEC || '15', 10);
const STATE_FILE = process.env.MERGE_WORKER_STATE_FILE
  || `${process.env.HOME || '/tmp'}/.xcmax/autonomy/para-merge-worker-state.json`;
const EXPECTED_GITHUB_ACTOR = String(process.env.MERGE_WORKER_EXPECTED_GITHUB_ACTOR || '').trim();
const REQUIRE_BOT_IDENTITY = process.env.MERGE_WORKER_REQUIRE_BOT_IDENTITY !== '0';
const BOT_MERGE_WORKFLOW = String(
  process.env.MERGE_WORKER_BOT_WORKFLOW || 'fhd-ai-self-heal-auto-merge.yml',
).trim();
const BOT_MERGE_WATCHDOG_REPOSITORY = String(
  process.env.MERGE_WORKER_REPOSITORY || '',
).trim();
const SELF_UPDATE_ENABLED = process.env.MERGE_WORKER_SELF_UPDATE !== '0';
const SELF_UPDATE_BRANCH = String(
  process.env.MERGE_WORKER_SELF_UPDATE_BRANCH || 'main',
).trim();
const SELF_UPDATE_SOURCE_PATH = (
  'FHD/scripts/autonomy/runtime_tools/merge_worker.mjs'
);
const SELF_UPDATE_CHECK_MS = Math.max(
  5 * 60 * 1000,
  Number.parseInt(
    process.env.MERGE_WORKER_SELF_UPDATE_CHECK_MS || String(15 * 60 * 1000),
    10,
  ),
);
export const BOT_MERGE_WATCHDOG_STALE_MS = Math.max(
  30 * 60 * 1000,
  Number.parseInt(
    process.env.MERGE_WORKER_BOT_WATCHDOG_STALE_MS || String(45 * 60 * 1000),
    10,
  ),
);
const BOT_MERGE_WATCHDOG_CHECK_MS = Math.max(
  60_000,
  Number.parseInt(
    process.env.MERGE_WORKER_BOT_WATCHDOG_CHECK_MS || String(5 * 60 * 1000),
    10,
  ),
);
const BOT_MERGE_WATCHDOG_DISPATCH_COOLDOWN_MS = Math.max(
  15 * 60 * 1000,
  Number.parseInt(
    process.env.MERGE_WORKER_BOT_WATCHDOG_DISPATCH_COOLDOWN_MS
      || String(30 * 60 * 1000),
    10,
  ),
);
const BACKEND_CI_WORKFLOW = String(
  process.env.MERGE_WORKER_BACKEND_CI_WORKFLOW || 'modstore-ci-backend-python.yml',
).trim();
const PRODUCTION_DEPLOY_WORKFLOW = String(
  process.env.MERGE_WORKER_PRODUCTION_DEPLOY_WORKFLOW || 'modstore-prod-deploy.yml',
).trim();
const MAX_RETRY_ATTEMPTS = Math.max(1, Number.parseInt(process.env.MERGE_WORKER_MAX_RETRIES || '5', 10));
const RETRY_BASE_MS = Math.max(1_000, Number.parseInt(process.env.MERGE_WORKER_RETRY_BASE_MS || '30000', 10));
const RETRY_MAX_MS = Math.max(RETRY_BASE_MS, Number.parseInt(process.env.MERGE_WORKER_RETRY_MAX_MS || '900000', 10));
export const INDETERMINATE_REVIEW_RECOVERY_MAX_AGE_MS = Math.max(
  60 * 60 * 1000,
  Number.parseInt(
    process.env.MERGE_WORKER_INDETERMINATE_RECOVERY_MAX_AGE_MS
      || String(24 * 60 * 60 * 1000),
    10,
  ),
);
export const TASK_CONCURRENCY = Math.min(
  8,
  Math.max(1, Number.parseInt(process.env.MERGE_WORKER_TASK_CONCURRENCY || '4', 10)),
);
const AI_REVIEW_TIMEOUT_MS = Math.max(
  30_000,
  Number.parseInt(process.env.MERGE_WORKER_AI_REVIEW_TIMEOUT_MS || '180000', 10),
);
export const AI_REVIEW_CHUNK_MAX_CHARS = Math.max(
  8_000,
  Number.parseInt(process.env.MERGE_WORKER_AI_REVIEW_CHUNK_MAX_CHARS || '22000', 10),
);
export const AI_REVIEW_MAX_CHUNKS = Math.max(
  1,
  Number.parseInt(process.env.MERGE_WORKER_AI_REVIEW_MAX_CHUNKS || '6', 10),
);
const MINIMAX_REVIEW_TIMEOUT_MS = Math.max(
  15_000,
  Number.parseInt(process.env.MERGE_WORKER_MINIMAX_REVIEW_TIMEOUT_MS || '90000', 10),
);
const MINIMAX_REVIEW_MODEL = String(
  process.env.MERGE_WORKER_MINIMAX_REVIEW_MODEL || process.env.MINIMAX_MODEL || 'MiniMax-M2.7',
).trim();
const MINIMAX_KEYCHAIN_SERVICE = String(
  process.env.MERGE_WORKER_MINIMAX_KEYCHAIN_SERVICE || 'xcmax-minimax-api-key',
).trim();
const TOKEN_TTL_MS = 5 * 60 * 1000; // Para guest 限 15min/30 次，复用 5 分钟避免耗尽
export const AUTO_PR_LABELS = Object.freeze(['risk:r0']);
export const INITIAL_PR_LABELS = Object.freeze(['hold-merge']);

// CI 等待策略（写进代码，不做隐式默认）：
// - 等哪些 check：`gh pr checks` 返回的全部检查，与 bot merge SLA 的三重门禁一致
// - 超时：MERGE_WORKER_CI_WAIT_TIMEOUT_MS，默认 60min
// - 超时后：MERGE_WORKER_CI_TIMEOUT_POLICY=retry|fail|human
//     retry → 退避后重新读取完整 rollup（默认；不把 CI 排队/长测误判为 AI 拒绝）
//     fail  → 抛错并标 terminal（不自动合并；merge-worker 记 failed）
//     human → 抛错文案含 needs-human，走人工（非 transient，不空转重试）
export const CI_WAIT_MODE = 'bot-merge-gate';
export const CI_WAIT_TIMEOUT_MS = Math.max(
  60_000,
  Number.parseInt(process.env.MERGE_WORKER_CI_WAIT_TIMEOUT_MS || String(60 * 60 * 1000), 10),
);
const requestedCiTimeoutPolicy = String(
  process.env.MERGE_WORKER_CI_TIMEOUT_POLICY || 'retry',
).trim().toLowerCase();
export const CI_TIMEOUT_POLICY = ['retry', 'fail', 'human'].includes(requestedCiTimeoutPolicy)
  ? requestedCiTimeoutPolicy
  : 'retry';

const FORBIDDEN_AUTO_MERGE_PATHS = [
  /^\.github\/workflows\//,
  /(^|\/)\.env(?:\.|$)/,
  /(^|\/)(?:secrets?|credentials?|tokens?)(?:\/|\.|$)/i,
  /(^|\/)(?:migrations?|alembic)(?:\/|$)/i,
  /(^|\/)Dockerfile/i,
  /(^|\/)docker-compose[^/]*\.ya?ml$/i,
  /(^|\/)package-lock\.json$/,
  /(^|\/)requirements[^/]*\.txt$/,
  /(^|\/)pyproject\.toml$/,
];

let cachedToken = '';
let cachedTokenAt = 0;
let botMergeWatchdogLastCheckedAt = 0;
let botMergeWatchdogLastDispatchAt = 0;
let selfUpdateLastCheckedAt = 0;

function log(...args) {
  console.log(new Date().toISOString().slice(11, 19), '[merge-worker]', ...args);
}

export function gitBlobSha(source) {
  const body = Buffer.isBuffer(source) ? source : Buffer.from(String(source || ''), 'utf8');
  return createHash('sha1')
    .update(Buffer.from(`blob ${body.length}\0`, 'utf8'))
    .update(body)
    .digest('hex');
}

export function decodeSelfUpdatePayload(payload) {
  if (String(payload?.encoding || '').trim().toLowerCase() !== 'base64') {
    throw new Error('self-update-content-encoding-invalid');
  }
  const expectedBlobSha = String(payload?.sha || '').trim().toLowerCase();
  if (!/^[0-9a-f]{40}$/.test(expectedBlobSha)) {
    throw new Error('self-update-blob-sha-invalid');
  }
  const encoded = String(payload?.content || '').replace(/\s+/g, '');
  if (!encoded) throw new Error('self-update-content-empty');
  const source = Buffer.from(encoded, 'base64');
  if (source.length === 0 || source.length > 5 * 1024 * 1024) {
    throw new Error('self-update-content-size-invalid');
  }
  if (gitBlobSha(source) !== expectedBlobSha) {
    throw new Error('self-update-blob-sha-mismatch');
  }
  const text = source.toString('utf8');
  if (
    !text.startsWith('#!/usr/bin/env node')
    || !text.includes('Para /api/tasks/merge-queue')
  ) {
    throw new Error('self-update-source-identity-invalid');
  }
  return {
    blobSha: expectedBlobSha,
    digest: createHash('sha256').update(source).digest('hex'),
    source,
  };
}

export function selfUpdateTemporaryPath(currentFile, pid = process.pid) {
  return `${currentFile}.self-update.${pid}.mjs`;
}

async function maybeSelfUpdate(nowMs = Date.now()) {
  if (
    !SELF_UPDATE_ENABLED
    || !BOT_MERGE_WATCHDOG_REPOSITORY
    || !SELF_UPDATE_BRANCH
  ) {
    return false;
  }
  if (nowMs - selfUpdateLastCheckedAt < SELF_UPDATE_CHECK_MS) return false;
  selfUpdateLastCheckedAt = nowMs;

  const { stdout } = await execFileAsync('gh', [
    'api',
    '--method', 'GET',
    `repos/${BOT_MERGE_WATCHDOG_REPOSITORY}/contents/${SELF_UPDATE_SOURCE_PATH}`,
    '-f', `ref=${SELF_UPDATE_BRANCH}`,
  ], {
    cwd: process.env.HOME || '/tmp',
    maxBuffer: 10 * 1024 * 1024,
    timeout: 30_000,
  });
  const remote = decodeSelfUpdatePayload(JSON.parse(stdout || '{}'));
  const currentFile = fileURLToPath(import.meta.url);
  const current = readFileSync(currentFile);
  const currentDigest = createHash('sha256').update(current).digest('hex');
  if (currentDigest === remote.digest) return false;

  const temporary = selfUpdateTemporaryPath(currentFile);
  try {
    writeFileSync(temporary, remote.source, { mode: statSync(currentFile).mode & 0o777 });
    chmodSync(temporary, statSync(currentFile).mode & 0o777);
    await execFileAsync(process.execPath, ['--check', temporary], {
      cwd: dirname(currentFile),
      maxBuffer: 10 * 1024 * 1024,
      timeout: 30_000,
    });
    renameSync(temporary, currentFile);
    writeFileSync(
      `${currentFile}.sha256`,
      `${remote.digest}  source_blob=${remote.blobSha} branch=${SELF_UPDATE_BRANCH}\n`,
      { mode: 0o600 },
    );
  } catch (error) {
    if (existsSync(temporary)) unlinkSync(temporary);
    throw error;
  }
  log(
    `自更新完成：branch=${SELF_UPDATE_BRANCH} `
    + `blob=${remote.blobSha.slice(0, 12)} sha256=${remote.digest.slice(0, 12)}`,
  );
  return true;
}

async function guestToken() {
  if (cachedToken && Date.now() - cachedTokenAt < TOKEN_TTL_MS) return cachedToken;
  const resp = await fetch(`${API_BASE}/api/auth/guest`, { method: 'POST' });
  if (!resp.ok) throw new Error(`guest auth ${resp.status}`);
  const body = await resp.json();
  cachedToken = body.token;
  cachedTokenAt = Date.now();
  return cachedToken;
}

async function fetchMergeQueue(token) {
  const resp = await fetch(`${API_BASE}/api/tasks/merge-queue`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!resp.ok) throw new Error(`merge-queue ${resp.status}`);
  const body = await resp.json();
  return body.tasks || [];
}

async function fetchTask(token, taskId) {
  const resp = await fetch(`${API_BASE}/api/tasks/${taskId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!resp.ok) throw new Error(`task ${taskId} ${resp.status}`);
  const body = await resp.json();
  return body.task || body;
}

function loadProcessed() {
  try {
    const raw = readFileSyncSafe(STATE_FILE);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function readFileSyncSafe(path) {
  if (!existsSync(path)) return '';
  return readFileSync(path, 'utf8');
}

function saveProcessed(state) {
  mkdirSync(dirname(STATE_FILE), { recursive: true, mode: 0o700 });
  const temporary = `${STATE_FILE}.${process.pid}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(state, null, 2)}\n`, { mode: 0o600 });
  renameSync(temporary, STATE_FILE);
}

async function git(cwd, args) {
  const { stdout, stderr } = await execFileAsync('git', args, {
    cwd,
    maxBuffer: 10 * 1024 * 1024,
    timeout: 60_000,
    env: { ...process.env, GIT_TERMINAL_PROMPT: '0' },
  });
  return (stdout || stderr).trim();
}

async function gitMaybe(cwd, args) {
  try {
    return await git(cwd, args);
  } catch {
    return '';
  }
}

async function postJson(token, path, body) {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });
  const text = await resp.text();
  let parsed = null;
  try { parsed = JSON.parse(text); } catch {}
  return { ok: resp.ok, status: resp.status, body: parsed, text };
}

export function buildMergeConflictPayload(task, reason, source = 'merge-worker') {
  return {
    branch_name: task.subTasks?.[0]?.branch_name || '',
    detail: String(reason).slice(0, 1000),
    source,
    workspace_path: String(task.workspace_path || ''),
  };
}

async function reportMergeConflict(token, task, reason, source = 'merge-worker') {
  const conflict = buildMergeConflictPayload(task, reason, source);
  return postJson(token, `/api/tasks/${task.id}/merge-conflict`, conflict);
}

async function reportMerged(token, task, sha) {
  return postJson(token, `/api/tasks/${task.id}/merge`, { merge_commit_sha: sha });
}

// 解析 GitHub repo owner/name，用于 gh --repo 参数
export function parseGithubRepo(repoUrl) {
  const url = String(repoUrl || '').trim();
  // git@github.com:owner/name.git 或 https://github.com/owner/name.git
  const m = url.match(/github\.com[:/]([^/]+)\/([^/]+?)(?:\.git)?(?:\/|$)/i);
  return m ? `${m[1]}/${m[2]}` : '';
}

export function forbiddenAutoMergePaths(paths) {
  return paths.filter((path) => FORBIDDEN_AUTO_MERGE_PATHS.some((pattern) => pattern.test(path)));
}

export function mergeRetryDelayMs(attempt, baseMs = RETRY_BASE_MS, maxMs = RETRY_MAX_MS) {
  const normalizedAttempt = Math.max(1, Number.parseInt(String(attempt), 10) || 1);
  return Math.min(maxMs, baseMs * (2 ** (normalizedAttempt - 1)));
}

export function isTransientMergeFailure(reason) {
  const text = String(reason || '').toLowerCase();
  const terminal = [
    'actor mismatch',
    'bot merge checks failed',
    'changed-files-empty',
    'ci-wait-timeout-fail',
    'ci-wait-timeout-needs-human',
    'closed without merge',
    'diff-too-large',
    'empty-diff',
    'forbidden-auto-merge-paths',
    'is not a bot identity',
    'manual-veto-active',
    'no-diff-available',
    'post-dispatch-check-failed',
    'reject:',
    'required checks failed',
    'cannot update pr branch due to conflicts',
  ];
  if (terminal.some((pattern) => text.includes(pattern))) return false;
  return true;
}

export function mergeFailuresAreRetryable(results) {
  return Array.isArray(results)
    && results.length > 0
    && results.every((result) => {
      if (result?.vetoed) return false;
      if (result?.retryable === true) return true;
      if (result?.retryable === false) return false;
      return isTransientMergeFailure(result?.reason || result?.error);
    });
}

export function isRecoverableIndeterminateReviewRecord(record, nowMs = Date.now()) {
  if (!['ai_rejected', 'retrying'].includes(String(record?.status || ''))) return false;
  if (!/\bindeterminate-review:\s*\{/.test(String(record?.reason || ''))) return false;
  const recordedAt = Date.parse(String(record?.at || ''));
  if (!Number.isFinite(recordedAt) || recordedAt > nowMs) return false;
  return nowMs - recordedAt <= INDETERMINATE_REVIEW_RECOVERY_MAX_AGE_MS;
}

export function taskHasRecoverableIndeterminateReviewConflict(task) {
  const conflict = task?.merge_conflict;
  return String(task?.status || '') === 'merge_conflict'
    && conflict
    && String(conflict.source || '') === 'merge-worker'
    && /\bindeterminate-review:\s*\{/.test(String(conflict.detail || ''));
}

export function isProcessTimeoutError(err) {
  const message = String(err?.message || err || '');
  const code = String(err?.code || '').toUpperCase();
  const signal = String(err?.signal || '').toUpperCase();
  return err?.killed === true
    || code === 'ETIMEDOUT'
    || signal === 'SIGTERM'
    || signal === 'SIGKILL'
    || /ETIMEDOUT|timed?\s*out|timeout/i.test(message);
}

export function blockingMergePollReason(pr, prNumber = '') {
  const labels = Array.isArray(pr?.labels) ? pr.labels : [];
  const hasManualVeto = labels.some(
    (label) => String(label?.name || label || '').trim().toLowerCase() === 'hold-merge',
  );
  if (hasManualVeto) {
    return `manual-veto-active: PR #${prNumber || '?'} has hold-merge label`;
  }

  const terminalConclusions = new Set([
    'ACTION_REQUIRED',
    'CANCELLED',
    'FAILURE',
    'STALE',
    'STARTUP_FAILURE',
    'TIMED_OUT',
  ]);
  const failedChecks = (Array.isArray(pr?.statusCheckRollup) ? pr.statusCheckRollup : [])
    .filter((check) => terminalConclusions.has(String(check?.conclusion || '').toUpperCase()))
    .map((check) => String(check?.name || 'unnamed-check'));
  if (failedChecks.length > 0) {
    return `post-dispatch-check-failed: PR #${prNumber || '?'} checks=${failedChecks.join(',')}`;
  }
  return '';
}

export function parseMergePollSnapshot(output) {
  const pr = JSON.parse(String(output || '{}'));
  return {
    pr,
    prState: String(pr.state || '').toUpperCase(),
    mergeOid: String(pr.mergeCommit?.oid || ''),
  };
}

export function extractSelfMaintenanceRunId(task) {
  const direct = String(task?.self_maintenance_run_id || task?.run_id || '').trim();
  const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  if (uuidPattern.test(direct)) return direct.toLowerCase();
  const description = String(task?.description || '');
  const match = description.match(
    /\bLOOP_RUN_ID\s*=\s*['"]([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})['"]/i,
  );
  return match ? match[1].toLowerCase() : '';
}

export function selectMatchingWorkflowRun(rows, mergeSha) {
  const wanted = String(mergeSha || '').trim().toLowerCase();
  return (Array.isArray(rows) ? rows : [])
    .filter((row) => String(row?.headSha || '').trim().toLowerCase() === wanted)
    .sort((left, right) => (
      Date.parse(String(right?.createdAt || '')) - Date.parse(String(left?.createdAt || ''))
    ))[0] || null;
}

export function botMergeWatchdogDecision(
  rows,
  {
    nowMs = Date.now(),
    staleAfterMs = BOT_MERGE_WATCHDOG_STALE_MS,
    lastDispatchAtMs = 0,
    dispatchCooldownMs = BOT_MERGE_WATCHDOG_DISPATCH_COOLDOWN_MS,
  } = {},
) {
  const items = Array.isArray(rows) ? rows : [];
  const active = items.find((row) => (
    ['queued', 'in_progress', 'requested', 'waiting']
      .includes(String(row?.status || '').trim().toLowerCase())
  ));
  if (active) {
    return {
      dispatch: false,
      reason: 'workflow-active',
      latest_run_at: String(active.createdAt || ''),
    };
  }
  const latestRunMs = items.reduce((latest, row) => {
    const parsed = Date.parse(String(row?.createdAt || ''));
    return Number.isFinite(parsed) ? Math.max(latest, parsed) : latest;
  }, 0);
  if (latestRunMs > 0 && nowMs - latestRunMs < staleAfterMs) {
    return {
      dispatch: false,
      reason: 'workflow-recent',
      latest_run_at: new Date(latestRunMs).toISOString(),
    };
  }
  if (lastDispatchAtMs > 0 && nowMs - lastDispatchAtMs < dispatchCooldownMs) {
    return {
      dispatch: false,
      reason: 'dispatch-cooldown',
      latest_run_at: latestRunMs > 0 ? new Date(latestRunMs).toISOString() : '',
    };
  }
  return {
    dispatch: true,
    reason: latestRunMs > 0 ? 'workflow-stale' : 'workflow-missing',
    latest_run_at: latestRunMs > 0 ? new Date(latestRunMs).toISOString() : '',
  };
}

async function maybeRecoverStaleBotMergeWorkflow(nowMs = Date.now()) {
  if (!BOT_MERGE_WORKFLOW || !BOT_MERGE_WATCHDOG_REPOSITORY) return;
  if (nowMs - botMergeWatchdogLastCheckedAt < BOT_MERGE_WATCHDOG_CHECK_MS) return;
  botMergeWatchdogLastCheckedAt = nowMs;
  const { stdout } = await execFileAsync('gh', [
    'api',
    '--method', 'GET',
    `repos/${BOT_MERGE_WATCHDOG_REPOSITORY}/actions/workflows/${BOT_MERGE_WORKFLOW}/runs`,
    '-f', 'per_page=5',
  ], {
    cwd: process.env.HOME || '/tmp',
    maxBuffer: 10 * 1024 * 1024,
    timeout: 30_000,
  });
  const payload = JSON.parse(stdout || '{}');
  const rows = (Array.isArray(payload.workflow_runs) ? payload.workflow_runs : [])
    .map((row) => ({
      createdAt: row?.created_at,
      status: row?.status,
    }));
  const decision = botMergeWatchdogDecision(rows, {
    nowMs,
    lastDispatchAtMs: botMergeWatchdogLastDispatchAt,
  });
  if (!decision.dispatch) return;
  await execFileAsync('gh', [
    'workflow', 'run', BOT_MERGE_WORKFLOW,
    '--repo', BOT_MERGE_WATCHDOG_REPOSITORY,
    '--ref', 'main',
    '-f', 'dry_run=false',
    '-f', 'scan_regular_prs=true',
  ], {
    cwd: process.env.HOME || '/tmp',
    maxBuffer: 10 * 1024 * 1024,
    timeout: 60_000,
  });
  botMergeWatchdogLastDispatchAt = nowMs;
  log(
    `  watchdog dispatched ${BOT_MERGE_WORKFLOW} `
    + `reason=${decision.reason} latest=${decision.latest_run_at || 'none'}`,
  );
}

export function nextMergeRetryState(previous, reason, nowMs = Date.now()) {
  const attempts = Math.max(0, Number(previous?.attempts || 0)) + 1;
  const delayMs = mergeRetryDelayMs(attempts);
  return {
    at: new Date(nowMs).toISOString(),
    attempts,
    exhausted: attempts > MAX_RETRY_ATTEMPTS,
    next_retry_at: new Date(nowMs + delayMs).toISOString(),
    reason: String(reason || '').slice(0, 2000),
    status: 'retrying',
  };
}

export async function runTaskQueueFairly(
  tasks,
  handler,
  concurrency = TASK_CONCURRENCY,
) {
  const items = Array.isArray(tasks) ? tasks : [];
  if (items.length === 0) return [];
  const workerCount = Math.min(
    items.length,
    Math.max(1, Number.parseInt(String(concurrency), 10) || 1),
  );
  const results = new Array(items.length);
  let cursor = 0;
  async function consume() {
    while (cursor < items.length) {
      const index = cursor;
      cursor += 1;
      try {
        results[index] = {
          status: 'fulfilled',
          value: await handler(items[index], index),
        };
      } catch (reason) {
        results[index] = { status: 'rejected', reason };
      }
    }
  }
  await Promise.all(Array.from({ length: workerCount }, () => consume()));
  return results;
}

async function listWorkflowRuns(workspace, repoFull, workflow, mergeSha) {
  const args = [
    'run', 'list',
    '--workflow', workflow,
    '--event', 'workflow_dispatch',
    '--commit', mergeSha,
    '--limit', '20',
    '--json', 'databaseId,status,conclusion,headSha,createdAt,url',
  ];
  if (repoFull) args.push('--repo', repoFull);
  const { stdout } = await execFileAsync('gh', args, {
    cwd: workspace || process.env.HOME,
    maxBuffer: 10 * 1024 * 1024,
    timeout: 30_000,
  });
  const rows = JSON.parse(stdout || '[]');
  return Array.isArray(rows) ? rows : [];
}

async function waitForSuccessfulBackendCI(workspace, repoFull, mergeSha) {
  const deadline = Date.now() + CI_WAIT_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const run = selectMatchingWorkflowRun(
      await listWorkflowRuns(workspace, repoFull, BACKEND_CI_WORKFLOW, mergeSha),
      mergeSha,
    );
    const status = String(run?.status || '').toLowerCase();
    const conclusion = String(run?.conclusion || '').toLowerCase();
    if (status === 'completed' && conclusion === 'success') return run;
    if (status === 'completed' && conclusion && conclusion !== 'success') {
      throw new Error(
        `post-merge-backend-ci-failed: sha=${mergeSha} conclusion=${conclusion}`,
      );
    }
    await new Promise((resolve) => setTimeout(resolve, 10_000));
  }
  throw new Error(`post-merge-backend-ci-timeout: sha=${mergeSha}`);
}

async function dispatchCorrelatedProductionDeploy(
  workspace,
  repoFull,
  mergeSha,
  runId,
) {
  const cwd = workspace || process.env.HOME;
  if (!repoFull) throw new Error('production-deploy-repo-missing');
  if (!PRODUCTION_DEPLOY_WORKFLOW) throw new Error('production-deploy-workflow-missing');

  const headArgs = ['api', `repos/${repoFull}/commits/main`, '--jq', '.sha'];
  const { stdout: headOut } = await execFileAsync('gh', headArgs, {
    cwd,
    maxBuffer: 1024 * 1024,
    timeout: 30_000,
  });
  const mainHead = String(headOut || '').trim().toLowerCase();
  if (mainHead !== String(mergeSha || '').trim().toLowerCase()) {
    throw new Error(`production-deploy-main-head-mismatch: expected=${mergeSha} actual=${mainHead}`);
  }

  const backendRun = await waitForSuccessfulBackendCI(workspace, repoFull, mergeSha);
  const baseline = new Set(
    (await listWorkflowRuns(
      workspace,
      repoFull,
      PRODUCTION_DEPLOY_WORKFLOW,
      mergeSha,
    )).map((row) => String(row?.databaseId || '')),
  );
  const dispatchArgs = [
    'workflow', 'run', PRODUCTION_DEPLOY_WORKFLOW,
    '--ref', 'main',
    '-f', `git_sha=${mergeSha}`,
    '-f', 'require_platform_key=true',
    '-f', `self_maintenance_run_id=${runId}`,
  ];
  if (repoFull) dispatchArgs.push('--repo', repoFull);
  await execFileAsync('gh', dispatchArgs, {
    cwd,
    maxBuffer: 10 * 1024 * 1024,
    timeout: 60_000,
  });

  const captureDeadline = Date.now() + 90_000;
  while (Date.now() < captureDeadline) {
    const runs = await listWorkflowRuns(
      workspace,
      repoFull,
      PRODUCTION_DEPLOY_WORKFLOW,
      mergeSha,
    );
    const run = selectMatchingWorkflowRun(
      runs.filter((row) => !baseline.has(String(row?.databaseId || ''))),
      mergeSha,
    );
    if (run) {
      return {
        status: 'dispatched',
        run_id: runId,
        merge_sha: mergeSha,
        backend_ci_run_id: String(backendRun?.databaseId || ''),
        workflow_run_id: String(run.databaseId || ''),
        workflow_url: String(run.url || ''),
        at: new Date().toISOString(),
      };
    }
    await new Promise((resolve) => setTimeout(resolve, 3_000));
  }
  throw new Error(`production-deploy-run-capture-timeout: sha=${mergeSha}`);
}

async function reconcileMergedDeployments(token, state) {
  for (const [taskId, record] of Object.entries(state)) {
    if (record?.status !== 'ai_reviewed_merged') continue;
    if (['dispatched', 'not_applicable', 'stale'].includes(record?.deployment?.status)) continue;
    try {
      const task = await fetchTask(token, taskId);
      const runId = extractSelfMaintenanceRunId(task);
      if (!runId) {
        record.deployment = {
          status: 'not_applicable',
          reason: 'self_maintenance_run_id_missing',
          at: new Date().toISOString(),
        };
        saveProcessed(state);
        continue;
      }
      const repoFull = parseGithubRepo(task.repo_url);
      const deployment = await dispatchCorrelatedProductionDeploy(
        '',
        repoFull,
        String(record.sha || ''),
        runId,
      );
      record.run_id = runId;
      record.deployment = deployment;
      saveProcessed(state);
      log(
        `task ${taskId} → production deploy dispatched `
        + `run=${deployment.workflow_run_id} sha=${String(record.sha || '').slice(0, 10)}`,
      );
    } catch (err) {
      const reason = String(err?.message || err);
      record.deployment = {
        status: reason.includes('main-head-mismatch') ? 'stale' : 'retrying',
        reason: reason.slice(0, 1000),
        at: new Date().toISOString(),
      };
      saveProcessed(state);
      log(`task ${taskId} deployment reconciliation: ${reason.slice(0, 300)}`);
    }
  }
}

async function verifyAutomationIdentity(workspace, repoFull) {
  const args = ['api', 'user', '--jq', '.login'];
  const { stdout } = await execFileAsync('gh', args, {
    cwd: workspace || process.env.HOME,
    maxBuffer: 1024 * 1024,
    timeout: 30_000,
  });
  const actor = String(stdout || '').trim();
  if (!actor) throw new Error('GitHub automation identity is empty');
  if (EXPECTED_GITHUB_ACTOR && actor !== EXPECTED_GITHUB_ACTOR) {
    throw new Error(`GitHub actor mismatch: expected=${EXPECTED_GITHUB_ACTOR} actual=${actor}`);
  }
  return actor;
}

async function changedFilesForPR(workspace, branch, baseBranch, prNumber, repoFull) {
  if (workspace) {
    const { stdout } = await execFileAsync('git', ['diff', '--name-only', `${baseBranch}...${branch}`], {
      cwd: workspace,
      maxBuffer: 10 * 1024 * 1024,
      timeout: 30_000,
    });
    return String(stdout || '').split('\n').map((item) => item.trim()).filter(Boolean);
  }
  if (!prNumber) throw new Error('cannot resolve changed files without workspace or PR');
  const args = ['pr', 'diff', prNumber, '--name-only'];
  if (repoFull) args.push('--repo', repoFull);
  const { stdout } = await execFileAsync('gh', args, {
    cwd: process.env.HOME,
    maxBuffer: 10 * 1024 * 1024,
    timeout: 30_000,
  });
  return String(stdout || '').split('\n').map((item) => item.trim()).filter(Boolean);
}

async function isGitHubOrigin(workspace, repoUrl) {
  if (!workspace) {
    // 无 workspace：只用 repo_url 判断
    return Boolean(parseGithubRepo(repoUrl));
  }
  try {
    const url = await git(workspace, ['remote', 'get-url', 'origin']);
    return /github\.com/.test(url);
  } catch {
    return Boolean(parseGithubRepo(repoUrl));
  }
}

async function ensureBranchOnOrigin(workspace, branch) {
  // 本地有该分支吗？没有则 fetch
  const local = await gitMaybe(workspace, ['rev-parse', '--verify', branch]);
  if (!local) {
    await gitMaybe(workspace, ['fetch', 'origin', `${branch}:${branch}`]);
  }
  // push 到 GitHub origin
  await git(workspace, ['push', 'origin', branch]);
}

async function ensureBaseBranchOnOrigin(workspace, baseBranch) {
  // 检查 base branch 是否在 origin 上
  const remoteRef = await gitMaybe(workspace, ['ls-remote', 'origin', baseBranch]);
  if (!remoteRef) {
    // base 不在 origin：本地有则 push，没有则报错
    const localBase = await gitMaybe(workspace, ['rev-parse', '--verify', baseBranch]);
    if (!localBase) {
      throw new Error(`base branch ${baseBranch} 本地和 origin 均不存在`);
    }
    await git(workspace, ['push', 'origin', baseBranch]);
    log(`  base branch ${baseBranch} 已 push 到 origin`);
  }
}

async function createPullRequest(workspace, branch, baseBranch, task, repoFull) {
  const title = String(task.title || branch).slice(0, 80);
  const body = [
    `## Para 自动派工产物`,
    ``,
    `**任务 ID**: ${task.id}`,
    `**工作分支**: \`${branch}\``,
    `**目标分支**: \`${baseBranch}\``,
    ``,
    `本 PR 由 merge-worker 自动创建，源任务由 Trae CLI 执行。`,
    ``,
    `**初始状态**：标 \`hold-merge\`，在独立 AI review 完成前禁止合并。`,
    `AI review APPROVE → 添加 \`risk:r0\`、移除 \`hold-merge\`，再触发 GitHub Actions bot 三重门禁合并。`,
    `合并身份固定为 \`github-actions[bot]\`，且仍受 required checks 和 branch protection 约束。`,
  ].join('\n');
  const args = [
    'pr', 'create',
    '--head', branch,
    '--base', baseBranch,
    '--title', title,
    '--body', body,
    // A PR must be visibly blocked before the independent merge review starts.
    // risk:r0 is added only after that review approves the exact diff.
    '--label', INITIAL_PR_LABELS.join(','),
  ];
  if (repoFull) args.push('--repo', repoFull);
  const cwd = workspace || process.env.HOME;
  const { stdout } = await execFileAsync('gh', args, {
    cwd,
    maxBuffer: 10 * 1024 * 1024,
    timeout: 60_000,
  });
  const out = (stdout || '').trim();
  const urlMatch = out.match(/https:\/\/github\.com\/[^\s]+/);
  // 提取 PR number
  const numMatch = out.match(/\/pull\/(\d+)/);
  return { url: urlMatch ? urlMatch[0] : out, number: numMatch ? numMatch[1] : '' };
}

export function githubIssueLabelsEndpoint(repoFull, prNumber) {
  return `repos/${repoFull}/issues/${prNumber}/labels`;
}

export function githubIssueLabelEndpoint(repoFull, prNumber, label) {
  return `${githubIssueLabelsEndpoint(repoFull, prNumber)}/${encodeURIComponent(label)}`;
}

export function requiredLabelsPresent(existingLabels, requiredLabels) {
  const existing = new Set(
    (Array.isArray(existingLabels) ? existingLabels : [])
      .map((label) => String(label?.name || label || '').trim().toLowerCase())
      .filter(Boolean),
  );
  return (Array.isArray(requiredLabels) ? requiredLabels : [])
    .every((label) => existing.has(String(label || '').trim().toLowerCase()));
}

async function prHasAllLabels(workspace, prNumber, repoFull, labels) {
  const args = repoFull
    ? [
      'api',
      `repos/${repoFull}/issues/${prNumber}`,
      '--jq', '[.labels[].name]',
    ]
    : [
      'pr', 'view', prNumber,
      '--json', 'labels',
      '--jq', '[.labels[].name]',
    ];
  try {
    const { stdout } = await execFileAsync('gh', args, {
      cwd: workspace || process.env.HOME,
      maxBuffer: 10 * 1024 * 1024,
      timeout: 30_000,
    });
    return requiredLabelsPresent(JSON.parse(stdout || '[]'), labels);
  } catch {
    return false;
  }
}

async function addPrLabels(workspace, prNumber, repoFull, labels) {
  // Best-effort 打标签。优先走 issues REST API，避免 `gh pr edit`
  // 查询已下线 Projects Classic 字段时连带失败，导致 veto 标签丢失。
  if (!prNumber) return false;
  const args = repoFull
    ? [
      'api',
      '--method', 'POST',
      githubIssueLabelsEndpoint(repoFull, prNumber),
      ...labels.flatMap((label) => ['-f', `labels[]=${label}`]),
    ]
    : ['pr', 'edit', prNumber, '--add-label', labels.join(',')];
  const cwd = workspace || process.env.HOME;
  try {
    await execFileAsync('gh', args, { cwd, maxBuffer: 10 * 1024 * 1024, timeout: 30_000 });
    return true;
  } catch (err) {
    if (await prHasAllLabels(workspace, prNumber, repoFull, labels)) {
      log(
        `  addPrLabels(${labels.join(',')}) 写回执失败但远端状态已满足 `
        + `PR #${prNumber}，按幂等成功继续`,
      );
      return true;
    }
    log(`  ⚠️ addPrLabels(${labels.join(',')}) 失败 PR #${prNumber}: ${String(err).slice(0, 200)}`);
    return false;
  }
}

async function removePrLabels(workspace, prNumber, repoFull, labels) {
  if (!prNumber) return false;
  const cwd = workspace || process.env.HOME;
  try {
    if (repoFull) {
      for (const label of labels) {
        await execFileAsync(
          'gh',
          ['api', '--method', 'DELETE', githubIssueLabelEndpoint(repoFull, prNumber, label)],
          { cwd, maxBuffer: 10 * 1024 * 1024, timeout: 30_000 },
        );
      }
    } else {
      await execFileAsync(
        'gh',
        ['pr', 'edit', prNumber, '--remove-label', labels.join(',')],
        { cwd, maxBuffer: 10 * 1024 * 1024, timeout: 30_000 },
      );
    }
    return true;
  } catch (err) {
    log(`  ⚠️ removePrLabels(${labels.join(',')}) 失败 PR #${prNumber}: ${String(err).slice(0, 200)}`);
    return false;
  }
}

async function updatePullRequestBranch(workspace, prNumber, repoFull) {
  if (!prNumber) throw new Error('cannot update PR branch without PR number');
  const args = ['pr', 'update-branch', prNumber];
  if (repoFull) args.push('--repo', repoFull);
  try {
    await execFileAsync('gh', args, {
      cwd: workspace || process.env.HOME,
      maxBuffer: 10 * 1024 * 1024,
      timeout: 90_000,
    });
  } catch (err) {
    const message = String(err?.message || err);
    if (/already up.to.date|not behind|no update needed/i.test(message)) return;
    throw new Error(`update-branch failed: ${message.slice(0, 500)}`);
  }
}

export function botMergeCheckArgs(prNumber, repoFull = '') {
  const args = [
    'pr', 'checks', String(prNumber),
    '--watch',
    '--fail-fast',
    '--interval', '10',
  ];
  if (repoFull) args.push('--repo', repoFull);
  return args;
}

async function waitForRequiredChecks(workspace, prNumber, repoFull) {
  if (!prNumber) throw new Error('cannot wait for required checks without PR number');
  // The bot workflow checks the complete rollup, not only branch-protection
  // required checks. Dispatching earlier makes the bot skip the PR and leaves
  // this worker polling for 30 minutes with no merge attempt in flight.
  const args = botMergeCheckArgs(prNumber, repoFull);
  try {
    await execFileAsync('gh', args, {
      cwd: workspace || process.env.HOME,
      maxBuffer: 10 * 1024 * 1024,
      timeout: CI_WAIT_TIMEOUT_MS,
    });
  } catch (err) {
    const message = String(err?.message || err);
    const timedOut = isProcessTimeoutError(err);
    if (timedOut) {
      if (CI_TIMEOUT_POLICY === 'human') {
        throw new Error(
          `ci-wait-timeout-needs-human: bot merge checks not green within ${CI_WAIT_TIMEOUT_MS}ms; `
          + `escalate to human (policy=human). detail=${message.slice(0, 600)}`,
        );
      }
      if (CI_TIMEOUT_POLICY === 'retry') {
        throw new Error(
          `ci-wait-timeout-retry: bot merge checks not green within ${CI_WAIT_TIMEOUT_MS}ms; `
          + `retry with backoff (policy=retry). detail=${message.slice(0, 600)}`,
        );
      }
      throw new Error(
        `ci-wait-timeout-fail: bot merge checks not green within ${CI_WAIT_TIMEOUT_MS}ms; `
        + `merge aborted (policy=fail). detail=${message.slice(0, 600)}`,
      );
    }
    throw new Error(`bot merge checks failed or unavailable: ${message.slice(0, 1000)}`);
  }
}

export function parseReviewVerdict(output) {
  const text = String(output || '').trim();
  if (!text) return null;
  try {
    const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/i)?.[1] || text;
    const candidate = fenced.match(/\{[\s\S]*\}/)?.[0];
    if (candidate) {
      const parsed = JSON.parse(candidate);
      const verdict = String(parsed?.verdict || '').trim().toLowerCase();
      const reason = String(parsed?.reason || parsed?.finding || '').trim();
      if (verdict === 'approve') return { verdict: 'approve', raw: text };
      if (verdict === 'reject') {
        return { verdict: 'reject', reason: `REJECT: ${reason || 'blocking finding'}`, raw: text };
      }
    }
  } catch {
    // Fall through to the strict one-line protocol.
  }
  const lines = text.split('\n');
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i].trim();
    if (/^(?:VERDICT\s*:\s*)?APPROVE$/i.test(line)) return { verdict: 'approve', raw: text };
    const reject = line.match(/^(?:VERDICT\s*:\s*)?REJECT\s*:\s*(.+)$/i);
    if (reject) return { verdict: 'reject', reason: `REJECT: ${reject[1].trim()}`, raw: text };
  }
  return null;
}

export async function resolveReviewWithFallback({ primary, fallback }) {
  let primaryRaw = '';
  let primaryError = '';
  try {
    primaryRaw = String(await primary() || '');
    const verdict = parseReviewVerdict(primaryRaw);
    if (verdict) return { ...verdict, provider: 'trae' };
  } catch (err) {
    primaryError = String(err?.message || err).slice(0, 300);
  }

  let fallbackRaw = '';
  let fallbackError = '';
  try {
    fallbackRaw = String(await fallback() || '');
    const verdict = parseReviewVerdict(fallbackRaw);
    if (verdict) return { ...verdict, provider: 'minimax' };
  } catch (err) {
    fallbackError = String(err?.message || err).slice(0, 300);
  }

  return {
    verdict: 'reject',
    reason: 'indeterminate-review',
    raw: fallbackRaw || primaryRaw,
    diagnostics: {
      primary: primaryError || (primaryRaw ? 'unparseable' : 'empty'),
      fallback: fallbackError || (fallbackRaw ? 'unparseable' : 'empty'),
    },
  };
}

export function chunkReviewDiff(diff, maxChars = AI_REVIEW_CHUNK_MAX_CHARS) {
  const text = String(diff || '');
  const limit = Math.max(1, Number(maxChars) || AI_REVIEW_CHUNK_MAX_CHARS);
  if (!text) return [];
  if (text.length <= limit) return [text];

  const chunks = [];
  let current = '';
  for (const line of text.match(/[^\n]*\n|[^\n]+$/g) || []) {
    let remainder = line;
    while (remainder.length > 0) {
      const room = limit - current.length;
      if (room === 0) {
        chunks.push(current);
        current = '';
        continue;
      }
      if (remainder.length <= room) {
        current += remainder;
        remainder = '';
        continue;
      }
      current += remainder.slice(0, room);
      remainder = remainder.slice(room);
      chunks.push(current);
      current = '';
    }
  }
  if (current) chunks.push(current);
  return chunks;
}

export async function reviewDiffInChunks(
  diff,
  reviewChunk,
  {
    maxChars = AI_REVIEW_CHUNK_MAX_CHARS,
    maxChunks = AI_REVIEW_MAX_CHUNKS,
  } = {},
) {
  const chunks = chunkReviewDiff(diff, maxChars);
  if (chunks.length === 0) {
    return { verdict: 'reject', reason: 'empty-diff', raw: '' };
  }
  if (chunks.length > maxChunks) {
    return {
      verdict: 'reject',
      reason: `diff-too-large:${String(diff).length}:chunks=${chunks.length}:limit=${maxChunks}`,
      raw: '',
    };
  }

  const approvals = [];
  const indeterminate = [];
  for (let index = 0; index < chunks.length; index += 1) {
    const result = await reviewChunk(chunks[index], {
      index,
      number: index + 1,
      total: chunks.length,
    });
    if (result?.verdict === 'approve') {
      approvals.push(result);
      continue;
    }
    if (result?.reason === 'indeterminate-review') {
      indeterminate.push({ chunk: index + 1, diagnostics: result.diagnostics || {} });
      continue;
    }
    return {
      ...result,
      verdict: 'reject',
      reason: `chunk ${index + 1}/${chunks.length}: ${result?.reason || 'indeterminate-review'}`,
    };
  }
  if (indeterminate.length > 0) {
    return {
      verdict: 'reject',
      reason: 'indeterminate-review',
      raw: '',
      diagnostics: { chunks: indeterminate },
    };
  }
  const providers = [...new Set(approvals.map((item) => item.provider).filter(Boolean))];
  return {
    verdict: 'approve',
    provider: providers.join('+') || 'unknown',
    reviewed_chunks: chunks.length,
    raw: '',
  };
}

function normalizeMiniMaxAnthropicBaseUrl() {
  let base = String(
    process.env.MINIMAX_ANTHROPIC_BASE_URL
      || process.env.MINIMAX_BASE_URL
      || 'https://api.minimaxi.com',
  ).trim().replace(/\/$/, '');
  base = base.replace(/\/(?:v1|v2|v3|v4)$/i, '');
  if (!base.endsWith('/anthropic')) base = `${base}/anthropic`;
  return base;
}

async function resolveMiniMaxApiKey() {
  const fromEnv = String(
    process.env.MINIMAX_TOKEN_PLAN_API_KEY
      || process.env.MINIMAX_CODING_PLAN_API_KEY
      || process.env.MINIMAX_API_KEY
      || '',
  ).trim();
  if (fromEnv) return fromEnv.replace(/^minimax(?=sk-cp-)/i, '');
  if (!MINIMAX_KEYCHAIN_SERVICE) return '';
  try {
    const { stdout } = await execFileAsync('security', [
      'find-generic-password', '-a', process.env.USER || '', '-s', MINIMAX_KEYCHAIN_SERVICE, '-w',
    ], {
      maxBuffer: 1024 * 1024,
      timeout: 10_000,
    });
    return String(stdout || '').trim().replace(/^minimax(?=sk-cp-)/i, '');
  } catch {
    return '';
  }
}

export async function runMiniMaxReview(prompt) {
  const apiKey = await resolveMiniMaxApiKey();
  if (!apiKey) throw new Error('minimax-key-unavailable');
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), MINIMAX_REVIEW_TIMEOUT_MS);
  try {
    const response = await fetch(`${normalizeMiniMaxAnthropicBaseUrl()}/v1/messages`, {
      method: 'POST',
      headers: {
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
        'x-api-key': apiKey,
      },
      body: JSON.stringify({
        model: MINIMAX_REVIEW_MODEL,
        max_tokens: 1024,
        system: 'You are an independent merge safety reviewer. Follow the verdict protocol exactly.',
        messages: [{ role: 'user', content: prompt }],
      }),
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`minimax-http-${response.status}`);
    const payload = await response.json();
    return (Array.isArray(payload?.content) ? payload.content : [])
      .filter((item) => item && item.type === 'text')
      .map((item) => String(item.text || ''))
      .join('\n')
      .trim();
  } finally {
    clearTimeout(timer);
  }
}

async function aiReviewPR(workspace, branch, baseBranch, prNumber, repoFull) {
  // merge-worker 自己拿 diff，把 diff 内容直接放进 prompt 让 trae-cli 只读审查。
  // 之前让 trae-cli 在 plan mode 跑 `gh pr diff` 经常被权限拒绝，
  // 改成 merge-worker 拿 diff 后让 trae-cli 不执行任何命令，只看 diff 内容。
  let diff = '';
  let diffSource = '';
  if (workspace) {
    diffSource = `git diff ${baseBranch}...${branch}`;
    try {
      const { stdout } = await execFileAsync('git', ['diff', `${baseBranch}...${branch}`], {
        cwd: workspace, maxBuffer: 10 * 1024 * 1024, timeout: 30_000,
      });
      diff = (stdout || '').trim();
    } catch (err) {
      log(`  获取 diff 失败 (${diffSource}): ${String(err).slice(0, 200)}，fail-closed REJECT`);
      return { verdict: 'reject', reason: 'diff-fetch-failed', raw: String(err) };
    }
  } else if (prNumber) {
    diffSource = `gh pr diff ${prNumber}${repoFull ? ` --repo ${repoFull}` : ''}`;
    const args = ['pr', 'diff', prNumber];
    if (repoFull) args.push('--repo', repoFull);
    try {
      const { stdout } = await execFileAsync('gh', args, {
        cwd: process.env.HOME, maxBuffer: 10 * 1024 * 1024, timeout: 30_000,
      });
      diff = (stdout || '').trim();
    } catch (err) {
      log(`  获取 diff 失败 (${diffSource}): ${String(err).slice(0, 200)}，fail-closed REJECT`);
      return { verdict: 'reject', reason: 'diff-fetch-failed', raw: String(err) };
    }
  } else {
    log(`  AI review 阻断：无 workspace 且无 PR number`);
    return { verdict: 'reject', reason: 'no-diff-available', raw: '' };
  }

  if (!diff) {
    log(`  diff 为空，fail-closed REJECT`);
    return { verdict: 'reject', reason: 'empty-diff', raw: '' };
  }

  const review = await reviewDiffInChunks(diff, async (diffChunk, chunk) => {
    const prompt = [
      `你是代码审查员。下面是 PR 的 git diff 第 ${chunk.number}/${chunk.total} 段。`,
      `这是按字符边界切出的连续原始片段；必须独立审查本段全部内容，不要执行任何命令：`,
      ``,
      '```diff',
      diffChunk,
      '```',
      ``,
      `必须覆盖三个维度：`,
      `1) security — 注入/密钥/反序列化/权限绕过`,
      `2) business_logic — 控制流/不变量/错误处理/API 契约/静默丢数据`,
      `3) performance — 慢查询、N+1、无界循环、热路径 sleep`,
      `任一维度有阻断问题则 REJECT。`,
      `如果本段可以合并，输出一行：APPROVE`,
      `如果本段有问题需要修改，输出一行：REJECT: <dimension>=<简要原因>`,
      `也可输出 JSON：{"verdict":"approve|reject","reason":"..."}，不要输出其他 JSON。`,
      `不要修改任何文件，只做审查。`,
    ].join('\n');
    log(
      `  AI review 开始 chunk=${chunk.number}/${chunk.total} `
      + `(trae-cli plan mode, diff=${diffSource}, ${diffChunk.length}/${diff.length} chars)...`,
    );
    return resolveReviewWithFallback({
      primary: async () => {
        const { stdout } = await execFileAsync('trae-cli', [
          '--print',
          '--output-format', 'text',
          '--permission-mode', 'plan',
          prompt,
        ], {
          cwd: workspace || process.env.HOME,
          maxBuffer: 10 * 1024 * 1024,
          timeout: AI_REVIEW_TIMEOUT_MS,
          env: { ...process.env, PATH: `${process.env.HOME}/.local/bin:${process.env.PATH}` },
        });
        return stdout;
      },
      fallback: async () => {
        log(`  Trae review 无明确结论，切换 MiniMax ${MINIMAX_REVIEW_MODEL} 复审...`);
        return runMiniMaxReview(prompt);
      },
    });
  });
  if (review.verdict === 'approve') {
    log(
      `  AI review APPROVE provider=${review.provider} `
      + `chunks=${review.reviewed_chunks || 1} total_chars=${diff.length}`,
    );
    return review;
  }
  if (review.reason === 'indeterminate-review') {
    log(`  AI review 未输出明确结论，fail-closed REJECT ${JSON.stringify(review.diagnostics)}`);
  }
  return review;
}

async function mergePR(workspace, prNumber, repoFull) {
  const cwd = workspace || process.env.HOME;
  const viewArgs = [
    'pr', 'view', prNumber,
    '--json', 'state,mergeCommit,labels,statusCheckRollup',
  ];
  if (repoFull) viewArgs.push('--repo', repoFull);
  if (REQUIRE_BOT_IDENTITY) {
    if (!BOT_MERGE_WORKFLOW) throw new Error('bot merge workflow is not configured');
    // Dispatch only after required checks are green.  The bot workflow scans
    // once per dispatch; dispatching while checks are pending would skip the
    // PR and leave the worker waiting for a later schedule tick.
    await waitForRequiredChecks(workspace, prNumber, repoFull);
    const { stdout: preflightOut } = await execFileAsync('gh', viewArgs, {
      cwd,
      maxBuffer: 10 * 1024 * 1024,
      timeout: 30_000,
    });
    const preflightBlocker = blockingMergePollReason(
      JSON.parse(preflightOut || '{}'),
      prNumber,
    );
    if (preflightBlocker) throw new Error(preflightBlocker);
    const dispatchArgs = [
      'workflow', 'run', BOT_MERGE_WORKFLOW,
      '--ref', 'main',
      '-f', 'dry_run=false',
      '-f', 'scan_regular_prs=true',
    ];
    if (repoFull) dispatchArgs.push('--repo', repoFull);
    await execFileAsync('gh', dispatchArgs, {
      cwd,
      maxBuffer: 10 * 1024 * 1024,
      timeout: 60_000,
    });
    log(`  dispatched ${BOT_MERGE_WORKFLOW}; merge will execute as github-actions[bot]`);
  } else {
    const mergeArgs = ['pr', 'merge', prNumber, '--merge', '--auto', '--delete-branch'];
    if (repoFull) mergeArgs.push('--repo', repoFull);
    try {
      await execFileAsync('gh', mergeArgs, {
        cwd,
        maxBuffer: 10 * 1024 * 1024,
        timeout: 60_000,
      });
    } catch (err) {
      const msg = String(err?.message || err);
      if (!/already merged|already enabled|automerge|auto-merge|mergeable|pull request merge enabled/i.test(msg)) {
        throw err;
      }
      log(`  gh pr merge --auto 提示（可接受）: ${msg.slice(0, 200)}`);
    }
  }
  // 轮询等待 PR merged（最多 30 分钟，每 30s 查一次）
  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 30_000));
    let pr = {};
    let prState = '';
    let mergeOid = '';
    try {
      const { stdout } = await execFileAsync('gh', viewArgs, {
        cwd,
        maxBuffer: 10 * 1024 * 1024,
        timeout: 30_000,
      });
      ({ pr, prState, mergeOid } = parseMergePollSnapshot(stdout));
    } catch (err) {
      log(`  轮询 PR #${prNumber} 状态失败: ${String(err).slice(0, 200)}`);
      continue;
    }
    if (prState === 'MERGED') {
      if (mergeOid) return mergeOid;
      // fallback：从 GitHub API 取 HEAD commit
      try {
        const headArgs = ['pr', 'view', prNumber, '--json', 'headRefOid'];
        if (repoFull) headArgs.push('--repo', repoFull);
        const { stdout: headOut } = await execFileAsync('gh', headArgs, {
          cwd, maxBuffer: 10 * 1024 * 1024, timeout: 30_000,
        });
        return JSON.parse(headOut || '{}').headRefOid || '';
      } catch {
        return '';
      }
    }
    if (prState === 'CLOSED') {
      throw new Error(`PR #${prNumber} closed without merge`);
    }
    const blocker = blockingMergePollReason(pr, prNumber);
    if (blocker) throw new Error(blocker);
  }
  throw new Error(`PR #${prNumber} 30 分钟内未 merge`);
}

async function checkExistingPR(workspace, branch, baseBranch, repoFull) {
  // 检查分支是否已有 PR（merged/open/closed），避免重复创建
  try {
    const args = [
      'pr', 'list',
      '--head', branch,
      '--base', baseBranch,
      '--state', 'all',
      '--json', 'number,state,mergeCommit,url',
      '--limit', '5',
    ];
    if (repoFull) args.push('--repo', repoFull);
    const cwd = workspace || process.env.HOME;
    const { stdout } = await execFileAsync('gh', args, {
      cwd,
      maxBuffer: 10 * 1024 * 1024,
      timeout: 30_000,
    });
    const prs = JSON.parse(stdout || '[]');
    return prs[0] || null;
  } catch {
    return null;
  }
}

function isExternalReviewRemediationTask(task) {
  return String(task?.description || '').includes('=== EXTERNAL MERGE REVIEW REMEDIATION ===');
}

function isSelfMaintenanceCanonicalMainTask(task) {
  return String(task?.description || '').includes(
    '=== SELF_MAINTENANCE_CANONICAL_MERGE_BASE:main ===',
  );
}

export function selectTaskMergeBase(task, parentBaseBranch = '') {
  const configuredBase = String(task?.branch || 'main').trim() || 'main';
  if (isSelfMaintenanceCanonicalMainTask(task)) return 'main';
  if (!isExternalReviewRemediationTask(task)) return configuredBase;
  const parentBase = String(parentBaseBranch || '').trim();
  if (!parentBase || parentBase === configuredBase) {
    throw new Error(`remediation-parent-base-unavailable:${configuredBase}`);
  }
  return parentBase;
}

async function findParentPullRequestBase(workspace, branch, repoFull) {
  const args = [
    'pr', 'list',
    '--head', branch,
    '--state', 'all',
    '--json', 'number,state,headRefName,baseRefName,createdAt',
    '--limit', '20',
  ];
  if (repoFull) args.push('--repo', repoFull);
  try {
    const { stdout } = await execFileAsync('gh', args, {
      cwd: workspace || process.env.HOME,
      maxBuffer: 10 * 1024 * 1024,
      timeout: 30_000,
    });
    const pullRequests = JSON.parse(stdout || '[]');
    const parent = pullRequests.find(
      (pr) => String(pr?.headRefName || '') === branch && String(pr?.baseRefName || '').trim(),
    );
    return String(parent?.baseRefName || '').trim();
  } catch {
    return '';
  }
}

async function fallbackDirectMerge(workspace, branches, baseBranch) {
  // 非 GitHub 仓库（如 file:// 本地测试）：走直接 merge
  const localBase = await gitMaybe(workspace, ['rev-parse', '--verify', baseBranch]);
  if (!localBase) {
    await gitMaybe(workspace, ['fetch', 'origin', `${baseBranch}:${baseBranch}`]);
  }
  await gitMaybe(workspace, ['checkout', baseBranch]);
  await gitMaybe(workspace, ['pull', '--ff-only', 'origin', baseBranch]);

  const mergeShas = [];
  for (const branch of branches) {
    const localRef = await gitMaybe(workspace, ['rev-parse', '--verify', branch]);
    if (!localRef) {
      await gitMaybe(workspace, ['fetch', 'origin', `${branch}:${branch}`]);
    }
    await git(workspace, ['merge', '--no-ff', '--no-edit', branch]);
    const sha = await git(workspace, ['rev-parse', 'HEAD']);
    mergeShas.push({ branch, sha });
    log(`  ✓ ${branch} → ${sha.slice(0, 10)} (直接 merge)`);
  }
  return mergeShas;
}

async function processTask(token, task, state) {
  if (state[task.id]?.status === 'merged' || state[task.id]?.status === 'ai_reviewed_merged' || state[task.id]?.status === 'conflict') {
    return;
  }
  const previousState = state[task.id];
  if (
    previousState?.status === 'retrying'
    && Date.parse(previousState.next_retry_at || '') > Date.now()
  ) {
    return;
  }
  const workspace = String(task.workspace_path || '').trim();
  const workspaceExists = workspace && existsSync(workspace);
  if (workspace && !workspaceExists) {
    log(`task ${task.id} 注意：workspace_path 已被回收 (${workspace})，改用 GitHub-only 模式`);
  }
  const repoUrl = String(task.repo_url || '').trim();
  const repoFull = parseGithubRepo(repoUrl);
  const subs = task.subTasks || [];
  const branches = subs
    .map((s) => String(s.branch_name || '').trim())
    .filter(Boolean);
  if (branches.length === 0) {
    log(`task ${task.id} 跳过：无 branch_name`);
    return;
  }
  let baseBranch = String(task.branch || 'main').trim() || 'main';
  const isGithub = await isGitHubOrigin(workspaceExists ? workspace : '', repoUrl);
  if (isGithub && (
    isExternalReviewRemediationTask(task) || isSelfMaintenanceCanonicalMainTask(task)
  )) {
    const parentBaseBranch = isExternalReviewRemediationTask(task)
      ? await findParentPullRequestBase(workspaceExists ? workspace : '', baseBranch, repoFull)
      : '';
    try {
      baseBranch = selectTaskMergeBase(task, parentBaseBranch);
      log(`task ${task.id} 分支提升：parent=${task.branch} → canonical base=${baseBranch}`);
    } catch (err) {
      const reason = String(err?.message || err);
      await reportMergeConflict(token, task, reason);
      state[task.id] = {
        status: 'conflict',
        at: new Date().toISOString(),
        reason,
        attempts: Number(state[task.id]?.attempts || 0),
      };
      saveProcessed(state);
      log(`task ${task.id} 阻断：${reason}`);
      return;
    }
  }
  if (!isGithub) {
    if (!workspaceExists) {
      log(`task ${task.id} 跳过：非 GitHub 仓库 且 workspace 已被回收，无法直接 merge`);
      return;
    }
    // 非 GitHub 但 workspace 还在 → 走 fallbackDirectMerge
  }
  log(`task ${task.id} 处理：${branches.length} 个分支 → base=${baseBranch} @ ${workspaceExists ? workspace : 'GitHub-only'}`);

  try {
    // 检查是否已有 merged PR（处理 task 之前已 merge 但 state 未记录的情况，
    // 比如手动 merge 后 task 又被重新放入 merge-queue）
    if (isGithub) {
      const actor = await verifyAutomationIdentity(workspaceExists ? workspace : '', repoFull);
      log(`  GitHub automation actor=${actor}`);
      for (const branch of branches) {
        const existingPR = await checkExistingPR(workspaceExists ? workspace : '', branch, baseBranch, repoFull);
        if (existingPR && String(existingPR.state || '').toUpperCase() === 'MERGED') {
          const sha = existingPR.mergeCommit?.oid || '';
          log(`task ${task.id} 跳过：分支 ${branch} 已有 merged PR #${existingPR.number} (sha=${sha.slice(0, 10)})`);
          const { ok } = await reportMerged(token, task, sha);
          if (ok) {
            state[task.id] = {
              status: 'ai_reviewed_merged',
              at: new Date().toISOString(),
              sha,
              prs: [{ branch, number: existingPR.number, url: existingPR.url, merged: true }],
            };
            saveProcessed(state);
            log(`task ${task.id} → ai_reviewed_merged (跳过重复处理)`);
          }
          return;
        }
      }
    }

    if (isGithub) {
      // GitHub 仓库：创建 PR → AI review → 自动 merge
      // workspace 存在时先确保 base branch 已 push（如本地新建的 demo base）
      if (workspaceExists) {
        await ensureBaseBranchOnOrigin(workspace, baseBranch);
      }
      const results = [];
      for (const branch of branches) {
        try {
          // 先检查是否已有 OPEN PR，避免重复创建
          const existingPR = await checkExistingPR(workspaceExists ? workspace : '', branch, baseBranch, repoFull);
          let prNumber = '';
          let prUrl = '';
          if (existingPR && String(existingPR.state || '').toUpperCase() === 'OPEN') {
            prNumber = String(existingPR.number || '');
            prUrl = String(existingPR.url || '');
            log(`  分支 ${branch} 已有 OPEN PR #${prNumber}，复用`);
          } else {
            // workspace 存在则先确保 branch 已 push；不存在则假设 e2e-agent 已经 push 过
            if (workspaceExists) {
              await ensureBranchOnOrigin(workspace, branch);
            }
            const created = await createPullRequest(workspaceExists ? workspace : '', branch, baseBranch, task, repoFull);
            prUrl = created.url;
            prNumber = created.number;
            log(`  ✓ ${branch} → PR #${prNumber}: ${prUrl}`);
          }

          // Existing PRs from older workers may already carry risk:r0.  Apply
          // the veto before updating or reviewing so no bot-merge race exists.
          const heldBeforeReview = await addPrLabels(
            workspaceExists ? workspace : '', prNumber, repoFull, INITIAL_PR_LABELS,
          );
          if (!heldBeforeReview) throw new Error('hold-merge-label-failed-before-review');

          // Bring the proposed branch onto the current base before reviewing.
          // A real conflict fails below and is never silently merged.
          await updatePullRequestBranch(workspaceExists ? workspace : '', prNumber, repoFull);

          const changedFiles = await changedFilesForPR(
            workspaceExists ? workspace : '',
            branch,
            baseBranch,
            prNumber,
            repoFull,
          );
          if (changedFiles.length === 0) {
            throw new Error('changed-files-empty');
          }
          const forbidden = forbiddenAutoMergePaths(changedFiles);
          if (forbidden.length > 0) {
            const reason = `forbidden-auto-merge-paths: ${forbidden.join(', ')}`;
            log(`  ✗ ${reason}`);
            await addPrLabels(workspaceExists ? workspace : '', prNumber, repoFull, ['hold-merge']);
            results.push({ branch, prUrl, prNumber, merged: false, reason, vetoed: true });
            continue;
          }

          // AI review
          const review = await aiReviewPR(workspaceExists ? workspace : '', branch, baseBranch, prNumber, repoFull);
          if (review.verdict === 'approve') {
            log(`  ✓ AI review: APPROVE → 启用 auto-merge for PR #${prNumber}`);
            const riskLabelAdded = await addPrLabels(
              workspaceExists ? workspace : '', prNumber, repoFull, AUTO_PR_LABELS,
            );
            if (!riskLabelAdded) throw new Error('risk-label-failed-after-review');
            const holdRemoved = await removePrLabels(
              workspaceExists ? workspace : '', prNumber, repoFull, INITIAL_PR_LABELS,
            );
            if (!holdRemoved) throw new Error('hold-merge-label-remove-failed-after-review');
            let mergeSha = '';
            try {
              mergeSha = await mergePR(
                workspaceExists ? workspace : '',
                prNumber,
                repoFull,
              );
            } catch (err) {
              await addPrLabels(
                workspaceExists ? workspace : '',
                prNumber,
                repoFull,
                INITIAL_PR_LABELS,
              );
              throw err;
            }
            results.push({ branch, prUrl, prNumber, merged: true, sha: mergeSha });
            log(`  ✓ merged (${mergeSha.slice(0, 10)})`);
          } else if (review.reason === 'indeterminate-review') {
            const diagnostics = JSON.stringify(review.diagnostics || {});
            const reason = `indeterminate-review: ${diagnostics}`;
            log(
              `  ⚠ AI review 无明确结论 → 保持 hold-merge 并进入有限重试：`
              + reason.slice(0, 300),
            );
            // Review provider timeout / missing key / unparsable output is an
            // operational failure, not a semantic REJECT. Keep the temporary
            // hold in place and let the bounded retry policy try both reviewers
            // again. Only an explicit REJECT is a terminal veto.
            results.push({
              branch,
              prUrl,
              prNumber,
              merged: false,
              reason,
              retryable: true,
              vetoed: false,
            });
          } else {
            log(`  ✗ AI review: ${review.reason} → PR #${prNumber} 打 hold-merge veto 保持 OPEN`);
            // Explicit AI review REJECT：打 hold-merge 标签强制 veto，
            // 防止 ai-self-heal-auto-merge SLA 12h 后 auto-merge。
            // 人工 review 后可手动移除 hold-merge 标签
            await addPrLabels(workspaceExists ? workspace : '', prNumber, repoFull, ['hold-merge']);
            results.push({ branch, prUrl, prNumber, merged: false, reason: review.reason, vetoed: true });
          }
        } catch (err) {
          results.push({ branch, error: String(err).slice(0, 500) });
          log(`  ✗ ${branch} 失败：${String(err).slice(0, 200)}`);
        }
      }

      const merged = results.filter((r) => r.merged);
      const failed = results.filter((r) => !r.merged);

      if (merged.length > 0) {
        // 至少一个 PR 被 AI approve 并 merge 了
        const finalSha = merged[merged.length - 1].sha;
        const { ok, status, body } = await reportMerged(token, task, finalSha);
        if (ok) {
          state[task.id] = {
            status: 'ai_reviewed_merged',
            at: new Date().toISOString(),
            sha: finalSha,
            run_id: extractSelfMaintenanceRunId(task),
            deployment: { status: 'pending', at: new Date().toISOString() },
            prs: results.map((r) => ({ branch: r.branch, number: r.prNumber, url: r.prUrl, merged: r.merged })),
          };
          saveProcessed(state);
          log(`task ${task.id} → ai_reviewed_merged (${merged.length}/${results.length} PR merged)`);
          await reconcileMergedDeployments(token, state);
        } else {
          log(`task ${task.id} merge 回传失败 ${status}: ${JSON.stringify(body).slice(0, 200)}`);
        }
      } else if (failed.length > 0) {
        // Review/policy vetoes are terminal. Operational failures retry with
        // bounded exponential backoff before being reported as a conflict.
        const reason = failed.map((r) => `${r.branch}: ${r.reason || r.error}`).join('\n');
        const retryable = mergeFailuresAreRetryable(failed);
        let terminalAttempts = Number(state[task.id]?.attempts || 0);
        if (retryable) {
          const retry = nextMergeRetryState(state[task.id], reason);
          if (!retry.exhausted) {
            state[task.id] = retry;
            saveProcessed(state);
            log(`task ${task.id} → retrying attempt=${retry.attempts} next=${retry.next_retry_at}`);
            return;
          }
          terminalAttempts = retry.attempts;
        }
        const conflictSource = failed.some((result) => result.vetoed)
          ? 'ai-review-veto'
          : 'merge-worker';
        await reportMergeConflict(token, task, reason, conflictSource);
        state[task.id] = {
          status: retryable ? 'conflict' : 'ai_rejected',
          at: new Date().toISOString(),
          reason,
          attempts: terminalAttempts,
        };
        saveProcessed(state);
        log(`task ${task.id} → ${state[task.id].status}`);
      }
    } else {
      // 非 GitHub（file:// 本地测试）：走直接 merge
      const mergeShas = await fallbackDirectMerge(workspace, branches, baseBranch);
      const finalSha = mergeShas[mergeShas.length - 1]?.sha || '';
      if (!finalSha) {
        log(`task ${task.id} 无 merge sha`);
        return;
      }
      const { ok, status, body } = await reportMerged(token, task, finalSha);
      if (ok) {
        state[task.id] = { status: 'merged', at: new Date().toISOString(), sha: finalSha };
        saveProcessed(state);
        log(`task ${task.id} → merged (${finalSha.slice(0, 10)})`);
      } else {
        log(`task ${task.id} merge 回传失败 ${status}: ${JSON.stringify(body).slice(0, 200)}`);
      }
    }
  } catch (err) {
    const reason = String(err);
    log(`task ${task.id} 异常：${reason.slice(0, 300)}`);
    let terminalAttempts = Number(state[task.id]?.attempts || 0);
    if (isTransientMergeFailure(reason)) {
      const retry = nextMergeRetryState(state[task.id], reason);
      if (!retry.exhausted) {
        state[task.id] = retry;
        saveProcessed(state);
        log(`task ${task.id} → retrying attempt=${retry.attempts} next=${retry.next_retry_at}`);
        return;
      }
      terminalAttempts = retry.attempts;
    }
    await reportMergeConflict(token, task, reason);
    state[task.id] = {
      status: 'conflict',
      at: new Date().toISOString(),
      reason: reason.slice(0, 2000),
      attempts: terminalAttempts,
    };
    saveProcessed(state);
  }
}

async function main() {
  log(`启动：API=${API_BASE} poll=${POLL_SEC}s state=${STATE_FILE}`);
  const state = loadProcessed();
  log(`已有 ${Object.keys(state).length} 条历史记录`);

  while (true) {
    try {
      if (await maybeSelfUpdate()) {
        log('自更新已原子落盘，退出并由 launchd 拉起新版本');
        process.exit(75);
      }
    } catch (err) {
      log(`自更新异常，继续运行当前已验证版本：${String(err).slice(0, 300)}`);
    }
    try {
      await maybeRecoverStaleBotMergeWorkflow();
    } catch (err) {
      log(`合并扫描 watchdog 异常：${String(err).slice(0, 300)}`);
    }
    try {
      const token = await guestToken();
      await reconcileMergedDeployments(token, state);
      const queue = await fetchMergeQueue(token);
      const queueById = new Map(queue.map((task) => [String(task?.id || ''), task]));
      const recoveryIds = Object.entries(state)
        .filter(([, record]) => isRecoverableIndeterminateReviewRecord(record))
        .map(([taskId]) => taskId);
      for (const taskId of recoveryIds) {
        if (queueById.has(taskId)) continue;
        try {
          const task = await fetchTask(token, taskId);
          if (taskHasRecoverableIndeterminateReviewConflict(task)) {
            queueById.set(taskId, task);
            log(`task ${taskId} 恢复：误终止 indeterminate-review → 有限重试`);
          }
        } catch (err) {
          log(`task ${taskId} 恢复查询失败：${String(err).slice(0, 200)}`);
        }
      }
      const effectiveQueue = [...queueById.values()];
      if (effectiveQueue.length > 0) {
        log(`队列 ${effectiveQueue.length} 个任务 (常规=${queue.length} 恢复=${effectiveQueue.length - queue.length})`);
      }
      const results = await runTaskQueueFairly(
        effectiveQueue,
        (task) => processTask(token, task, state),
      );
      for (const result of results) {
        if (result?.status === 'rejected') {
          log(`队列任务异常：${String(result.reason).slice(0, 300)}`);
        }
      }
    } catch (err) {
      log(`轮询异常：${String(err).slice(0, 300)}`);
    }
    await new Promise((r) => setTimeout(r, POLL_SEC * 1000));
  }
}

const executedDirectly = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (executedDirectly) {
  main().catch((err) => {
    console.error('[merge-worker] fatal', err);
    process.exit(1);
  });
}
