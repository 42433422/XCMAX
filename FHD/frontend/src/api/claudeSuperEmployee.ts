import { apiFetch } from '@/utils/apiBase';
import type {
  CodexSuperEmployeeApiOptions as ClaudeApiOptions,
  CodexSuperEmployeeDispatch as ClaudeDispatch,
  CodexSuperEmployeeMessage as ClaudeMessage,
} from '@/api/codexSuperEmployee';

// Claude 超级员工与 Codex 同构（同一套消息/派工形状），只是工具与端点不同。
export type ClaudeSuperEmployeeMessage = ClaudeMessage;
export type ClaudeSuperEmployeeDispatch = ClaudeDispatch;
export type ClaudeSuperEmployeeApiScope = 'admin' | 'mobile';
export type ClaudeSuperEmployeeApiOptions = ClaudeApiOptions;

const jsonHeaders: HeadersInit = { 'Content-Type': 'application/json' };

function claudeEndpoint(scope: ClaudeSuperEmployeeApiScope = 'admin'): string {
  return scope === 'mobile'
    ? '/api/mobile/v1/admin/claude-super-employee/messages'
    : '/api/admin/claude-super-employee/messages';
}

async function readJson<T = Record<string, unknown>>(res: Response): Promise<T> {
  const ct = res.headers.get('content-type') || '';
  if (!ct.toLowerCase().includes('application/json')) {
    throw new Error(res.status === 401 ? '未登录' : `请求失败（HTTP ${res.status}）`);
  }
  return (await res.json()) as T;
}

function errorMessage(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim() ? value : fallback;
}

function unwrapPayload<T extends Record<string, unknown>>(
  data: T & { data?: unknown; success?: boolean; message?: unknown },
  fallback: string,
): T {
  if (data.success === false) {
    throw new Error(errorMessage(data.message, fallback));
  }
  if (data.data && typeof data.data === 'object' && !Array.isArray(data.data)) {
    const payload = data.data as T & { success?: boolean; message?: unknown };
    if (payload.success === false) {
      throw new Error(errorMessage(payload.message, fallback));
    }
    return payload;
  }
  return data;
}

export async function fetchClaudeSuperEmployeeMessages(
  options: ClaudeSuperEmployeeApiOptions = {},
): Promise<ClaudeSuperEmployeeMessage[]> {
  const res = await apiFetch(claudeEndpoint(options.scope), { headers: jsonHeaders });
  const data = await readJson<{
    success?: boolean;
    message?: string;
    messages?: ClaudeSuperEmployeeMessage[];
    data?: { messages?: ClaudeSuperEmployeeMessage[] };
  }>(res);
  const payload = unwrapPayload(data, '加载 Claude 对话失败');
  return payload.messages ?? [];
}

export async function sendClaudeSuperEmployeeMessage(
  message: string,
  context?: Record<string, unknown>,
  options: ClaudeSuperEmployeeApiOptions = {},
): Promise<{
  dispatch?: ClaudeSuperEmployeeDispatch;
  message?: ClaudeSuperEmployeeMessage;
  assistant_message?: ClaudeSuperEmployeeMessage;
  messages: ClaudeSuperEmployeeMessage[];
}> {
  const res = await apiFetch(claudeEndpoint(options.scope), {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ message, context: context ?? {} }),
  });
  const data = await readJson<{
    success?: boolean;
    message?: ClaudeSuperEmployeeMessage | string;
    assistant_message?: ClaudeSuperEmployeeMessage;
    dispatch?: ClaudeSuperEmployeeDispatch;
    messages?: ClaudeSuperEmployeeMessage[];
    data?: {
      message?: ClaudeSuperEmployeeMessage | string;
      assistant_message?: ClaudeSuperEmployeeMessage;
      dispatch?: ClaudeSuperEmployeeDispatch;
      messages?: ClaudeSuperEmployeeMessage[];
    };
  }>(res);
  const payload = unwrapPayload(data, 'Claude 调用失败');
  return {
    dispatch: payload.dispatch,
    message: payload.message && typeof payload.message === 'object' ? payload.message : undefined,
    assistant_message: payload.assistant_message,
    messages: payload.messages ?? [],
  };
}
