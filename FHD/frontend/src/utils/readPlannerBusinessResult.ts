import type { ChatPlannerPayload } from '@/types/chat'
import { asRecord } from '@/utils/typeGuards'

const VISIBLE_BUSINESS_RESULT_STATUSES = new Set([
  'failed',
  'cancelled',
  'blocked',
  'unknown',
  'pending_approval',
  'waiting_user',
  'waiting_approval',
])

function nestedData(data: ChatPlannerPayload): Record<string, unknown> {
  return asRecord(asRecord(data.data).data)
}

function isEmptyFactValue(value: unknown): boolean {
  if (value === null || value === undefined || value === '') return true
  if (Array.isArray(value)) return value.length === 0
  if (typeof value === 'object') return Object.keys(value as object).length === 0
  return false
}

function hasVisibleBusinessFacts(facts: unknown): boolean {
  if (!facts || typeof facts !== 'object' || Array.isArray(facts)) return false
  return Object.values(facts as Record<string, unknown>).some((value) => !isEmptyFactValue(value))
}

function completedToolCount(result: Record<string, unknown>): number {
  const raw = asRecord(result.evidence).completed_tool_count
  const count = typeof raw === 'number' ? raw : Number(raw)
  return Number.isFinite(count) ? count : 0
}

function hasVisibleArtifactValue(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 0
  if (value && typeof value === 'object') return Object.keys(value as object).length > 0
  return Boolean(value)
}

function hasVisibleBusinessArtifacts(result: Record<string, unknown>): boolean {
  const artifactIds = asRecord(result.evidence).artifact_ids
  if (Array.isArray(artifactIds) && artifactIds.some((item) => String(item || '').trim())) return true
  return hasVisibleArtifactValue(result.artifacts)
}

function payloadHasBusinessExecution(payload: ChatPlannerPayload): boolean {
  const tool = asRecord(payload.toolCall)
  return Object.values(tool).some((value) => value !== null && value !== undefined && String(value).trim())
}

export function isVisibleChatBusinessResult(result: unknown, payload?: ChatPlannerPayload): boolean {
  if (!result || typeof result !== 'object' || Array.isArray(result)) return false
  const row = result as Record<string, unknown>
  if (!Object.keys(row).length) return false
  const status = String(row.status || '').trim()
  const summary = typeof row.summary === 'string' ? row.summary.trim() : ''
  return Boolean(
    hasVisibleBusinessFacts(row.facts) ||
    hasVisibleBusinessArtifacts(row) ||
    completedToolCount(row) > 0 ||
    row.pending_approval ||
    row.requires_reconciliation ||
    VISIBLE_BUSINESS_RESULT_STATUSES.has(status) ||
    (status === 'completed' && summary && payload && payloadHasBusinessExecution(payload)),
  )
}

export function readPlannerBusinessResult(data: ChatPlannerPayload): Record<string, unknown> | undefined {
  const inner = nestedData(data)
  const envelope = asRecord(data.data)
  const businessResult = asRecord(
    data.businessResult ||
      data.business_result ||
      envelope.businessResult ||
      envelope.business_result ||
      inner.businessResult ||
      inner.business_result,
  )
  if (!Object.keys(businessResult).length) return undefined
  return isVisibleChatBusinessResult(businessResult, data) ? businessResult : undefined
}
