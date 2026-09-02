/**
 * AI 制作草稿审核共享辅助（原单文件机械迁出）。
 */
import type { InjectionKey } from 'vue'
import type { PipelineStages, SkillData } from '../../../composables/useEmployeeAiDraft'
import { getAccessToken } from '../../../infrastructure/storage/tokenStore'

/** 可编辑草稿表单（流水线产物的本地副本）。 */
export interface DraftForm {
  id: string
  name: string
  role: string
  scenario: string
  industry: string
  complexity: string
  systemPrompt: string
  pricingTier: string
  pricingCny: number
  pricingPeriod: string
  skills: SkillData[]
}

/** 卡片子组件经此注入与入口同一份可编辑草稿对象（字段编辑行为与原单文件一致）。 */
export const EMP_DRAFT_FORM_KEY: InjectionKey<DraftForm> = Symbol('empDraftForm')

export const STAGE_KEYS = ['parse_intent', 'resolve_workflow', 'design_v2', 'suggest_skills', 'suggest_pricing', 'assemble'] as const

export const STAGE_LABELS: Record<string, string> = {
  parse_intent: '身份解析',
  resolve_workflow: '工作流选型',
  design_v2: '配置设计',
  suggest_skills: '技能建议',
  suggest_pricing: '定价建议',
  assemble: '清单装配',
}

export function cardClassFor(stages: PipelineStages, stage: keyof PipelineStages) {
  const s = stages[stage].status
  return {
    'emp-card--running': s === 'running',
    'emp-card--done': s === 'done',
    'emp-card--error': s === 'error',
  }
}

export function badgeClassFor(stages: PipelineStages, stage: keyof PipelineStages) {
  const s = stages[stage].status
  return {
    'emp-badge--running': s === 'running',
    'emp-badge--done': s === 'done',
    'emp-badge--error': s === 'error',
  }
}

export function badgeTextFor(stages: PipelineStages, stage: keyof PipelineStages) {
  const map: Record<string, string> = { idle: '', running: '处理中', done: '✓', error: '✗' }
  return map[stages[stage].status] ?? ''
}

export function fmtJson(val: unknown) {
  try {
    return JSON.stringify(val, null, 2)
  } catch {
    return String(val)
  }
}

export function authJsonHeaders(): Record<string, string> {
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  const t = getAccessToken()
  if (t) h.Authorization = `Bearer ${t}`
  return h
}
