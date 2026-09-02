import type { ApprovalRequest, ApprovalWorkflowExecution } from '@/api/approval'

/**
 * 拆分自 ApprovalWorkspaceView.vue 脚本的纯工具函数
 * （原第 293–297、322–325、409–423、556–602 行）；逻辑逐字迁移，行为不变。
 */

export const FINAL_STATUSES = ['approved', 'rejected', 'withdrawn', 'cancelled'] as const

export const isFinalStatus = (status: string) =>
  (FINAL_STATUSES as readonly string[]).includes(status)

export const isPendingAiWorkflowApproval = (request?: ApprovalRequest | null) =>
  request?.business_type === 'workflow_tool' &&
  !isFinalStatus(request.status) &&
  !request.current_node_id

export const getWorkflowExecutionStatusLabel = (execution?: ApprovalWorkflowExecution) => {
  if (!execution) return ''
  if (!execution.workflow_executed) return '未触发执行'
  if (execution.success === true) return '执行完成'
  if (execution.success === false) return '执行失败'
  return '已触发执行'
}

export const buildWorkflowExecutionAlert = (execution?: ApprovalWorkflowExecution) => {
  if (!execution) return ''
  const status = getWorkflowExecutionStatusLabel(execution)
  const nodes = `${execution.nodes_executed || 0}/${execution.nodes_total || 0}`
  const message = execution.message ? `，${execution.message}` : ''
  return `\nAI 工作流：${status}（节点 ${nodes}）${message}`
}

// 工具函数
export const getBusinessIcon = (type: string) => {
  const icons: Record<string, string> = {
    shipment: 'fa-truck',
    purchase: 'fa-shopping-cart',
    expense: 'fa-money',
    contract: 'fa-file-text'
  }
  return `fa ${icons[type] || 'fa-file'}`
}

export const getBusinessLabel = (type: string) => {
  const labels: Record<string, string> = {
    shipment: '出货单',
    purchase: '采购',
    expense: '费用',
    contract: '合同'
  }
  return labels[type] || type
}

export const getStatusLabel = (status: string) => {
  const labels: Record<string, string> = {
    pending: '待审批',
    in_progress: '审批中',
    approved: '已通过',
    rejected: '已拒绝',
    withdrawn: '已撤回'
  }
  return labels[status] || status
}

export const getActionIcon = (action: string) => {
  const icons: Record<string, string> = {
    approve: 'fa-check',
    reject: 'fa-times',
    transfer: 'fa-exchange',
    withdraw: 'fa-undo'
  }
  return `fa ${icons[action] || 'fa-info'}`
}

export const formatTime = (isoString: string) => {
  if (!isoString) return ''
  const date = new Date(isoString)
  return date.toLocaleString('zh-CN')
}
