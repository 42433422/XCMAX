/** 全景仪表盘 AI 业务数据（#aibiz）嵌入 URL */
export function xcagiAibizDashboardUrl(): string {
  const base = (
    import.meta.env.VITE_XCAGI_DASHBOARD_ORIGIN as string | undefined
  )?.trim().replace(/\/$/, '')
  const origin =
    base ||
    (typeof window !== 'undefined' && window.location?.origin
      ? window.location.origin.replace(/\/$/, '')
      : '')
  if (origin) {
    return `${origin}/xcmax-dashboard/XCAGI-Full-Pipeline.html?embed=shell#aibiz`
  }
  return 'http://127.0.0.1:8765/XCAGI-Full-Pipeline.html?embed=shell#aibiz'
}
