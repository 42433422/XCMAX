/**
 * 工具/动作的人类可读标签。
 *
 * 与 AgentRunTrace 共用，避免两套渲染各写一份映射后逐渐漂移。
 */
const TOOL_LABELS: Array<[RegExp, string]> = [
  [/elt|导入/i, '数据对接'],
  [/business[_-]?db|database|sql/i, '业务数据库'],
  [/browser|web/i, '浏览器'],
  [/search/i, '搜索'],
  [/shell|terminal|command|exec/i, '终端'],
  [/file|document|word|pdf/i, '文档'],
  [/excel|sheet/i, '表格'],
  [/mail|message|wechat|wecom/i, '消息'],
  [/approval|approve/i, '审批中心'],
  [/customer/i, '客户资料'],
  [/product|material|inventory/i, '业务资料'],
]

const ACTION_LABELS: Record<string, string> = {
  write: '写入',
  create: '创建',
  update: '更新',
  delete: '删除',
  query: '查询',
  list: '读取列表',
  search: '搜索',
  read: '读取',
  import: '导入',
  export: '导出',
  execute: '执行',
  send: '发送',
  approve: '审批',
}

export function toolDisplayName(toolId: string): string {
  const raw = String(toolId || '').trim()
  const match = TOOL_LABELS.find(([pattern]) => pattern.test(raw))
  return match?.[1] || raw.replace(/[_-]+/g, ' ') || '工具'
}

export function actionDisplayName(action: string): string {
  const raw = String(action || '').trim().toLowerCase()
  return ACTION_LABELS[raw] || raw.replace(/[_-]+/g, ' ') || '执行'
}

export function toolIconClass(toolId: string, action = ''): string {
  const raw = `${toolId} ${action}`
  if (/business[_-]?db|database|sql|customer|product|material|inventory/i.test(raw)) return 'fa-database'
  if (/browser|web/i.test(raw)) return 'fa-globe'
  if (/search|query|find/i.test(raw)) return 'fa-search'
  if (/shell|terminal|command|exec|code/i.test(raw)) return 'fa-terminal'
  if (/excel|sheet|table/i.test(raw)) return 'fa-table'
  if (/file|document|word|pdf/i.test(raw)) return 'fa-file-text-o'
  if (/mail|message|wechat|wecom|send/i.test(raw)) return 'fa-envelope-o'
  if (/approval|approve/i.test(raw)) return 'fa-check-square-o'
  if (/upload|import/i.test(raw)) return 'fa-upload'
  return 'fa-wrench'
}
