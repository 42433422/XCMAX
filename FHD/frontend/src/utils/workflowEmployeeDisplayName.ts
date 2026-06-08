/**
 * 从任务面板标题解析「头顶短名」（员工空间等轻量展示用）。
 * 例：`工作流 · 标签打印 AI 员工` → `标签打印`
 */
export function shortNameFromPanelTitle(raw: string): string {
  let s = String(raw || '').trim()
  if (!s) return '员工'
  s = s.replace(/^工作流\s*[·•]\s*/i, '')
  s = s.replace(/\s*AI\s*员工\s*$/i, '')
  s = s.replace(/\s+/g, ' ').trim()
  return s || '员工'
}
