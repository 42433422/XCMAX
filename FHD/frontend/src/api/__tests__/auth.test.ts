import { describe, expect, it } from 'vitest';
import { authApi } from '@/api/auth';

describe('authApi', () => {
  it('exposes session validation', () => {
    expect(typeof authApi.validateSession).toBe('function');
  });
});
