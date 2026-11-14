import { ref } from 'vue'
import type { Ref } from 'vue'
import { getUnifiedLedger, type UnifiedLedgerEntry } from '@/api/financeLedger'

/**
 * 客户财务台账（到款/开票）状态簇。仅依赖 selectedUserId。
 */
export function useFinanceLedger(selectedUserId: Ref<number | null>) {
  const financeLedgerItems = ref<UnifiedLedgerEntry[]>([])
  const financeLedgerLoading = ref(false)

  async function loadFinanceLedger() {
    if (!selectedUserId.value) {
      financeLedgerItems.value = []
      return
    }
    financeLedgerLoading.value = true
    try {
      const res = await getUnifiedLedger({
        market_user_id: selectedUserId.value,
        limit: 50,
      })
      financeLedgerItems.value = res.items || []
    } catch {
      financeLedgerItems.value = []
    } finally {
      financeLedgerLoading.value = false
    }
  }

  return { financeLedgerItems, financeLedgerLoading, loadFinanceLedger }
}