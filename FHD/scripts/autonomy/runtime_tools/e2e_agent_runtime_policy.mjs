import { rmSync } from 'node:fs';
import { dirname, normalize, resolve } from 'node:path';

const SUPPORTED_TOOLS = new Set(['trae', 'codex', 'cursor', 'claude_code']);

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

export const supportedToolNames = Object.freeze([...SUPPORTED_TOOLS]);
