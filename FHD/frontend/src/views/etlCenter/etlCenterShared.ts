/**
 * 数据对接中心纯函数标签与格式化工具（拆分自 views/EtlCenterView.vue，行为保持一致）。
 */
import type { Ref } from 'vue'
import type { EtlCapabilities, EtlRunRow } from '@/api/etl'

export function createTargetLabel(capabilities: Ref<EtlCapabilities | null>) {
  return (type: string) => {
    if (type === 'auto') return '智能识别（推荐）'
    return capabilities.value?.targets.find((item) => item.type === type)?.label || type
  }
}

export function actionLabel(action: string) {
  return ({ new: '新增', update: '更新', skip: '跳过', error: '错误' } as Record<string, string>)[action] || action
}

export function actionReason(action: string) {
  return action === 'skip' ? '重复数据，默认不写入' : '无差异'
}

export function stageLabel(stage: string) {
  return (
    (
      {
        queued: '等待后台任务',
        parsing: '解析文件',
        validating: '转换与校验',
        preview_ready: '解析完成',
        executing: '执行写入',
      } as Record<string, string>
    )[stage] || stage
  )
}

export function statusLabel(status: string) {
  return (
    (
      {
        queued: '排队中',
        previewing: '解析中',
        preview_ready: '待写入',
        executing: '写入中',
        completed: '已写入',
        failed: '失败',
        interrupted: '已中断',
      } as Record<string, string>
    )[status] || status
  )
}

export function sheetRoleLabel(role: unknown) {
  return (
    (
      {
        delivery_note_template_and_records: '送货单版式与发货数据',
        supporting_customer_product_data: '客户与产品补充数据',
        finance_or_reconciliation: '财务或对账附表',
        reference_catalog: '参考目录',
        non_target_appendix: '非业务附表',
      } as Record<string, string>
    )[String(role || '')] || '工作表'
  )
}

export function sheetPlanStatusLabel(status: unknown) {
  return (
    (
      {
        included: '纳入本次导入',
        reviewed: '已读取，仅作参考',
        excluded: '已排除',
      } as Record<string, string>
    )[String(status || '')] || '已检查'
  )
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

export function compactRecord(value: Record<string, unknown>) {
  return Object.entries(value)
    .slice(0, 5)
    .map(([key, item]) => `${key}: ${String(item ?? '')}`)
    .join(' · ')
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
