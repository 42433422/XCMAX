import type { ApprovalRequest, ApprovalWorkflowExecution } from '@/api/approval'

/** Approval presentation helpers; never mutate or execute the approved payload. */

export const FINAL_STATUSES = ['approved', 'rejected', 'withdrawn', 'cancelled'] as const

/** Display persisted sales terms without changing the approved tool payload. */
const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)

export function salesApprovalPreview(request?: ApprovalRequest | null) {
  const data = request?.business_data
  if (request?.business_type !== 'workflow_tool' || data?.tool_id !== 'sales'
    || !['create_order', 'quote', 'execute_closed_loop'].includes(data.action || '') || !data.params) return null
  const params = data.params
  const payload = isRecord(params.payload) ? params.payload : null
  const order = payload && isRecord(payload.order) ? payload.order : null
  const termSource = order ?? params
  const items = Array.isArray(termSource.items) ? termSource.items.map(item =>
    item && typeof item === 'object' && !Array.isArray(item) ? item as Record<string, unknown> : {}) : []
  const decimal = (value: unknown) => {
    if (typeof value !== 'number' && typeof value !== 'string') return null
    const text = String(value).trim()
    if (text.length > 40 || !/^\d+(?:\.\d+)?$/.test(text)) return null
    const [whole, fraction = ''] = text.split('.')
    return { value: BigInt(whole + fraction), scale: fraction.length }
  }
  const terms = items.map(item => {
    const quantity = decimal(item.quantity), price = decimal(item.unit_price)
    return quantity && quantity.value > 0n && price
      ? { value: quantity.value * price.value, scale: quantity.scale + price.scale } : null
  })
  let amount: string | null = null
  if (terms.length && terms.every(term => term !== null)) {
    const scale = Math.max(...terms.map(term => term!.scale))
    // ES2015 builds lower ** to Math.pow, which rejects BigInt operands.
    const sum = terms.reduce((total, term) => total + term!.value * BigInt('1' + '0'.repeat(scale - term!.scale)), 0n)
    const digits = sum.toString().padStart(scale + 1, '0')
    amount = `${scale ? digits.slice(0, -scale) : digits}.${(scale ? digits.slice(-scale) : '').padEnd(2, '0')}`
  }
  const customerName = termSource.customer_name
  const currency = termSource.currency
  const operation = data.action === 'quote' ? '创建销售报价'
    : data.action === 'execute_closed_loop' ? '销售闭环' : '创建销售订单'
  return {
    operation,
    customer: typeof customerName === 'string' && customerName.trim() ? customerName : '未填写', items, amount,
    currency: currency === undefined ? 'CNY' : typeof currency === 'string' ? currency : '币种待确认',
  }
}

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
