import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

const mockGet = vi.fn();
const mockPost = vi.fn();

vi.mock('@/api/core', () => ({
  api: {
    get: (...args: any[]) => mockGet(...args),
    post: (...args: any[]) => mockPost(...args),
  },
  primeCsrfCookie: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('@/api/marketAccount', () => ({
  LS_MARKET_ACCESS_TOKEN: 'market_access_token',
  LS_MARKET_USER_JSON: 'market_user_json',
}));

import { authApi } from '@/api/auth';

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
});

describe('authApi.login', () => {
  it('should call POST /api/auth/login', async () => {
    mockPost.mockResolvedValueOnce({
      success: true,
      user: { id: 1, username: 'test' },
    });

    const result = await authApi.login('testuser', 'pass123');
    expect(mockPost).toHaveBeenCalledWith('/api/auth/login', {
      username: 'testuser',
      password: 'pass123',
    });
    expect(result.success).toBe(true);
  });
});

describe('authApi.getCurrentUser', () => {
  it('should call GET /api/auth/me', async () => {
    mockGet.mockResolvedValueOnce({
      success: true,
      user: { id: 1, username: 'test' },
      permissions: ['read'],
    });

    const result = await authApi.getCurrentUser();
    expect(mockGet).toHaveBeenCalledWith('/api/auth/me');
    expect(result.success).toBe(true);
  });
});

describe('authApi.validateSession', () => {
  it('should call GET /api/auth/session/validate', async () => {
    mockGet.mockResolvedValueOnce({ success: true });

    const result = await authApi.validateSession();
    expect(mockGet).toHaveBeenCalledWith('/api/auth/session/validate');
    expect(result.success).toBe(true);
  });
});

describe('authApi.logout', () => {
  it('should clear localStorage and call POST /api/auth/logout', async () => {
    const removeItemSpy = vi.spyOn(Storage.prototype, 'removeItem');
    mockPost.mockResolvedValueOnce({ success: true });

    await authApi.logout();
    expect(removeItemSpy).toHaveBeenCalledWith('market_access_token');
    expect(removeItemSpy).toHaveBeenCalledWith('market_user_json');
    expect(mockPost).toHaveBeenCalledWith('/api/auth/logout', {});
    removeItemSpy.mockRestore();
  });
});
