import { apiFetch } from '@/utils/apiBase';

export type CodexSuperEmployeeMessage = {
  id: string;
  role: 'user' | 'assistant' | 'system';
  body: string;
  created_at: string;
  status?: string;
  dispatch_request_id?: string;
  kind?: 'dispatcher' | 'codex_result' | string;
  task_id?: string;
  task_status?: string;
  subtask_id?: string;
  device_name?: string;
};

export type CodexSuperEmployeeDispatch = {
  request_id: string;
  status: string;
  accepted?: boolean;
  queued?: boolean;
  device_scope?: string;
  reason?: string;
  outbox_path?: string;
};

export type CodexSuperEmployeeApiScope = 'admin' | 'mobile';

export type CodexSuperEmployeeApiOptions = {
  scope?: CodexSuperEmployeeApiScope;
};

const jsonHeaders: HeadersInit = { 'Content-Type': 'application/json' };

function codexEndpoint(scope: CodexSuperEmployeeApiScope = 'admin'): string {
  return scope === 'mobile'
    ? '/api/mobile/v1/admin/codex-super-employee/messages'
    : '/api/admin/codex-super-employee/messages';
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

function unwrapCodexPayload<T extends Record<string, unknown>>(
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

export async function fetchCodexSuperEmployeeMessages(
  options: CodexSuperEmployeeApiOptions = {},
): Promise<CodexSuperEmployeeMessage[]> {
  const res = await apiFetch(codexEndpoint(options.scope), { headers: jsonHeaders });
  const data = await readJson<{
    success?: boolean;
    message?: string;
    messages?: CodexSuperEmployeeMessage[];
    data?: { messages?: CodexSuperEmployeeMessage[] };
  }>(res);
  const payload = unwrapCodexPayload(data, '加载 Codex 对话失败');
  return payload.messages ?? [];
}

export async function sendCodexSuperEmployeeMessage(
  message: string,
  context?: Record<string, unknown>,
  options: CodexSuperEmployeeApiOptions = {},
): Promise<{
  dispatch?: CodexSuperEmployeeDispatch;
  message?: CodexSuperEmployeeMessage;
  assistant_message?: CodexSuperEmployeeMessage;
  messages: CodexSuperEmployeeMessage[];
}> {
  const res = await apiFetch(codexEndpoint(options.scope), {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ message, context: context ?? {} }),
  });
  const data = await readJson<{
    success?: boolean;
    message?: CodexSuperEmployeeMessage | string;
    assistant_message?: CodexSuperEmployeeMessage;
    dispatch?: CodexSuperEmployeeDispatch;
    messages?: CodexSuperEmployeeMessage[];
    data?: {
      message?: CodexSuperEmployeeMessage | string;
      assistant_message?: CodexSuperEmployeeMessage;
      dispatch?: CodexSuperEmployeeDispatch;
      messages?: CodexSuperEmployeeMessage[];
    };
  }>(res);
  const payload = unwrapCodexPayload(data, 'Codex 调用失败');
  return {
    dispatch: payload.dispatch,
    message: payload.message && typeof payload.message === 'object' ? payload.message : undefined,
    assistant_message: payload.assistant_message,
    messages: payload.messages ?? [],
  };
}
