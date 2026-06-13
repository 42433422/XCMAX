import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, buildFullApiUrl, getRuntimeApiBase, XCAGI_PROMPT_LAN_GATE_EVENT } from '@/api/core';

/** 构造类 Response 对象（只 mock fetch 这一外部边界，铁律4） */
function makeResponse(opts: {
  ok?: boolean;
  status?: number;
  contentType?: string;
  json?: unknown;
}) {
  const { ok = true, status = 200, contentType = 'application/json', json } = opts;
  return {
    ok,
    status,
    headers: { get: (k: string) => (k.toLowerCase() === 'content-type' ? contentType : null) },
    json: async () => json,
  } as unknown as Response;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  // 清 csrf cookie
  document.cookie = 'csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT';
  delete (window as unknown as { __XCMAX_API_BASE__?: string }).__XCMAX_API_BASE__;
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('api/core URL helpers', () => {
  it('getRuntimeApiBase returns string', () => {
    expect(typeof getRuntimeApiBase()).toBe('string');
  });

  it('buildFullApiUrl keeps absolute url', () => {
    expect(buildFullApiUrl('https://x.com/a')).toBe('https://x.com/a');
  });

  it('buildFullApiUrl prefixes injected base for relative url', () => {
    (window as unknown as { __XCMAX_API_BASE__?: string }).__XCMAX_API_BASE__ = '/fhd-api';
    expect(buildFullApiUrl('/api/x')).toBe('/fhd-api/api/x');
    expect(buildFullApiUrl('api/x')).toBe('/fhd-api/api/x');
  });
});

describe('ApiError', () => {
  it('carries status and data', () => {
    const e = new ApiError('boom', 418, { detail: 'teapot' });
    expect(e.name).toBe('ApiError');
    expect(e.status).toBe(418);
    expect(e.data).toEqual({ detail: 'teapot' });
    expect(e instanceof Error).toBe(true);
  });
});

describe('api.get', () => {
  it('builds query string skipping null/undefined', async () => {
    fetchMock.mockResolvedValue(makeResponse({ json: { success: true } }));
    await api.get('/api/items', { a: 1, b: null, c: undefined, d: 'x' });
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('a=1');
    expect(url).toContain('d=x');
    expect(url).not.toContain('b=');
    expect(url).not.toContain('c=');
  });

  it('returns parsed json on success', async () => {
    fetchMock.mockResolvedValue(makeResponse({ json: { ok: 1 } }));
    const out = await api.get('/api/x');
    expect(out).toEqual({ ok: 1 });
  });

  it('GET does not attach CSRF header', async () => {
    document.cookie = 'csrf_token=tok123';
    fetchMock.mockResolvedValue(makeResponse({ json: {} }));
    await api.get('/api/x');
    const cfg = fetchMock.mock.calls[0][1] as RequestInit;
    expect((cfg.headers as Record<string, string>)['X-CSRF-Token']).toBeUndefined();
  });
});

describe('api.post', () => {
  it('sends JSON body with content-type', async () => {
    fetchMock.mockResolvedValue(makeResponse({ json: {} }));
    await api.post('/api/x', { name: 'a' });
    const cfg = fetchMock.mock.calls[0][1] as RequestInit;
    expect(cfg.method).toBe('POST');
    expect(cfg.body).toBe(JSON.stringify({ name: 'a' }));
    expect((cfg.headers as Record<string, string>)['Content-Type']).toBe('application/json');
  });

  it('attaches CSRF header on POST when cookie present', async () => {
    document.cookie = 'csrf_token=tok123';
    fetchMock.mockResolvedValue(makeResponse({ json: {} }));
    await api.post('/api/x', {});
    const cfg = fetchMock.mock.calls[0][1] as RequestInit;
    expect((cfg.headers as Record<string, string>)['X-CSRF-Token']).toBe('tok123');
  });

  it('sends FormData without forcing JSON content-type', async () => {
    fetchMock.mockResolvedValue(makeResponse({ json: {} }));
    const fd = new FormData();
    fd.append('f', 'v');
    await api.post('/api/upload', fd);
    const cfg = fetchMock.mock.calls[0][1] as RequestInit;
    expect(cfg.body).toBe(fd);
    expect((cfg.headers as Record<string, string>)['Content-Type']).toBeUndefined();
  });
});

describe('api.put/patch/delete', () => {
  it('put sends body', async () => {
    fetchMock.mockResolvedValue(makeResponse({ json: {} }));
    await api.put('/api/x', { a: 1 });
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('PUT');
  });

  it('patch sends body', async () => {
    fetchMock.mockResolvedValue(makeResponse({ json: {} }));
    await api.patch('/api/x', { a: 1 });
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('PATCH');
  });

  it('delete without data has no body', async () => {
    fetchMock.mockResolvedValue(makeResponse({ json: {} }));
    await api.delete('/api/x');
    const cfg = fetchMock.mock.calls[0][1] as RequestInit;
    expect(cfg.method).toBe('DELETE');
    expect(cfg.body).toBeUndefined();
  });

  it('delete with data sends JSON body', async () => {
    fetchMock.mockResolvedValue(makeResponse({ json: {} }));
    await api.delete('/api/x', { id: 9 });
    expect((fetchMock.mock.calls[0][1] as RequestInit).body).toBe(JSON.stringify({ id: 9 }));
  });
});

describe('api.download', () => {
  it('returns raw response for blob', async () => {
    const resp = makeResponse({ contentType: 'application/octet-stream', json: undefined });
    fetchMock.mockResolvedValue(resp);
    const out = await api.download('/api/file', { a: 1 });
    expect(out).toBe(resp);
  });
});

describe('error handling', () => {
  it('throws ApiError with json message', async () => {
    fetchMock.mockResolvedValue(makeResponse({ ok: false, status: 400, json: { message: '坏了' } }));
    await expect(api.get('/api/x')).rejects.toMatchObject({ status: 400, message: '坏了' });
  });

  it('uses nested error.message', async () => {
    fetchMock.mockResolvedValue(
      makeResponse({ ok: false, status: 422, json: { error: { message: '校验失败' } } })
    );
    await expect(api.get('/api/x')).rejects.toMatchObject({ message: '校验失败' });
  });

  it('uses detail field', async () => {
    fetchMock.mockResolvedValue(makeResponse({ ok: false, status: 404, json: { detail: '找不到' } }));
    await expect(api.get('/api/x')).rejects.toMatchObject({ message: '找不到' });
  });

  it('falls back to status message for non-json error', async () => {
    fetchMock.mockResolvedValue(makeResponse({ ok: false, status: 500, contentType: 'text/html' }));
    await expect(api.get('/api/x')).rejects.toMatchObject({ status: 500 });
  });

  it('wraps network error as ApiError status 0', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(api.get('/api/x')).rejects.toMatchObject({ status: 0 });
  });
});

describe('non-json success', () => {
  it('returns raw response when content-type not json', async () => {
    const resp = makeResponse({ contentType: 'text/plain', json: undefined });
    fetchMock.mockResolvedValue(resp);
    const out = await api.get('/api/x');
    expect(out).toBe(resp);
  });
});

describe('LAN gate event', () => {
  it('dispatches prompt-lan-gate on 401 license_required', async () => {
    const listener = vi.fn();
    window.addEventListener(XCAGI_PROMPT_LAN_GATE_EVENT, listener);
    fetchMock.mockResolvedValue(
      makeResponse({ ok: false, status: 401, json: { error: 'license_required', message: '需授权' } })
    );
    await expect(api.get('/api/x')).rejects.toBeInstanceOf(ApiError);
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(XCAGI_PROMPT_LAN_GATE_EVENT, listener);
  });

  it('does not dispatch for unrelated 401', async () => {
    const listener = vi.fn();
    window.addEventListener(XCAGI_PROMPT_LAN_GATE_EVENT, listener);
    fetchMock.mockResolvedValue(makeResponse({ ok: false, status: 401, json: { error: 'unauthorized' } }));
    await expect(api.get('/api/x')).rejects.toBeInstanceOf(ApiError);
    expect(listener).not.toHaveBeenCalled();
    window.removeEventListener(XCAGI_PROMPT_LAN_GATE_EVENT, listener);
  });
});
