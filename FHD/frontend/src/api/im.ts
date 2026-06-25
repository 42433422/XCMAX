import { apiFetch, getApiBase } from '@/utils/apiBase';

export type ImConversationSummary = {
  id: number;
  title: string;
  is_direct: boolean;
  last_message_at: string | null;
  last_message_preview: string;
  unread_count: number;
  is_enterprise_dedicated_cs?: boolean;
};

export type ImMessage = {
  id: number;
  conversation_id: number;
  sender_user_id: number;
  sender_display_name?: string;
  body: string;
  created_at: string | null;
};

export type ImContact = {
  id: number;
  display_name: string;
  username: string;
  is_enterprise_dedicated_cs?: boolean;
};

const jsonHeaders: HeadersInit = { 'Content-Type': 'application/json' };

/** 仅当响应确为 JSON 时解析；否则抛出清晰错误（避免把 SPA 的 HTML 当 JSON 解析）。 */
async function readJson<T = Record<string, unknown>>(res: Response): Promise<T> {
  const ct = res.headers.get('content-type') || '';
  if (!ct.toLowerCase().includes('application/json')) {
    throw new Error(res.status === 401 ? '未登录' : `请求失败（HTTP ${res.status}）`);
  }
  return (await res.json()) as T;
}

export async function fetchImContacts(keyword?: string): Promise<ImContact[]> {
  const suffix = keyword && keyword.trim() ? `?q=${encodeURIComponent(keyword.trim())}` : '';
  const res = await apiFetch(`/api/im/contacts${suffix}`, { headers: jsonHeaders });
  const data = await readJson<{ success?: boolean; contacts?: ImContact[] }>(res);
  if (!data.success) throw new Error('加载联系人失败');
  return data.contacts ?? [];
}

/** 桌面端固定联系人条目(后端 surface SSOT 派生:assistant/super/dedicated_cs)。 */
export type ImFixedEntry = {
  id: string;
  kind: string;
  name: string;
  summary: string;
  avatar: string;
  route: string;
  backend: string;
};

export type ImFixedContacts = {
  device: string;
  side: string;
  top: ImFixedEntry[];
  bottom: ImFixedEntry[];
};

/**
 * 桌面端消息页固定联系人组成(surface SSOT: device=desktop × side)。
 * 以 platform 为界切 top/bottom,顺序即 SSOT 声明序。fail-safe:任何失败返回空段,
 * 交由调用方回退,绝不抛断列表渲染。
 */
export async function fetchDesktopFixedContacts(): Promise<ImFixedContacts> {
  const empty: ImFixedContacts = { device: 'desktop', side: '', top: [], bottom: [] };
  try {
    const res = await apiFetch('/api/im/fixed-contacts', { headers: jsonHeaders });
    const data = await readJson<{ success?: boolean } & Partial<ImFixedContacts>>(res);
    if (!data.success) return empty;
    return {
      device: data.device ?? 'desktop',
      side: data.side ?? '',
      top: data.top ?? [],
      bottom: data.bottom ?? [],
    };
  } catch {
    return empty;
  }
}

export async function fetchImConversations(): Promise<ImConversationSummary[]> {
  const res = await apiFetch('/api/im/conversations', { headers: jsonHeaders });
  const data = await readJson<{ success?: boolean; conversations?: ImConversationSummary[] }>(res);
  if (!data.success) throw new Error('加载会话失败');
  return data.conversations ?? [];
}

export async function fetchImUnreadTotal(): Promise<number> {
  try {
    const res = await apiFetch('/api/im/unread-total', { headers: jsonHeaders });
    const ct = res.headers.get('content-type') || '';
    if (!res.ok || !ct.toLowerCase().includes('application/json')) return 0;
    const data = (await res.json()) as { success?: boolean; unread_total?: number };
    if (!data.success) return 0;
    return Number(data.unread_total ?? 0);
  } catch {
    return 0;
  }
}

export async function createDirectConversation(
  peerUserId: number
): Promise<{ id: number; title: string | null; created: boolean }> {
  const res = await apiFetch('/api/im/conversations/direct', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ peer_user_id: peerUserId }),
  });
  const data = await readJson<{
    success?: boolean;
    conversation?: { id: number; title: string | null; created: boolean };
    message?: string;
  }>(res);
  if (!data.success || !data.conversation) {
    throw new Error(data.message ?? '创建会话失败');
  }
  return data.conversation;
}

export async function fetchImMessages(
  conversationId: number,
  opts?: { limit?: number; beforeId?: number }
): Promise<ImMessage[]> {
  const q = new URLSearchParams();
  if (opts?.limit) q.set('limit', String(opts.limit));
  if (opts?.beforeId) q.set('before_id', String(opts.beforeId));
  const suffix = q.toString() ? `?${q}` : '';
  const res = await apiFetch(`/api/im/conversations/${conversationId}/messages${suffix}`, {
    headers: jsonHeaders,
  });
  const data = await readJson<{ success?: boolean; messages?: ImMessage[] }>(res);
  if (!data.success) throw new Error('加载消息失败');
  return data.messages ?? [];
}

export async function sendImMessage(conversationId: number, body: string): Promise<ImMessage> {
  const res = await apiFetch(`/api/im/conversations/${conversationId}/messages`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ body }),
  });
  const data = await readJson<{ success?: boolean; message?: ImMessage }>(res);
  const msg = data.message;
  if (!data.success || !msg) throw new Error('发送失败');
  return msg;
}

export async function markImRead(conversationId: number, lastMessageId: number): Promise<void> {
  await apiFetch(`/api/im/conversations/${conversationId}/read`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ last_message_id: lastMessageId }),
  });
}

export function imWebSocketUrl(): string {
  const apiBase = getApiBase().replace(/\/$/, '');
  if (/^https?:\/\//i.test(apiBase)) {
    return `${apiBase.replace(/^http/i, 'ws')}/ws/im`;
  }

  const origin =
    typeof window !== 'undefined' && window.location?.origin
      ? window.location.origin.replace(/^http/i, 'ws')
      : 'ws://127.0.0.1:5000';
  const prefix = apiBase ? (apiBase.startsWith('/') ? apiBase : `/${apiBase}`) : '';
  return `${origin}${prefix}/ws/im`;
}
