/**
 * AdminDutyEmployeeGraph 的常量与纯工具函数（由入口组件原文机械迁出）。
 */
import { ALL_PLANNED_YUANGON_PKG_IDS, YUANGON_AREAS } from '../../../domain/yuangonDutyRoster'
import {
  BUTLER_VIRTUAL_AREA_COLOR,
  BUTLER_VIRTUAL_AREA_ID,
  BUTLER_VIRTUAL_AREA_LABEL,
  BUTLER_VIRTUAL_EMPLOYEE_ID,
} from '../../../domain/butlerEmployeeProfile'
import type { EmpRow, HealthLv, LlmActLv, RunNodeStatus } from './adminDutyTypes'

export const EXEC_METRICS_PAGE = 30


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


export const AREA_COLORS: Record<string, string> = {
  'site-and-marketing': '#0ea5e9',
  'server-and-ops':     '#f59e0b',
  'modstore-backend':   '#a78bfa',
  'modstore-frontend':  '#34d399',
  'platform-core':      '#fb923c',
  'quality-and-docs':   '#60a5fa',
  [BUTLER_VIRTUAL_AREA_ID]: BUTLER_VIRTUAL_AREA_COLOR,
}


export const VIRTUAL_AREAS: Record<string, { label: string; ids: string[] }> = {
  [BUTLER_VIRTUAL_AREA_ID]: { label: BUTLER_VIRTUAL_AREA_LABEL, ids: [BUTLER_VIRTUAL_EMPLOYEE_ID] },
}


export const ALL_AREAS: Record<string, { label: string; ids: string[] }> = {
  ...YUANGON_AREAS,
  ...VIRTUAL_AREAS,
}


export const VIRTUAL_EMPLOYEE_IDS = new Set<string>([BUTLER_VIRTUAL_EMPLOYEE_ID])


export function isVirtualEmployee(id: string): boolean {
  return VIRTUAL_EMPLOYEE_IDS.has(id)
}


export function isDeployedDutyRosterRow(e: EmpRow): boolean {
  return !isVirtualEmployee(e.id) && e.source === 'catalog'
}


export function isDutyGraphMember(e: EmpRow): boolean {
  return isVirtualEmployee(e.id) || ALL_PLANNED_IDS.has(e.id)
}


export const allHandsAreaPalette: Record<string, string> = AREA_COLORS

export const CENTER_ID = '__center__'

export const CLIENT_CENTER_ID = '__client_center__'

export const NODE_W    = 220

export const NODE_H    = 64

export const WORKSHOP_NODE_W = 200

export const WORKSHOP_NODE_H = 56


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


export function formatDurationMs(ms: number) {
  if (!Number.isFinite(ms) || ms < 0) return '—'
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(2)} s`
}


export function formatRate(r: number) { return `${Math.round(r)}%` }

export function formatTime(iso?: string | null) {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) }
  catch { return iso }
}
