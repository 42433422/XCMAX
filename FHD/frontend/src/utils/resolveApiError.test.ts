import { describe, expect, it } from 'vitest';
import { resolveApiErrorMessage } from './resolveApiError';

describe('resolveApiErrorMessage', () => {
  const t = (key: string) => (key === 'errors.ERR_DEMO' ? '演示错误' : key);

  it('prefers translated error code', () => {
    expect(resolveApiErrorMessage(t, { code: 'ERR_DEMO', message: 'raw' })).toBe('演示错误');
  });

  it('falls back to server message when code missing translation', () => {
    expect(resolveApiErrorMessage(t, { code: 'ERR_UNKNOWN', message: '服务端说明' })).toBe(
      '服务端说明',
    );
  });

  it('uses fallback when payload empty', () => {
    expect(resolveApiErrorMessage(t, null, '默认')).toBe('默认');
  });
});
