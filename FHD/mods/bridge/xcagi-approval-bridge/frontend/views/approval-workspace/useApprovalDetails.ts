import { onScopeDispose, ref, watch } from 'vue'
import { approvalApi, type ApprovalRequest } from '@/api/approval'
import { productReadScopeKey } from '@/utils/productReadAccountScope'
import { getAuthSessionEpoch } from '@/utils/authSessionCache'
import { isPendingAiWorkflowApproval, isWorkflowExecutionRunning } from './awHelpers'

export function useApprovalDetails(deps: { getCurrentUserId: () => number }) {
  const showDetails = ref(false)
  const selectedRequest = ref<ApprovalRequest | null>(null)
  const canApprove = ref(false)
  const detailLoading = ref(false)
  const detailError = ref('')
  const accountScope = () => JSON.stringify([getAuthSessionEpoch(), productReadScopeKey('xcagi-approval-bridge')])
  let active = true, generation = 0, timer: ReturnType<typeof setTimeout> | undefined
  const stopPolling = () => { if (timer) clearTimeout(timer); timer = undefined }

  // 查看详情
  const viewDetails = async (requestId: number) => {
    const scope = accountScope(), userId = deps.getCurrentUserId(), request = ++generation
    if (!active || !userId) return
    stopPolling()
    const current = () => active && request === generation && scope === accountScope() && userId === deps.getCurrentUserId()
    detailLoading.value = true; detailError.value = ''; canApprove.value = false
    try {
      const res = await approvalApi.getRequestDetails(requestId)
      if (!current()) return
      if (!res.success || !res.data) throw new Error(res.message || '审批详情暂时无法读取，请刷新。')
      const record = res.data as ApprovalRequest
      if (record.id !== requestId) throw new Error('审批详情与原请求不一致，请刷新核对。')
      selectedRequest.value = record
      showDetails.value = true
      canApprove.value = ['pending', 'in_progress'].includes(record.status) && record.runtime_available !== false &&
        !record.workflow_execution?.execution_accepted && !record.workflow_execution?.requires_reconciliation &&
        record.workflow_execution?.code !== 'outcome_unknown' &&
        (record.current_approvers?.includes(userId) || isPendingAiWorkflowApproval(record))
      if (isWorkflowExecutionRunning(record.workflow_execution)) timer = setTimeout(() => { void viewDetails(requestId) }, 2000)
    } catch (error) {
      if (current()) { detailError.value = error instanceof Error ? error.message : '审批详情读取失败，请刷新。'; showDetails.value = true }
    } finally { if (current()) detailLoading.value = false }
  }

  const closeDetails = () => {
    generation++; stopPolling()
    showDetails.value = false
    selectedRequest.value = null
    canApprove.value = false
    detailLoading.value = false; detailError.value = ''
  }
  watch(accountScope, closeDetails, { flush: 'sync' })
  onScopeDispose(() => { active = false; closeDetails() })

  return { showDetails, selectedRequest, canApprove, detailLoading, detailError, viewDetails, closeDetails }
}
