export const REFUND_REASON_MIN = 5
export const REFUND_REASON_MAX = 1000

export type RefundStatusTone = 'pending' | 'rejected' | 'approved' | 'failed' | 'unknown'

export const refundStatusMap: Record<string, { label: string; tone: RefundStatusTone }> = {
  pending: { label: '待审核', tone: 'pending' },
  approved: { label: '已退回钱包', tone: 'approved' },
  rejected: { label: '已拒绝', tone: 'rejected' },
  refunded: { label: '已退款', tone: 'approved' },
  refund_failed: { label: '退款失败', tone: 'failed' },
}

export function refundStatusText(status: string): string {
  return refundStatusMap[status]?.label || status || '未知'
}

export function refundStatusTone(status: string): RefundStatusTone {
  return refundStatusMap[status]?.tone || 'unknown'
}

export function validateRefundForm(orderNo: unknown, reason: unknown): string {
  const trimmedOrderNo = String(orderNo || '').trim()
  const trimmedReason = String(reason || '').trim()
  if (!trimmedOrderNo) return '请填写订单号'
  if (trimmedReason.length < REFUND_REASON_MIN) return `退款原因至少 ${REFUND_REASON_MIN} 个字`
  if (trimmedReason.length > REFUND_REASON_MAX) return `退款原因最多 ${REFUND_REASON_MAX} 个字`
  return ''
}

export function formatRefundTime(value: unknown, locale = 'zh-CN'): string {
  if (!value) return '—'
  const d = new Date(String(value))
  if (Number.isNaN(d.getTime())) return String(value)
  return d.toLocaleString(locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
