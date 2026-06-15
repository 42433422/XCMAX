import { describe, expect, it } from 'vitest';
import { extractAccountMeta } from './extractAccountMeta';

describe('extractAccountMeta', () => {
  it('returns empty object for invalid input', () => {
    expect(extractAccountMeta(null)).toEqual({});
    expect(extractAccountMeta(undefined)).toEqual({});
  });

  it('merges nested data with top-level overrides', () => {
    const raw = {
      data: { account_kind: 'enterprise', company_brand: 'Nested' },
      market_is_admin: true,
      company_brand: 'Top',
    };
    expect(extractAccountMeta(raw)).toEqual({
      account_kind: 'enterprise',
      company_brand: 'Top',
      market_is_admin: true,
    });
  });

  it('ignores empty top-level values', () => {
    const raw = {
      data: { account_kind: 'admin' },
      market_is_admin: '',
      impersonating_username: null,
    };
    expect(extractAccountMeta(raw)).toEqual({ account_kind: 'admin' });
  });
});
