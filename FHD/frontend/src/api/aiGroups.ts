import { apiFetch } from '@/utils/apiBase';

export type AiGroupMember = {
  employee_id: string;
  mod_id: string;
  name: string;
  avatar: string;
  summary: string;
};

export type AiGroup = {
  id: string;
  name: string;
  department_key: string;
  member_count: number;
  members: AiGroupMember[];
  last_message_preview: string;
  last_message_at: string;
};

export type AiGroupMessage = {
  id: string;
  group_id: string;
  role: 'user' | 'ai';
  sender_id: string;
  sender_name: string;
  sender_avatar: string;
  body: string;
  created_at: string;
};

export type AiGroupApiScope = 'admin' | 'mobile';

const jsonHeaders: HeadersInit = { 'Content-Type': 'application/json' };

function base(scope: AiGroupApiScope): string {
  return scope === 'mobile' ? '/api/mobile/v1/ai-groups' : '/api/admin/ai-groups';
}

async function readJson<T = Record<string, unknown>>(res: Response): Promise<T> {
  const ct = res.headers.get('content-type') || '';
  if (!ct.toLowerCase().includes('application/json')) {
    throw new Error(res.status === 401 ? '未登录' : `请求失败（HTTP ${res.status}）`);
  }
  return (await res.json()) as T;
}

function unwrap<T extends Record<string, unknown>>(data: T & { data?: unknown; success?: boolean; message?: unknown }, fallback: string): T {
  if (data.success === false) throw new Error(typeof data.message === 'string' && data.message ? data.message : fallback);
  if (data.data && typeof data.data === 'object' && !Array.isArray(data.data)) {
    return data.data as T;
  }
  return data;
}

export async function fetchAiGroups(scope: AiGroupApiScope = 'admin'): Promise<AiGroup[]> {
  const res = await apiFetch(base(scope), { headers: jsonHeaders });
  const data = await readJson<{ groups?: AiGroup[]; data?: { groups?: AiGroup[] } }>(res);
  return unwrap(data, '加载群聊失败').groups ?? [];
}

export async function createAiGroup(name: string, scope: AiGroupApiScope = 'admin'): Promise<AiGroup | null> {
  const res = await apiFetch(base(scope), { method: 'POST', headers: jsonHeaders, body: JSON.stringify({ name }) });
  const data = await readJson<{ group?: AiGroup; data?: { group?: AiGroup } }>(res);
  return unwrap(data, '建群失败').group ?? null;
}

export async function fetchAiGroupMessages(groupId: string, scope: AiGroupApiScope = 'admin'): Promise<AiGroupMessage[]> {
  const res = await apiFetch(`${base(scope)}/${encodeURIComponent(groupId)}/messages`, { headers: jsonHeaders });
  const data = await readJson<{ messages?: AiGroupMessage[]; data?: { messages?: AiGroupMessage[] } }>(res);
  return unwrap(data, '加载群消息失败').messages ?? [];
}

export async function postAiGroupMessage(
  groupId: string,
  message: string,
  mentions: string[] = [],
  scope: AiGroupApiScope = 'admin',
): Promise<{ group?: AiGroup; messages: AiGroupMessage[] }> {
  const res = await apiFetch(`${base(scope)}/${encodeURIComponent(groupId)}/messages`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ message, mentions, sender_name: '我' }),
  });
  const data = await readJson<{ group?: AiGroup; messages?: AiGroupMessage[]; data?: { group?: AiGroup; messages?: AiGroupMessage[] } }>(res);
  const payload = unwrap(data, '发送失败');
  return { group: payload.group, messages: payload.messages ?? [] };
}

export async function addAiGroupMember(
  groupId: string,
  member: Partial<AiGroupMember> & { employee_id: string },
  scope: AiGroupApiScope = 'admin',
): Promise<AiGroup | null> {
  const res = await apiFetch(`${base(scope)}/${encodeURIComponent(groupId)}/members`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(member),
  });
  const data = await readJson<{ group?: AiGroup; data?: { group?: AiGroup } }>(res);
  return unwrap(data, '添加成员失败').group ?? null;
}

export async function removeAiGroupMember(groupId: string, employeeId: string, scope: AiGroupApiScope = 'admin'): Promise<AiGroup | null> {
  const res = await apiFetch(
    `${base(scope)}/${encodeURIComponent(groupId)}/members/${encodeURIComponent(employeeId)}`,
    { method: 'DELETE', headers: jsonHeaders },
  );
  const data = await readJson<{ group?: AiGroup; data?: { group?: AiGroup } }>(res);
  return unwrap(data, '移除成员失败').group ?? null;
}
