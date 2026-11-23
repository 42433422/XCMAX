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
  const fulfillment = payload && isRecord(payload.fulfillment) ? payload.fulfillment : null
  const explicitQuantities = fulfillment?.line_quantities
  const deliveryQuantities = fulfillment?.requested === true
    ? Array.isArray(explicitQuantities)
      ? items.map((_, index) => decimal(explicitQuantities[index]) ? explicitQuantities[index] : null)
      : items.map(item => item.quantity)
    : null
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
  const receipt = payload && isRecord(payload.payment_allocation) ? payload.payment_allocation : null
  const receiptAmount = receipt?.requested === true && decimal(receipt.amount) ? String(receipt.amount) : null
  const customerName = termSource.customer_name
  const currency = termSource.currency
  const operation = data.action === 'quote' ? '创建销售报价'
    : data.action === 'execute_closed_loop' ? '销售闭环' : '创建销售订单'
  return {
    operation,
    customer: typeof customerName === 'string' && customerName.trim() ? customerName : '未填写', items, deliveryQuantities, amount, receiptAmount,
    currency: currency === undefined ? 'CNY' : typeof currency === 'string' ? currency : '币种待确认',
  }
}

export const isFinalStatus = (status: string) =>
  (FINAL_STATUSES as readonly string[]).includes(status)

export const isPendingAiWorkflowApproval = (request?: ApprovalRequest | null) =>
  request?.business_type === 'workflow_tool' &&
  !isFinalStatus(request.status) &&
  !request.current_node_id

/** 列表行执行状态徽标；无执行记录时返回 null，不占位。 */
export const getExecutionBadge = (execution?: ApprovalWorkflowExecution) => {
  if (!execution) return null
  if (execution.requires_reconciliation || execution.code === 'outcome_unknown' || execution.execution_state === 'unknown') return { label: '结果待核对', tone: 'warn' }
  const state = execution.execution_state || execution.code || (execution.execution_accepted ? 'queued' : '')
  const pending: Record<string, string> = { queued: '等待执行', pending: '等待执行', planning: '规划中', running: '执行中', retrying: '恢复中', paused: '已暂停', blocked: '执行受阻', waiting_user: '等待补充信息', waiting_input: '等待补充信息', waiting_auth: '等待授权', waiting_approval: '等待后续审批', waiting_user_decision: '等待确认' }
  if (!execution.workflow_executed && pending[state]) return { label: pending[state], tone: 'running' }
  if (!execution.workflow_executed) return { label: '未触发执行', tone: 'muted' }
  if (execution.success === true) return { label: '执行完成', tone: 'ok' }
  if (execution.success === false) return { label: '执行失败', tone: 'fail' }
  return { label: '执行中', tone: 'running' }
}

export const getWorkflowExecutionStatusLabel = (execution?: ApprovalWorkflowExecution) => getExecutionBadge(execution)?.label || ''

export const isWorkflowExecutionRunning = (execution?: ApprovalWorkflowExecution) => !!execution &&
  !execution.workflow_executed && !execution.requires_reconciliation && execution.code !== 'outcome_unknown' &&
  ['queued', 'pending', 'planning', 'running', 'retrying'].includes(execution.execution_state || execution.code || (execution.execution_accepted ? 'queued' : ''))

export const getStatusTone = (status: string) =>
  status === 'approved' ? 'ok'
    : status === 'rejected' ? 'fail'
      : status === 'pending' ? 'warn'
        : status === 'in_progress' ? 'info' : 'muted'

export const getApplicantLabel = (request: ApprovalRequest) =>
  request.applicant_id ? `发起人 #${request.applicant_id}` : '发起人未知'

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
    contract: 'fa-file-text',
    workflow_tool: 'fa-bolt'
  }
  return `fa ${icons[type] || 'fa-file-o'}`
}

export const getBusinessLabel = (type: string) => {
  const labels: Record<string, string> = {
    shipment: '出货单',
    purchase: '采购',
    expense: '费用',
    contract: '合同',
    workflow_tool: 'AI 对话操作'
  }
  return labels[type] || type
}

export const getStatusLabel = (status: string) => {
  const labels: Record<string, string> = {
    pending: '待审批',
    in_progress: '审批中',
    approved: '已通过',
    rejected: '已拒绝',
    withdrawn: '已撤回',
    cancelled: '已取消',
    expired: '已失效',
    draft: '草稿',
    completed: '已完成'
  }
  return labels[status] || status
}

/** AI 自动提交的审批标题形如「智能对话写操作：elt_import.preview」，展示时转成中文业务动作。 */
const AI_TITLE_PREFIX = '智能对话写操作：'
const TOOL_LABELS: Record<string, string> = {
  elt_import: '数据导入',
  dataset_rag: '知识库',
  document_template: '模板库',
  business_db: '业务数据',
  sales: '销售',
  customers: '客户',
  orders: '订单',
  tickets: '工单',
  im: '客服会话',
  workflow: '工作流'
}
const ACTION_LABELS: Record<string, string> = {
  preview: '预演',
  execute: '执行',
  query: '查询',
  search: '检索',
  clear: '清理',
  clear_dataset: '清理',
  create_order: '创建销售订单',
  quote: '创建销售报价',
  execute_closed_loop: '销售闭环',
  ingest: '导入',
  auto_ingest: '批量导入',
  withdraw_auto_ingest: '撤回批量导入',
  withdraw: '撤回',
  write: '写入',
  update: '更新',
  delete: '删除',
  create: '创建',
  submit: '提交',
  upload: '上传',
  export: '导出',
  diff_versions: '版本对比'
}

export function formatRequestTitle(request?: ApprovalRequest | null) {
  const title = String(request?.title || '').trim()
  if (!request || !title.startsWith(AI_TITLE_PREFIX)) return title
  const data = request.business_data || {}
  const suffix = title.slice(AI_TITLE_PREFIX.length).trim()
  const [parsedTool, parsedAction] = suffix.split('.')
  const tool = String(data.tool_id || parsedTool || '')
  const action = String(data.action || parsedAction || '')
  const toolLabel = TOOL_LABELS[tool]
  const actionLabel = ACTION_LABELS[action]
  if (!toolLabel && !actionLabel) return title
  return [toolLabel || tool, actionLabel || action].filter(Boolean).join(' · ')
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
