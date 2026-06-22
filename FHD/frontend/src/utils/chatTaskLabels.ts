export function formatTaskTime(ts: number): string {
  if (!ts) return ''
  return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

export function formatTaskSourceLabel(source: string): string {
  const s = String(source || '').trim()
  const map: Record<string, string> = {
    workflow: '工作流',
    excel: 'Excel',
    print: '打印',
    shipment: '发货单',
    manual: '手动',
    system: 'AI 员工',
    wechat: '微信',
    agent: 'Agent',
    pro: 'AI 链路',
    normal: '对话',
  }
  return map[s] || s || '—'
}
