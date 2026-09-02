// 拆分自 App.vue：纯函数（逻辑逐字迁移，行为不变）。
export function formatConvTime(ts: number | undefined): string {
  if (!ts) return ''
  const d = new Date(ts)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  if (diffMs < 60000) return '刚刚'
  if (diffMs < 3600000) return `${Math.floor(diffMs / 60000)}分钟前`
  if (diffMs < 86400000) return `${Math.floor(diffMs / 3600000)}小时前`
  if (diffMs < 604800000) return `${Math.floor(diffMs / 86400000)}天前`
  return `${d.getMonth() + 1}/${d.getDate()}`
}
