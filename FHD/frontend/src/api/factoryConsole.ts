import { apiFetch } from '@/utils/apiBase';

/**
 * 顶层管理端「项目工厂」控制台 API。
 *
 * 闭环：拉项目（workspaces）+ 工厂员工（employees）→ 操作者选项目 → 用工厂员工的
 * `endpoint`（复用现有超级员工对话通道）发消息，并在 `context.workspace_id` 带上所选项目。
 * 路由侧据平台密钥铸造工厂授权、对该 Workspace 派工。仅平台管理端可见。
 */

export interface FactoryWorkspace {
  id: string;
  label: string;
  isolation: string;
  default_branch: string;
  vcs_kind: string;
}

export interface FactoryEmployee {
  id: string;
  display_name: string;
  display_tool: string;
  avatar_letter: string;
  summary: string;
  scope: string;
  endpoint: string | null;
}

const jsonHeaders: HeadersInit = { 'Content-Type': 'application/json' };

async function readJson<T = Record<string, unknown>>(res: Response): Promise<T> {
  const ct = res.headers.get('content-type') || '';
  if (!ct.toLowerCase().includes('application/json')) {
    throw new Error(res.status === 401 ? '未登录' : `请求失败（HTTP ${res.status}）`);
  }
  return (await res.json()) as T;
}

function unwrap<T>(data: { success?: boolean; message?: unknown }, value: T, fallback: string): T {
  if (data.success === false) {
    const msg = typeof data.message === 'string' && data.message.trim() ? data.message : fallback;
    throw new Error(msg);
  }
  return value;
}

export async function fetchFactoryWorkspaces(): Promise<FactoryWorkspace[]> {
  const res = await apiFetch('/api/admin/factory/workspaces', { headers: jsonHeaders });
  const data = await readJson<{ success?: boolean; message?: string; workspaces?: FactoryWorkspace[] }>(res);
  return unwrap(data, data.workspaces ?? [], '加载项目列表失败');
}

export async function fetchFactoryEmployees(): Promise<FactoryEmployee[]> {
  const res = await apiFetch('/api/admin/factory/employees', { headers: jsonHeaders });
  const data = await readJson<{ success?: boolean; message?: string; employees?: FactoryEmployee[] }>(res);
  return unwrap(data, data.employees ?? [], '加载工厂员工失败');
}

/**
 * 向某工厂员工的对话端点派工，带上所选项目（workspace_id 进 context）。
 * `endpoint` 取自 {@link fetchFactoryEmployees} 返回项；message 形状与超级员工一致。
 */
export async function dispatchFactoryTask(
  endpoint: string,
  message: string,
  workspaceId: string,
  context: Record<string, unknown> = {},
): Promise<Record<string, unknown>> {
  const res = await apiFetch(endpoint, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ message, context: { ...context, workspace_id: workspaceId } }),
  });
  const data = await readJson<Record<string, unknown>>(res);
  return unwrap(data, data, '派工失败');
}
