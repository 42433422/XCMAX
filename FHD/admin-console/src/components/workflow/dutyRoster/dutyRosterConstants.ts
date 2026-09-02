import {
  BUTLER_PROFILE,
  BUTLER_VIRTUAL_AREA_ID,
  BUTLER_VIRTUAL_AREA_LABEL,
  BUTLER_VIRTUAL_AREA_COLOR,
  BUTLER_VIRTUAL_EMPLOYEE_ID,
} from '@host/domain/butlerEmployeeProfile'
import {
  ALL_PLANNED_YUANGON_PKG_IDS,
  YUANGON_PKG_ROLE_LABELS,
  YUANGON_AREAS,
} from '@host/domain/yuangonDutyRoster'
import type { EmpRow, GraphViewMode, HealthLv, LlmActLv, RunNodeStatus } from './dutyRosterTypes'
/**
 * DutyRosterGraphPanel 纯常量与纯函数（无响应式依赖）。
 *
 * 由原文机械切分而来（行为保持不变）。
 */

export const DEFAULT_GRAPH_VIEW_MODE: GraphViewMode = 'department'
export const GRAPH_VIEW_TOKENS = new Set([
  'department',
  'dept',
  '六部门',
  'hub',
  'center',
  '中心',
  '中心图',
  'legacy-area',
  'area',
  '物理',
  '物理分区',
  'client',
  'workshop',
  '车间',
  '客户端车间',
])

export function normalizeViewToken(raw: unknown): string {
  return String(Array.isArray(raw) ? raw[0] : raw || '').trim().toLowerCase()
}

export function isGraphViewToken(raw: unknown): boolean {
  return GRAPH_VIEW_TOKENS.has(normalizeViewToken(raw))
}

export function parseViewModeFromQuery(raw: unknown): GraphViewMode {
  const v = normalizeViewToken(raw)
  if (v === 'department' || v === 'dept' || v === '六部门') return 'department'
  if (v === 'hub' || v === 'center' || v === '中心' || v === '中心图') return 'hub'
  if (v === 'legacy-area' || v === 'area' || v === '物理' || v === '物理分区') return 'legacy-area'
  if (v === 'client' || v === 'workshop' || v === '车间' || v === '客户端车间') return 'client'
  return DEFAULT_GRAPH_VIEW_MODE
}

export const EXEC_METRICS_PAGE = 30

// 编制矩阵见 ../../domain/yuangonDutyRoster（与 duty_roster.py 对齐）
export const ALL_PLANNED_IDS = ALL_PLANNED_YUANGON_PKG_IDS

export const CRAFT_PIPELINE_ORDER = [
  'intent-analyst',
  'employee-planner',
  'artifact-generator',
  'quality-validator',
  'miniapp-builder',
  'script-binder',
  'workflow-automator',
  'pack-registrar',
  'sandbox-tester',
  'code-validator',
  'self-checker',
  'host-checker',
  'hex-quality-assessor',
]

export function craftEmployeeDependsOn(employeeId: string): string | undefined {
  const idx = CRAFT_PIPELINE_ORDER.indexOf(employeeId)
  return idx > 0 ? CRAFT_PIPELINE_ORDER[idx - 1] : undefined
}

// Area colours (for node borders / group backgrounds)
export const AREA_COLORS: Record<string, string> = {
  'site-and-marketing': '#0ea5e9',
  'server-and-ops':     '#f59e0b',
  'modstore-backend':   '#a78bfa',
  'modstore-frontend':  '#34d399',
  'platform-core':      '#fb923c',
  'quality-and-docs':   '#60a5fa',
  [BUTLER_VIRTUAL_AREA_ID]: BUTLER_VIRTUAL_AREA_COLOR,
}

/** 数字管家：前端虚拟员工，与 ``YUANGON_AREAS`` 同等渲染但不走后端 */
export const VIRTUAL_AREAS: Record<string, { label: string; ids: string[] }> = {
  [BUTLER_VIRTUAL_AREA_ID]: { label: BUTLER_VIRTUAL_AREA_LABEL, ids: [BUTLER_VIRTUAL_EMPLOYEE_ID] },
}

/** 渲染用区域字典（编制矩阵 + 虚拟管家） */
export const ALL_AREAS: Record<string, { label: string; ids: string[] }> = {
  ...YUANGON_AREAS,
  ...VIRTUAL_AREAS,
}

export const VIRTUAL_EMPLOYEE_IDS = new Set<string>([BUTLER_VIRTUAL_EMPLOYEE_ID])

export function isVirtualEmployee(id: string): boolean {
  return VIRTUAL_EMPLOYEE_IDS.has(id)
}

/** 值班图节点仅允许编制矩阵 + 数字管家（防止 employees 被污染或旧缓存仍带全库列表） */
export function isDutyGraphMember(e: EmpRow): boolean {
  return isVirtualEmployee(e.id) || ALL_PLANNED_IDS.has(e.id)
}

// ─────────────────────────────────────────────────────────────────────────────
// State
// ─────────────────────────────────────────────────────────────────────────────

export function dgLoopRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : {}
}

export function dgLoopArray(v: unknown): unknown[] {
  return Array.isArray(v) ? v : []
}

export function dgLoopString(v: unknown): string {
  return String(v ?? '').trim()
}

export function dgLoopFirstText(...values: unknown[]): string {
  for (const value of values) {
    const text = dgLoopString(value)
    if (text) return text
  }
  return ''
}

export function dgLoopNumber(value: unknown): number | null {
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

export function collectDutyLoopEmployeeIds(value: unknown, out: Set<string>) {
  if (value == null) return
  if (typeof value === 'string') {
    const matches = value.match(/\b[a-z][a-z0-9]+(?:-[a-z0-9]+)+\b/g) || []
    for (const id of matches) {
      if (ALL_PLANNED_IDS.has(id)) out.add(id)
    }
    return
  }
  if (Array.isArray(value)) {
    for (const item of value) collectDutyLoopEmployeeIds(item, out)
    return
  }
  if (typeof value !== 'object') return
  const row = value as Record<string, unknown>
  const direct = dgLoopString(row.employee_id || row.employeeId || row.emp_id || row.empId || row.actor || row.assignee)
  if (direct && ALL_PLANNED_IDS.has(direct)) out.add(direct)
  for (const child of Object.values(row)) collectDutyLoopEmployeeIds(child, out)
}

export function stripEmbeddedReasoningTrace(s: string): string {
  const tagPairs: Array<{ o: string; c: string }> = [
    { o: 'think', c: 'think' },
    { o: 'thinking', c: 'thinking' },
    { o: 'redacted' + '_' + 'thinking', c: 'redacted' + '_' + 'thinking' },
  ]
  let out = s
  for (let p = 0; p < 12; p++) {
    let next = out
    for (const { o, c } of tagPairs) {
      const re = new RegExp('<' + o + '\\b[^>]*>[\\s\\S]*?</' + c + '>', 'gi')
      next = next.replace(re, '')
    }
    next = next.replace(/\n{3,}/g, '\n\n').trim()
    if (next === out) break
    out = next
  }
  return out
}

export const CENTER_ID = '__center__'
export const CLIENT_CENTER_ID = '__client_center__'
export const NODE_W    = 220
export const NODE_H    = 64
export const DEPT_OUTER_COLS = 3
export const DEPT_INNER_COLS = 3
export const DEPT_GROUP_GAP_X = 44
export const DEPT_GROUP_GAP_Y = 40
export const WORKSHOP_NODE_W = 200
export const WORKSHOP_NODE_H = 56

// ─────────────────────────────────────────────────────────────────────────────
// Health helpers
// ─────────────────────────────────────────────────────────────────────────────
export const HEALTH_COLOR: Record<HealthLv, string> = {
  healthy: '#4ade80', warn: '#f59e0b', idle: '#6b7280', unknown: '#374151',
}
export const HEALTH_LABEL: Record<HealthLv, string> = {
  healthy: '健康', warn: '告警', idle: '无记录', unknown: '—',
}

export const RUN_STATUS_COLOR: Record<RunNodeStatus, string> = {
  idle: '#374151',
  pending: '#64748b',
  running: '#3b82f6',
  success: '#22c55e',
  failed: '#ef4444',
  skipped: '#f59e0b',
}
export const RUN_STATUS_LABEL: Record<RunNodeStatus, string> = {
  idle: '未运行',
  pending: '等待',
  running: '运行中',
  success: '成功',
  failed: '失败',
  skipped: '跳过',
}

export const LLM_ACT_COLOR: Record<LlmActLv, string> = {
  activated: '#818cf8',   // purple – LLM connected
  no_key:    '#ef4444',   // red    – key missing
  echo_only: '#6b7280',   // gray   – no LLM needed
  unknown:   '#374151',   // dark   – not yet loaded
}
export const LLM_ACT_LABEL: Record<LlmActLv, string> = {
  activated: 'LLM 已激活',
  no_key:    'LLM 无密钥',
  echo_only: '仅回显',
  unknown:   '加载中',
}

export function parseJsonObjectInput(raw: string): Record<string, unknown> {
  const text = String(raw || '').trim()
  if (!text) return {}
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch (err: unknown) {
    throw new Error(err instanceof Error ? err.message : 'input_data JSON 解析失败')
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('input_data 必须是 JSON 对象')
  }
  return parsed as Record<string, unknown>
}

export function formatDurationMs(ms: number) {
  if (!Number.isFinite(ms) || ms < 0) return '—'
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(2)} s`
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────
export function formatRate(r: number) { return `${Math.round(r)}%` }
export function formatTime(iso?: unknown) {
  if (!iso) return '—'
  try { return new Date(iso as string).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) }
  catch { return String(iso) }
}
