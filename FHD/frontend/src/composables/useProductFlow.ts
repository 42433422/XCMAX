import { ref } from 'vue'
import { readBuildEdition, type HostEdition } from '@/constants/genericModPack'
import {
  markHostPackAcknowledged,
  markProductFlowCompleted,
  isFirstAiTaskPending,
  resolveProductFlowEntryStep,
  readProductFlowCompleted,
  type ProductFlowStepId,
} from '@/constants/productFlow'
import { isShellEditionBuild } from '@/constants/platformShellMode'
import type { DeliverableStatus } from '@/constants/platformShell'
import { fetchDeliverableStatus } from '@/utils/platformShellApi'

const deliverableRef = ref<DeliverableStatus | null>(null)
const deliverableLoading = ref(false)

export function useProductFlow() {
  async function refreshDeliverable(force = false) {
    deliverableLoading.value = true
    try {
      deliverableRef.value = await fetchDeliverableStatus(force)
      if (deliverableRef.value?.deliverable) {
        markHostPackAcknowledged()
      }
      return deliverableRef.value
    } finally {
      deliverableLoading.value = false
    }
  }

  function edition(): HostEdition {
    return readBuildEdition()
  }

  function needsProductFlow(): boolean {
    if (!isShellEditionBuild()) return false
    return !readProductFlowCompleted()
  }

  function resolveEntryStep(queryStep?: unknown): ProductFlowStepId {
    return resolveProductFlowEntryStep(queryStep)
  }

  function completeFlowAndGoChat(router: { replace: (x: { path: string }) => void }) {
    markProductFlowCompleted()
    markHostPackAcknowledged()
    const path = typeof window !== 'undefined' && window.location.pathname.startsWith('/mod/') ? '/' : '/'
    router.replace({ path })
  }

  return {
    deliverable: deliverableRef,
    deliverableLoading,
    refreshDeliverable,
    edition,
    needsProductFlow,
    resolveEntryStep,
    completeFlowAndGoChat,
    markProductFlowCompleted,
    markHostPackAcknowledged,
    readProductFlowCompleted,
  }
}

export function shouldRouteToProductOnboarding(toName: string | symbol | null | undefined): boolean {
  const name = String(toName || '')
  if (
    name === 'product-onboarding' ||
    name === 'login' ||
    name === 'lan-gate' ||
    name === 'settings' ||
    name === 'mod-store' ||
    name === 'im' ||
    name === 'desktop-runtime' ||
    name === 'workflow-employee-space' ||
    name === 'workflow-employee-stitch-full'
  ) {
    return false
  }
  return needsProductFlowStatic()
}

function needsProductFlowStatic(): boolean {
  if (!isShellEditionBuild()) return false
  // The first-order prompt must be allowed to enter chat before its bound run can
  // produce completion evidence. Pending is not the same as completed.
  if (isFirstAiTaskPending()) return false
  return !readProductFlowCompleted()
}
