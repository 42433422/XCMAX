import { stripInternalMarkers } from './lightMarkdown'

/** User-facing excerpt of agent plan markdown (no protocol blocks). */
export function formatPlanMdForDisplay(md: string, max = 1200): string {
  const s = stripInternalMarkers(String(md || ''))
    .replace(/^#+\s+/gm, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
  if (!s) return '（无计划摘要）'
  return s.length > max ? `${s.slice(0, max)}…` : s
}

export function formatBriefGoalForDisplay(goal: string, max = 200): string {
  const s = stripInternalMarkers(String(goal || '')).replace(/\s+/g, ' ').trim()
  if (!s) return '(无任务描述)'
  return s.length > max ? `${s.slice(0, max)}…` : s
}
