import type { EtlRunRow } from '@/api/etl'

export function actionLabel(action: string) {
  return ({ new: '新增', update: '更新', skip: '跳过', error: '需确认' } as Record<string, string>)[action] || action
}

export function actionReason(action: string) {
  return action === 'skip' ? '重复数据，默认不写入' : '无差异'
}

export function stageLabel(stage: string) {
  return ({
    queued: '等待后台任务',
    parsing: '读取文件',
    classifying_sheets: '逐 Sheet 识别业务对象',
    validating: '转换与校验',
    preview_ready: '预演完成',
    executing: '执行写入',
  } as Record<string, string>)[stage] || stage
}

export function statusLabel(status: string) {
  return ({
    planned: '已规划',
    queued: '排队中',
    previewing: '预演中',
    preview_ready: '待确认',
    executing: '执行中',
    completed: '已完成',
    failed: '失败',
    interrupted: '已中断',
  } as Record<string, string>)[status] || status
}

export function hasBlockingRowIssues(row: EtlRunRow) {
  return row.validation_issues.some((issue) => issue.severity === 'error')
}

export function sheetStructureLabel(value: unknown) {
  return ({
    empty: '空工作表',
    single_document: '一表一单',
    multi_document: '一表多单',
    unclassified: '待识别',
    not_inspected: '待取证',
  } as Record<string, string>)[String(value || '')] || '待识别'
}

export function sheetRangeText(sheet: Record<string, unknown>) {
  const observed = String(sheet.observed_effective_range || '').trim()
  const physical = String(sheet.physical_range || '').trim()
  if (sheet.is_empty === true) return '无业务单元格'
  if (sheet.evidence_complete === true && observed) return `有效区域 ${observed}`
  if (observed && physical && observed !== physical) return `已取证 ${observed} · 物理范围 ${physical}`
  return observed || physical ? `区域 ${observed || physical}` : '区域待确认'
}

export function sheetRoleLabel(role: unknown) {
  return ({
    delivery_note_template_and_records: '送货单版式与发货数据',
    supporting_customer_product_data: '客户与产品补充数据',
    finance_or_reconciliation: '财务或对账附表',
    reference_catalog: '参考目录',
    non_target_appendix: '非业务附表',
  } as Record<string, string>)[String(role || '')] || '工作表'
}

export function sheetPlanStatusLabel(status: unknown) {
  return ({
    included: '纳入预演',
    reviewed: '已读取，仅作参考',
    excluded: '已排除',
  } as Record<string, string>)[String(status || '')] || '已检查'
}

export function sheetPlanRows(item: Record<string, unknown>) {
  const rows = Number(item.rows || 0)
  return Number.isFinite(rows) && rows > 0 ? `${rows} 行候选数据` : ''
}

export function latestRecordSelectionText(selection: Record<string, unknown>) {
  const stale = Number(selection.stale_records_skipped || 0)
  const future = Number(selection.future_dated_records_skipped || 0)
  const parts = [
    !Number.isFinite(stale) || stale <= 0
      ? '同一客户同一产品按来源日期择最新有效记录。'
      : `同一客户同一产品已按来源日期选择最新有效记录，并排除 ${stale} 条较早或同日旧记录。`,
  ]
  if (Number.isFinite(future) && future > 0) parts.push(`另隔离 ${future} 条未来日期记录。`)
  return parts.join(' ')
}

export function confidenceClass(value: number) {
  return value >= 0.9 ? 'confidence-high' : value >= 0.6 ? 'confidence-medium' : 'confidence-low'
}

export function documentTypeLabel(type: unknown) {
  return ({
    purchase_order: '采购单',
    delivery_note: '送货单',
    quotation: '报价单',
    invoice: '发票',
    packing_list: '装箱单',
    attendance: '考勤表',
    customer_directory: '客户表',
    product_catalog: '产品表',
    shipment_ledger: '出货明细',
    generic_table: '通用表格',
    ignore: '不导入',
  } as Record<string, string>)[String(type || '')] || String(type || '未知单据')
}

export function fileStructureLabel(type: unknown) {
  return ({
    single_document: '一份文件一张单',
    one_per_sheet: '每个工作表一张单',
    multiple_sections: '同一工作表多段单据',
    mixed_workbook: '多种业务对象混合',
    summary: '汇总表',
    unknown: '待确认',
  } as Record<string, string>)[String(type || '')] || String(type || '待确认')
}

export function documentHeaderFields(document: Record<string, unknown>) {
  const value = document.header_fields
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    : []
}

export function documentTables(document: Record<string, unknown>) {
  const value = document.tables
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    : []
}

export function localizedModelText(value: unknown, fallback: string) {
  const text = String(value || '').trim()
  if (!text) return fallback
  const lower = text.toLowerCase()
  if (
    lower.includes('total')
    && ['no total', 'not present', 'no explicit', 'missing'].some((marker) => lower.includes(marker))
  ) {
    const amount = text.match(/(?:would\s+be|equals?|is)\s*(?:[A-Z]{3}\s*)?([0-9][0-9,]*(?:\.[0-9]+)?)/i)?.[1]
    const calculated = amount ? `；按明细金额计算合计为 ${amount}` : ''
    return `单据中未找到明确的合计金额单元格${calculated}，请人工核对。`
  }
  if (lower.includes('complete normalized record') && lower.includes('new insert')) {
    return '字段完整且未发现重复记录，模型建议新增；最终仍以主数据校验结果为准。'
  }
  if (/[\u3400-\u9fff]/u.test(text) && (text.match(/[A-Za-z]{3,}/g) || []).length < 3) return text
  return fallback
}

export function documentIssues(document: Record<string, unknown>) {
  const value = document.issues
  if (!Array.isArray(value)) return []
  return value.map((item) => {
    if (item && typeof item === 'object' && !Array.isArray(item)) {
      return localizedModelText(
        (item as Record<string, unknown>).message,
        '模型发现单据结构存在需要人工确认的问题，请结合来源单元格复核。',
      )
    }
    return localizedModelText(item, '模型发现单据结构存在需要人工确认的问题，请结合来源单元格复核。')
  }).filter(Boolean)
}

export function rowAdviceReason(row: EtlRunRow) {
  return localizedModelText(
    row.llm_suggestion.reason,
    row.llm_suggestion.action
      ? '模型已给出处理建议；最终仍以系统校验结果为准。'
      : '确定性规则建议',
  )
}

export function compactRecord(value: Record<string, unknown>) {
  return Object.entries(value).slice(0, 5).map(([key, item]) => `${key}: ${String(item ?? '')}`).join(' · ')
}

export function ocrTableRow(row: EtlRunRow) {
  const table = row.provenance.table_position
  return table && typeof table === 'object' && 'row' in table
    ? String((table as Record<string, unknown>).row || row.source_row)
    : String(row.source_row)
}

export function diffText(row: EtlRunRow) {
  return JSON.stringify({ 更新前: row.before, 更新后: row.after }, null, 2)
}

export function formatTime(value?: string | null) {
  return value ? new Date(value).toLocaleString() : '—'
}
