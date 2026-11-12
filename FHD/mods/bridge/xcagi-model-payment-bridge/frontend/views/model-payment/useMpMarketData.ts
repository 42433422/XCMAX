import { computed, ref } from 'vue';
import type { Ref } from 'vue';
import {
  LS_MARKET_ACCESS_TOKEN,
  LS_MARKET_USER_JSON,
  fetchMarketAccountOverview,
  fetchMarketLlmCatalog,
  type MarketAccountOverviewData,
  type MarketLlmCatalogData,
} from '@/api/marketAccount';
import {
  CACHE_KEYS,
  CACHE_TTL,
  clearCachedMarketData,
  formatCacheAge,
  getCacheAge,
  getCachedData,
  setCachedData,
} from './mpMarketCache';
import { marketBase } from './mpHandoff';
import { formatInteger, formatMoney, providersFromOverview } from './useMpCatalog';

/** 市场账户概览 / 模型目录数据加载（拆分自 ModelPaymentView.vue，逻辑不变） */

export function useMpMarketData(deps: {
  isOffline: Ref<boolean>;
  dataSource: Ref<'network' | 'cache' | 'offline'>;
}) {
  const { isOffline, dataSource } = deps;

  const marketOverview = ref<MarketAccountOverviewData | null>(null);
  const marketSyncWarning = ref('');
  const llmCatalog = ref<MarketLlmCatalogData | null>(null);
  const llmCatalogLoading = ref(false);
  const llmCatalogMessage = ref('');
  const marketToken = ref(window.localStorage.getItem(LS_MARKET_ACCESS_TOKEN) || '');
  const hasSessionMarketToken = ref(false);

  const lastSyncTime = ref<number | null>(null);
  const isRefreshing = ref(false);

  function applyMarketToken(token: string): boolean {
    const next = (token || '').trim();
    if (!next) return false;
    const prev = (marketToken.value || window.localStorage.getItem(LS_MARKET_ACCESS_TOKEN) || '').trim();
    const changed = Boolean(prev && prev !== next);
    marketToken.value = next;
    window.localStorage.setItem(LS_MARKET_ACCESS_TOKEN, next);
    if (changed) {
      clearCachedMarketData();
      marketOverview.value = null;
      llmCatalog.value = null;
      lastSyncTime.value = null;
    }
    return changed;
  }

  function readStoredMarketToken(): string {
    return (marketToken.value || window.localStorage.getItem(LS_MARKET_ACCESS_TOKEN) || '').trim();
  }

  function shouldRetryOverviewWithStoredToken(error: unknown): boolean {
    const message = error instanceof Error ? error.message : String(error || '');
    return /尚未绑定市场账号|authorization\s*必填/i.test(message);
  }

  // 从缓存恢复数据（页面加载时立即显示）
  function restoreFromCache(): boolean {
    let restored = false;

    const cachedOverview = getCachedData<MarketAccountOverviewData>(CACHE_KEYS.OVERVIEW);
    if (cachedOverview && !marketOverview.value) {
      marketOverview.value = cachedOverview;
      restored = true;
    }

    const cachedCatalog = getCachedData<MarketLlmCatalogData>(CACHE_KEYS.LLM_CATALOG);
    if (cachedCatalog && !llmCatalog.value) {
      llmCatalog.value = cachedCatalog;
      restored = true;
    }

    if (restored) {
      const overviewAge = getCacheAge(CACHE_KEYS.OVERVIEW);
      const catalogAge = getCacheAge(CACHE_KEYS.LLM_CATALOG);
      const oldestAge = Math.max(overviewAge ?? 0, catalogAge ?? 0);
      lastSyncTime.value = Date.now() - oldestAge;
    }

    return restored;
  }

  // ========== 数据加载函数（带智能缓存）==========

  async function refreshMarketOverview(auth?: string, forceRefresh = false) {
    // 账户概览优先走后端当前会话绑定的 market token；若 handoff 未确认，则用登录时写入的本地 token 兜底。
    const storedToken = readStoredMarketToken();
    let token = auth === undefined ? (hasSessionMarketToken.value ? '' : storedToken) : (auth || storedToken);

    if (!forceRefresh) {
      const cacheAge = getCacheAge(CACHE_KEYS.OVERVIEW);
      if (cacheAge !== null && cacheAge < CACHE_TTL.OVERVIEW) {
        console.log(`[ModelPayment] 使用缓存的账户概览 (${formatCacheAge(cacheAge)})`);
        return;
      }
    }

    try {
      let data: MarketAccountOverviewData;
      try {
        data = await fetchMarketAccountOverview(token, forceRefresh);
      } catch (e) {
        if (!token && storedToken && shouldRetryOverviewWithStoredToken(e)) {
          token = storedToken;
          data = await fetchMarketAccountOverview(token);
        } else {
          throw e;
        }
      }
      marketOverview.value = data;
      marketSyncWarning.value =
        (typeof data.sync_warning === 'string' && data.sync_warning.trim()) ||
        (data.degraded || data.market_unreachable
          ? `无法连接修茈市场（${data.market_base_url || marketBase}），请使用顶部按钮打开钱包充值。`
          : '');
      setCachedData(CACHE_KEYS.OVERVIEW, data);
      lastSyncTime.value = Date.now();

      if (!llmCatalog.value?.providers?.length) {
        const fallbackProviders = providersFromOverview(data);
        if (fallbackProviders.length) {
          llmCatalog.value = {
            providers: fallbackProviders,
            market_base_url: data.market_base_url,
          };
          setCachedData(CACHE_KEYS.LLM_CATALOG, llmCatalog.value);
        }
      }

      if (token) {
        marketToken.value = token;
        window.localStorage.setItem(LS_MARKET_ACCESS_TOKEN, token);
      }
      window.localStorage.setItem(LS_MARKET_USER_JSON, JSON.stringify(data.user));
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      marketSyncWarning.value = `账户同步失败：${msg}。请确认后端已启动且 XCAGI_MARKET_BASE_URL 指向可用市场（如生产 119.27.178.147:9999）。`;
      if (!marketOverview.value) {
        const cached = getCachedData<MarketAccountOverviewData>(CACHE_KEYS.OVERVIEW);
        if (cached) {
          marketOverview.value = cached;
          console.warn('[ModelPayment] API请求失败，使用缓存数据');
        }
      }
      console.warn('[ModelPayment] 拉取市场余额失败:', e);
    }
  }

  async function refreshLlmCatalog(auth?: string, forceRefresh = false) {
    const token = auth || marketToken.value || window.localStorage.getItem(LS_MARKET_ACCESS_TOKEN) || '';

    if (!forceRefresh) {
      const cacheAge = getCacheAge(CACHE_KEYS.LLM_CATALOG);
      if (cacheAge !== null && cacheAge < CACHE_TTL.LLM_CATALOG) {
        console.log(`[ModelPayment] 使用缓存的模型目录 (${formatCacheAge(cacheAge)})`);
        return;
      }
    }

    llmCatalogLoading.value = true;
    llmCatalogMessage.value = '';
    try {
      llmCatalog.value = await fetchMarketLlmCatalog(token, forceRefresh);
      setCachedData(CACHE_KEYS.LLM_CATALOG, llmCatalog.value);
      lastSyncTime.value = Date.now();
    } catch (e: any) {
      if (!llmCatalog.value) {
        const cached = getCachedData<MarketLlmCatalogData>(CACHE_KEYS.LLM_CATALOG);
        if (cached) {
          llmCatalog.value = cached;
          llmCatalogMessage.value = '模型目录接口暂不可用，已加载本地缓存。';
        }
      }

      const fallbackProviders = providersFromOverview(marketOverview.value);
      if (fallbackProviders.length && !llmCatalog.value) {
        llmCatalog.value = {
          providers: fallbackProviders,
          market_base_url: marketOverview.value?.market_base_url,
        };
        llmCatalogMessage.value = '模型目录接口暂不可用，已回退展示账号概览中的模型列表。';
      } else if (!llmCatalog.value) {
        llmCatalogMessage.value = '模型目录同步失败，请稍后重试。';
      }
      console.warn('[ModelPayment] 拉取模型目录失败:', e);
    } finally {
      llmCatalogLoading.value = false;
      isRefreshing.value = false;
    }
  }

  // 强制刷新（用户点击按钮）
  async function forceRefreshAll() {
    isRefreshing.value = true;
    await Promise.all([
      refreshMarketOverview(undefined, true),
      refreshLlmCatalog(undefined, true),
    ]);
  }

  const marketBalanceText = computed(() => {
    if (!marketOverview.value) return '—';
    return formatMoney(marketOverview.value.wallet?.balance);
  });

  const marketBalanceHint = computed(() => {
    if (marketSyncWarning.value) return marketSyncWarning.value;
    if (isOffline.value) return '离线模式：显示本地缓存数据';
    if (!marketOverview.value) {
      return hasSessionMarketToken.value || readStoredMarketToken()
        ? '正在同步账户信息…'
        : '尚未绑定修茈市场账号，请先登录软件';
    }
    const source = dataSource.value === 'cache' ? '（缓存）' : '';
    const age = lastSyncTime.value ? formatCacheAge(Date.now() - lastSyncTime.value) : '刚刚';
    return `已同步修茈市场钱包与会员信息${source}（${age}更新）`;
  });

  const marketEmptyHint = computed(() => {
    if (marketSyncWarning.value) return marketSyncWarning.value;
    if (!lastSyncTime.value) return '正在加载账户信息…';
    return '尚未绑定修茈市场账号，请登录软件后在设置中同步市场 Token';
  });

  const marketMembershipLabel = computed(() => (
    marketOverview.value?.membership?.label
    || marketOverview.value?.membership?.tier
    || '普通用户'
  ));

  const marketMembershipReferenceText = computed(() => {
    const v = marketOverview.value?.wallet?.membership_reference_yuan;
    const n = Number(v);
    if (!Number.isFinite(n) || n <= 0) return '—';
    return `¥${Math.floor(n)}`;
  });

  const marketExperienceText = computed(() => formatInteger(marketOverview.value?.user?.experience));

  const marketByokText = computed(() => (
    marketOverview.value?.membership?.can_byok ? '已开通' : '未开通'
  ));

  return {
    marketOverview,
    marketSyncWarning,
    llmCatalog,
    llmCatalogLoading,
    llmCatalogMessage,
    marketToken,
    hasSessionMarketToken,
    lastSyncTime,
    isRefreshing,
    applyMarketToken,
    readStoredMarketToken,
    restoreFromCache,
    refreshMarketOverview,
    refreshLlmCatalog,
    forceRefreshAll,
    marketBalanceText,
    marketBalanceHint,
    marketEmptyHint,
    marketMembershipLabel,
    marketMembershipReferenceText,
    marketExperienceText,
    marketByokText,
  };
}
