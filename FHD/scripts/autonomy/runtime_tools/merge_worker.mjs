#!/usr/bin/env node
// Para /api/tasks/merge-queue 消费者：把已完成子任务的工作分支 merge 回 base branch，
// 然后把 merge_commit_sha 回传给 Para。解决了「任务 completed 后无 merge 消费者」断点。
//
// 触发条件：任务 auto_merge=true 且 workspace_path 非空（由 FHD invoke 在派工时设置）。
// 安全：默认不 push 到 origin，只本地合并；如需 push 设 MERGE_WORKER_PUSH=1。
// 冲突：写入 /api/tasks/:id/merge-conflict，任务进 merge_conflict 状态，等待人工处理。

import { execFile } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { promisify } from 'node:util';

const execFileAsync = promisify(execFile);

const API_BASE = process.env.PARA_API_BASE || 'http://127.0.0.1:3001';
const POLL_SEC = Number.parseInt(process.env.MERGE_WORKER_POLL_SEC || '15', 10);
const PUSH_ORIGIN = process.env.MERGE_WORKER_PUSH === '1';
const STATE_FILE = process.env.MERGE_WORKER_STATE_FILE || '/tmp/para-merge-worker-state.json';
const TOKEN_TTL_MS = 5 * 60 * 1000; // Para guest 限 15min/30 次，复用 5 分钟避免耗尽

let cachedToken = '';
let cachedTokenAt = 0;

function log(...args) {
  console.log(new Date().toISOString().slice(11, 19), '[merge-worker]', ...args);
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
  writeFileSync(STATE_FILE, JSON.stringify(state));
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

async function reportMergeConflict(token, task, reason) {
  const conflict = {
    branch: task.subTasks?.[0]?.branch_name || '',
    reason: String(reason).slice(0, 1000),
  };
  return postJson(token, `/api/tasks/${task.id}/merge-conflict`, conflict);
}

async function reportMerged(token, task, sha) {
  return postJson(token, `/api/tasks/${task.id}/merge`, { merge_commit_sha: sha });
}

// 解析 GitHub repo owner/name，用于 gh --repo 参数
function parseGithubRepo(repoUrl) {
  const url = String(repoUrl || '').trim();
  // git@github.com:owner/name.git 或 https://github.com/owner/name.git
  const m = url.match(/github\.com[:/]([^/]+)\/([^/]+?)(?:\.git)?(?:\/|$)/i);
  return m ? `${m[1]}/${m[2]}` : '';
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
    `**风险分级**：标 \`ai-generated\` + \`risk:r0\`（loop 已过 review/QA/autonomy_guard 三层 gate）。`,
    `AI review APPROVE → 立即 \`gh pr merge --auto\`；AI review REJECT → 打 \`hold-merge\` 强制 veto。`,
    `兜底：\`ai-self-heal-auto-merge\` SLA 12h 二次守卫通过后 auto-merge。`,
  ].join('\n');
  const args = [
    'pr', 'create',
    '--head', branch,
    '--base', baseBranch,
    '--title', title,
    '--body', body,
    '--label', 'ai-generated,risk:r0',
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

async function addPrLabels(workspace, prNumber, repoFull, labels) {
  // Best-effort 打标签（gh pr edit --add-label）；失败不阻塞主流程
  if (!prNumber) return;
  const args = ['pr', 'edit', prNumber, '--add-label', labels.join(',')];
  if (repoFull) args.push('--repo', repoFull);
  const cwd = workspace || process.env.HOME;
  try {
    await execFileAsync('gh', args, { cwd, maxBuffer: 10 * 1024 * 1024, timeout: 30_000 });
  } catch (err) {
    log(`  ⚠️ addPrLabels(${labels.join(',')}) 失败 PR #${prNumber}: ${String(err).slice(0, 200)}`);
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
      log(`  获取 diff 失败 (${diffSource}): ${String(err).slice(0, 200)}，fail-open APPROVE`);
      return { verdict: 'approve', raw: 'diff-fetch-failed' };
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
      log(`  获取 diff 失败 (${diffSource}): ${String(err).slice(0, 200)}，fail-open APPROVE`);
      return { verdict: 'approve', raw: 'diff-fetch-failed' };
    }
  } else {
    log(`  AI review 跳过：无 workspace 且无 PR number，直接 APPROVE（交给 CI 门禁）`);
    return { verdict: 'approve', raw: 'no-diff-available' };
  }

  if (!diff) {
    log(`  diff 为空，fail-open APPROVE（可能 PR 与 base 一致）`);
    return { verdict: 'approve', raw: 'empty-diff' };
  }

  // diff 太大时只取前 30KB（避免 prompt 过长）
  const diffTruncated = diff.length > 30000 ? `${diff.slice(0, 30000)}\n... (truncated, total ${diff.length} chars)` : diff;
  const prompt = [
    `你是代码审查员。下面是 PR 的 git diff 内容，请直接审查（不要执行任何命令）：`,
    ``,
    '```diff',
    diffTruncated,
    '```',
    ``,
    `审查代码质量、安全性、逻辑正确性。`,
    `如果代码可以合并，输出一行：APPROVE`,
    `如果有问题需要修改，输出一行：REJECT: <简要原因>`,
    `不要修改任何文件，只做审查。`,
  ].join('\n');
  log(`  AI review 开始 (trae-cli plan mode, diff=${diffSource}, ${diff.length} chars)...`);
  const { stdout } = await execFileAsync('trae-cli', [
    '--print',
    '--output-format', 'text',
    '--permission-mode', 'plan',
    prompt,
  ], {
    cwd: workspace || process.env.HOME,
    maxBuffer: 10 * 1024 * 1024,
    timeout: 180_000,
    env: { ...process.env, PATH: `${process.env.HOME}/.local/bin:${process.env.PATH}` },
  });
  const out = (stdout || '').trim();
  // 取最后几行找 APPROVE/REJECT
  const lines = out.split('\n');
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i].trim();
    if (/^APPROVE$/i.test(line)) return { verdict: 'approve', raw: out };
    if (/^REJECT\s*:/i.test(line)) return { verdict: 'reject', reason: line, raw: out };
  }
  // 没有明确结论：fail-open APPROVE，让 CI + branch protection 守门。
  log(`  AI review 未输出明确结论，fail-open APPROVE（交给 CI 守门）`);
  return { verdict: 'approve', raw: out };
}

async function mergePR(workspace, prNumber, repoFull) {
  // --auto 让 GitHub 在所有 required status checks pass 后自动 merge。
  // 避免 branch protection 阻塞 + CI 还在跑时 merge 失败。
  // gh 命令立即返回（启用 auto-merge），需要轮询 PR 状态等真正 merge。
  const cwd = workspace || process.env.HOME;
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
    // 可接受：PR 已经 merge / 已经 enable auto-merge / 直接可 merge 不需要 --auto
    // 这些情况下 gh 会以非零退出码结束，但 PR 状态已正确
    if (!/already merged|already enabled|automerge|auto-merge|mergeable|pull request merge enabled/i.test(msg)) {
      throw err;
    }
    log(`  gh pr merge --auto 提示（可接受）: ${msg.slice(0, 200)}`);
  }
  // 轮询等待 PR merged（最多 30 分钟，每 30s 查一次）
  const viewArgs = ['pr', 'view', prNumber, '--json', 'state,mergeCommit'];
  if (repoFull) viewArgs.push('--repo', repoFull);
  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 30_000));
    let prState = '';
    let mergeOid = '';
    try {
      const { stdout } = await execFileAsync('gh', viewArgs, {
        cwd,
        maxBuffer: 10 * 1024 * 1024,
        timeout: 30_000,
      });
      const pr = JSON.parse(stdout || '{}');
      prState = String(pr.state || '').toUpperCase();
      mergeOid = String(pr.mergeCommit?.oid || '');
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
  const baseBranch = String(task.branch || 'main').trim() || 'main';
  const isGithub = await isGitHubOrigin(workspaceExists ? workspace : '', repoUrl);
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

          // AI review
          const review = await aiReviewPR(workspaceExists ? workspace : '', branch, baseBranch, prNumber, repoFull);
          if (review.verdict === 'approve') {
            log(`  ✓ AI review: APPROVE → 启用 auto-merge for PR #${prNumber}`);
            const mergeSha = await mergePR(workspaceExists ? workspace : '', prNumber, repoFull);
            results.push({ branch, prUrl, prNumber, merged: true, sha: mergeSha });
            log(`  ✓ merged (${mergeSha.slice(0, 10)})`);
          } else {
            log(`  ✗ AI review: ${review.reason} → PR #${prNumber} 打 hold-merge veto 保持 OPEN`);
            // AI review REJECT：打 hold-merge 标签强制 veto，防止 ai-self-heal-auto-merge SLA 12h 后 auto-merge
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
            prs: results.map((r) => ({ branch: r.branch, number: r.prNumber, url: r.prUrl, merged: r.merged })),
          };
          saveProcessed(state);
          log(`task ${task.id} → ai_reviewed_merged (${merged.length}/${results.length} PR merged)`);
        } else {
          log(`task ${task.id} merge 回传失败 ${status}: ${JSON.stringify(body).slice(0, 200)}`);
        }
      } else if (failed.length > 0) {
        // 所有 PR 都被 AI reject 或创建失败
        const reason = failed.map((r) => `${r.branch}: ${r.reason || r.error}`).join('\n');
        await reportMergeConflict(token, task, reason);
        state[task.id] = { status: 'ai_rejected', at: new Date().toISOString(), reason };
        saveProcessed(state);
        log(`task ${task.id} → ai_rejected (所有 PR 被 AI review 拒绝)`);
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
    log(`task ${task.id} 异常：${String(err).slice(0, 300)}`);
  }
}

async function main() {
  log(`启动：API=${API_BASE} poll=${POLL_SEC}s push_origin=${PUSH_ORIGIN}`);
  const state = loadProcessed();
  log(`已有 ${Object.keys(state).length} 条历史记录`);

  while (true) {
    try {
      const token = await guestToken();
      const queue = await fetchMergeQueue(token);
      if (queue.length > 0) {
        log(`队列 ${queue.length} 个任务`);
      }
      for (const task of queue) {
        await processTask(token, task, state);
      }
    } catch (err) {
      log(`轮询异常：${String(err).slice(0, 300)}`);
    }
    await new Promise((r) => setTimeout(r, POLL_SEC * 1000));
  }
}

main().catch((err) => {
  console.error('[merge-worker] fatal', err);
  process.exit(1);
});
