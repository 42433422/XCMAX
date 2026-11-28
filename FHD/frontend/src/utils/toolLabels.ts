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

const RUNTIME_ACTIVITIES: Record<string, readonly [string, string]> = {
  execute_excel_read: ['阅读你的 Excel 文档', 'Excel 文档读取'],
  execute_excel_structure: ['检查你的 Excel 工作簿结构', '工作簿结构检查'],
  execute_excel_write: ['制作你的 Excel 文档', 'Excel 文档制作'],
  execute_word_read: ['阅读你的 Word 文档', 'Word 文档读取'],
  execute_word_structure: ['检查你的 Word 文档结构', 'Word 文档结构检查'],
  execute_word_write: ['制作你的 Word 文档', 'Word 文档制作'],
  capability_search: ['查找完成任务所需的能力', '任务能力查找'],
  capability_describe: ['核对任务所需的操作', '操作要求核对'],
  execute_action: ['执行你的任务', '任务执行'],
  task_evidence: ['核对任务的执行结果', '执行结果核对'],
  request_input: ['整理需要你确认的信息', '待确认信息整理'],
}

function runtimeActivity(toolId: string, action: string): readonly [string, string] | undefined {
  const name = action.split('__').at(-1) || ''
  const key = toolId === 'excel_analysis' ? `execute_excel_${name}` : name
  return RUNTIME_ACTIVITIES[key] || (toolId === 'xcmax' ? ['处理你的任务', '任务处理'] : undefined)
}

export function toolActivityLabel(toolId: string, action: string, status: string): string | undefined {
  const activity = runtimeActivity(toolId, action)
  if (!activity) return undefined
  const [verb, subject] = activity
  if (status === 'running' || status === 'pending') return `小C正在${verb}`
  if (status === 'success') return `小C已完成${subject}`
  if (status === 'approval') return `小C正在等待你确认${subject}`
  if (status === 'failed') return `小C未能完成${subject}`
  if (status === 'blocked' || status === 'paused') return `小C已暂停${subject}`
  if (status === 'cancelled') return `小C已停止${subject}`
  return `小C正在核对${subject}结果`
}

export function runtimeToolResultStatus(toolId: string, action: string, status: unknown) {
  if (status === 'failed') return 'failed'
  if (status === 'completed' && toolId === 'xcmax' && action === 'capability_search') return 'success'
  return 'waiting'
}

export function toolDisplayName(toolId: string): string {
  const raw = String(toolId || '').trim()
  if (raw === 'xcmax') return '小C助手'
  const match = TOOL_LABELS.find(([pattern]) => pattern.test(raw))
  return match?.[1] || raw.replace(/[_-]+/g, ' ') || '工具'
}

export function actionDisplayName(action: string): string {
  const raw = String(action || '').trim().toLowerCase().split('__').at(-1) || ''
  if (RUNTIME_ACTIVITIES[raw]) return RUNTIME_ACTIVITIES[raw][1]
  return ACTION_LABELS[raw] || raw.replace(/[_-]+/g, ' ') || '执行'
}

export function toolIconClass(toolId: string, action = ''): string {
  const raw = `${toolId} ${action}`
  if (/business[_-]?db|database|sql|customer|product|material|inventory/i.test(raw)) return 'fa-database'
  if (/browser|web/i.test(raw)) return 'fa-globe'
  if (/search|query|find/i.test(raw)) return 'fa-search'
  if (/excel|sheet|table/i.test(raw)) return 'fa-table'
  if (/shell|terminal|command|exec|code/i.test(raw)) return 'fa-terminal'
  if (/file|document|word|pdf/i.test(raw)) return 'fa-file-text-o'
  if (/mail|message|wechat|wecom|send/i.test(raw)) return 'fa-envelope-o'
  if (/approval|approve/i.test(raw)) return 'fa-check-square-o'
  if (/upload|import/i.test(raw)) return 'fa-upload'
  return 'fa-wrench'
}
