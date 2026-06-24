import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock('@/utils/apiBase', () => ({ apiFetch }));

import { dispatchFactoryTask, fetchFactoryEmployees, fetchFactoryWorkspaces } from './factoryConsole';

function jsonRes(body: unknown, { status = 200, ct = 'application/json' } = {}) {
  return {
    status,
    headers: { get: () => ct },
    json: async () => body,
  } as unknown as Response;
}

beforeEach(() => {
  apiFetch.mockReset();
});

describe('factoryConsole api', () => {
  it('fetches workspaces from the admin factory endpoint', async () => {
    apiFetch.mockResolvedValueOnce(jsonRes({ success: true, workspaces: [{ id: 'xcmax' }] }));

    const ws = await fetchFactoryWorkspaces();

    expect(ws).toHaveLength(1);
    expect(apiFetch).toHaveBeenCalledWith('/api/admin/factory/workspaces', expect.anything());
  });

  it('fetches factory employees', async () => {
    apiFetch.mockResolvedValueOnce(
      jsonRes({ success: true, employees: [{ id: 'claude-factory-employee' }] }),
    );

    const emps = await fetchFactoryEmployees();

    expect(emps[0]?.id).toBe('claude-factory-employee');
    expect(apiFetch).toHaveBeenCalledWith('/api/admin/factory/employees', expect.anything());
  });

  it('dispatches a task carrying workspace_id inside context', async () => {
    apiFetch.mockResolvedValueOnce(jsonRes({ success: true, messages: [] }));

    await dispatchFactoryTask('/api/admin/claude-super-employee/messages', '修复登录', 'xcmax');

    expect(apiFetch).toHaveBeenCalledWith(
      '/api/admin/claude-super-employee/messages',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ message: '修复登录', context: { workspace_id: 'xcmax' } }),
      }),
    );
  });

  it('merges extra context while keeping the selected workspace', async () => {
    apiFetch.mockResolvedValueOnce(jsonRes({ success: true }));

    await dispatchFactoryTask('/ep', 'go', 'repo-2', { source: 'console' });

    const body = JSON.parse((apiFetch.mock.calls[0]?.[1] as { body: string }).body);
    expect(body.context).toEqual({ source: 'console', workspace_id: 'repo-2' });
  });

  it('throws the server message when success is false', async () => {
    apiFetch.mockResolvedValueOnce(jsonRes({ success: false, message: '仅管理端可见' }));

    await expect(fetchFactoryWorkspaces()).rejects.toThrow('仅管理端可见');
  });

  it('throws 未登录 on a non-json (401) response', async () => {
    apiFetch.mockResolvedValueOnce(jsonRes({}, { ct: 'text/html', status: 401 }));

    await expect(fetchFactoryEmployees()).rejects.toThrow('未登录');
  });

  it('falls back to empty arrays when payload omits the list', async () => {
    apiFetch.mockResolvedValueOnce(jsonRes({ success: true }));
    expect(await fetchFactoryWorkspaces()).toEqual([]);

    apiFetch.mockResolvedValueOnce(jsonRes({ success: true }));
    expect(await fetchFactoryEmployees()).toEqual([]);
  });
});
