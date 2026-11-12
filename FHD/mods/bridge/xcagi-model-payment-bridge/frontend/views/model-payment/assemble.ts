import { onMounted, onUnmounted } from 'vue';
import { fetchSessionMarketHandoff } from '@/api/marketAccount';
import { useMpOffline } from './useMpOffline'
import { useMpMarketData } from './useMpMarketData'
import { useMpCatalog } from './useMpCatalog'
import { useMpMembershipPlans } from './useMpMembershipPlans'
import { useMpHandoff } from './mpHandoff'
import { useMpMarketActions } from './useMpMarketActions'
import {
  providerInitials, providerModelCount, providerState,
} from './useMpCatalog'

/**
 * 组装模型服务视图全部状态与动作；子组件通过单一 ctx prop 共享，
 * 逻辑自 ModelPaymentView.vue 逐字迁移，行为不变。
 */
export function assembleMpModelPayment() {
  const offline = useMpOffline({
    refreshOverview: () => marketData.refreshMarketOverview(),
    refreshCatalog: () => marketData.refreshLlmCatalog(),
    forceRefreshAll: () => marketData.forceRefreshAll(),
  })
  const marketData = useMpMarketData({ isOffline: offline.isOffline, dataSource: offline.dataSource })
  const handoff = useMpHandoff()
  const catalog = useMpCatalog(marketData.llmCatalog)
  const plans = useMpMembershipPlans()
  const actions = useMpMarketActions({
    marketPlanUrl: handoff.marketPlanUrl,
    forceRefreshAll: marketData.forceRefreshAll,
  })

  onMounted(async () => {
    // 0. 初始化离线状态监听
    offline.setupOnlineListeners();
    offline.updateOnlineStatus();

    // 0b. 会员套餐改从后端代理市场接口读取（失败保底 FALLBACK_PLANS）
    void plans.loadMembershipPlans();

    // 1. 立即从缓存恢复数据（秒开体验）
    const hasCache = marketData.restoreFromCache();
    if (hasCache) {
      console.log('[ModelPayment] 从缓存恢复数据');

      // 如果离线，标记数据来源为缓存
      if (offline.isOffline.value) {
        offline.dataSource.value = 'cache';
        offline.cacheTimestamp.value = marketData.lastSyncTime.value;
      }
    }

    // 1b. 会话内有修茈 JWT 时优先覆盖本地旧 token，避免模型页读到另一个市场账号的缓存余额。
    if (!offline.isOffline.value) {
      try {
        const handoffData = await fetchSessionMarketHandoff();
        const mt = handoffData?.token?.trim();
        if (mt) {
          marketData.hasSessionMarketToken.value = true;
          const changed = marketData.applyMarketToken(mt);
          if (changed) {
            console.log('[ModelPayment] 市场 token 已随当前会话更新，已清理旧账号缓存');
          }
        } else {
          marketData.hasSessionMarketToken.value = false;
        }
      } catch {
        marketData.hasSessionMarketToken.value = false;
        /* 静默：无会话映射或非登录态属正常 */
      }
    }

    // 2. 后台静默刷新（不阻塞UI）
    if (!offline.isOffline.value) {
      marketData.refreshMarketOverview(undefined, true).catch(() => {});
      marketData.refreshLlmCatalog().catch(() => {});
    }
  });

  onUnmounted(() => {
    offline.cleanupOnlineListeners();
  });

  return {
    ...offline,
    ...marketData,
    ...handoff,
    ...catalog,
    ...plans,
    ...actions,
    providerInitials,
    providerModelCount,
    providerState,
  }
}

export type ModelPaymentCtx = ReturnType<typeof assembleMpModelPayment>
