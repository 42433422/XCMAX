import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { authApi } from '@/api/auth';

function makeResponse(opts: { ok?: boolean; status?: number; json?: unknown }) {
  const { ok = true, status = 200, json = { success: true } } = opts;
  return {
    ok,
    status,
    headers: { get: () => 'application/json' },
    json: async () => json,
  } as unknown as Response;
}

function findCall(method: string, pathPart: string) {
  return (global.fetch as ReturnType<typeof vi.fn>).mock.calls.find(([url, cfg]) => {
    const m = (cfg as RequestInit | undefined)?.method || 'GET';
    return m === method && String(url).includes(pathPart);
  });
}

describe('authApi phase1', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue(makeResponse({ json: { success: true, data: {} } }));
    vi.stubGlobal('fetch', fetchMock);
    document.cookie = 'csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT';
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('login posts credentials with account_kind', async () => {
    await authApi.login('u', 'pass', 'enterprise');
    const call = findCall('POST', '/api/auth/login');
    expect(call).toBeTruthy();
    const body = JSON.parse(String((call![1] as RequestInit).body));
    expect(body).toMatchObject({
      username: 'u',
      password: 'pass',
      account_kind: 'enterprise',
    });
  });

  it('validateSession calls GET /api/auth/session/validate', async () => {
    await authApi.validateSession();
    const call = findCall('GET', '/api/auth/session/validate');
    expect(call).toBeTruthy();
  });

  it('logout posts to /api/auth/logout', async () => {
    await authApi.logout();
    const call = findCall('POST', '/api/auth/logout');
    expect(call).toBeTruthy();
  });

  it('register posts registration payload', async () => {
    await authApi.register({
      username: 'newuser',
      password: 'secret',
      email: 'a@b.com',
    });
    const call = findCall('POST', '/api/auth/register');
    expect(call).toBeTruthy();
    const body = JSON.parse(String((call![1] as RequestInit).body));
    expect(body.username).toBe('newuser');
    expect(body.email).toBe('a@b.com');
  });

  it('getCurrentUser calls GET /api/auth/me', async () => {
    await authApi.getCurrentUser();
    const call = findCall('GET', '/api/auth/me');
    expect(call).toBeTruthy();
  });
});
