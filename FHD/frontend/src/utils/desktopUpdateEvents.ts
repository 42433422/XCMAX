/** 把 electron-updater 事件翻译为用户可读文案，替代原始 JSON 输出 */

export interface RawUpdateEvent {
  type?: string
  data?: Record<string, unknown> | null
}

export function describeUpdateEvent(event: unknown): string {
  const e = (event || {}) as RawUpdateEvent
  const data = (e.data || {}) as Record<string, unknown>
  const version = String(data.version || '')
  switch (e.type) {
    case 'checking-for-update':
      return '正在检查更新…'
    case 'update-available':
      return version ? `发现新版本 ${version}，正在下载…` : '发现新版本，正在下载…'
    case 'update-not-available':
      return '当前已是最新版本'
    case 'download-progress': {
      const pct = Number(data.percent)
      return Number.isFinite(pct) ? `正在下载更新（${pct.toFixed(0)}%）` : '正在下载更新…'
    }
    case 'update-downloaded':
      return version ? `新版本 ${version} 已下载，重启后安装` : '更新已下载，重启后安装'
    case 'error': {
      const message = String(data.message || '未知错误')
      return `更新出错：${message}`
    }
    default:
      return e.type ? `更新事件：${e.type}` : '更新事件'
  }
}
