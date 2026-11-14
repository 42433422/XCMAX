/**
 * 拆分自 ApprovalRulesView.vue 脚本的纯工具函数与标签映射
 * （原第 156–183 行）；逻辑逐字迁移，行为不变。
 */

export const toolLabels = {
  shipment_generate: '发货单生成',
  print: '打印操作',
  products: '产品管理',
  customers: '客户管理'
}

export const actionLabels = {
  execute: '执行',
  create: '创建',
  update: '更新',
  delete: '删除'
}

export const getActionLabel = (tool_id, action) => {
  return `${toolLabels[tool_id] || tool_id} - ${actionLabels[action] || action}`
}

export const getTriggerLabel = (trigger) => {
  const labels = { always: '始终', conditional: '条件', never: '从不' }
  return labels[trigger] || trigger
}

export const formatTime = (isoString) => {
  if (!isoString) return ''
  const date = new Date(isoString)
  return date.toLocaleString('zh-CN')
}
