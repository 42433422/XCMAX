import { onMounted } from 'vue'
import { useApprovalData } from './useApprovalData'
import { useApprovalDetails } from './useApprovalDetails'
import { useApprovalActions } from './useApprovalActions'
import {
  isFinalStatus, getBusinessIcon, getBusinessLabel, getStatusLabel, getActionIcon, formatTime,
  formatRequestTitle, getWorkflowExecutionStatusLabel,
} from './awHelpers'

export function assembleApprovalWorkspace() {
  const details = useApprovalDetails({ getCurrentUserId: () => data.getCurrentUserId() })
  const data = useApprovalData({ viewDetails: (id) => details.viewDetails(id), closeDetails: details.closeDetails })
  const actions = useApprovalActions({
    getCurrentUserId: () => data.getCurrentUserId(),
    loadData: data.loadData,
    closeDetails: details.closeDetails,
    viewDetails: details.viewDetails,
    initiatedRequests: data.initiatedRequests,
  })

  onMounted(data.reloadAccount)

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
    formatRequestTitle,
    getWorkflowExecutionStatusLabel,
  }
}

export type ApprovalWorkspaceCtx = ReturnType<typeof assembleApprovalWorkspace>
