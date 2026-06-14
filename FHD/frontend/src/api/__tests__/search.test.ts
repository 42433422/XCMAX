import { describe, expect, it } from 'vitest';
import { searchApi } from '../search';

describe('search api module', () => {
  it('exports searchV0 helper', () => {
    expect(typeof searchApi.searchV0).toBe('function');
  });
});
