import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ApiError, api } from '@/api/core';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

beforeEach(() => {
  mockFetch.mockReset();
});

describe('ApiError', () => {
  it('should set status and data', () => {
    const err = new ApiError('test error', 400, { detail: 'bad' });
    expect(err.message).toBe('test error');
    expect(err.status).toBe(400);
    expect(err.data).toEqual({ detail: 'bad' });
    expect(err.name).toBe('ApiError');
  });
});

describe('api.get', () => {
  it('should make GET request with params', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ success: true, data: [1, 2, 3] }),
    });

    const result = await api.get('/api/test', { foo: 'bar' });
    expect(mockFetch).toHaveBeenCalledTimes(1);
    const calledUrl = mockFetch.mock.calls[0][0];
    expect(calledUrl).toContain('/api/test?');
    expect(calledUrl).toContain('foo=bar');
    expect(result.success).toBe(true);
  });

  it('should make GET request without params', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ success: true }),
    });

    const result = await api.get('/api/test');
    expect(result.success).toBe(true);
  });
});

describe('api.post', () => {
  it('should make POST request with JSON body', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ success: true, data: { id: 1 } }),
    });

    const result = await api.post('/api/test', { name: 'hello' });
    expect(mockFetch).toHaveBeenCalledTimes(1);
    const callOpts = mockFetch.mock.calls[0][1];
    expect(callOpts.method).toBe('POST');
    expect(callOpts.body).toBe(JSON.stringify({ name: 'hello' }));
    expect(result.success).toBe(true);
  });
});

describe('api.delete', () => {
  it('should make DELETE request', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ success: true }),
    });

    await api.delete('/api/test/1');
    const callOpts = mockFetch.mock.calls[0][1];
    expect(callOpts.method).toBe('DELETE');
  });
});

describe('error handling', () => {
  it('should throw ApiError on non-ok response', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ message: 'Not found' }),
    });

    await expect(api.get('/api/missing')).rejects.toThrow();
    try {
      await api.get('/api/missing');
    } catch (e: any) {
      expect(e).toBeInstanceOf(ApiError);
      expect(e.status).toBe(404);
    }
  });

  it('should throw ApiError on network error', async () => {
    mockFetch.mockRejectedValueOnce(new Error('Network failure'));

    await expect(api.get('/api/test')).rejects.toThrow();
    try {
      await api.get('/api/test');
    } catch (e: any) {
      expect(e).toBeInstanceOf(ApiError);
      expect(e.status).toBe(0);
    }
  });
});
