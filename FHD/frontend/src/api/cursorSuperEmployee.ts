import { apiFetch } from '@/utils/apiBase';
import type {
  CodexSuperEmployeeApiOptions as CursorApiOptions,
  CodexSuperEmployeeDispatch as CursorDispatch,
  CodexSuperEmployeeMessage as CursorMessage,
} from '@/api/codexSuperEmployee';

// Cursor 超级员工与 Codex 同构（同一套消息/派工形状），只是工具与端点不同。
export type CursorSuperEmployeeMessage = CursorMessage;
export type CursorSuperEmployeeDispatch = CursorDispatch;
export type CursorSuperEmployeeApiScope = 'admin' | 'mobile';
export type CursorSuperEmployeeApiOptions = CursorApiOptions;

const jsonHeaders: HeadersInit = { 'Content-Type': 'application/json' };

function cursorEndpoint(scope: CursorSuperEmployeeApiScope = 'admin'): string {
  return scope === 'mobile'
    ? '/api/mobile/v1/admin/cursor-super-employee/messages'
    : '/api/admin/cursor-super-employee/messages';
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

export async function fetchCursorSuperEmployeeMessages(
  options: CursorSuperEmployeeApiOptions = {},
): Promise<CursorSuperEmployeeMessage[]> {
  const res = await apiFetch(cursorEndpoint(options.scope), { headers: jsonHeaders });
  const data = await readJson<{
    success?: boolean;
    message?: string;
    messages?: CursorSuperEmployeeMessage[];
    data?: { messages?: CursorSuperEmployeeMessage[] };
  }>(res);
  const payload = unwrapPayload(data, '加载 Cursor 对话失败');
  return payload.messages ?? [];
}

export async function sendCursorSuperEmployeeMessage(
  message: string,
  context?: Record<string, unknown>,
  options: CursorSuperEmployeeApiOptions = {},
): Promise<{
  dispatch?: CursorSuperEmployeeDispatch;
  message?: CursorSuperEmployeeMessage;
  assistant_message?: CursorSuperEmployeeMessage;
  messages: CursorSuperEmployeeMessage[];
}> {
  const res = await apiFetch(cursorEndpoint(options.scope), {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ message, context: context ?? {} }),
  });
  const data = await readJson<{
    success?: boolean;
    message?: CursorSuperEmployeeMessage | string;
    assistant_message?: CursorSuperEmployeeMessage;
    dispatch?: CursorSuperEmployeeDispatch;
    messages?: CursorSuperEmployeeMessage[];
    data?: {
      message?: CursorSuperEmployeeMessage | string;
      assistant_message?: CursorSuperEmployeeMessage;
      dispatch?: CursorSuperEmployeeDispatch;
      messages?: CursorSuperEmployeeMessage[];
    };
  }>(res);
  const payload = unwrapPayload(data, 'Cursor 调用失败');
  return {
    dispatch: payload.dispatch,
    message: payload.message && typeof payload.message === 'object' ? payload.message : undefined,
    assistant_message: payload.assistant_message,
    messages: payload.messages ?? [],
  };
}
