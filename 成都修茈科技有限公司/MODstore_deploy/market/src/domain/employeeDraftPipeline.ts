/**
 * Employee AI draft SSE pipeline — shared types and event reducer.
 * Single source of truth: Pinia workbench store + useAgentLoop SSE consumer.
 */

import type { Ref } from 'vue'

export type StageStatus = 'idle' | 'running' | 'done' | 'error'

export interface StageState<T = unknown> {
  status: StageStatus
  data: T | null
  error: string
  warnings?: string[]
}

export interface IntentData {
  id: string
  name: string
  role: string
  scenario: string
  industry: string
  complexity: string
}

export interface WorkflowData {
  workflow_id: number | null
  workflow_name: string
  match_score: number
  generated: boolean
  sandbox_passed?: boolean
}

export interface V2Data {
  perception: Record<string, unknown>
  memory: Record<string, unknown>
  cognition: Record<string, unknown>
  actions: Record<string, unknown>
}

export interface SkillData {
  name: string
  brief: string
  unverified: boolean
}

export interface PricingData {
  tier: string
  cny: number
  period: string
  reasoning: string
}

export interface PipelineStages {
  parse_intent: StageState<IntentData>
  resolve_workflow: StageState<WorkflowData>
  design_v2: StageState<V2Data>
  suggest_skills: StageState<SkillData[]>
  suggest_pricing: StageState<PricingData>
  assemble: StageState<Record<string, unknown>>
}

export interface PipelineStatus {
  phase: 'idle' | 'running' | 'done' | 'error'
  current: string
  manifest: Record<string, unknown> | null
  fatalError: string
}

export interface EmployeeDraftReviewMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  /** SSE event kind when role is assistant */
  kind?: string
  content: string
  ts: number
}

export function makeStageState<T = unknown>(): StageState<T> {
  return { status: 'idle', data: null, error: '', warnings: [] }
}

export function makeStages(): PipelineStages {
  return {
    parse_intent: makeStageState<IntentData>(),
    resolve_workflow: makeStageState<WorkflowData>(),
    design_v2: makeStageState<V2Data>(),
    suggest_skills: makeStageState<SkillData[]>(),
    suggest_pricing: makeStageState<PricingData>(),
    assemble: makeStageState<Record<string, unknown>>(),
  }
}

export function makePipelineStatus(): PipelineStatus {
  return {
    phase: 'idle',
    current: '',
    manifest: null,
    fatalError: '',
  }
}

function stageBucket(stages: PipelineStages): Record<string, StageState> {
  return stages as unknown as Record<string, StageState>
}

/**
 * Applies one SSE `data:` JSON event from `/api/workbench/employee-ai/draft`.
 * Mutates stages, status, and progressMessages ref in place.
 */
export function applyEmployeeDraftPipelineEvent(
  stages: PipelineStages,
  status: PipelineStatus,
  progressMessages: Ref<string[]>,
  ev: Record<string, unknown>,
): void {
  const event = ev.event as string
  const stage = ev.stage as string
  const byStage = stageBucket(stages)

  if (event === 'stage_start') {
    status.current = stage
    if (stage in byStage) {
      byStage[stage].status = 'running'
    }
    return
  }

  if (event === 'stage_progress') {
    if (typeof ev.message === 'string') {
      progressMessages.value.push(ev.message)
    }
    return
  }

  if (event === 'stage_done') {
    if (stage in byStage) {
      const s = byStage[stage]
      s.status = 'done'
      s.data = (ev.data ?? null) as unknown
      s.warnings = Array.isArray(ev.warnings) ? (ev.warnings as string[]) : []
    }
    return
  }

  if (event === 'stage_error') {
    if (stage in byStage) {
      const s = byStage[stage]
      s.status = 'error'
      s.error = String(ev.error ?? '')
    }
    const retryable = ev.retryable === true
    if (!retryable && stage !== 'suggest_skills' && stage !== 'suggest_pricing') {
      status.phase = 'error'
      status.fatalError = String(ev.error ?? '流水线失败')
    }
    return
  }

  if (event === 'pipeline_done') {
    status.phase = 'done'
    status.manifest = (ev.manifest as Record<string, unknown>) ?? null
    return
  }

  if (event === 'pipeline_error') {
    status.phase = 'error'
    status.fatalError = String(ev.error ?? '初始化失败')
  }
}
