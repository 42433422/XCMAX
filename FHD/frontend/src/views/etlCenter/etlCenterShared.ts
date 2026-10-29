/**
 * 数据对接中心纯函数标签与格式化工具（拆分自 views/EtlCenterView.vue，行为保持一致）。
 */
import type { Ref } from 'vue'
import type { EtlCapabilities, EtlRun, EtlRunRow } from '@/api/etl'

export function createTargetLabel(capabilities: Ref<EtlCapabilities | null>) {
  return (type: string) => {
    if (type === 'auto') return '智能识别（推荐）'
    return capabilities.value?.targets.find((item) => item.type === type)?.label || type
  }
}

export function actionLabel(action: string) {
  return ({ new: '新增', update: '更新', skip: '跳过', error: '错误' } as Record<string, string>)[action] || action
}

export function actionReason(row: EtlRunRow) {
  if (row.action_overridden) return `用户主动${actionLabel(row.final_action)}（原建议：${actionLabel(row.suggested_action)}）`
  if (row.final_action !== 'skip') return '无差异'
  return row.match_ref ? '已匹配现有记录，默认跳过' : '按规则跳过；具体原因请查看原建议'
}

export function targetOperation(type?: string) {
  if (type === 'export_xlsx') return { action: '生成 Excel 文件', verb: '生成文件', processing: '正在生成文件', done: '文件已生成', count: '已生成文件数据' }
  if (type === 'export_csv') return { action: '生成 CSV 文件', verb: '生成文件', processing: '正在生成文件', done: '文件已生成', count: '已生成文件数据' }
  if (type === 'webhook') return { action: '发送到外部系统', verb: '发送', processing: '正在发送', done: '发送完成', count: '已确认发送' }
  return { action: '写入数据库', verb: '写入', processing: '执行写入', done: '已写入', count: '已写入' }
}

export function resultNeedsVerification(run: EtlRun) {
  return run.status === 'outcome_unknown' || run.rollback_status === 'outcome_unknown' || run.error?.code === 'ETL_OUTCOME_UNKNOWN'
}

export function stageLabel(stage: string, targetType?: string) {
  if (stage === 'executing') return targetOperation(targetType).processing
  return (
    (
      {
        queued: '等待后台任务',
        parsing: '解析文件',
        loading: '保存原始数据',
        source_loaded: '原始数据已保存',
        transforming: '转换与校验',
        validating: '转换与校验',
        preview_ready: '解析完成',
        executing: '执行写入',
      } as Record<string, string>
    )[stage] || stage
  )
}

export function statusLabel(status: string, rollbackStatus?: string | null, targetType?: string) {
  if (rollbackStatus === 'completed') return '已撤销'
  if (rollbackStatus === 'outcome_unknown' || status === 'outcome_unknown') return '结果待核对'
  if (status === 'completed') return targetOperation(targetType).done
  if (status === 'executing') return targetOperation(targetType).processing
  if (status === 'preview_ready') return `待确认${targetOperation(targetType).verb}`
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

export function recordValue(value: unknown) {
  return value != null && typeof value === 'object' ? JSON.stringify(value) : String(value ?? '')
}

export function hiddenFieldCount(value: Record<string, unknown>) {
  return Math.max(0, Object.keys(value).length - 5)
}

export function compactRecord(value: Record<string, unknown>) {
  return Object.entries(value)
    .slice(0, 5)
    .map(([key, item]) => `${key}: ${recordValue(item)}`)
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
