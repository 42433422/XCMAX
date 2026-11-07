/** Layered work-status copy for the database and knowledge employees. */

const HEADER_LABELS = new Set([
  '产品名称', '商品名称', '货品名称', '品名', '数量', '单价', '金额', '规格', '备注',
  '客户名称', '单据日期', '购买单位', '购货单位', '客户', '型号', '日期', '合计', '总计', '小计',
])
const FAILED = new Set(['failed', 'interrupted', 'outcome_unknown'])

export type WorkbookEmployeeReportModel = {
  employee: 'database' | 'knowledge'
  name: string
  role: string
  outcome: string
  lines: string[]
}

type Entities = { customers: number; purchase_units: number; products: number; records: number }

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' ? value as Record<string, unknown> : null
}

function entitiesOf(business: Record<string, unknown> | null): Entities | null {
  const receipt = record(business?.receipt)
  const details = record(business?.details)
  for (const source of [record(receipt?.entities), record(details?.entities)]) {
    if (!source) continue
    const read = (key: string) => {
      const number = Number(source[key])
      return Number.isFinite(number) && number >= 0 ? number : null
    }
    const customers = read('customers')
    const purchaseUnits = read('purchase_units')
    const products = read('products')
    const records = read('records')
    if (customers === null || purchaseUnits === null || products === null || records === null) continue
    return { customers, purchase_units: purchaseUnits, products, records }
  }
  return null
}

function contentSlice(value: unknown): string {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  if (!text || HEADER_LABELS.has(text)) return ''
  const chars = Array.from(text)
  const slice = chars.slice(0, 42).join('')
  return chars.length > 42 ? `${slice}…` : slice
}

function unfinished(name: string, role: string, employee: WorkbookEmployeeReportModel['employee']): WorkbookEmployeeReportModel {
  return { employee, name, role, outcome: `${name}没有做完。`, lines: ['这一步被跳过或结果不可用。'] }
}

export function workbookEmployeeReports(intake: unknown): WorkbookEmployeeReportModel[] {
  const plan = record(intake)
  if (!plan) return []
  const reports: WorkbookEmployeeReportModel[] = []
  const business = record(plan.business)
  const detection = record(plan.detection)
  const databaseStopped = detection?.degraded === true || business?.skipped === true || FAILED.has(String(business?.status || ''))
  const entities = entitiesOf(business)
  if (databaseStopped) reports.push(unfinished('数据库导入员', '写入业务数据库', 'database'))
  else if (entities) {
    const { customers, purchase_units: units, products, records } = entities
    reports.push({
      employee: 'database',
      name: '数据库导入员',
      role: '写入业务数据库',
      outcome: `本次入库：客户 ${customers}，购买单位 ${units}，产品 ${products}，明细 ${records}。`,
      lines: [`客户 ${customers}`, `购买单位 ${units}`, `产品 ${products}`, `明细 ${records}`],
    })
  }
  const knowledge = record(plan.knowledge)
  const knowledgeKnown = !!knowledge && ('degraded' in knowledge || 'content' in knowledge || knowledge.lane === 'knowledge')
  if (knowledgeKnown) {
    const stopped = knowledge.degraded === true || knowledge.action === 'error' || knowledge.action === 'skip'
    if (stopped) reports.push(unfinished('知识整理员', '整理知识内容', 'knowledge'))
    else if (knowledge.action === 'new' || knowledge.action === 'update') {
      const documents = Number(knowledge.documents)
      if (Number.isFinite(documents) && documents >= 0) {
        const slice = contentSlice(knowledge.content)
        reports.push({
          employee: 'knowledge',
          name: '知识整理员',
          role: '整理知识内容',
          outcome: `本次整理 ${documents} 份文档。`,
          lines: slice ? [`文档 ${documents} 份`, `内容：${slice}`] : [`文档 ${documents} 份`],
        })
      }
    }
  }
  return reports
}
