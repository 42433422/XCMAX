/** 市场数据 localStorage 缓存工具（拆分自 ModelPaymentView.vue，逻辑不变） */

export const CACHE_KEYS = {
  OVERVIEW: 'xcagi_market_overview_cache',
  LLM_CATALOG: 'xcagi_market_llm_catalog_cache',
} as const;

export const CACHE_TTL = {
  OVERVIEW: 30 * 1000,          // 账户概览：30秒（支付后快速刷新）
  LLM_CATALOG: 30 * 60 * 1000,  // 模型目录：30分钟
} as const;

export interface CacheEntry<T> {
  data: T;
  timestamp: number;
}

export function getCachedData<T>(key: string): T | null {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const entry: CacheEntry<T> = JSON.parse(raw);
    return entry.data;
  } catch (e) {
    console.warn(`[Cache] 读取失败 (${key}):`, e);
    return null;
  }
}

export function setCachedData<T>(key: string, data: T): void {
  try {
    const entry: CacheEntry<T> = { data, timestamp: Date.now() };
    window.localStorage.setItem(key, JSON.stringify(entry));
  } catch (e) {
    console.warn(`[Cache] 写入失败 (${key}):`, e);
  }
}

export function clearCachedMarketData(): void {
  try {
    window.localStorage.removeItem(CACHE_KEYS.OVERVIEW);
    window.localStorage.removeItem(CACHE_KEYS.LLM_CATALOG);
  } catch (e) {
    console.warn('[Cache] 清理市场账号缓存失败:', e);
  }
}

export function getCacheAge(key: string): number | null {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const entry: CacheEntry<any> = JSON.parse(raw);
    return Date.now() - entry.timestamp;
  } catch (e) {
    return null;
  }
}

export function formatCacheAge(ms: number): string {
  if (ms < 60 * 1000) return '刚刚';
  if (ms < 60 * 60 * 1000) return `${Math.floor(ms / 60000)} 分钟前`;
  return `${Math.floor(ms / 3600000)} 小时前`;
}
