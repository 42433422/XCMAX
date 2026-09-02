import {
  LS_MARKET_ACCESS_TOKEN,
  fetchSessionMarketHandoff,
} from '@/api/marketAccount';
import type { MarketMembershipPlan } from './useMpMembershipPlans';

/** 打开市场购买链接（拆分自 ModelPaymentView.vue，逻辑不变） */

export function useMpMarketActions(deps: {
  marketToken: { value: string };
  hasSessionMarketToken: { value: boolean };
  applyMarketToken: (token: string) => boolean;
  appendMarketHandoffHash: (url: string) => string;
  marketPlanUrl: (plan: MarketMembershipPlan) => string;
  forceRefreshAll: () => Promise<void>;
}) {
  const {
    marketToken, hasSessionMarketToken, applyMarketToken,
    appendMarketHandoffHash, marketPlanUrl, forceRefreshAll,
  } = deps;

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

  return { resolveMarketAccessToken, openMarketPlan };
}
