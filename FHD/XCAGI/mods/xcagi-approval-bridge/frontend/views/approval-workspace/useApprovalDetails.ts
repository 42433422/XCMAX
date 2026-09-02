import { ref } from 'vue'
import { approvalApi, type ApprovalRequest } from '@/api/approval'
import { isPendingAiWorkflowApproval } from './awHelpers'

/**
 * 拆分自 ApprovalWorkspaceView.vue 脚本（原第 312–314、384–407 行）；
 * 逻辑逐字迁移，行为不变。viewDetails 依赖当前用户 ID，经 deps 注入。
 */
export function useApprovalDetails(deps: { getCurrentUserId: () => number }) {
  // 详情弹窗
  const showDetails = ref(false)
  const selectedRequest = ref<ApprovalRequest | null>(null)
  const canApprove = ref(false)

  // 查看详情
  const viewDetails = async (requestId: number) => {
    try {
      const res = await approvalApi.getRequestDetails(requestId)
      if (res.success) {
        const request = res.data as ApprovalRequest
        selectedRequest.value = request
        showDetails.value = true

        // 判断当前用户是否可以审批
        const userId = deps.getCurrentUserId()
        canApprove.value =
          request.current_approvers?.includes(userId) || isPendingAiWorkflowApproval(request)
      }
    } catch (error) {
      console.error('加载详情失败:', error)
    }
  }

  const closeDetails = () => {
    showDetails.value = false
    selectedRequest.value = null
    canApprove.value = false
  }

  return { showDetails, selectedRequest, canApprove, viewDetails, closeDetails }
}
