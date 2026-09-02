import { computed } from 'vue';
import type { Ref } from 'vue';
import {
  LS_MARKET_ACCESS_TOKEN,
  type MarketAccountOverviewData,
} from '@/api/marketAccount';
import type { MarketMembershipPlan } from './useMpMembershipPlans';

/** 市场站点地址与跳转 URL 组装（拆分自 ModelPaymentView.vue，逻辑不变） */

export const marketBase = String(
  import.meta.env.VITE_MARKET_BASE || 'https://xiu-ci.com',
).replace(/\/$/, '');
export const plansUrlBase = String(
  import.meta.env.VITE_MARKET_PLANS_URL || `${marketBase}/plans`,
).replace(/\/$/, '');
export const walletUrlBase = String(
  import.meta.env.VITE_MARKET_WALLET_URL || `${marketBase}/wallet`,
).replace(/\/$/, '');

export function withQuery(base: string, params: Record<string, string | number>): string {
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

export function useMpHandoff(
  marketOverview: Ref<MarketAccountOverviewData | null>,
  marketToken: Ref<string>,
) {
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

  const rechargeAmounts = [10, 30, 100, 300];

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

  return {
    plansUrl,
    walletUrl,
    plansUrlHandoff,
    walletUrlHandoff,
    appendMarketHandoffHash,
    marketPlanUrl,
    rechargeLinks,
  };
}
