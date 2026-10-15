/**
 * 价值展示条折算口径（SSOT）：
 * 真实已完成任务数（/api/agent/task-runtime progress.completed_count）
 * × 每单人工成本（1.9–5.8 元伪随机）= 预计节约人工费用。
 *
 * 1.9–5.8 元/单 来源（吞吐口径评估）：
 * 电商/批发小助理岗日成本约 ¥280（月薪 ¥4,500 × 1.35 企业负担 ÷ 21.75 天），
 * 每天处理 48–150 单（含客服与异常处理约 60 单为中性，纯打单满负荷 150 单为上沿）。
 * 每单成本按任务序号伪随机且确定（同任务数结果稳定，不随刷新抖动；新增任务递增）。
 */
export const VALUE_STATS_COST_PER_TASK_MIN_CNY = 1.9
export const VALUE_STATS_COST_PER_TASK_MAX_CNY = 5.8
export const VALUE_STATS_REFRESH_MS = 5 * 60 * 1000

/** 单个任务的伪随机人工成本（确定性：taskIndex 相同结果相同），范围 [MIN, MAX]。 */
function perTaskCostCny(taskIndex: number): number {
  const x = Math.sin(taskIndex + 1) * 43758.5453
  const frac = x - Math.floor(x)
  return (
    VALUE_STATS_COST_PER_TASK_MIN_CNY +
    (VALUE_STATS_COST_PER_TASK_MAX_CNY - VALUE_STATS_COST_PER_TASK_MIN_CNY) * frac
  )
}

/** 折算节约人工费用（元）：逐单累加伪随机成本；非法输入按 0 处理。 */
export function estimateLaborCostSavedCny(completedCount: unknown): number {
  const count = Math.floor(Number(completedCount))
  if (!Number.isFinite(count) || count <= 0) return 0
  let total = 0
  for (let i = 0; i < count; i += 1) total += perTaskCostCny(i)
  return total
}

/** 千分位人民币文案：1234 -> ¥1,234。 */
export function formatCny(value: number): string {
  return `¥${Math.round(value).toLocaleString('en-US')}`
}
