import { apiFetch } from '@/utils/apiBase';
import type {
  CodexSuperEmployeeApiOptions as TraeApiOptions,
  CodexSuperEmployeeDispatch as TraeDispatch,
  CodexSuperEmployeeMessage as TraeMessage,
} from '@/api/codexSuperEmployee';

export type TraeSuperEmployeeMessage = TraeMessage;
export type TraeSuperEmployeeDispatch = TraeDispatch;
export type TraeSuperEmployeeApiScope = 'admin' | 'mobile';
export type TraeSuperEmployeeApiOptions = TraeApiOptions;

const jsonHeaders: HeadersInit = { 'Content-Type': 'application/json' };

function traeEndpoint(scope: TraeSuperEmployeeApiScope = 'admin'): string {
  return scope === 'mobile'
    ? '/api/mobile/v1/admin/trae-super-employee/messages'
    : '/api/admin/trae-super-employee/messages';
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

export async function fetchTraeSuperEmployeeMessages(
  options: TraeSuperEmployeeApiOptions = {},
): Promise<TraeSuperEmployeeMessage[]> {
  const res = await apiFetch(traeEndpoint(options.scope), { headers: jsonHeaders });
  const data = await readJson<{
    success?: boolean;
    message?: string;
    messages?: TraeSuperEmployeeMessage[];
    data?: { messages?: TraeSuperEmployeeMessage[] };
  }>(res);
  const payload = unwrapPayload(data, '加载 Trae 对话失败');
  return payload.messages ?? [];
}

export async function sendTraeSuperEmployeeMessage(
  message: string,
  context?: Record<string, unknown>,
  options: TraeSuperEmployeeApiOptions = {},
): Promise<{
  dispatch?: TraeSuperEmployeeDispatch;
  message?: TraeSuperEmployeeMessage;
  assistant_message?: TraeSuperEmployeeMessage;
  messages: TraeSuperEmployeeMessage[];
}> {
  const res = await apiFetch(traeEndpoint(options.scope), {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ message, context: context ?? {} }),
  });
  const data = await readJson<{
    success?: boolean;
    message?: TraeSuperEmployeeMessage | string;
    assistant_message?: TraeSuperEmployeeMessage;
    dispatch?: TraeSuperEmployeeDispatch;
    messages?: TraeSuperEmployeeMessage[];
    data?: {
      message?: TraeSuperEmployeeMessage | string;
      assistant_message?: TraeSuperEmployeeMessage;
      dispatch?: TraeSuperEmployeeDispatch;
      messages?: TraeSuperEmployeeMessage[];
    };
  }>(res);
  const payload = unwrapPayload(data, 'Trae 调用失败');
  return {
    dispatch: payload.dispatch,
    message: payload.message && typeof payload.message === 'object' ? payload.message : undefined,
    assistant_message: payload.assistant_message,
    messages: payload.messages ?? [],
  };
}
