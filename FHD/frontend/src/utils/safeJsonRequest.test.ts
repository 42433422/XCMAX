import { describe, expect, it, vi } from 'vitest';
import { safeJsonRequest } from './safeJsonRequest';

function mockResponse(
  status: number,
  body: string,
  contentType = 'application/json',
): Response {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: { get: (k: string) => (k === 'content-type' ? contentType : null) },
    text: async () => body,
  } as Response;
}

describe('safeJsonRequest', () => {
  it('parses successful JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockResponse(200, '{"ok":true}')));
    const res = await safeJsonRequest<{ ok: boolean }>('/api/x');
    expect(res.ok).toBe(true);
    expect(res.data).toEqual({ ok: true });
    expect(res.status).toBe(200);
  });

  it('returns structured error for non-JSON body', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockResponse(502, '<html>', 'text/html')));
    const res = await safeJsonRequest('/api/x');
    expect(res.ok).toBe(false);
    expect(res.data).toBeNull();
    expect(res.message).toContain('未返回JSON');
  });

  it('surfaces API error message from JSON body', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(mockResponse(400, '{"message":"bad input"}')),
    );
    const res = await safeJsonRequest('/api/x');
    expect(res.ok).toBe(false);
    expect(res.message).toBe('bad input');
    expect(res.data).toEqual({ message: 'bad input' });
  });

  it('handles invalid JSON payload', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockResponse(200, '{bad')));
    const res = await safeJsonRequest('/api/x');
    expect(res.ok).toBe(false);
    expect(res.message).toContain('JSON解析失败');
  });

  it('handles a missing content-type header as non-JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        status: 200,
        ok: true,
        headers: { get: () => null },
        text: async () => '<html>',
      } as Response),
    );
    const res = await safeJsonRequest('/api/x');
    expect(res.ok).toBe(false);
    expect(res.message).toContain('未返回JSON');
  });

  it('omits the body snippet when non-JSON body is empty', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockResponse(502, '', 'text/html')));
    const res = await safeJsonRequest('/api/x');
    expect(res.ok).toBe(false);
    expect(res.message).toContain('未返回JSON');
    expect(res.message).not.toContain('响应片段');
  });

  it('parses an empty JSON body as an empty object', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockResponse(200, '')));
    const res = await safeJsonRequest('/api/x');
    expect(res.ok).toBe(true);
    expect(res.data).toEqual({});
  });

  it('falls back to a generic message when JSON error has no message', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(mockResponse(500, '{"error":"boom"}')),
    );
    const res = await safeJsonRequest('/api/x');
    expect(res.ok).toBe(false);
    expect(res.data).toEqual({ error: 'boom' });
    expect(res.message).toBe('请求失败（500）');
  });
});
