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
});
