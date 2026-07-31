import { computed, ref, type Ref } from 'vue'
import { fetchDeliverableStatus } from '@/utils/platformShellApi'
import type { DeliverableStatus } from '@/constants/platformShell'

export function useHostFoundationStatus<T extends { id?: unknown }>(
  mods: Ref<T[]>,
  expectedBridgeIds: () => readonly string[],
  modelPaymentBridgeId: string,
) {
  const status = ref<DeliverableStatus | null>(null)
  const foundationReady = computed(() => status.value?.host_foundation_bridges_ready === true)
  const modelPaymentBridgeInstalled = computed(() => (
    foundationReady.value
    || mods.value.some((mod) => String(mod.id || '').trim() === modelPaymentBridgeId)
  ))
  const hostBridgeInstalledCount = computed(() => {
    if (foundationReady.value) return expectedBridgeIds().length
    const installedIds = new Set(mods.value.map((mod) => String(mod.id || '').trim()))
    return expectedBridgeIds().filter((id) => installedIds.has(id)).length
  })

  async function refreshHostFoundationStatus() {
    try {
      status.value = await fetchDeliverableStatus(true)
    } catch {
      status.value = null
    }
  }

  return {
    hostBridgeInstalledCount,
    modelPaymentBridgeInstalled,
    refreshHostFoundationStatus,
  }
}
