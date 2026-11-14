/** Format a Business Harness terminal result for chat and task surfaces. */

const FACT_LABELS: Record<string, string> = {
  customer_id: '客户 ID',
  product_id: '产品 ID',
  material_id: '原材料 ID',
  order_id: '订单 ID',
  record_id: '记录 ID',
  request_no: '请求单号',
  order_number: '业务单号',
  doc_name: '文档',
  created: '新增',
  updated: '更新',
  count: '数量',
  total: '合计',
  row_count: '明细行数',
  amount_total: '合计金额',
}

export function formatBusinessResultSummary(result: unknown): string {
  if (!result || typeof result !== 'object') return ''
  const row = result as Record<string, unknown>
  const summary = typeof row.summary === 'string' ? row.summary.trim() : ''
  const facts =
    row.facts && typeof row.facts === 'object' && !Array.isArray(row.facts)
      ? (row.facts as Record<string, unknown>)
      : {}
  const renderedFacts = Object.entries(facts)
    .filter(([, value]) => value !== '' && value !== null && value !== undefined)
    .map(([key, value]) => `${FACT_LABELS[key] || key}：${String(value)}`)
  const status = typeof row.status === 'string' ? row.status.trim() : ''
  if (!summary && !renderedFacts.length) {
    if (status && status !== 'completed') return status
    return ''
  }
  return [summary, ...renderedFacts].filter(Boolean).join('；').slice(0, 800)
}
