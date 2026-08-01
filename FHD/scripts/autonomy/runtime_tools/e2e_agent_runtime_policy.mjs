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

export const supportedToolNames = Object.freeze([...SUPPORTED_TOOLS]);
