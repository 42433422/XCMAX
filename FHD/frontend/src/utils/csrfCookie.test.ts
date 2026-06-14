import { describe, expect, it } from 'vitest';
import { readCsrfTokenFromCookie, shouldAttachCsrfHeader } from './csrfCookie';

describe('csrfCookie', () => {
  it('readCsrfTokenFromCookie parses document.cookie', () => {
    Object.defineProperty(document, 'cookie', {
      writable: true,
      value: 'session=abc; csrf_token=token%2B1; other=1',
    });
    expect(readCsrfTokenFromCookie()).toBe('token+1');
  });

  it('shouldAttachCsrfHeader skips safe methods', () => {
    expect(shouldAttachCsrfHeader('GET', {})).toBe(false);
    expect(shouldAttachCsrfHeader('POST', {})).toBe(true);
  });

  it('shouldAttachCsrfHeader skips when csrf or bearer present', () => {
    expect(shouldAttachCsrfHeader('POST', { 'X-CSRF-Token': 't' })).toBe(false);
    expect(shouldAttachCsrfHeader('PUT', { Authorization: 'Bearer abc' })).toBe(false);
  });
});
