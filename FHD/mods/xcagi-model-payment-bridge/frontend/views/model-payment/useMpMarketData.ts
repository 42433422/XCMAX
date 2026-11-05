import { computed, ref, watch, getCurrentScope, onScopeDispose } from 'vue';
import type { Ref } from 'vue';
import { captureAuthSession, getAuthSessionEpoch } from '@/utils/authSessionCache';
import { productReadAccountEpoch } from '@/utils/productReadAccountScope';
import { getRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime';
import {
  readCurrentMarketAccessToken,
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
  marketCacheOwner,
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
  const marketToken = ref(readCurrentMarketAccessToken());
  const hasSessionMarketToken = ref(false);

  const lastSyncTime = ref<number | null>(null);
  const isRefreshing = ref(false);
  let lifetime = 0;
  let overviewRequest = 0;
  let catalogRequest = 0;
  let refreshRequest = 0;
  const stop = watch([getAuthSessionEpoch, () => productReadAccountEpoch.value], () => {
    lifetime++;
    marketOverview.value = null;
    llmCatalog.value = null;
    marketToken.value = '';
    hasSessionMarketToken.value = false;
    marketSyncWarning.value = '';
    llmCatalogMessage.value = '';
    lastSyncTime.value = null;
    llmCatalogLoading.value = false;
    isRefreshing.value = false;
  }, { flush: 'sync' });
  if (getCurrentScope()) onScopeDispose(() => { lifetime++; stop(); });

  function currentRequest(): () => boolean {
    const current = captureAuthSession();
    const generation = lifetime;
    return () => current() && generation === lifetime;
  }

  function applyMarketToken(token: string): boolean {
    const next = (token || '').trim();
    if (!next) return false;
    const prev = (marketToken.value || readCurrentMarketAccessToken()).trim();
    const changed = Boolean(prev && prev !== next);
    marketToken.value = next;
    // The handoff caller commits credentials only after checking its session owner.
    if (changed) {
      clearCachedMarketData();
      marketOverview.value = null;
      llmCatalog.value = null;
      lastSyncTime.value = null;
    }
    return changed;
  }

  function readStoredMarketToken(): string {
    return marketCacheOwner() ? (marketToken.value || readCurrentMarketAccessToken()).trim() : '';
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
    const sessionCurrent = currentRequest();
    const request = ++overviewRequest;
    const owner = marketCacheOwner();
    const current = () => sessionCurrent() && request === overviewRequest;
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
        if (!current()) return;
        if (!token && storedToken && shouldRetryOverviewWithStoredToken(e)) {
          token = storedToken;
          data = await fetchMarketAccountOverview(token);
        } else {
          throw e;
        }
      }
      if (!current()) return;
      const expectedUser = getRuntimeTenantStorageScopeInput()?.marketUserId;
      if (expectedUser != null && data.user?.id != null && String(expectedUser) !== String(data.user.id)) {
        throw new Error('返回账户与当前账号不一致，请重新登录。');
      }
      marketOverview.value = data;
      marketSyncWarning.value =
        (typeof data.sync_warning === 'string' && data.sync_warning.trim()) ||
        (data.degraded || data.market_unreachable
          ? `无法连接修茈市场（${data.market_base_url || marketBase}），请使用顶部按钮打开钱包充值。`
          : '');
      setCachedData(CACHE_KEYS.OVERVIEW, data, owner);
      lastSyncTime.value = Date.now();

      if (!llmCatalog.value?.providers?.length) {
        const fallbackProviders = providersFromOverview(data);
        if (fallbackProviders.length) {
          llmCatalog.value = {
            providers: fallbackProviders,
            market_base_url: data.market_base_url,
          };
          setCachedData(CACHE_KEYS.LLM_CATALOG, llmCatalog.value, owner);
        }
      }

      if (token) marketToken.value = token;
      try { window.localStorage.setItem(LS_MARKET_USER_JSON, JSON.stringify(data.user)); } catch { /* private mode */ }
    } catch (e) {
      if (!current()) return;
      const msg = e instanceof Error ? e.message : String(e);
      marketSyncWarning.value = `账户同步失败：${msg}。请重试或重新登录。`;
      if (!marketOverview.value) {
        const cached = getCachedData<MarketAccountOverviewData>(CACHE_KEYS.OVERVIEW, owner);
        if (cached) {
          marketOverview.value = cached;
          console.warn('[ModelPayment] API请求失败，使用缓存数据');
        }
      }
      console.warn('[ModelPayment] 拉取市场余额失败:', e);
    }
  }

  async function refreshLlmCatalog(auth?: string, forceRefresh = false) {
    const sessionCurrent = currentRequest();
    const request = ++catalogRequest;
    const owner = marketCacheOwner();
    const current = () => sessionCurrent() && request === catalogRequest;
    const token = auth || readStoredMarketToken();

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
      const data = await fetchMarketLlmCatalog(token, forceRefresh);
      if (!current()) return;
      llmCatalog.value = data;
      setCachedData(CACHE_KEYS.LLM_CATALOG, data, owner);
      lastSyncTime.value = Date.now();
    } catch (e) {
      if (!current()) return;
      if (!llmCatalog.value) {
        const cached = getCachedData<MarketLlmCatalogData>(CACHE_KEYS.LLM_CATALOG, owner);
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
      if (current()) llmCatalogLoading.value = false;
    }
  }

  // 强制刷新（用户点击按钮）
  async function forceRefreshAll() {
    const current = currentRequest();
    const request = ++refreshRequest;
    isRefreshing.value = true;
    try {
      await Promise.all([refreshMarketOverview(undefined, true), refreshLlmCatalog(undefined, true)]);
    } finally {
      if (current() && request === refreshRequest) isRefreshing.value = false;
    }
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
