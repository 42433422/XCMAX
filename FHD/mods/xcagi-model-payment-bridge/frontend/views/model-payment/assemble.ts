import { onMounted, onUnmounted } from 'vue';
import { fetchSessionMarketHandoff, persistMarketTokensFromHandoff } from '@/api/marketAccount';
import { captureAuthSession } from '@/utils/authSessionCache';
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
  const handoffController = new AbortController()
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

  onMounted(() => {
    const sessionCurrent = captureAuthSession()
    const current = () => sessionCurrent() && !handoffController.signal.aborted
    offline.setupOnlineListeners();
    offline.updateOnlineStatus();
    void plans.loadMembershipPlans();
    if (marketData.restoreFromCache() && offline.isOffline.value) {
      offline.dataSource.value = 'cache';
      offline.cacheTimestamp.value = marketData.lastSyncTime.value;
    }
    if (offline.isOffline.value) return
    // Session handoff waits on market entitlement sync. Paint and the wallet read do not.
    void marketData.refreshMarketOverview(undefined, true, true)
    void marketData.refreshLlmCatalog()
    void (async () => {
      try {
        const handoffData = await fetchSessionMarketHandoff({ signal: handoffController.signal });
        if (!current()) return;
        const mt = handoffData?.token?.trim();
        if (mt && persistMarketTokensFromHandoff(handoffData)) {
          marketData.hasSessionMarketToken.value = true;
          if (marketData.applyMarketToken(mt)) {
            void marketData.refreshMarketOverview(undefined, true, true)
            void marketData.refreshLlmCatalog(undefined, true)
          }
        } else {
          marketData.hasSessionMarketToken.value = false;
        }
      } catch {
        if (current()) marketData.hasSessionMarketToken.value = false;
      }
    })()
  });

  onUnmounted(() => {
    handoffController.abort()
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
