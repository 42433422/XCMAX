import { apiFetch } from '@/utils/apiBase';
import type { CodexSuperEmployeeApiScope } from '@/api/codexSuperEmployee';

export type SuperEmployeeStreamTool = 'codex' | 'claude' | 'cursor' | 'trae';

export type SuperEmployeeStreamHandlers = {
  onToken?: (text: string) => void;
  onStatus?: (text: string) => void;
  signal?: AbortSignal;
};

function streamEndpoint(tool: SuperEmployeeStreamTool, scope: CodexSuperEmployeeApiScope = 'admin'): string {
  const prefix = scope === 'mobile' ? '/api/mobile/v1/admin' : '/api/admin';
  return `${prefix}/${tool}-super-employee/messages/stream`;
}

/**
 * 桌面/管理端超级员工真 SSE（与手机 LAN stream 同协议）。
 * 事件：token / status / done / error。
 */
export async function streamSuperEmployeeMessage(
  tool: SuperEmployeeStreamTool,
  message: string,
  context: Record<string, unknown> = {},
  options: SuperEmployeeStreamHandlers & { scope?: CodexSuperEmployeeApiScope } = {},
): Promise<string> {
  const scope = options.scope ?? 'admin';
  const res = await apiFetch(streamEndpoint(tool, scope), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify({ message, context }),
    signal: options.signal,
    // 长任务：不走默认短超时
    timeoutMs: 0,
  });
  if (!res.ok) {
    const ct = res.headers.get('content-type') || '';
    if (ct.includes('application/json')) {
      const data = (await res.json()) as { message?: string };
      throw new Error(String(data.message || `流式调用失败（HTTP ${res.status}）`));
    }
    throw new Error(`流式调用失败（HTTP ${res.status}）`);
  }
  if (!res.body) {
    throw new Error('流式响应无 body');
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let assembled = '';
  let doneText = '';

  const handleEvent = (raw: string) => {
    const lines = raw.split('\n');
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith('data:')) continue;
      const payload = trimmed.slice('data:'.length).trim();
      if (!payload || payload === '[DONE]') continue;
      let json: Record<string, unknown>;
      try {
        json = JSON.parse(payload) as Record<string, unknown>;
      } catch {
        continue;
      }
      const type = String(json.type || '');
      if (type === 'token') {
        const text = String(json.text || '');
        if (text) {
          assembled += text;
          options.onToken?.(text);
        }
      } else if (type === 'status') {
        const text = String(json.text || '');
        if (text) options.onStatus?.(text);
      } else if (type === 'done') {
        const result = json.result;
        if (result && typeof result === 'object' && !Array.isArray(result)) {
          const response = (result as { response?: unknown }).response;
          if (typeof response === 'string' && response.trim()) {
            doneText = response;
          }
        }
        if (!doneText && typeof json.text === 'string' && json.text.trim()) {
          doneText = json.text;
        }
      } else if (type === 'error') {
        throw new Error(String(json.message || '流式调用失败'));
      }
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop() || '';
    for (const part of parts) {
      if (part.trim()) handleEvent(part);
    }
  }
  if (buffer.trim()) handleEvent(buffer);

  return (doneText || assembled).trim() || '（无回复）';
}
