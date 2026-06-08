/** XCAGI 全景 HTML 嵌入 URL（由 FastAPI 挂载 /xcmax-dashboard → 仓根 XCAGI-Full-Pipeline.html） */

function dashboardBase(): string {
  // iframe 必须与页面同源，否则后端 CSP frame-ancestors 'self' 会拦截（如 :5001 嵌 :5100）
  if (typeof window !== 'undefined' && window.location?.origin) {
    return `${window.location.origin}/xcmax-dashboard/XCAGI-Full-Pipeline.html`
  }
  const apiBase = String(import.meta.env.VITE_API_BASE || '').trim().replace(/\/$/, '')
  if (apiBase) {
    return `${apiBase}/xcmax-dashboard/XCAGI-Full-Pipeline.html`
  }
  return '/xcmax-dashboard/XCAGI-Full-Pipeline.html'
}

/** 六线 loops 轨（等同本地 file://…/XCAGI-Full-Pipeline.html#s-loops） */
export function xcmaxAutomationPolicyEmbedUrl(): string {
  return `${dashboardBase()}?embed=loops#s-loops`
}

/** 新标签页打开（完整页，非 iframe 嵌入） */
export function xcmaxAutomationPolicyOpenUrl(): string {
  return `${dashboardBase()}#s-loops`
}

export function xcmaxDutyTimeArchitectureEmbedUrl(): string {
  return `${dashboardBase()}?embed=shell&view=mermaid`
}
