import { onMounted } from 'vue'
import { appAlert } from '@/utils/appDialog'
import { useApprovalData } from './useApprovalData'
import { useApprovalDetails } from './useApprovalDetails'
import { useApprovalActions } from './useApprovalActions'
import {
  isFinalStatus, getBusinessIcon, getBusinessLabel, getStatusLabel, getActionIcon, formatTime,
  getWorkflowExecutionStatusLabel,
} from './awHelpers'

/**
 * 组装审批工作台视图全部状态与动作；子组件通过单一 ctx prop 共享，
 * 逻辑自 ApprovalWorkspaceView.vue 逐字迁移，行为不变。
 */
export function assembleApprovalWorkspace() {
  const details = useApprovalDetails({ getCurrentUserId: () => data.getCurrentUserId() })
  const data = useApprovalData({ viewDetails: (id) => details.viewDetails(id) })
  const actions = useApprovalActions({
    getCurrentUserId: () => data.getCurrentUserId(),
    loadData: data.loadData,
    closeDetails: details.closeDetails,
    initiatedRequests: data.initiatedRequests,
    selectedRequest: details.selectedRequest,
    canApprove: details.canApprove,
    showDetails: details.showDetails,
  })

  onMounted(async () => {
    try {
      await data.resolveCurrentUserId()
      await data.loadData()
    } catch (error) {
      console.error('无法从登录会话解析审批用户:', error)
      await appAlert('登录会话无效，无法打开审批工作台')
    }
  })

  return {
    ...data,
    ...details,
    ...actions,
    // 纯工具函数随 ctx 暴露给模板（原 SFC 脚本内直接可见）
    isFinalStatus,
    getBusinessIcon,
    getBusinessLabel,
    getStatusLabel,
    getActionIcon,
    formatTime,
    getWorkflowExecutionStatusLabel,
  }
}

export type ApprovalWorkspaceCtx = ReturnType<typeof assembleApprovalWorkspace>
