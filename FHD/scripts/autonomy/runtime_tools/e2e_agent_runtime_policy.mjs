import { rmSync } from 'node:fs';
import { dirname, normalize, resolve } from 'node:path';

import { isPolicyFailure, isTraeProviderFailoverEligible } from './trae_failover.mjs';

const SUPPORTED_TOOLS = new Set(['trae', 'codex', 'cursor', 'claude_code']);

// DEVFLEET_FORCE_* 是硬覆盖：设置后只跑被强制的工具、不回退。
// 想要"先试首选、失败自动换"请改用 DEVFLEET_TOOL_FALLBACK_ORDER（见下方），
// 它取代 Mac 上 10-11 起的 DEVFLEET_FORCE_CURSOR=1；两者同时设置时 FORCE 优先、回退链不生效。
export function forcedToolName(env = process.env) {
  if (env.DEVFLEET_FORCE_TRAE === '1') return 'trae';
  if (env.DEVFLEET_FORCE_CODEX === '1') return 'codex';
  if (env.DEVFLEET_FORCE_CLAUDE === '1') return 'claude_code';
  if (env.DEVFLEET_FORCE_CURSOR === '1') return 'cursor';
  return '';
}

export function requestedToolName(task = {}, agentConfig = null) {
  const raw = String(task?.tool || task?.tool_name || agentConfig?.devTool || '').trim();
  return SUPPORTED_TOOLS.has(raw) ? raw : '';
}

export function effectiveToolName({
  task = {},
  agentConfig = null,
  env = process.env,
  fallback = '',
} = {}) {
  const forced = forcedToolName(env);
  if (forced) return forced;
  const requested = requestedToolName(task, agentConfig);
  if (requested) return requested;
  return SUPPORTED_TOOLS.has(fallback) ? fallback : '';
}

export async function withFailureCleanup(taskDir, prepare, cleanup) {
  try {
    return await prepare();
  } catch (error) {
    cleanup(taskDir);
    throw error;
  }
}

// 只删本任务自己的工作区：taskDir 必须是规范化路径，且正好是 root 的直接子目录。
export function removeOwnWorkspace(taskDir, root) {
  if (!taskDir || normalize(taskDir) !== taskDir || dirname(resolve(taskDir)) !== resolve(root)) return false;
  rmSync(taskDir, { recursive: true, force: true });
  return true;
}

// 工具回退链（DEVFLEET_TOOL_FALLBACK_ORDER，如 codex,cursor,claude_code,trae）。
// 取代 DEVFLEET_FORCE_CURSOR 这类硬强制：先试任务请求的工具，失败再按顺序试下一个，
// 跳过未安装的、不重复。未配置时返回空数组，执行路径与旧版完全一致。
export function toolFallbackOrder(env = process.env) {
  const seen = new Set();
  for (const raw of String(env.DEVFLEET_TOOL_FALLBACK_ORDER || '').split(',')) {
    const name = raw.trim().toLowerCase().replace(/-/g, '_');
    if (SUPPORTED_TOOLS.has(name)) seen.add(name);
  }
  return [...seen];
}

// provider（默认）：只在额度/登录/鉴权/欠费/限流/超时/服务商错误时换工具；
// any：任何失败都换。普通代码或测试失败在 provider 模式下不换工具。
export function toolFallbackMode(env = process.env) {
  return String(env.DEVFLEET_TOOL_FALLBACK_ON || '').trim().toLowerCase() === 'any' ? 'any' : 'provider';
}

// 返回本任务要依次尝试的工具；null 表示未启用回退链（走旧路径）。
// 强制开关（DEVFLEET_FORCE_*）设置时仍是覆盖：只跑被强制的那一个，不回退。
export function toolAttemptPlan({
  task = {},
  agentConfig = null,
  env = process.env,
  isAvailable = () => true,
} = {}) {
  const order = toolFallbackOrder(env);
  if (!order.length || forcedToolName(env)) return null;
  const requested = requestedToolName(task, agentConfig);
  const candidates = requested ? [requested, ...order] : order;
  return [...new Set(candidates)].filter((tool) => isAvailable(tool));
}

const LOGIN_OR_BILLING_FAILURES = [
  '401',
  '402',
  'credit balance',
  'insufficient credits',
  'invalid api key',
  'invoice',
  'login required',
  'not authenticated',
  'not logged in',
  'payment required',
  'please log in',
  'please login',
  'subscription',
  'unauthorized',
  'unpaid',
];

export function isToolFallbackEligible(failureText, mode = 'provider') {
  if (mode === 'any') return true;
  const raw = String(failureText || '').toLowerCase();
  if (!raw || isPolicyFailure(raw)) return false;
  if (isTraeProviderFailoverEligible(raw)) return true;
  return LOGIN_OR_BILLING_FAILURES.some((pattern) => raw.includes(pattern));
}

// 换下一个工具前把工作区原地还原到任务基线（丢弃上一个工具的半成品改动和提交）。
// 不删目录、不重新 clone，避免 #29 那种 clone 到已存在目录的 "already exists" 失败。
// .devfleet/ 等写在 .git/info/exclude 里的元数据属于被忽略文件，clean -fd 不会删。
export async function resetWorkspaceForNextTool(git, taskDir, task, baseHead) {
  if (!baseHead || !task?.work_branch) throw new Error('no task base HEAD/work branch to reset to');
  await git(taskDir, ['checkout', '-f', '-B', task.work_branch, baseHead]);
  await git(taskDir, ['clean', '-fd']);
}

export const supportedToolNames = Object.freeze([...SUPPORTED_TOOLS]);
