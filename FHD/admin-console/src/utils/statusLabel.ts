/** 管理端状态码 → 中文展示文案（只改显示；未知值原样返回，不吞信息）。 */
const STATUS_LABELS: Record<string, string> = {
  pending: '待处理', open: '待处理', queued: '排队中', waiting: '等待中', created: '已创建',
  running: '进行中', in_progress: '进行中', processing: '处理中', dispatched: '已派单',
  completed: '已完成', done: '已完成', resolved: '已解决', closed: '已关闭',
  success: '成功', succeeded: '成功', ok: '正常', passed: '通过', ready: '就绪',
  failed: '失败', failure: '失败', error: '出错', timeout: '超时', blocked: '受阻',
  cancelled: '已取消', canceled: '已取消', skipped: '已跳过', expired: '已过期',
  approved: '已批准待合入', rejected: '已驳回', paid: '已支付', unpaid: '未支付', refunded: '已退款',
  in_dev: '开发中',
  rework: '已打回待返工', held: '已暂缓',
  active: '启用', inactive: '停用', unknown: '未知',
}

export function statusLabel(value: unknown): string {
  const raw = String(value ?? '').trim()
  if (!raw) return '未知'
  return STATUS_LABELS[raw.toLowerCase()] || raw
}
