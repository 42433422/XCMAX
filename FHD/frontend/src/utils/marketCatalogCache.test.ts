import { describe, expect, it, beforeEach } from 'vitest';
import {
  buildMarketCatalogCacheKey,
  clearMarketCatalogCache,
  isMarketCatalogCacheFresh,
  readMarketCatalogCache,
  writeMarketCatalogCache,
} from './marketCatalogCache';

describe('marketCatalogCache', () => {
  beforeEach(() => {
    clearMarketCatalogCache();
  });

  it('builds stable keys', () => {
    expect(buildMarketCatalogCacheKey('office', '  ')).toBe('office:');
    expect(buildMarketCatalogCacheKey('office', 'excel')).toBe('office:excel');
  });

  it('round-trips cache entries', () => {
    const key = buildMarketCatalogCacheKey('office');
    writeMarketCatalogCache(key, 'office', [{ id: 'excel-generate-employee', name: 'Excel' } as never]);
    const hit = readMarketCatalogCache(key);
    expect(hit?.items).toHaveLength(1);
    expect(isMarketCatalogCacheFresh(hit)).toBe(true);
  });
});
