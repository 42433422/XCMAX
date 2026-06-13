<template>
  <div class="page-view mp-root" id="view-model-payment">
    <!-- 离线/数据来源提示条 -->
    <div v-if="isOffline" class="mp-status-banner mp-status-banner--offline">
      <span class="mp-status-dot"></span>
      <span class="mp-status-text">离线模式 - 显示本地缓存数据</span>
      <button class="mp-status-btn" @click="retryConnection">重新连接</button>
    </div>
    <div v-else-if="dataSource === 'cache'" class="mp-status-banner mp-status-banner--cached">
      <span class="mp-status-dot"></span>
      <span class="mp-status-text">缓存模式 - {{ cacheAgeText }}</span>
    </div>

    <div class="page-content">
      <div class="page-header mp-hero">
        <div class="mp-hero-text">
          <h2>模型服务</h2>
          <p class="muted header-sub">
            余额与充值走修茈市场；本页汇总展示，支付在
            <a :href="walletUrlHandoff" target="_blank" rel="noopener noreferrer">钱包</a>
            /
            <a :href="plansUrlHandoff" target="_blank" rel="noopener noreferrer">套餐</a>
            完成。
          </p>
        </div>
        <div class="mp-hero-actions">
          <a class="mp-hero-btn mp-hero-btn--primary" :href="walletUrlHandoff" target="_blank" rel="noopener noreferrer">
            打开修茈钱包
          </a>
          <a class="mp-hero-btn" :href="plansUrlHandoff" target="_blank" rel="noopener noreferrer">会员套餐</a>
          <button type="button" class="mp-hero-btn" :disabled="isRefreshing" @click="forceRefreshAll()">
            {{ isRefreshing ? '同步中…' : '刷新' }}
          </button>
        </div>
      </div>

      <p v-if="marketSyncWarning" class="mp-sync-warning" role="status">{{ marketSyncWarning }}</p>

      <details class="mp-fold" open>
        <summary class="mp-fold-title">账户余额</summary>
      <div class="card mp-panel mp-status mp-balance">
        <div class="mp-panel-head">
          <span class="mp-panel-icon mp-balance-icon" aria-hidden="true">¥</span>
          <div class="mp-balance-text">
            <div class="card-header mp-panel-title">
              账户余额（本机汇总）
              <a
                :href="walletUrlHandoff"
                target="_blank"
                rel="noopener noreferrer"
                class="mp-balance-link"
              >
                修茈钱包
                <i class="fa fa-external-link" aria-hidden="true"></i>
              </a>
            </div>
            <p class="muted mp-panel-desc">
              {{ marketBalanceHint }}
            </p>
          </div>
          <div class="mp-balance-amount">
            <span class="mp-balance-currency">¥</span>
            <span class="mp-balance-num">{{ marketBalanceText }}</span>
            <span class="mp-balance-unit">CNY</span>
          </div>
        </div>
        <div v-if="marketOverview" class="mp-market-quota">
          <div>
            <span>会员</span>
            <strong>{{ marketMembershipLabel }}</strong>
          </div>
          <div>
            <span>累计权益参考</span>
            <strong>{{ marketMembershipReferenceText }}</strong>
          </div>
          <div>
            <span>经验</span>
            <strong>{{ marketExperienceText }}</strong>
          </div>
          <div>
            <span>BYOK</span>
            <strong>{{ marketByokText }}</strong>
          </div>
        </div>
        <p v-else class="muted mp-market-empty">
          {{ marketEmptyHint }}
        </p>
      </div>
      </details>

      <details class="mp-fold">
        <summary class="mp-fold-title">快捷充值（跳转修茈钱包）</summary>
        <div class="mp-recharge-grid mp-recharge-grid--compact">
          <a
            v-for="item in rechargeLinks"
            :key="item.amount"
            class="mp-recharge-card"
            :href="item.url"
            target="_blank"
            rel="noopener noreferrer"
          >
            <strong>¥{{ item.amount }}</strong>
            <span>{{ item.label }}</span>
          </a>
        </div>
      </details>

      <details class="mp-fold">
        <summary class="mp-fold-title">修茈会员套餐（{{ membershipPlans.length }} 档，点击跳转购买）</summary>
        <div class="mp-plans mp-plans--compact">
          <article
            v-for="(p, idx) in membershipPlans"
            :key="p.id"
            class="mp-plan"
            :class="['mp-plan--t' + (idx % 3), { 'is-selected': p.recommended }]"
            role="button"
            tabindex="0"
            :aria-label="`打开修茈市场购买 ${p.title}`"
            @click="openMarketPlan(p)"
            @keydown.enter.prevent="openMarketPlan(p)"
          >
            <div class="mp-plan-topbar" aria-hidden="true" />
            <div class="mp-plan-head">
              <h3 class="mp-plan-title">{{ p.title }}</h3>
              <div class="mp-plan-head-tags">
                <span v-if="p.badge" class="mp-badge">{{ p.badge }}</span>
              </div>
            </div>
            <p class="mp-desc">{{ p.description }}</p>
            <div class="mp-price-block">
              <span class="mp-price-currency">¥</span>
              <span class="mp-price-num">{{ p.price }}</span>
              <span class="mp-price-unit">CNY</span>
            </div>
            <ul class="mp-feature-list">
              <li v-for="feature in p.features" :key="feature">{{ feature }}</li>
            </ul>
            <div class="mp-actions">
              <button
                type="button"
                class="mp-pay mp-pay--ali mp-pay--full"
                @click.stop="openMarketPlan(p)"
              >
                <span class="mp-pay-ico mp-pay-ico-ali" aria-hidden="true">修</span>
                <span>去修茈市场购买</span>
              </button>
            </div>
          </article>
        </div>
      </details>

      <details class="mp-fold">
        <summary class="mp-fold-title">
          模型支持
          <span v-if="llmProviders.length" class="mp-fold-badge">{{ llmProviders.length }} 家供应商</span>
        </summary>
        <p v-if="llmCatalogMessage" class="mp-sync-message">{{ llmCatalogMessage }}</p>
        <div v-if="llmCatalogLoading && !llmProviders.length" class="mp-loading muted">正在同步模型目录...</div>
        <div v-else-if="llmProviders.length" class="mp-llm-grid mp-llm-grid--scroll" role="list">
          <article
            v-for="provider in llmProviders"
            :key="provider.provider"
            class="mp-llm-tile"
            :class="`mp-llm-tile--${providerState(provider)}`"
            role="listitem"
            :title="provider.error || `${provider.label || provider.provider} · ${providerModelCount(provider)} 个模型`"
          >
            <span class="mp-llm-icon" aria-hidden="true">{{ providerInitials(provider) }}</span>
            <strong>{{ provider.label || provider.provider }}</strong>
            <small>{{ providerModelCount(provider) }} 个模型</small>
          </article>
        </div>
        <div v-else class="mp-loading muted">暂无可展示模型目录；可点击顶部「刷新」或登录后重试。</div>
      </details>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import {
  LS_MARKET_ACCESS_TOKEN,
  LS_MARKET_USER_JSON,
  fetchMarketAccountOverview,
  fetchMarketLlmCatalog,
  fetchSessionMarketHandoff,
  type MarketAccountOverviewData,
  type MarketLlmCatalogData,
  type MarketLlmProvider,
} from '@/api/marketAccount';
import { swManager } from '@/utils/serviceWorker';

const router = useRouter();

const marketBase = String(
  import.meta.env.VITE_MARKET_BASE || 'https://xiu-ci.com/market',
).replace(/\/$/, '');
const plansUrlBase = String(
  import.meta.env.VITE_MARKET_PLANS_URL || `${marketBase}/plans`,
).replace(/\/$/, '');
const walletUrlBase = String(
  import.meta.env.VITE_MARKET_WALLET_URL || `${marketBase}/wallet`,
).replace(/\/$/, '');

const plansUrl = computed(() => {
  const userId = marketOverview.value?.user?.id;
  const username = marketOverview.value?.user?.username;
  const params: Record<string, string | number> = { source: 'fhd' };

  if (userId) params.user_id = userId;
  if (username) params.username = username;

  return withQuery(plansUrlBase, params);
});

const walletUrl = computed(() => {
  const userId = marketOverview.value?.user?.id;
  const username = marketOverview.value?.user?.username;
  const params: Record<string, string | number> = { source: 'fhd' };

  if (userId) params.user_id = userId;
  if (username) params.username = username;

  return withQuery(walletUrlBase, params);
});

/** 跨域打开修茈站点时附带 JWT，与市场站 modstore_token 对齐。
 * - query：`xcagi_mt` — HTTP 301/302 **不会保留 hash**，经 CDN/裸跳 https 时只能靠 query 把令牌带到落地页。
 * - hash：`#xcagi_mt=` — 首跳无中间重定向时优先由 hash 传递（相对不易进入 Referer）。
 */
function appendMarketHandoffHash(url: string): string {
  const token = (marketToken.value || window.localStorage.getItem(LS_MARKET_ACCESS_TOKEN) || '').trim();
  if (!token) return url;
  try {
    const u = new URL(url);
    u.searchParams.set('xcagi_mt', token);
    u.hash = `xcagi_mt=${encodeURIComponent(token)}`;
    return u.toString();
  } catch {
    try {
      const u = new URL(url, window.location.origin);
      u.searchParams.set('xcagi_mt', token);
      u.hash = `xcagi_mt=${encodeURIComponent(token)}`;
      return u.toString();
    } catch {
      const join = url.includes('?') ? '&' : '?';
      return `${url}${join}xcagi_mt=${encodeURIComponent(token)}#xcagi_mt=${encodeURIComponent(token)}`;
    }
  }
}

const plansUrlHandoff = computed(() => appendMarketHandoffHash(plansUrl.value));
const walletUrlHandoff = computed(() => appendMarketHandoffHash(walletUrl.value));

type MarketMembershipPlan = {
  id: string;
  tier: string;
  title: string;
  price: string;
  description: string;
  badge?: string;
  recommended?: boolean;
  features: string[];
};

const membershipPlans: MarketMembershipPlan[] = [
  {
    id: 'plan_basic',
    tier: 'vip',
    title: 'VIP',
    price: '9.90',
    description: '入门会员，解锁基础 AI 调用与平台能力。',
    features: ['基础 AI 对话', '基础模型额度', '可购买更多余额', '会员身份标识'],
  },
  {
    id: 'plan_pro',
    tier: 'vip_plus',
    title: 'VIP+',
    price: '29.90',
    description: '进阶会员，更高额度 + BYOK + 用量明细。',
    badge: '推荐',
    recommended: true,
    features: ['更高 AI 调用额度', 'BYOK 自有密钥', '优先模型接入', '用量明细'],
  },
  {
    id: 'plan_enterprise',
    tier: 'svip1',
    title: 'SVIP',
    price: '99.90',
    description: '企业级会员，含更高额度、团队与高级能力入口。',
    features: ['企业级 AI 额度', '高级功能优先体验', '团队协作入口', 'SVIP 身份标识'],
  },
];

const rechargeAmounts = [10, 30, 100, 300];

const marketOverview = ref<MarketAccountOverviewData | null>(null);
const marketSyncWarning = ref('');
const llmCatalog = ref<MarketLlmCatalogData | null>(null);
const llmCatalogLoading = ref(false);
const llmCatalogMessage = ref('');
const marketToken = ref(window.localStorage.getItem(LS_MARKET_ACCESS_TOKEN) || '');
const hasSessionMarketToken = ref(false);

const lastSyncTime = ref<number | null>(null);
const isRefreshing = ref(false);

// ========== 离线状态检测 ==========
const isOffline = ref(!navigator.onLine);
const dataSource = ref<'network' | 'cache' | 'offline'>('network');
const cacheTimestamp = ref<number | null>(null);

// 监听Service Worker状态变化
let unsubSW: (() => void) | null = null;

// ========== 智能缓存系统 ==========

const CACHE_KEYS = {
  OVERVIEW: 'xcagi_market_overview_cache',
  LLM_CATALOG: 'xcagi_market_llm_catalog_cache',
} as const;

const CACHE_TTL = {
  OVERVIEW: 30 * 1000,          // 账户概览：30秒（支付后快速刷新）
  LLM_CATALOG: 30 * 60 * 1000,  // 模型目录：30分钟
} as const;

interface CacheEntry<T> {
  data: T;
  timestamp: number;
}

function getCachedData<T>(key: string): T | null {
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

function setCachedData<T>(key: string, data: T): void {
  try {
    const entry: CacheEntry<T> = { data, timestamp: Date.now() };
    window.localStorage.setItem(key, JSON.stringify(entry));
  } catch (e) {
    console.warn(`[Cache] 写入失败 (${key}):`, e);
  }
}

function clearCachedMarketData(): void {
  try {
    window.localStorage.removeItem(CACHE_KEYS.OVERVIEW);
    window.localStorage.removeItem(CACHE_KEYS.LLM_CATALOG);
  } catch (e) {
    console.warn('[Cache] 清理市场账号缓存失败:', e);
  }
}

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

function getCacheAge(key: string): number | null {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const entry: CacheEntry<any> = JSON.parse(raw);
    return Date.now() - entry.timestamp;
  } catch (e) {
    return null;
  }
}

function formatCacheAge(ms: number): string {
  if (ms < 60 * 1000) return '刚刚';
  if (ms < 60 * 60 * 1000) return `${Math.floor(ms / 60000)} 分钟前`;
  return `${Math.floor(ms / 3600000)} 小时前`;
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
      data = await fetchMarketAccountOverview(token);
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

function providersFromOverview(data: MarketAccountOverviewData | null): MarketLlmProvider[] {
  const raw = (data as any)?.llm?.providers;
  if (!Array.isArray(raw)) return [];
  return raw.filter((p) => p && p.provider);
}

function formatMoney(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return n.toFixed(2);
}

function formatInteger(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return String(Math.floor(n));
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

// 离线状态计算属性
const cacheAgeText = computed(() => {
  if (!cacheTimestamp.value) return '未知时间';
  const age = Date.now() - cacheTimestamp.value;
  return formatCacheAge(age);
});

const offlineStatusText = computed(() => {
  if (isOffline.value) {
    if (dataSource.value === 'offline') return '完全离线，数据来自本地存储';
    return '网络不可用，显示Service Worker缓存数据';
  }
  return '';
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

const llmProviders = computed<MarketLlmProvider[]>(() => (
  (llmCatalog.value?.providers || [])
    .filter((p) => p && p.provider)
    .sort((a, b) => providerModelCount(b) - providerModelCount(a))
));

function providerModelCount(provider: MarketLlmProvider): number {
  if (Array.isArray(provider.models_detailed) && provider.models_detailed.length) {
    return provider.models_detailed.length;
  }
  return Array.isArray(provider.models) ? provider.models.length : 0;
}

function providerInitials(provider: MarketLlmProvider): string {
  const label = (provider.label || provider.provider || '').trim();
  if (!label) return '?';
  const parts = label.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  return label.slice(0, 2).toUpperCase();
}

function providerState(provider: MarketLlmProvider): 'ok' | 'warn' {
  return provider.error ? 'warn' : 'ok';
}

function withQuery(base: string, params: Record<string, string | number>): string {
  try {
    if (!base || typeof base !== 'string') {
      console.warn('[ModelPayment] withQuery: base URL is empty or invalid');
      return '#';
    }

    const u = new URL(base, window.location.origin);
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== '') {
        u.searchParams.set(k, String(v));
      }
    }
    return u.toString();
  } catch (error) {
    console.error('[ModelPayment] withQuery URL construction failed:', error, { base, params });
    
    // 降级：手动拼接查询参数
    try {
      const queryString = Object.entries(params)
        .filter(([, v]) => v !== undefined && v !== null && v !== '')
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join('&');
      
      return queryString ? `${base}?${queryString}` : base;
    } catch (fallbackError) {
      console.error('[ModelPayment] withQuery fallback also failed:', fallbackError);
      return base || '#';
    }
  }
}

function marketPlanUrl(plan: MarketMembershipPlan): string {
  const userId = marketOverview.value?.user?.id;
  const username = marketOverview.value?.user?.username;

  const params: Record<string, string | number> = {
    plan: plan.id,
    tier: plan.tier,
    source: 'fhd',
  };

  if (userId) {
    params.user_id = userId;
  }
  if (username) {
    params.username = username;
  }

  return withQuery(plansUrl.value, params);
}

/** 本地或会话中的修茈 JWT；无令牌时不应外链跳转（否则落地页无法识别身份）。 */
async function resolveMarketAccessToken(): Promise<string> {
  console.log('[ModelPayment] 优先从当前会话获取市场 token...');
  try {
    const handoff = await fetchSessionMarketHandoff();
    const mt = handoff?.token?.trim();
    if (mt) {
      console.log('[ModelPayment] 从会话获取到 token');
      hasSessionMarketToken.value = true;
      applyMarketToken(mt);
      return mt;
    }
    hasSessionMarketToken.value = false;
    console.warn('[ModelPayment] 会话中无可用 token（可能未登录或会话已过期）');
  } catch (error) {
    hasSessionMarketToken.value = false;
    console.error('[ModelPayment] 获取会话 token 失败:', error);
  }

  const t = (marketToken.value || window.localStorage.getItem(LS_MARKET_ACCESS_TOKEN) || '').trim();
  if (t) {
    console.log('[ModelPayment] 从本地存储获取到 token');
    return t;
  }
  return '';
}

async function openMarketPlan(plan: MarketMembershipPlan) {
  const token = await resolveMarketAccessToken();

  try {
    const url = appendMarketHandoffHash(marketPlanUrl(plan));

    if (token) {
      console.log('[ModelPayment] 使用 token 打开市场链接');
      const newWindow = window.open(url, '_blank', 'noopener,noreferrer');

      if (newWindow) {
        console.log('[ModelPayment] 成功打开新窗口');

        // 监听支付完成后自动刷新（用户返回时）
        const handleVisibilityChange = () => {
          if (document.visibilityState === 'visible') {
            console.log('[ModelPayment] 用户返回页面，强制刷新支付状态');
            forceRefreshAll();
            document.removeEventListener('visibilitychange', handleVisibilityChange);
          }
        };
        document.addEventListener('visibilitychange', handleVisibilityChange);

        // 30秒后移除监听器（避免长期占用）
        setTimeout(() => {
          document.removeEventListener('visibilitychange', handleVisibilityChange);
        }, 30000);

        return;
      }

      console.warn('[ModelPayment] 弹窗被拦截，降级为当前窗口跳转');
      window.location.href = url;
      return;
    }

    console.log('[ModelPayment] 无 token，直接打开市场链接（由市场处理登录）');
    const newWindow = window.open(url, '_blank', 'noopener,noreferrer');

    if (newWindow) {
      return;
    }

    window.location.href = url;
  } catch (error) {
    console.error('[ModelPayment] 打开市场链接失败:', error);

    const fallbackUrl = appendMarketHandoffHash(marketPlanUrl(plan));
    navigator.clipboard.writeText(fallbackUrl).then(() => {
      alert(`链接已复制到剪贴板（弹窗可能被浏览器拦截）：\n${fallbackUrl}`);
    }).catch(() => {
      alert(`请手动访问：\n${fallbackUrl}`);
    });
  }
}

const rechargeLinks = computed(() => {
  const userId = marketOverview.value?.user?.id;
  const username = marketOverview.value?.user?.username;

  return rechargeAmounts.map((amount) => {
    const params: Record<string, string | number> = {
      recharge: amount,
      source: 'fhd',
    };

    if (userId) {
      params.user_id = userId;
    }
    if (username) {
      params.username = username;
    }

    return {
      amount,
      label: amount < 100 ? '轻量补充' : '高频调用',
      url: appendMarketHandoffHash(withQuery(walletUrl.value, params)),
    };
  });
});

// ========== 离线状态管理函数 ==========

function updateOnlineStatus() {
  isOffline.value = !navigator.onLine;
  
  if (isOffline.value) {
    dataSource.value = cacheTimestamp.value ? 'cache' : 'offline';
  } else {
    // 恢复在线后自动刷新
    if (dataSource.value !== 'network') {
      dataSource.value = 'network';
      refreshMarketOverview().catch(() => {});
      refreshLlmCatalog().catch(() => {});
    }
  }
}

async function retryConnection() {
  console.log('[ModelPayment] User requested retry...');
  
  // 尝试简单的网络请求检测连接
  try {
    const response = await fetch('/api/health', { 
      method: 'GET',
      cache: 'no-store',
      signal: AbortSignal.timeout(5000)
    });
    
    if (response.ok) {
      isOffline.value = false;
      dataSource.value = 'network';
      
      // 刷新数据
      await forceRefreshAll();
      alert('网络已恢复！数据已更新。');
    } else {
      throw new Error(`HTTP ${response.status}`);
    }
  } catch (error) {
    isOffline.value = true;
    alert('仍然无法连接到服务器。请检查您的网络连接。');
  }
}

function setupOnlineListeners() {
  window.addEventListener('online', updateOnlineStatus);
  window.addEventListener('offline', updateOnlineStatus);

  // 监听Service Worker状态
  unsubSW = swManager.onChange((status) => {
    isOffline.value = status.offline;
    
    // 如果SW报告离线但浏览器认为在线，以SW为准（更准确）
    if (status.offline && navigator.onLine) {
      console.warn('[ModelPayment] SW reports offline but browser says online');
      isOffline.value = true;
    }
  });
}

function cleanupOnlineListeners() {
  window.removeEventListener('online', updateOnlineStatus);
  window.removeEventListener('offline', updateOnlineStatus);
  
  if (unsubSW) {
    unsubSW();
    unsubSW = null;
  }
}

onMounted(async () => {
  // 0. 初始化离线状态监听
  setupOnlineListeners();
  updateOnlineStatus();

  // 1. 立即从缓存恢复数据（秒开体验）
  const hasCache = restoreFromCache();
  if (hasCache) {
    console.log('[ModelPayment] 从缓存恢复数据');
    
    // 如果离线，标记数据来源为缓存
    if (isOffline.value) {
      dataSource.value = 'cache';
      cacheTimestamp.value = lastSyncTime.value;
    }
  }

  // 1b. 会话内有修茈 JWT 时优先覆盖本地旧 token，避免模型页读到另一个市场账号的缓存余额。
  if (!isOffline.value) {
    try {
      const handoff = await fetchSessionMarketHandoff();
      const mt = handoff?.token?.trim();
      if (mt) {
        hasSessionMarketToken.value = true;
        const changed = applyMarketToken(mt);
        if (changed) {
          console.log('[ModelPayment] 市场 token 已随当前会话更新，已清理旧账号缓存');
        }
      } else {
        hasSessionMarketToken.value = false;
      }
    } catch {
      hasSessionMarketToken.value = false;
      /* 静默：无会话映射或非登录态属正常 */
    }
  }

  // 2. 后台静默刷新（不阻塞UI）
  if (!isOffline.value) {
    refreshMarketOverview(undefined, true).catch(() => {});
    refreshLlmCatalog().catch(() => {});
  }
});

onUnmounted(() => {
  cleanupOnlineListeners();
});
</script>

<style scoped>
/* ========== 状态提示条（专业简洁设计）========== */
.mp-status-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  margin-bottom: 14px;
  border-radius: 6px;
  font-size: 0.875rem;
  line-height: 1.4;
}

.mp-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.mp-status-text {
  flex: 1;
  color: inherit;
}

.mp-status-btn {
  padding: 5px 14px;
  background: transparent;
  border: 1px solid currentColor;
  border-radius: 4px;
  color: inherit;
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.15s;
  white-space: nowrap;
}

.mp-status-btn:hover {
  opacity: 0.75;
}

/* 离线状态 */
.mp-status-banner--offline {
  background: #fefce8;
  border: 1px solid #eab308;
  color: #854d0e;
}

.mp-status-banner--offline .mp-status-dot {
  background: #eab308;
}

/* 缓存状态 */
.mp-status-banner--cached {
  background: #f5f5f5;
  border: 1px solid #d4d4d4;
  color: #525252;
}

.mp-status-banner--cached .mp-status-dot {
  background: #a3a3a3;
}

.mp-root .page-content {
  max-width: 1200px;
}

.mp-hero {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px 16px;
  margin-bottom: 8px;
}

.mp-hero-text h2 {
  letter-spacing: -0.02em;
}

.mp-hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.mp-hero-btn {
  display: inline-flex;
  align-items: center;
  padding: 8px 14px;
  border-radius: 8px;
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: #fff;
  color: #1e293b;
  font-size: 0.8125rem;
  font-weight: 600;
  text-decoration: none;
  cursor: pointer;
}

.mp-hero-btn--primary {
  background: #2563eb;
  border-color: #2563eb;
  color: #fff;
}

.mp-hero-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.mp-sync-warning {
  margin: 0 0 12px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #fff7ed;
  border: 1px solid #fdba74;
  color: #9a3412;
  font-size: 0.8125rem;
  line-height: 1.5;
}

.mp-fold {
  margin-bottom: 12px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 12px;
  background: #fff;
  padding: 0 14px 14px;
}

.mp-fold-title {
  cursor: pointer;
  font-weight: 600;
  font-size: 0.9375rem;
  padding: 14px 0;
  list-style: none;
  display: flex;
  align-items: center;
  gap: 8px;
}

.mp-fold-title::-webkit-details-marker {
  display: none;
}

.mp-fold-badge {
  font-size: 0.75rem;
  font-weight: 500;
  color: #64748b;
}

.mp-recharge-grid--compact {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.mp-plans--compact .mp-plan {
  padding: 14px;
}

.mp-llm-grid--scroll {
  max-height: 280px;
  overflow-y: auto;
}

.header-sub {
  margin: 0.35rem 0 0;
  max-width: 40rem;
  line-height: 1.55;
  font-size: 0.95rem;
}

.header-sub a {
  color: #2563eb;
  font-weight: 600;
  text-decoration: none;
}

.header-sub a:hover {
  text-decoration: underline;
}

.mp-balance-link {
  margin-left: 10px;
  font-size: 0.75rem;
  font-weight: 600;
  color: #2563eb;
  text-decoration: none;
  white-space: nowrap;
}

.mp-balance-link:hover {
  text-decoration: underline;
}

.mp-balance-link i {
  margin-left: 4px;
  font-size: 0.7rem;
}

.mp-panel {
  border-radius: 16px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  margin-bottom: 1.25rem;
}

.mp-panel-head {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 14px;
}

.mp-panel-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2.25rem;
  height: 2.25rem;
  border-radius: 12px;
  background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%);
  color: #475569;
  font-size: 0.85rem;
  flex-shrink: 0;
}

.mp-panel-title {
  margin: 0 0 4px;
  font-size: 1rem;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.mp-panel-desc {
  margin: 0;
  font-size: 0.875rem;
}

.mp-balance .mp-panel-head {
  align-items: center;
  margin-bottom: 0;
  gap: 14px;
}

.mp-balance .mp-panel-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 10px;
}

.mp-balance-text {
  flex: 1 1 auto;
  min-width: 0;
}

.mp-balance-icon {
  background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
  color: #1d4ed8;
  font-size: 1.05rem;
  font-weight: 800;
}

.mp-balance-amount {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  flex-shrink: 0;
  padding: 10px 16px;
  border-radius: 14px;
  background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
  border: 1px solid rgba(59, 130, 246, 0.22);
}

.mp-balance-currency {
  font-size: 0.95rem;
  font-weight: 700;
  color: #1d4ed8;
  align-self: flex-start;
  margin-top: 0.35em;
}

.mp-balance-num {
  font-size: 1.75rem;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}

.mp-balance-unit {
  font-size: 0.6rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: #64748b;
  text-transform: uppercase;
  margin-left: 4px;
}

.mp-market-quota {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px dashed rgba(15, 23, 42, 0.12);
}

.mp-market-quota > div {
  padding: 10px 12px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid rgba(15, 23, 42, 0.06);
}

.mp-market-quota span {
  display: block;
  margin-bottom: 4px;
  font-size: 0.72rem;
  color: #64748b;
}

.mp-market-quota strong {
  color: #0f172a;
  font-size: 0.92rem;
}

.mp-market-empty {
  margin: 12px 0 0;
  padding-top: 12px;
  border-top: 1px dashed rgba(15, 23, 42, 0.12);
  font-size: 0.82rem;
}

@media (max-width: 560px) {
  .mp-balance .mp-panel-head {
    flex-wrap: wrap;
  }
  .mp-balance-amount {
    width: 100%;
    justify-content: flex-end;
  }
}

.mp-plans-section {
  margin-top: 0.5rem;
}

.mp-section-kicker {
  margin: 0 0 4px;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #64748b;
}

.mp-section-lead {
  margin: 0 0 1.25rem;
  font-size: 0.875rem;
}

.mp-section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 1.1rem;
}

.mp-section-head .mp-section-lead {
  margin-bottom: 0;
}

.mp-refresh-btn {
  min-height: 38px;
  flex-shrink: 0;
  padding: 0 14px;
  border-radius: 12px;
  border: 1px solid rgba(37, 99, 235, 0.26);
  color: #1d4ed8;
  background: linear-gradient(180deg, #eff6ff 0%, #dbeafe 100%);
  font-weight: 700;
  cursor: pointer;
}

.mp-refresh-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.mp-plans {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr));
  gap: 1.25rem;
}

.mp-plan {
  --accent: #059669;
  --accent-2: #10b981;
  --accent-soft: #ecfdf5;
  --ring: rgba(5, 150, 105, 0.35);

  position: relative;
  cursor: pointer;
  text-align: left;
  border-radius: 20px;
  padding: 1.35rem 1.4rem 1.25rem;
  background: linear-gradient(165deg, #ffffff 0%, #f8fafc 55%, #f1f5f9 100%);
  border: 1px solid rgba(15, 23, 42, 0.09);
  box-shadow:
    0 1px 2px rgba(15, 23, 42, 0.04),
    0 12px 32px -12px rgba(15, 23, 42, 0.14);
  transition:
    transform 0.22s cubic-bezier(0.22, 1, 0.36, 1),
    box-shadow 0.22s ease,
    border-color 0.2s ease;
  outline: none;
}

.mp-plan:hover {
  transform: translateY(-3px);
  box-shadow:
    0 2px 4px rgba(15, 23, 42, 0.06),
    0 20px 40px -16px rgba(15, 23, 42, 0.18);
}

.mp-plan:focus-visible {
  box-shadow:
    0 0 0 3px #fff,
    0 0 0 6px var(--ring),
    0 12px 32px -12px rgba(15, 23, 42, 0.14);
}

.mp-plan.is-selected {
  border-color: var(--ring);
  box-shadow:
    0 0 0 1px var(--ring),
    0 16px 36px -14px rgba(15, 23, 42, 0.2);
}

.mp-plan--t1 {
  --accent: #4f46e5;
  --accent-2: #6366f1;
  --accent-soft: #eef2ff;
  --ring: rgba(79, 70, 229, 0.4);
}

.mp-plan--t2 {
  --accent: #0e7490;
  --accent-2: #06b6d4;
  --accent-soft: #ecfeff;
  --ring: rgba(14, 116, 144, 0.38);
}

.mp-llm-section {
  margin-top: 1.6rem;
}

.mp-llm-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 142px), 1fr));
  gap: 12px;
}

.mp-llm-tile {
  display: grid;
  justify-items: center;
  gap: 8px;
  min-height: 112px;
  padding: 14px 10px;
  border-radius: 16px;
  background: linear-gradient(160deg, #ffffff 0%, #f8fafc 100%);
  border: 1px solid rgba(15, 23, 42, 0.08);
  box-shadow: 0 10px 26px -20px rgba(15, 23, 42, 0.28);
  text-align: center;
}

.mp-llm-tile--warn {
  border-color: rgba(245, 158, 11, 0.32);
  background: linear-gradient(160deg, #fff 0%, #fffbeb 100%);
}

.mp-llm-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 12px;
  color: #1e40af;
  background: linear-gradient(135deg, #eff6ff, #dbeafe);
  border: 1px solid rgba(59, 130, 246, 0.18);
  font-size: 0.74rem;
  font-weight: 900;
}

.mp-llm-tile strong {
  max-width: 100%;
  color: #0f172a;
  font-size: 0.86rem;
  line-height: 1.25;
  word-break: break-word;
}

.mp-llm-tile small {
  color: #64748b;
  font-size: 0.72rem;
}

.mp-loading,
.mp-sync-message {
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.7);
  border: 1px dashed rgba(15, 23, 42, 0.12);
  font-size: 0.84rem;
}

.mp-sync-message {
  margin: 0 0 12px;
  color: #b45309;
  background: #fffbeb;
  border-color: rgba(245, 158, 11, 0.22);
}

.mp-plan-topbar {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 4px;
  border-radius: 20px 20px 0 0;
  background: linear-gradient(90deg, var(--accent), var(--accent-2));
  opacity: 0.95;
}

.mp-plan-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-top: 6px;
}

.mp-plan-title {
  margin: 0;
  font-size: 1.125rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: #0f172a;
  line-height: 1.35;
}

.mp-badge {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 5px 10px;
  border-radius: 999px;
  background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
  color: #92400e;
  border: 1px solid rgba(245, 158, 11, 0.35);
}

.mp-plan-head-tags {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.mp-desc {
  margin: 10px 0 1.1rem;
  font-size: 0.8125rem;
  line-height: 1.55;
  color: #64748b;
  min-height: 2.6em;
}

.mp-feature-list {
  display: grid;
  gap: 6px;
  margin: 0 0 1.15rem;
  padding: 0;
  list-style: none;
  color: #334155;
  font-size: 0.8rem;
  line-height: 1.45;
}

.mp-feature-list li {
  position: relative;
  padding-left: 18px;
}

.mp-feature-list li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0.6em;
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--accent);
  transform: translateY(-50%);
}

.mp-price-block {
  display: flex;
  align-items: baseline;
  gap: 4px 8px;
  flex-wrap: wrap;
  margin-bottom: 1.15rem;
  padding: 12px 14px;
  border-radius: 14px;
  background: var(--accent-soft);
  border: 1px solid rgba(15, 23, 42, 0.07);
}

.mp-price-currency {
  font-size: 1rem;
  font-weight: 700;
  color: var(--accent);
  align-self: flex-start;
  margin-top: 0.35em;
}

.mp-price-num {
  font-size: 2rem;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}

.mp-price-unit {
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: #94a3b8;
  text-transform: uppercase;
  margin-left: 2px;
}

.mp-actions {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
}

.mp-pay {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 44px;
  padding: 0 12px;
  border-radius: 12px;
  border: none;
  font-size: 0.8125rem;
  font-weight: 700;
  cursor: pointer;
  transition:
    transform 0.15s ease,
    box-shadow 0.15s ease,
    filter 0.15s ease;
}

.mp-pay:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
  filter: grayscale(0.2);
}

.mp-pay:not(:disabled):hover {
  transform: translateY(-1px);
}

.mp-pay:not(:disabled):active {
  transform: translateY(0);
}

.mp-pay--full {
  width: 100%;
}

.mp-pay--ali {
  color: #1e40af;
  background: linear-gradient(180deg, #eff6ff 0%, #dbeafe 100%);
  box-shadow: 0 1px 0 rgba(255, 255, 255, 0.75) inset, 0 2px 8px rgba(37, 99, 235, 0.18);
  border: 1px solid rgba(59, 130, 246, 0.45);
}

.mp-pay--ali:not(:disabled):hover {
  box-shadow: 0 1px 0 rgba(255, 255, 255, 0.85) inset, 0 6px 16px rgba(37, 99, 235, 0.25);
}

.mp-pay-ico-ali {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.15rem;
  height: 1.15rem;
  border-radius: 4px;
  font-size: 0.65rem;
  font-weight: 900;
  color: #fff;
  background: linear-gradient(135deg, #1677ff 0%, #0958d9 100%);
}

 

.mp-recharge-section {
  margin-top: 1.5rem;
}

.mp-recharge-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 180px), 1fr));
  gap: 0.85rem;
}

.mp-recharge-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 1rem 1.1rem;
  border-radius: 16px;
  text-decoration: none;
  color: #0f172a;
  background: linear-gradient(160deg, #fff 0%, #f8fafc 100%);
  border: 1px solid rgba(15, 23, 42, 0.08);
  box-shadow: 0 10px 28px -18px rgba(15, 23, 42, 0.25);
  transition: transform 0.18s ease, border-color 0.18s ease;
}

.mp-recharge-card:hover {
  transform: translateY(-2px);
  border-color: rgba(37, 99, 235, 0.28);
}

.mp-recharge-card strong {
  font-size: 1.35rem;
  letter-spacing: -0.03em;
}

.mp-recharge-card span {
  color: #64748b;
  font-size: 0.8rem;
}

</style>
