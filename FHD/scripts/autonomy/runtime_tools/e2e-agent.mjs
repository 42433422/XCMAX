#!/usr/bin/env node
/**
 * 轻量 E2E 设备代理：WebSocket 连接 DevFleet，接收 execute_task，
 * 克隆工作区并等待 auto-touch / Trae 改码，完成后 commit + push。
 * 用于 npm run e2e:loop -- --auto-touch 在无桌面代理在线时保底闭环。
 */
import { execFile, spawn } from 'node:child_process';
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { promisify } from 'node:util';
import { createRequire } from 'node:module';
import {
  describeTraeFailure,
  isTraeProviderFailoverEligible,
  parseTraeStream,
} from './trae_failover.mjs';

const require = createRequire(import.meta.url);
const WebSocket = require('ws');

const execFileAsync = promisify(execFile);

const token = process.env.DEVFLEET_DEVICE_TOKEN || resolveDeviceToken();
const apiBase = (process.env.DEVFLEET_API_URL || 'http://localhost:3001').replace(/\/$/, '');
const workspaceRoot = process.env.DEVFLEET_WORKSPACE_ROOT || '/tmp/devfleet-e2e/agent-workspace';
const bareRepo = process.env.DEVFLEET_BARE_REPO || '/Users/a4243342/XCMAX-runtime/devfleet-bare.git';
const wsUrl = `${apiBase.replace(/^http/, 'ws')}/ws/device?token=${encodeURIComponent(token)}`;
const toolCommandTimeoutMs = (() => {
  const raw = process.env.DEVFLEET_AI_AGENT_TIMEOUT_MS?.trim();
  const parsed = raw ? Number.parseInt(raw, 10) : NaN;
  if (Number.isFinite(parsed) && parsed > 0) return parsed;
  return 900_000;
})();
const gitCommandTimeoutMs = (() => {
  const raw = process.env.DEVFLEET_GIT_TIMEOUT_MS?.trim();
  const parsed = raw ? Number.parseInt(raw, 10) : NaN;
  if (Number.isFinite(parsed) && parsed > 0) return parsed;
  return 900_000;
})();
applyNoProxyDefaults([apiBase, process.env.DEVFLEET_REPO_URL || '', bareRepo]);

function applyNoProxyDefaults(values = []) {
  const defaults = [
    'localhost',
    '127.0.0.1',
    '::1',
    '.local',
    '*.local',
    '10.0.0.0/8',
    '172.16.0.0/12',
    '192.168.0.0/16',
    '169.254.0.0/16',
    'fc00::/7',
    'fe80::/10',
  ];
  const entries = `${process.env.NO_PROXY || ''},${process.env.no_proxy || ''}`
    .split(',')
    .map((entry) => entry.trim())
    .filter(Boolean);
  for (const entry of defaults) appendUniqueNoProxy(entries, entry);
  for (const value of values) {
    const host = lanHostFromConnectionValue(value);
    if (host) appendUniqueNoProxy(entries, host);
  }
  const merged = entries.join(',');
  process.env.NO_PROXY = merged;
  process.env.no_proxy = merged;
}

function appendUniqueNoProxy(entries, entry) {
  if (!entries.some((existing) => existing.toLowerCase() === entry.toLowerCase())) {
    entries.push(entry);
  }
}

function lanHostFromConnectionValue(value) {
  const token = String(value || '').trim();
  if (!token) return null;
  if (token.startsWith('git@')) {
    const host = token.slice(4).split(':')[0];
    return isLanHost(host) ? host : null;
  }
  try {
    const host = new URL(token).hostname;
    return isLanHost(host) ? host : null;
  } catch {
    return null;
  }
}

function isLanHost(host) {
  const normalized = String(host || '').replace(/^\[/, '').replace(/\]$/, '').toLowerCase();
  if (!normalized || normalized === 'localhost' || normalized.endsWith('.local')) return true;
  const parts = normalized.split('.').map((part) => Number.parseInt(part, 10));
  if (parts.length === 4 && parts.every((part) => Number.isInteger(part) && part >= 0 && part <= 255)) {
    return parts[0] === 10
      || parts[0] === 127
      || (parts[0] === 169 && parts[1] === 254)
      || (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31)
      || (parts[0] === 192 && parts[1] === 168);
  }
  return normalized === '::1'
    || normalized.startsWith('fc')
    || normalized.startsWith('fd')
    || normalized.startsWith('fe80:');
}

function resolveAgentConfig() {
  const paths = [
    join(homedir(), 'Library/Application Support/com.devfleet.desktop/agent.json'),
    join(homedir(), 'Library/Application Support/com.devfleet.app/agent.json'),
  ];
  for (const path of paths) {
    if (!existsSync(path)) continue;
    try {
      return JSON.parse(readFileSync(path, 'utf8'));
    } catch {
      // ignore
    }
  }
  return null;
}

function resolveCursorAgentBin() {
  if (process.env.DEVFLEET_CURSOR_AGENT?.trim()) {
    return process.env.DEVFLEET_CURSOR_AGENT.trim();
  }
  const local = join(homedir(), '.local/bin/agent');
  if (existsSync(local)) return local;
  return 'agent';
}

function resolveCodexAgentBin() {
  const configured = process.env.DEVFLEET_CODEX_AGENT?.trim();
  if (configured) {
    const isPath = configured.includes('/') || configured.includes('\\');
    if (!isPath || existsSync(configured)) return configured;
  }
  const candidates = [
    join(homedir(), '.local/bin/codex'),
    join(homedir(), 'XCMAX-runtime/harmony/command-line-tools/tool/node/bin/codex'),
    '/Applications/Codex.app/Contents/Resources/codex',
  ];
  for (const candidate of candidates) {
    if (existsSync(candidate)) return candidate;
  }
  return 'codex';
}

function cursorAgentAvailable() {
  const bin = resolveCursorAgentBin();
  if (bin.includes('/') || bin.includes('\\')) return existsSync(bin);
  return true;
}

function resolveTraeAgentBin() {
  if (process.env.DEVFLEET_TRAE_AGENT?.trim()) {
    return process.env.DEVFLEET_TRAE_AGENT.trim();
  }
  const candidates = [
    join(homedir(), '.local/bin/trae-cli'),
    join(homedir(), '.local/share/trae-cli/trae-cli'),
    join(homedir(), '.local/bin/trae-agent'),
    join(homedir(), '.local/bin/ta'),
  ];
  for (const c of candidates) if (existsSync(c)) return c;
  return 'trae-cli';
}

function traeAgentAvailable() {
  const bin = resolveTraeAgentBin();
  if (bin.includes('/') || bin.includes('\\')) return existsSync(bin);
  return true;
}

function codexAgentAvailable() {
  const bin = resolveCodexAgentBin();
  if (bin.includes('/') || bin.includes('\\')) return existsSync(bin);
  return true;
}

async function runCursorAgent(taskDir, prompt) {
  const agentBin = resolveCursorAgentBin();
  const { stdout, stderr } = await execFileAsync(
    agentBin,
    ['-p', '--force', '--trust', '--output-format', 'text', prompt],
    {
      cwd: taskDir,
      maxBuffer: 10 * 1024 * 1024,
      timeout: toolCommandTimeoutMs,
      env: process.env,
    },
  );
  return (stdout || stderr || '').trim();
}

async function runTraeAgent(taskDir, prompt) {
  // Large self-maintenance prompts blow up argv. Persist full prompt to disk.
  const promptDir = join(taskDir, '.devfleet');
  mkdirSync(promptDir, { recursive: true });
  const promptPath = join(promptDir, 'AGENT_PROMPT.md');
  writeFileSync(promptPath, String(prompt || ''), 'utf8');
  const shortPrompt = [
    'Read and execute the full task instructions in .devfleet/AGENT_PROMPT.md exactly.',
    'Do not ask clarifying questions. Implement the required changes, run the mandated verifications, and stop when done.',
  ].join(' ');

  const traeBin = resolveTraeAgentBin();
  const permMode = process.env.DEVFLEET_TRAE_PERMISSION_MODE?.trim() || 'bypass_permissions';
  const args = [
    '--print',
    '--output-format',
    'stream-json',
    '--permission-mode',
    permMode,
  ];
  if (process.env.DEVFLEET_TRAE_YOLO !== '0') args.push('--yolo');
  args.push(shortPrompt);
  const { stdout, stderr } = await execFileAsync(
    traeBin,
    args,
    {
      cwd: taskDir,
      maxBuffer: 10 * 1024 * 1024,
      timeout: toolCommandTimeoutMs,
      env: process.env,
    },
  );
  const combined = (stdout || stderr || '').trim();
  const structured = parseTraeStream(stdout);
  if (structured.error) {
    const error = new Error(structured.error);
    error.stdout = stdout;
    error.stderr = stderr;
    throw error;
  }
  return structured.output || combined;
}

async function runCodexAgent(taskDir, prompt) {
  const codexBin = resolveCodexAgentBin();
  // Speed lever: report-only (review/QA) tasks may use a faster model and/or
  // lower reasoning effort, leaving the code step untouched. Env-driven; both
  // unset => identical to previous behavior (zero regression).
  const isReportOnly = String(prompt || '').toLowerCase().includes('modstore_report_only=1');
  const codexArgs = ['exec', '--sandbox', 'workspace-write', '--ephemeral'];
  if (isReportOnly) {
    const roModel = process.env.DEVFLEET_CODEX_REVIEW_MODEL?.trim();
    const roEffort = process.env.DEVFLEET_CODEX_REVIEW_EFFORT?.trim();
    if (roModel) codexArgs.push('-m', roModel);
    if (roEffort) codexArgs.push('-c', `model_reasoning_effort="${roEffort}"`);
  }
  codexArgs.push('-');
  return new Promise((resolve, reject) => {
    const child = spawn(
      codexBin,
      codexArgs,
      {
        cwd: taskDir,
        env: process.env,
        stdio: ['pipe', 'pipe', 'pipe'],
      },
    );
    let stdout = '';
    let stderr = '';
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGTERM');
      setTimeout(() => {
        if (!child.killed) child.kill('SIGKILL');
      }, 3000).unref();
    }, toolCommandTimeoutMs);

    child.stdout.on('data', (chunk) => {
      stdout = (stdout + chunk.toString()).slice(-10 * 1024 * 1024);
    });
    child.stderr.on('data', (chunk) => {
      stderr = (stderr + chunk.toString()).slice(-10 * 1024 * 1024);
    });
    child.on('error', (err) => {
      clearTimeout(timer);
      reject(err);
    });
    child.on('close', (code, signal) => {
      clearTimeout(timer);
      const output = (stdout || stderr || '').trim();
      if (timedOut) {
        reject(new Error(`Codex CLI timeout after ${toolCommandTimeoutMs}ms${output ? `: ${output.slice(-1000)}` : ''}`));
        return;
      }
      // Codex 经常以非零退出码结束（例如 sandbox 限制、patch 应用失败），
      // 但文件改动可能已经落盘。我们 resolve 并把退出码包含在输出里，
      // 由调用方在 catch 块检查 git status 决定是否 finalizeTask。
      if (code !== 0) {
        resolve(`[codex exit=${code}${signal ? ` signal=${signal}` : ''}]\n${output}`);
        return;
      }
      resolve(output);
    });
    child.stdin.end(prompt);
  });
}

function resolveClaudeAgentBin() {
  if (process.env.DEVFLEET_CLAUDE_AGENT?.trim()) {
    return process.env.DEVFLEET_CLAUDE_AGENT.trim();
  }
  const candidates = [
    join(homedir(), '.local/bin/claude'),
    join(homedir(), '.claude/local/claude'),
    '/opt/homebrew/bin/claude',
    '/usr/local/bin/claude',
  ];
  for (const c of candidates) if (existsSync(c)) return c;
  return 'claude';
}

function claudeAgentAvailable() {
  const bin = resolveClaudeAgentBin();
  if (bin.includes('/') || bin.includes('\\')) return existsSync(bin);
  return true;
}

// 用本地 Claude Code CLI 在工作区自动改码（headless，自动接受文件编辑）。
// 必须显式关 stdin：claude -p 默认 wait for stdin 3s 后 proceed without it，
// 但 execFile 留着 pipe 开着 claude 会一直挂起；用 spawn + stdin.end() 立刻解锁。
async function runClaudeAgent(taskDir, prompt) {
  const claudeBin = resolveClaudeAgentBin();
  const permMode = process.env.DEVFLEET_CLAUDE_PERMISSION_MODE?.trim() || 'acceptEdits';
  return new Promise((resolve, reject) => {
    const child = spawn(
      claudeBin,
      ['-p', prompt, '--output-format', 'text', '--permission-mode', permMode],
      { cwd: taskDir, env: process.env, stdio: ['pipe', 'pipe', 'pipe'] },
    );
    let stdout = '';
    let stderr = '';
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGTERM');
      setTimeout(() => { if (!child.killed) child.kill('SIGKILL'); }, 3000).unref();
    }, toolCommandTimeoutMs);
    child.stdout.on('data', (chunk) => {
      stdout = (stdout + chunk.toString()).slice(-10 * 1024 * 1024);
    });
    child.stderr.on('data', (chunk) => {
      stderr = (stderr + chunk.toString()).slice(-10 * 1024 * 1024);
    });
    child.on('error', (err) => { clearTimeout(timer); reject(err); });
    child.on('close', (code, signal) => {
      clearTimeout(timer);
      const output = (stdout || stderr || '').trim();
      if (timedOut) {
        reject(new Error(`Claude CLI timeout after ${toolCommandTimeoutMs}ms${output ? `: ${output.slice(-1000)}` : ''}`));
        return;
      }
      if (code !== 0) {
        reject(new Error(`Claude CLI exited with code ${code}${signal ? ` signal ${signal}` : ''}: ${(stdout || stderr || '').slice(-2000)}`));
        return;
      }
      resolve(output);
    });
    child.stdin.end();
  });
}

function resolveDeviceToken() {
  const paths = [
    join(homedir(), 'Library/Application Support/com.devfleet.desktop/agent.json'),
    join(homedir(), 'Library/Application Support/com.devfleet.app/agent.json'),
  ];
  for (const path of paths) {
    if (!existsSync(path)) continue;
    try {
      const parsed = JSON.parse(readFileSync(path, 'utf8'));
      if (parsed.deviceToken) return parsed.deviceToken;
    } catch {
      // ignore
    }
  }
  throw new Error('缺少 DEVFLEET_DEVICE_TOKEN，且未找到 agent.json');
}

const git = async (cwd, args, options = {}) => {
  const { stdout, stderr } = await execFileAsync('git', args, {
    cwd,
    maxBuffer: 10 * 1024 * 1024,
    timeout: options.timeout ?? gitCommandTimeoutMs,
    env: {
      ...process.env,
      GIT_TERMINAL_PROMPT: '0',
    },
  });
  return (stdout || stderr).trim();
};

async function gitMaybe(cwd, args) {
  try {
    return await git(cwd, args);
  } catch {
    return '';
  }
}

async function postTaskReport(task, { progress = 0, status = 'running', content, level = 'info' }) {
  const response = await fetch(`${apiBase}/api/devices/me/task-report`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      task_id: task.task_id,
      subtask_id: task.subtask_id,
      progress,
      status,
      content: String(content || '').slice(0, 4000) || 'E2E agent 状态更新',
      level,
    }),
  });
  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new Error(`task-report failed: ${response.status} ${text.slice(0, 500)}`);
  }
}

// 任务完成后，把 workspace_path 上报给 Para API，让 merge-worker 能找到工作区入队 merge。
// 用 guest token 调 /api/tasks/:id/request-merge（device token 只能调 /me/* 路径）。
let cachedGuestToken = '';
let cachedGuestTokenAt = 0;
async function getGuestToken() {
  if (cachedGuestToken && Date.now() - cachedGuestTokenAt < 5 * 60 * 1000) return cachedGuestToken;
  const resp = await fetch(`${apiBase}/api/auth/guest`, { method: 'POST' });
  if (!resp.ok) throw new Error(`guest auth failed: ${resp.status}`);
  const body = await resp.json();
  cachedGuestToken = body.token;
  cachedGuestTokenAt = Date.now();
  return cachedGuestToken;
}

async function requestMergeOnComplete(task, taskDir) {
  try {
    const guestToken = await getGuestToken();
    const resp = await fetch(`${apiBase}/api/tasks/${task.task_id}/request-merge`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${guestToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        workspace_path: taskDir,
        auto_merge: true,
      }),
    });
    if (!resp.ok) {
      const text = await resp.text().catch(() => '');
      console.error(`[e2e-agent] request-merge failed: ${resp.status} ${text.slice(0, 300)}`);
      return false;
    }
    console.log(`[e2e-agent] request-merge 成功: task=${task.task_id} workspace=${taskDir}`);
    return true;
  } catch (err) {
    console.error('[e2e-agent] request-merge 异常', err);
    return false;
  }
}

const send = (ws, payload) => {
  if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload));
};

const safeDir = (value) => value.replace(/[^a-zA-Z0-9._-]+/g, '-');

function safeTaskDirName(task) {
  const taskId = String(task?.task_id || Date.now());
  const subtaskId = String(task?.subtask_id || task?.work_branch || 'subtask');
  return safeDir(`${taskId}-${subtaskId}`);
}

async function sourceWorkspaceFromTask(task) {
  const raw = String(task?.workspace_root || task?.source_workspace || '').trim();
  const candidates = [];
  if (raw) candidates.push(raw);
  const envSources = String(process.env.DEVFLEET_SOURCE_WORKSPACE || '')
    .split(':')
    .map((entry) => entry.trim())
    .filter(Boolean);
  candidates.push(...envSources);
  candidates.push('/Users/a4243342/Desktop/XCMAX');

  const description = String(task?.description || '');
  const match = description.match(/管理端来源工作区：([^\r\n]+)/);
  if (match?.[1]) candidates.push(match[1].trim());

  for (const candidate of candidates) {
    if (!candidate || !existsSync(candidate)) continue;
    const root = await gitMaybe(candidate, ['rev-parse', '--show-toplevel']);
    if (root && existsSync(root)) return root;
  }
  return '';
}

function normalizeRepoKey(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  let token = raw.replace(/^git@([^:]+):/, 'https://$1/');
  try {
    const parsed = new URL(token);
    token = `${parsed.hostname}${parsed.pathname}`;
  } catch {
    token = token.replace(/^https?:\/\//, '').replace(/^ssh:\/\//, '');
  }
  return token
    .replace(/\.git$/i, '')
    .replace(/\/+$/g, '')
    .toLowerCase();
}

async function sourceWorkspaceMatchesRepo(sourceWorkspace, repoUrl) {
  if (!sourceWorkspace) return false;
  if (!repoUrl) return true;
  const wanted = normalizeRepoKey(repoUrl);
  if (!wanted) return true;
  const remotes = await gitMaybe(sourceWorkspace, ['remote', '-v']);
  if (remotes.split(/\r?\n/).some((line) => normalizeRepoKey(line.split(/\s+/)[1] || '').includes(wanted))) {
    return true;
  }
  return wanted.includes('github.com/42433422/xcmax')
    && sourceWorkspace.replace(/\\/g, '/').endsWith('/XCMAX');
}

async function refreshBaseBranchFromOrigin(taskDir, repoUrl, baseBranch) {
  const remoteRef = `refs/remotes/origin/${baseBranch}`;
  await git(taskDir, ['remote', 'set-url', 'origin', repoUrl]);
  await git(taskDir, ['remote', 'set-url', '--push', 'origin', repoUrl]);
  await git(taskDir, [
    'fetch',
    '--no-tags',
    'origin',
    `+refs/heads/${baseBranch}:${remoteRef}`,
  ]);
  const remoteHead = await git(taskDir, [
    'rev-parse',
    '--verify',
    `${remoteRef}^{commit}`,
  ]);
  await git(taskDir, ['checkout', '-B', baseBranch, remoteHead]);
  const localHead = await git(taskDir, ['rev-parse', '--verify', 'HEAD']);
  if (localHead !== remoteHead) {
    throw new Error(
      `base refresh mismatch branch=${baseBranch} local=${localHead} remote=${remoteHead}`,
    );
  }
  console.log(`[e2e-agent] 基线已刷新 ${baseBranch}@${remoteHead.slice(0, 12)}`);
  return remoteHead;
}

async function cloneSourceWorkspace(sourceWorkspace, taskDir, task) {
  // 先尝试从本地 sourceWorkspace clone（快，避免 GitHub 网络延迟）。
  // 如果 sourceWorkspace 太大或 clone 失败，fallback 到 GitHub repoUrl（带代理）。
  try {
    await git(process.cwd(), ['clone', '--shared', sourceWorkspace, taskDir]);
  } catch (cloneErr) {
    console.error(`[e2e-agent] clone sourceWorkspace 失败 (${String(cloneErr).slice(0, 200)})，尝试从 GitHub clone`);
    const repoUrl = String(task?.repo_url || '').trim();
    const baseBranch = String(task?.base_branch || 'main').trim() || 'main';
    if (!repoUrl) throw cloneErr;
    // 从 GitHub clone，用 --depth 1 避免 clone 全部历史
    await git(process.cwd(), ['clone', '--depth', '1', '--single-branch', '--branch', baseBranch, repoUrl, taskDir]);
    // clone 成功后 origin 已经指向 GitHub，不需要再 set-url
    if (task.work_branch) {
      await gitMaybe(taskDir, ['checkout', '-B', task.work_branch]);
    }
    return;
  }
  const repoUrl = String(task?.repo_url || '').trim();
  const baseBranch = String(task?.base_branch || 'main').trim() || 'main';
  if (repoUrl) {
    // sourceWorkspace 是本地路径，clone 后 origin 指向它。
    // 必须 fail-closed 地刷新并核对远程基线。不能用 fetch 输出或 loose-ref
    // 文件是否存在判断成功：成功 fetch 可以没有 stdout，remote ref 也可能
    // 只存在于 packed-refs；旧逻辑会因此悄悄从陈旧本地 main 创建工作分支。
    await refreshBaseBranchFromOrigin(taskDir, repoUrl, baseBranch);
  } else if (task.base_branch) {
    if (!(await gitMaybe(taskDir, ['checkout', task.base_branch]))) {
      await gitMaybe(taskDir, ['checkout', '-B', task.base_branch, `origin/${task.base_branch}`]);
    }
  }
  await git(taskDir, ['checkout', '-B', task.work_branch]);
}

function excludeAgentMetadata(taskDir) {
  const excludePath = join(taskDir, '.git', 'info', 'exclude');
  if (!existsSync(excludePath)) return;
  const current = readFileSync(excludePath, 'utf8');
  const existing = new Set(current.split(/\r?\n/).map((line) => line.trim()));
  const missing = ['.devfleet/', '.trae/'].filter((entry) => !existing.has(entry));
  if (!missing.length) return;
  writeFileSync(
    excludePath,
    `${current}${current.endsWith('\n') || !current ? '' : '\n'}${missing.join('\n')}\n`,
  );
}

function isReportOnlyTask(task) {
  const text = `${task?.title || ''}\n${task?.description || ''}`.toLowerCase();
  const explicit = [...text.matchAll(/(?:modstore_)?report_only\s*[:=]\s*(0|1|true|false)/g)];
  if (explicit.length) {
    const value = explicit.at(-1)[1];
    return value === '1' || value === 'true';
  }
  return text.includes('modstore_report_only=1')
    || text.includes('report_only=true')
    || text.includes('[report-only]')
    || text.includes('report-only mode')
    || text.includes('只读')
    || text.includes('不要修改')
    || text.includes('不修改任何文件');
}

function reportOnlyTargetBranch(task) {
  if (!isReportOnlyTask(task)) return '';
  const texts = [
    String(task?.description || ''),
    String(task?.title || ''),
  ];
  for (const text of texts) {
    const match = text.match(/target branch (?:to inspect|to verify)\s*:\s*`([^`\r\n]+)`/i)
      || text.match(/\bTARGET_BRANCH=([^\s\r\n]+)/i);
    const branch = (match?.[1] || '').trim();
    if (!branch || branch.startsWith('-') || branch.includes('..') || /[\s~^:?*[\\]/.test(branch)) {
      continue;
    }
    return branch;
  }
  return '';
}

async function prepareReportOnlyTargetBranch(taskDir, task) {
  const targetBranch = reportOnlyTargetBranch(task);
  if (!targetBranch) return null;
  const baseBranch = (task?.base_branch || 'main').trim() || 'main';
  const baseRef = `refs/remotes/origin/${baseBranch}`;
  const targetRef = `refs/remotes/origin/${targetBranch}`;
  await git(taskDir, [
    'fetch',
    '--no-tags',
    'origin',
    `+refs/heads/${baseBranch}:${baseRef}`,
  ]);
  let targetSource = 'origin';
  if (targetBranch !== baseBranch) {
    try {
      await git(taskDir, [
        'fetch',
        '--no-tags',
        'origin',
        `+refs/heads/${targetBranch}:${targetRef}`,
      ]);
    } catch (originError) {
      if (!existsSync(bareRepo)) throw originError;
      await git(taskDir, [
        'fetch',
        '--no-tags',
        bareRepo,
        `+refs/heads/${targetBranch}:${targetRef}`,
      ]);
      targetSource = 'bareRepo';
    }
  }
  await git(taskDir, ['cat-file', '-e', `${baseRef}^{commit}`]);
  await git(taskDir, ['cat-file', '-e', `${targetRef}^{commit}`]);
  const baseSha = await git(taskDir, ['rev-parse', '--verify', `${baseRef}^{commit}`]);
  const targetSha = await git(taskDir, ['rev-parse', '--verify', `${targetRef}^{commit}`]);
  const evidence = {
    verified_at: new Date().toISOString(),
    base_branch: baseBranch,
    base_ref: baseRef,
    base_sha: baseSha,
    target_branch: targetBranch,
    target_ref: targetRef,
    target_sha: targetSha,
    target_source: targetSource,
  };
  console.log(
    `[e2e-agent] report-only refs verified base=${baseSha.slice(0, 12)} target=${targetSha.slice(0, 12)} source=${targetSource}`,
  );
  return evidence;
}

function reportOnlyRefEvidencePrompt(evidence) {
  if (!evidence) return '';
  return [
    '',
    'E2E_REPORT_ONLY_REF_EVIDENCE_JSON:',
    JSON.stringify(evidence),
    'The e2e-agent fetched and verified both refs with git cat-file immediately before invoking you.',
    'Use the exact base_ref and target_ref above. If a lookup disagrees, retry the exact refs once before reporting target_branch_unavailable.',
  ].join('\n');
}

function buildReportOnlyContent(task, output) {
  const body = String(output || '').trim();
  return [
    '[e2e-agent] report-only task completed',
    `task_id=${task.task_id}`,
    `subtask_id=${task.subtask_id}`,
    '',
    body || '执行器已正常返回，但没有产生额外文本输出。',
  ].join('\n').slice(0, 4000);
}

const defaultCapabilities = () => ({
  node_version: process.version,
  docker: false,
  gpu: false,
  e2e_agent: true,
});

async function prepareWorkspace(task) {
  const repoUrl = (task.repo_url || '').trim();
  const taskDir = join(workspaceRoot, safeTaskDirName(task));
  mkdirSync(workspaceRoot, { recursive: true });
  await execFileAsync('rm', ['-rf', taskDir]);
  const sourceWorkspace = await sourceWorkspaceFromTask(task);

  if (sourceWorkspace && await sourceWorkspaceMatchesRepo(sourceWorkspace, repoUrl)) {
    await cloneSourceWorkspace(sourceWorkspace, taskDir, task);
    return taskDir;
  }

  if (!repoUrl) {
    mkdirSync(taskDir, { recursive: true });
    if (!existsSync(join(taskDir, '.git'))) await git(taskDir, ['init', '-b', task.base_branch || 'main']);
    try {
      await git(taskDir, ['checkout', task.work_branch]);
    } catch {
      await git(taskDir, ['checkout', '-b', task.work_branch]);
    }
    return taskDir;
  }

  await git(process.cwd(), ['clone', '--branch', task.base_branch || 'main', '--single-branch', repoUrl, taskDir]);
  await git(taskDir, ['checkout', '-b', task.work_branch]);
  return taskDir;
}

const WORKSPACE_RETENTION_MS = (() => {
  const raw = process.env.DEVFLEET_WORKSPACE_RETENTION_MS?.trim();
  const parsed = raw ? Number.parseInt(raw, 10) : NaN;
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 2 * 60 * 60 * 1000;
})();

// 任务终态后回收 per-task 克隆：分支已 push 到 origin/bareRepo，本地克隆可弃。
// 仅删 workspaceRoot 下的任务子目录，绝不删共享根（无 repoUrl 时 taskDir === workspaceRoot）。
function cleanupWorkspace(taskDir) {
  try {
    if (!taskDir || taskDir === workspaceRoot) return;
    if (!taskDir.startsWith(`${workspaceRoot}/`)) return;
    if (!existsSync(taskDir)) return;
    rmSync(taskDir, { recursive: true, force: true });
    console.log(`[e2e-agent] 已回收工作区 ${taskDir}`);
  } catch (err) {
    console.error('[e2e-agent] 工作区回收失败', err);
  }
}

// 启动时清理崩溃遗留的陈旧任务工作区，防止 workspace 无限膨胀。
function gcStaleWorkspaces() {
  try {
    if (!existsSync(workspaceRoot)) return;
    const now = Date.now();
    for (const name of readdirSync(workspaceRoot)) {
      if (!/^[0-9a-f]{8}-[0-9a-f]{4}-/i.test(name)) continue; // 仅任务 UUID 目录
      const dir = join(workspaceRoot, name);
      try {
        const st = statSync(dir);
        if (st.isDirectory() && now - st.mtimeMs > WORKSPACE_RETENTION_MS) {
          rmSync(dir, { recursive: true, force: true });
          console.log(`[e2e-agent] GC 清理陈旧工作区 ${dir}`);
        }
      } catch {}
    }
  } catch (err) {
    console.error('[e2e-agent] 工作区 GC 失败', err);
  }
}

// 工具(如 trae)可能按 prompt 指示自行 commit —— 此时工作区干净，
// 仅靠 git status 永远检测不到。HEAD 相对任务基线移动也算有效变更。
async function headMovedFromBase(taskDir, baseHead) {
  const head = (await gitMaybe(taskDir, ['rev-parse', '--verify', 'HEAD'])).trim();
  if (!head) return false;
  return head !== baseHead;
}

async function waitForMeaningfulChanges(taskDir, timeoutMs = 900_000, baseHead = '') {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const dirty = await git(taskDir, [
      'status', '--porcelain', '--', '.',
    ]);
    if (dirty) return true;
    if (baseHead !== undefined && await headMovedFromBase(taskDir, baseHead)) return true;
    await new Promise((resolve) => setTimeout(resolve, 3000));
  }
  return false;
}

async function pushBranch(taskDir, branch) {
  try {
    await git(taskDir, ['push', '-u', 'origin', branch]);
    return true;
  } catch (e) {
    // origin push may fail for file:// or missing HTTP git daemon / auth
    console.log(`[e2e-agent] push to origin failed (will try bareRepo): ${String(e).slice(0, 200)}`);
  }
  try {
    if (!existsSync(bareRepo)) {
      mkdirSync(bareRepo, { recursive: true });
      await execFileAsync('git', ['init', '--bare', bareRepo]);
    }
    await git(taskDir, ['push', '-u', bareRepo, `HEAD:${branch}`]);
    console.log(`[e2e-agent] pushed branch ${branch} to bareRepo ${bareRepo}`);
    return true;
  } catch (e) {
    // 无可用远端（origin 与 bareRepo 都不可推）：本地已 commit，
    // 结果通过 task_log 回传，不让整个任务因推送失败而崩。
    console.error(`[e2e-agent] push to bareRepo ${bareRepo} also failed: ${String(e).slice(0, 300)}`);
    return false;
  }
}

// trae-cli 写完代码后自动格式化 .py 文件，避免 Black formatter CI 失败。
// 扫描 git diff 找出修改过的 .py 文件，对它们跑 black/ruff format。
// 如果 black/ruff 不可用，跳过（不阻塞任务）。
async function autoFormatPythonFiles(taskDir, ws, task) {
  try {
    // 找出本次工作区修改/新增的 .py 文件
    const status = await gitMaybe(taskDir, ['status', '--porcelain']);
    if (!status) return;
    const pyFiles = status
      .split(/\r?\n/)
      .map((line) => line.slice(3).trim().split(/\s+/)[0])
      .filter((file) => file && file.endsWith('.py'))
      .filter((file) => !file.startsWith('.git/'))
      .slice(0, 50);
    if (pyFiles.length === 0) return;

    // 优先用 ruff format（XCMAX 工作区规则：格式化唯一工具是 Ruff）
    // 回退到 black（如果 ruff 不可用）
    const formatters = [
      { cmd: 'ruff', args: ['format', ...pyFiles] },
      { cmd: 'python3', args: ['-m', 'ruff', 'format', ...pyFiles] },
      { cmd: 'black', args: pyFiles },
      { cmd: 'python3', args: ['-m', 'black', ...pyFiles] },
    ];
    let formatted = false;
    let lastError = '';
    for (const { cmd, args } of formatters) {
      try {
        await execFileAsync(cmd, args, {
          cwd: taskDir,
          maxBuffer: 5 * 1024 * 1024,
          timeout: 30_000,
        });
        formatted = true;
        send(ws, {
          type: 'task_log',
          task_id: task.task_id,
          subtask_id: task.subtask_id,
          content: `[e2e-agent] 自动格式化 ${pyFiles.length} 个 .py 文件 (via ${cmd})`,
          level: 'info',
        });
        break;
      } catch (err) {
        lastError = String(err?.message || err).slice(0, 200);
        // 试下一个 formatter
      }
    }
    if (!formatted) {
      // 不阻塞任务，只记日志
      send(ws, {
        type: 'task_log',
        task_id: task.task_id,
        subtask_id: task.subtask_id,
        content: `[e2e-agent] 自动格式化跳过：ruff/black 不可用或全部失败 (${lastError})`,
        level: 'warn',
      });
    }
  } catch (err) {
    // 格式化失败不阻塞任务，CI 失败时再人工修复
    console.error('[e2e-agent] autoFormatPythonFiles error', err);
  }
}

async function finalizeTask(ws, task, taskDir, baseHead = '') {
  const status = await gitMaybe(taskDir, ['status', '--porcelain']);
  if (!status || !status.trim()) {
    // 工作区干净但 HEAD 已移动：工具(如 trae)已自行 commit → 跳过空 commit，直接 push。
    if (await headMovedFromBase(taskDir, baseHead)) {
      const pushedCommitted = await pushBranch(taskDir, task.work_branch);
      send(ws, {
        type: 'task_progress',
        task_id: task.task_id,
        subtask_id: task.subtask_id,
        progress: 100,
        status: 'completed',
      });
      send(ws, {
        type: 'task_log',
        task_id: task.task_id,
        subtask_id: task.subtask_id,
        content: pushedCommitted
          ? '[e2e-agent] 工具已自行 commit，分支已 push'
          : '[e2e-agent] 工具已自行 commit（无可用远端，结果见日志/本地分支）',
        level: 'info',
      });
      // Only explicitly pre-authorized tasks may enqueue from the device agent.
      // Self-maintenance tasks are authorized later by review + QA + autonomy_guard.
      if (pushedCommitted && task.auto_merge === true) {
        await requestMergeOnComplete(task, taskDir);
      }
      return true;
    }
    send(ws, {
      type: 'task_log',
      task_id: task.task_id,
      subtask_id: task.subtask_id,
      content: '[e2e-agent] finalizeTask: git status 空，无文件改动可提交',
      level: 'info',
    });
    return false;
  }
  await git(taskDir, ['config', 'user.name', 'DevFleet E2E Agent']);
  await git(taskDir, ['config', 'user.email', 'e2e@devfleet.local']);
  await git(taskDir, ['add', '-A', '--', '.']);
  await git(taskDir, ['commit', '-m', `devfleet: ${task.title}`]);
  const pushed = await pushBranch(taskDir, task.work_branch);
  send(ws, {
    type: 'task_progress',
    task_id: task.task_id,
    subtask_id: task.subtask_id,
    progress: 100,
    status: 'completed',
  });
  send(ws, {
    type: 'task_log',
    task_id: task.task_id,
    subtask_id: task.subtask_id,
    content: pushed
      ? 'E2E agent 已完成 commit 与 push'
      : 'E2E agent 已完成 commit（无可用远端，结果见日志/本地分支）',
    level: 'info',
  });
  if (pushed && task.auto_merge === true) {
    await requestMergeOnComplete(task, taskDir);
  }
  return true;
}

async function failTask(ws, task, content) {
  const message = String(content || 'E2E agent 执行失败').slice(0, 4000);
  send(ws, {
    type: 'task_log',
    task_id: task.task_id,
    subtask_id: task.subtask_id,
    content: message,
    level: 'error',
  });
  send(ws, {
    type: 'task_progress',
    task_id: task.task_id,
    subtask_id: task.subtask_id,
    progress: 0,
    status: 'failed',
  });
  try {
    await postTaskReport(task, {
      progress: 0,
      status: 'failed',
      content: message,
      level: 'error',
    });
  } catch (err) {
    console.error('[e2e-agent] task-report failed', err);
  }
}

async function handleTask(ws, task) {
  let taskDir = null;
  try {
  send(ws, {
    type: 'task_progress',
    task_id: task.task_id,
    subtask_id: task.subtask_id,
    progress: 10,
    status: 'running',
  });
  taskDir = await prepareWorkspace(task);
  const reportOnly = isReportOnlyTask(task);
  const reportOnlyRefEvidence = reportOnly
    ? await prepareReportOnlyTargetBranch(taskDir, task)
    : null;
  mkdirSync(join(taskDir, '.devfleet'), { recursive: true });
  if (reportOnlyRefEvidence) {
    writeFileSync(
      join(taskDir, '.devfleet', 'REPORT_ONLY_REFS.json'),
      `${JSON.stringify(reportOnlyRefEvidence, null, 2)}\n`,
    );
  }
  const executionPrompt = `${task.description}${reportOnlyRefEvidencePrompt(reportOnlyRefEvidence)}`;
  writeFileSync(
    join(taskDir, '.devfleet', 'TASK.md'),
    `# DevFleet 任务\n\n## 标题\n${task.title}\n\n## 要求\n${executionPrompt}\n\n## 工作分支\n${task.work_branch}\n`,
  );
  excludeAgentMetadata(taskDir);
  // 任务基线 HEAD：工具自行 commit 时靠它识别变更（工作区会是干净的）。
  // 新仓库无提交时为空串，之后任何 HEAD 出现即视为变更。
  const baseHead = (await gitMaybe(taskDir, ['rev-parse', '--verify', 'HEAD'])).trim();
  send(ws, {
    type: 'task_log',
    task_id: task.task_id,
    subtask_id: task.subtask_id,
    content: `[e2e-agent] 工作区就绪: ${taskDir}`,
    level: 'info',
  });
  send(ws, {
    type: 'task_progress',
    task_id: task.task_id,
    subtask_id: task.subtask_id,
    progress: 40,
    status: 'running',
  });

  const agentConfig = resolveAgentConfig();
  const requestedTool = task.tool || agentConfig?.devTool;
  const hasExplicitTool = ['claude_code', 'cursor', 'codex', 'trae'].includes(requestedTool);
  // FORCE_* overrides explicit device/tool assignment so DEVFLEET_FORCE_CODEX=1
  // is not bypassed by device.dev_tool=trae.
  let devTool = requestedTool;
  if (process.env.DEVFLEET_FORCE_TRAE === '1') {
    devTool = 'trae';
  } else if (process.env.DEVFLEET_FORCE_CODEX === '1') {
    devTool = 'codex';
  } else if (process.env.DEVFLEET_FORCE_CLAUDE === '1') {
    devTool = 'claude_code';
  } else if (process.env.DEVFLEET_FORCE_CURSOR === '1') {
    devTool = 'cursor';
  }
  let toolError = '';
  let toolOutput = '';
  const useTrae =
    (devTool === 'trae' || (!hasExplicitTool && process.env.DEVFLEET_FORCE_TRAE === '1'))
    && traeAgentAvailable();
  const useClaude =
    !useTrae
    && (devTool === 'claude_code' || (!hasExplicitTool && process.env.DEVFLEET_FORCE_CLAUDE === '1'))
    && claudeAgentAvailable();
  const useCursor =
    !useTrae
    && !useClaude
    && (devTool === 'cursor' || (process.env.DEVFLEET_E2E_CURSOR !== '0' && !hasExplicitTool && process.env.DEVFLEET_FORCE_CURSOR === '1'))
    && cursorAgentAvailable();
  const useCodex =
    !useTrae
    && !useClaude
    && !useCursor
    && (devTool === 'codex' || (!hasExplicitTool && process.env.DEVFLEET_FORCE_CODEX === '1'))
    && codexAgentAvailable();
  if (requestedTool && requestedTool !== devTool) {
    send(ws, {
      type: 'task_log',
      task_id: task.task_id,
      subtask_id: task.subtask_id,
      content: `[e2e-agent] tool override: requested=${requestedTool} effective=${devTool}`,
      level: 'info',
    });
  }

  if (useTrae) {
    send(ws, {
      type: 'task_log',
      task_id: task.task_id,
      subtask_id: task.subtask_id,
      content: '[e2e-agent] 调用 Trae CLI 修改代码',
      level: 'info',
    });
    try {
      const output = await runTraeAgent(taskDir, executionPrompt);
      if (output) toolOutput = `${toolOutput}\n${output}`.trim();
      if (output) {
        send(ws, {
          type: 'task_log',
          task_id: task.task_id,
          subtask_id: task.subtask_id,
          content: output.slice(0, 4000),
          level: 'info',
        });
      }
      // trae-cli 写完代码后自动格式化 .py 文件，避免 Black formatter CI 失败
      await autoFormatPythonFiles(taskDir, ws, task);
    } catch (err) {
      const failure = describeTraeFailure(err);
      toolError = `Trae CLI 失败: ${failure.summary}`;
      send(ws, {
        type: 'task_log',
        task_id: task.task_id,
        subtask_id: task.subtask_id,
        content: `[e2e-agent] ${toolError}`,
        level: 'warn',
      });
      const failoverEnabled = process.env.DEVFLEET_TRAE_CODEX_FAILOVER !== '0';
      const forceCodex = process.env.DEVFLEET_FORCE_CODEX === '1';
      if (
        failoverEnabled
        && codexAgentAvailable()
        && (forceCodex || isTraeProviderFailoverEligible(failure))
      ) {
        send(ws, {
          type: 'task_log',
          task_id: task.task_id,
          subtask_id: task.subtask_id,
          content: `[e2e-agent] Trae failed; fail over to Codex CLI (${failure.summary.slice(0, 200)})`,
          level: 'warn',
        });
        try {
          const output = await runCodexAgent(taskDir, executionPrompt);
          const codexNonZero = String(output || '').startsWith('[codex exit=');
          if (output) toolOutput = `${toolOutput}\n${output}`.trim();
          if (output) {
            send(ws, {
              type: 'task_log',
              task_id: task.task_id,
              subtask_id: task.subtask_id,
              content: output.slice(0, 4000),
              level: codexNonZero ? 'warn' : 'info',
            });
          }
          toolError = codexNonZero
            ? `Codex failover returned non-zero: ${String(output || '').slice(0, 500)}`
            : '';
          await autoFormatPythonFiles(taskDir, ws, task);
        } catch (codexErr) {
          toolError = `Trae provider unavailable; Codex failover failed: ${codexErr instanceof Error ? codexErr.message : String(codexErr)}`;
          send(ws, {
            type: 'task_log',
            task_id: task.task_id,
            subtask_id: task.subtask_id,
            content: `[e2e-agent] ${toolError.slice(0, 1200)}`,
            level: 'warn',
          });
        }
      }
    }
  }

  if (useClaude) {
    send(ws, {
      type: 'task_log',
      task_id: task.task_id,
      subtask_id: task.subtask_id,
      content: '[e2e-agent] 调用 Claude CLI 修改代码',
      level: 'info',
    });
    try {
      const output = await runClaudeAgent(taskDir, executionPrompt);
      if (output) toolOutput = `${toolOutput}\n${output}`.trim();
      if (output) {
        send(ws, {
          type: 'task_log',
          task_id: task.task_id,
          subtask_id: task.subtask_id,
          content: output.slice(0, 4000),
          level: 'info',
        });
      }
    } catch (err) {
      toolError = `Claude CLI 失败: ${err instanceof Error ? err.message : String(err)}`;
      send(ws, {
        type: 'task_log',
        task_id: task.task_id,
        subtask_id: task.subtask_id,
        content: `[e2e-agent] ${toolError}`,
        level: 'warn',
      });
    }
  }

  if (useCursor) {
    send(ws, {
      type: 'task_log',
      task_id: task.task_id,
      subtask_id: task.subtask_id,
      content: `[e2e-agent] 调用 Cursor Agent CLI 修改代码`,
      level: 'info',
    });
    try {
      const output = await runCursorAgent(taskDir, executionPrompt);
      if (output) toolOutput = `${toolOutput}\n${output}`.trim();
      if (output) {
        send(ws, {
          type: 'task_log',
          task_id: task.task_id,
          subtask_id: task.subtask_id,
          content: output.slice(0, 4000),
          level: 'info',
        });
      }
    } catch (err) {
      toolError = `Cursor Agent 失败: ${err instanceof Error ? err.message : String(err)}`;
      send(ws, {
        type: 'task_log',
        task_id: task.task_id,
        subtask_id: task.subtask_id,
        content: `[e2e-agent] ${toolError}`,
        level: 'warn',
      });
    }
  }

  if (useCodex) {
    send(ws, {
      type: 'task_log',
      task_id: task.task_id,
      subtask_id: task.subtask_id,
      content: '[e2e-agent] 调用 Codex CLI 修改代码',
      level: 'info',
    });
    try {
      const output = await runCodexAgent(taskDir, executionPrompt);
      const codexNonZero = String(output || '').startsWith('[codex exit=');
      if (output) toolOutput = `${toolOutput}\n${output}`.trim();
      if (output) {
        send(ws, {
          type: 'task_log',
          task_id: task.task_id,
          subtask_id: task.subtask_id,
          content: output.slice(0, 4000),
          level: codexNonZero ? 'warn' : 'info',
        });
      }
      // codex 完成后（无论退出码 0 或非 0）直接进入 finalizeTask（commit + push）。
      // codex 的 --ephemeral sandbox 可能导致 git status 检测不到修改，但文件可能已落盘。
      // finalizeTask 内部会检查 git status，无改动时不会空 commit。
      if (!reportOnly) {
        send(ws, {
          type: 'task_progress',
          task_id: task.task_id,
          subtask_id: task.subtask_id,
          progress: 80,
          status: 'running',
        });
        const finalized = await finalizeTask(ws, task, taskDir);
        if (finalized) {
          return;
        }
        // finalizeTask 返回 false（无改动可提交）。
        if (codexNonZero) {
          toolError = `Codex CLI 非零退出且无文件改动: ${output.slice(0, 500)}`;
          send(ws, {
            type: 'task_log',
            task_id: task.task_id,
            subtask_id: task.subtask_id,
            content: `[e2e-agent] ${toolError}`,
            level: 'warn',
          });
        }
      } else if (codexNonZero) {
        // Report-only reviews often exit non-zero after writing the report.
        // Keep the message for logs, but do not hard-fail report-only below
        // when we already have usable output (otherwise merge→deploy never runs).
        toolError = reportOnly
          ? ''
          : `Codex CLI 非零退出: ${output.slice(0, 500)}`;
        if (reportOnly && output) {
          send(ws, {
            type: 'task_log',
            task_id: task.task_id,
            subtask_id: task.subtask_id,
            content: `[e2e-agent] Codex report-only exited non-zero; accepting output anyway`,
            level: 'warn',
          });
        }
      }
    } catch (err) {
      toolError = `Codex CLI 失败: ${err instanceof Error ? err.message : String(err)}`;
      send(ws, {
        type: 'task_log',
        task_id: task.task_id,
        subtask_id: task.subtask_id,
        content: `[e2e-agent] ${toolError}`,
        level: 'warn',
      });
    }
  }

  if (reportOnly) {
    if (toolError && !String(toolOutput || '').trim()) {
      await failTask(ws, task, `[e2e-agent] report-only 执行器失败: ${toolError}`);
      return;
    }
    toolError = '';
    const content = buildReportOnlyContent(task, toolOutput);
    send(ws, {
      type: 'task_log',
      task_id: task.task_id,
      subtask_id: task.subtask_id,
      content,
      level: 'info',
    });
    send(ws, {
      type: 'task_progress',
      task_id: task.task_id,
      subtask_id: task.subtask_id,
      progress: 100,
      status: 'completed',
    });
    try {
      await postTaskReport(task, {
        progress: 100,
        status: 'completed',
        content,
        level: 'info',
      });
    } catch (err) {
      await failTask(
        ws,
        task,
        `[e2e-agent] report-only 完成回写失败: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
    return;
  }

  const waitMs = useTrae || useClaude || useCursor || useCodex ? 120_000 : 900_000;
  if (!(await waitForMeaningfulChanges(taskDir, waitMs, baseHead))) {
    await failTask(
      ws,
      task,
      toolError
        ? `[e2e-agent] ${toolError}; ${waitMs}ms 内未检测到有效代码变更`
        : `[e2e-agent] ${waitMs}ms 内未检测到有效代码变更`,
    );
    return;
  }

  send(ws, {
    type: 'task_progress',
    task_id: task.task_id,
    subtask_id: task.subtask_id,
    progress: 80,
    status: 'running',
  });
  await finalizeTask(ws, task, taskDir, baseHead);
  } finally {
    // 无论成功/失败/未变更，任务结束即回收 per-task 克隆，避免 workspace 撑爆磁盘。
    cleanupWorkspace(taskDir);
  }
}

const supportedToolNames = ['trae', 'codex', 'cursor', 'claude_code'];
const taskQueuesByTool = new Map(supportedToolNames.map((tool) => [tool, []]));
const runningTools = new Set();
const knownSubtasks = new Set();

function taskToolName(task) {
  const raw = String(task?.tool || task?.tool_name || '').trim();
  return supportedToolNames.includes(raw) ? raw : 'codex';
}

function effectiveToolName(task) {
  if (process.env.DEVFLEET_FORCE_TRAE === '1') return 'trae';
  if (process.env.DEVFLEET_FORCE_CODEX === '1') return 'codex';
  if (process.env.DEVFLEET_FORCE_CLAUDE === '1') return 'claude_code';
  if (process.env.DEVFLEET_FORCE_CURSOR === '1') return 'cursor';
  return taskToolName(task);
}

function isSelfMaintenanceTask(task) {
  const text = `${task?.title || ''}\n${task?.description || ''}`.toLowerCase();
  return text.includes('self-maintenance') || text.includes('modstore self-maintenance');
}

function enqueueTask(ws, task) {
  const subtaskId = String(task?.subtask_id || '').trim();
  if (subtaskId && knownSubtasks.has(subtaskId)) return false;
  if (subtaskId) knownSubtasks.add(subtaskId);
  const tool = effectiveToolName(task);
  if (!task.tool && !task.tool_name) task.tool = tool;
  const item = { ws, task, tool };
  const queue = taskQueuesByTool.get(tool);
  // Prioritize self-maintenance over incident scout/fix floods.
  if (isSelfMaintenanceTask(task)) queue.unshift(item);
  else queue.push(item);
  publishToolStatus(ws);
  drainToolQueue(tool);
  return true;
}

async function recoverPendingTask(ws) {
  if (ws.readyState !== WebSocket.OPEN) return;
  try {
    const response = await fetch(`${apiBase}/api/devices/me/pending-task`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) throw new Error(`pending-task HTTP ${response.status}`);
    const body = await response.json();
    const pending = body?.task;
    if (!pending?.id || !pending?.subtask_id) return;
    const recovered = {
      base_branch: pending.base_branch,
      description: pending.description,
      repo_url: pending.repo_url,
      subtask_id: pending.subtask_id,
      task_id: pending.id,
      title: pending.title,
      tool: pending.tool,
      work_branch: pending.work_branch,
    };
    if (enqueueTask(ws, recovered)) {
      console.log(`[e2e-agent] recovered running subtask ${pending.subtask_id}`);
    }
  } catch (err) {
    console.error('[e2e-agent] pending task recovery failed', err);
  }
}

function drainToolQueue(tool) {
  if (runningTools.has(tool)) return;
  const queue = taskQueuesByTool.get(tool) || [];
  const next = queue.shift();
  if (!next) return;
  runningTools.add(tool);
  publishToolStatus(next.ws);
  handleTask(next.ws, next.task)
    .catch((err) => {
      console.error('[e2e-agent] task error', err);
      return failTask(
        next.ws,
        next.task,
        `[e2e-agent] 未捕获任务异常: ${err instanceof Error ? err.message : String(err)}`,
      );
    })
    .finally(() => {
      const subtaskId = String(next.task?.subtask_id || '').trim();
      if (subtaskId) knownSubtasks.delete(subtaskId);
      runningTools.delete(tool);
      publishToolStatus(next.ws);
      setImmediate(() => drainToolQueue(tool));
      setTimeout(() => recoverPendingTask(next.ws), 500);
    });
}

function toolExecutionStatus(tool, installed) {
  if (!installed) return 'not_installed';
  const queued = (taskQueuesByTool.get(tool) || []).length > 0;
  return runningTools.has(tool) || queued ? 'running' : 'idle';
}

function publishToolStatus(ws) {
  const traeInstalled = traeAgentAvailable();
  const codexInstalled = codexAgentAvailable();
  const cursorInstalled = cursorAgentAvailable();
  const claudeInstalled = claudeAgentAvailable();
  send(ws, {
    type: 'tool_status',
    tools: [
      { tool_name: 'trae', status: toolExecutionStatus('trae', traeInstalled) },
      { tool_name: 'codex', status: toolExecutionStatus('codex', codexInstalled) },
      { tool_name: 'cursor', status: toolExecutionStatus('cursor', cursorInstalled) },
      { tool_name: 'claude_code', status: toolExecutionStatus('claude_code', claudeInstalled) },
    ],
    capabilities: {
      ...defaultCapabilities(),
      e2e_agent: true,
      trae_cli: traeInstalled,
      cursor_agent_cli: cursorInstalled,
      codex_cli: codexInstalled,
      claude_cli: claudeInstalled,
    },
  });
}

function connect() {
  const ws = new WebSocket(wsUrl);
  ws.on('open', () => {
    console.log('[e2e-agent] online');
    publishToolStatus(ws);
    recoverPendingTask(ws);
  });
  ws.on('message', (raw) => {
    try {
      const msg = JSON.parse(String(raw));
      if (msg.type === 'execute_task') {
        enqueueTask(ws, msg);
      }
    } catch (err) {
      console.error('[e2e-agent] bad message', err);
    }
  });
  ws.on('close', () => {
    console.log('[e2e-agent] disconnected, retry in 3s');
    setTimeout(connect, 3000);
  });
  ws.on('error', (err) => console.error('[e2e-agent] ws error', err.message));
  const heartbeat = setInterval(() => {
    if (ws.readyState !== WebSocket.OPEN) {
      clearInterval(heartbeat);
      return;
    }
    publishToolStatus(ws);
  }, 30_000);
}

if (process.argv.includes('--spawn')) {
  const child = spawn(process.execPath, [new URL(import.meta.url).pathname], {
    detached: true,
    stdio: 'ignore',
    env: process.env,
  });
  child.unref();
  console.log(`[e2e-agent] spawned pid ${child.pid}`);
} else {
  gcStaleWorkspaces();
  connect();
}
