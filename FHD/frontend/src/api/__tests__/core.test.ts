import { describe, expect, it } from 'vitest';
import { ApiError, type ApiResponse } from '@/api/core';
import { authApi } from '@/api/auth';

describe('api core types', () => {
  it('ApiResponse uses success boolean', () => {
    const sample: ApiResponse<{ id: number }> = { success: true, data: { id: 1 } };
    expect(sample.success).toBe(true);
  });

  it('ApiError carries unknown data payload', () => {
    const err = new ApiError('bad', 400, { detail: 'x' });
    expect(err.status).toBe(400);
    expect(err.data).toEqual({ detail: 'x' });
  });
});

describe('auth api module', () => {
  it('exports authApi.login', () => {
    expect(typeof authApi.login).toBe('function');
  });
});
