import api from '@/api/core'

export type ManagementWorkStatus =
  | 'assigned'
  | 'running'
  | 'cancel_requested'
  | 'waiting_decision'
  | 'retrying'
  | 'verifying'
  | 'delivered'
  | 'accepted'
  | 'blocked'
  | 'failed'
  | 'cancelled'

export type ManagementDecision = {
  decision_id: string
  question: string
  options: unknown[]
  recommendation?: string
  status: string
  decision?: string
  due_at?: string | null
}

export type ManagementWorkEvent = {
  id: number
  event_type: string
  actor_type: string
  actor_id?: string
  message?: string
  payload?: Record<string, unknown>
  created_at?: string | null
}

export type ManagementFactEvidence = {
  evidence_id: string
  task_id: string
  attempt: number
  check_id: string
  criterion_ids: string[]
  kind: string
  trust_level: string
  status: string
  source_ref?: string
  observed_at?: string | null
  expires_at?: string | null
  collector_version?: string
  payload?: Record<string, unknown>
  payload_sha256?: string
  signature?: string
}

export type ManagementVerificationReceipt = {
  receipt_id: string
  task_id: string
  attempt: number
  result_digest: string
  fact_bundle_digest: string
  fact_required: boolean
  fact_outcome: string
  audit_outcome: string
  status: string
  verifier_employee_id?: string
  audit?: Record<string, unknown>
  created_at?: string | null
}

export type ManagementWorkOperation = {
  operation_id: string
  operation_key: string
  task_id: string
  employee_id: string
  task_revision: number
  logical_step: string
  attempt: number
  kind: string
  target: string
  request_digest: string
  status: string
  reversible: boolean
  external_ref?: string
  result?: Record<string, unknown>
  error?: string
  compensation_status: string
  compensation?: Record<string, unknown>
  lease_expires_at?: string | null
  created_at?: string | null
  updated_at?: string | null
  completed_at?: string | null
}

export type ManagementWorkItem = {
  task_id: string
  title: string
  description: string
  owner_employee_id: string
  employee_partition?: 'management_duty'
  status: ManagementWorkStatus
  priority: string
  risk_level: string
  progress: number
  current_stage?: string
  last_update?: string
  result_summary?: string
  error?: string
  error_kind?: string
  attempt_count: number
  max_attempts: number
  acceptance_criteria?: unknown[]
  artifacts?: unknown[]
  evidence?: unknown[]
  fact_evidence?: ManagementFactEvidence[]
  verification_receipts?: ManagementVerificationReceipt[]
  operations?: ManagementWorkOperation[]
  heartbeat_at?: string | null
  updated_at?: string | null
  completed_at?: string | null
  events?: ManagementWorkEvent[]
  decisions?: ManagementDecision[]
}

export type ManagementAcceptanceGate = {
  allowed: boolean
  receipt: ManagementVerificationReceipt | null
  currentReceipt: ManagementVerificationReceipt | null
  currentFacts: ManagementFactEvidence[]
  blockers: string[]
}

const PASS_OUTCOME = 'pass'
const INDEPENDENT_TRUST_LEVEL = 'independent_observation'
const VERIFICATION_OFFICER = 'delivery-receipt-officer'
const KNOWN_OPERATION_STATUSES = new Set(['running', 'succeeded', 'failed', 'uncertain'])
const KNOWN_COMPENSATION_STATUSES = new Set([
  'not_required',
  'available',
  'required',
  'compensated',
  'failed',
  'conflict',
  'unavailable',
])

function normalized(value: unknown): string {
  return String(value || '').trim().toLowerCase()
}

function present(value: unknown): boolean {
  return String(value || '').trim().length > 0
}

function validAttempt(value: unknown): number | null {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

export function currentAttemptVerificationReceipt(
  item: ManagementWorkItem | null | undefined,
): ManagementVerificationReceipt | null {
  if (!item) return null
  const attempt = validAttempt(item.attempt_count)
  if (attempt === null || !present(item.task_id)) return null
  const receipts = Array.isArray(item.verification_receipts)
    ? item.verification_receipts
    : []
  for (let index = receipts.length - 1; index >= 0; index -= 1) {
    const receipt = receipts[index]
    if (
      receipt.task_id === item.task_id
      && validAttempt(receipt.attempt) === attempt
    ) {
      return receipt
    }
  }
  return null
}

/**
 * Only a PASS receipt for this exact task and execution attempt authorizes the
 * owner's normal accept action. Historical receipts remain visible for audit,
 * but can never approve a retried candidate.
 */
export function currentAttemptPassReceipt(
  item: ManagementWorkItem | null | undefined,
): ManagementVerificationReceipt | null {
  const receipt = currentAttemptVerificationReceipt(item)
  if (
    receipt
    && present(receipt.receipt_id)
    && present(receipt.result_digest)
    && present(receipt.fact_bundle_digest)
    && normalized(receipt.status) === PASS_OUTCOME
    && normalized(receipt.fact_outcome) === PASS_OUTCOME
    && normalized(receipt.audit_outcome) === PASS_OUTCOME
    && String(receipt.verifier_employee_id || '').trim() === VERIFICATION_OFFICER
  ) {
    return receipt
  }
  return null
}

/**
 * Full owner-acceptance gate. Backend validation remains authoritative, while
 * this mirrors it fail-closed so the desktop never invites an unsafe accept.
 */
export function managementAcceptanceGate(
  item: ManagementWorkItem | null | undefined,
  nowMs = Date.now(),
): ManagementAcceptanceGate {
  if (!item) {
    return {
      allowed: false,
      receipt: null,
      currentReceipt: null,
      currentFacts: [],
      blockers: ['任务详情尚未加载。'],
    }
  }

  const attempt = validAttempt(item.attempt_count)
  const blockers: string[] = []
  const currentReceipt = currentAttemptVerificationReceipt(item)
  const receipt = currentAttemptPassReceipt(item)
  const allFacts = Array.isArray(item.fact_evidence) ? item.fact_evidence : []
  const currentFacts = attempt === null
    ? []
    : allFacts.filter((fact) => validAttempt(fact.attempt) === attempt)
  const currentTaskFacts = currentFacts.filter((fact) => fact.task_id === item.task_id)

  if (attempt === null) {
    blockers.push('当前执行 attempt 缺失或无效。')
  }

  if (item.status !== 'delivered') {
    blockers.push(`任务状态为 ${item.status}，只有 delivered 状态可以验收。`)
  }
  if (!currentReceipt) {
    blockers.push(`第 ${attempt ?? 0} 次执行没有与当前 task_id 匹配的独立验收回执。`)
  } else if (!receipt) {
    if (!present(currentReceipt.receipt_id)) blockers.push('当前验收回执缺少 receipt_id。')
    if (!present(currentReceipt.result_digest)) blockers.push('当前验收回执缺少 result_digest。')
    if (!present(currentReceipt.fact_bundle_digest)) blockers.push('当前验收回执缺少 fact_bundle_digest。')
    if (normalized(currentReceipt.status) !== PASS_OUTCOME) {
      blockers.push(`当前验收回执状态为 ${currentReceipt.status || 'unknown'}，未通过。`)
    }
    if (normalized(currentReceipt.fact_outcome) !== PASS_OUTCOME) {
      blockers.push(`当前验收回执事实结果为 ${currentReceipt.fact_outcome || 'unknown'}，未通过。`)
    }
    if (normalized(currentReceipt.audit_outcome) !== PASS_OUTCOME) {
      blockers.push(`当前验收回执语义结果为 ${currentReceipt.audit_outcome || 'unknown'}，未通过。`)
    }
    if (String(currentReceipt.verifier_employee_id || '').trim() !== VERIFICATION_OFFICER) {
      blockers.push('当前验收回执不是由 delivery-receipt-officer 生成。')
    }
  }

  if (currentReceipt?.fact_required && currentTaskFacts.length === 0) {
    blockers.push(`第 ${attempt ?? 0} 次回执要求独立事实，但当前没有事实证据。`)
  }
  for (const fact of allFacts) {
    const factName = fact.check_id || fact.evidence_id || 'unknown'
    if (!present(fact.task_id)) {
      blockers.push(`事实 ${factName} 缺少 task_id。`)
    }
    if (validAttempt(fact.attempt) === null) {
      blockers.push(`事实 ${factName} 缺少有效 attempt。`)
    }
  }
  for (const fact of currentFacts) {
    const factName = fact.check_id || fact.evidence_id || 'unknown'
    if (fact.task_id !== item.task_id) {
      blockers.push(`事实 ${factName} 的 task_id 与当前任务不一致。`)
    }
    if (normalized(fact.status) !== PASS_OUTCOME) {
      blockers.push(`事实 ${factName} 状态为 ${fact.status || 'unknown'}，未通过。`)
    }
    if (normalized(fact.trust_level) !== INDEPENDENT_TRUST_LEVEL) {
      blockers.push(`事实 ${factName} 缺少可信的 independent_observation 标记。`)
    }
    if (!present(fact.payload_sha256)) {
      blockers.push(`事实 ${factName} 缺少 payload_sha256。`)
    }
    if (!present(fact.signature)) {
      blockers.push(`事实 ${factName} 缺少独立采集签名。`)
    }
    const expiresAt = String(fact.expires_at || '').trim()
    if (!expiresAt) {
      blockers.push(`事实 ${factName} 缺少 expires_at。`)
    } else {
      const expiresMs = Date.parse(expiresAt)
      if (Number.isNaN(expiresMs)) {
        blockers.push(`事实 ${factName} 的过期时间无效。`)
      } else if (expiresMs <= nowMs) {
        blockers.push(`事实 ${factName} 已于 ${new Date(expiresMs).toLocaleString()} 过期。`)
      }
    }
  }

  const blockingOperationStatuses = new Set(['running', 'uncertain'])
  const blockingCompensationStatuses = new Set([
    'required',
    'failed',
    'conflict',
    'unavailable',
  ])
  for (const operation of Array.isArray(item.operations) ? item.operations : []) {
    const operationName = operation.logical_step || operation.kind || operation.operation_id
    if (!present(operation.task_id)) {
      blockers.push(`外部操作 ${operationName} 缺少 task_id。`)
    } else if (operation.task_id !== item.task_id) {
      blockers.push(`外部操作 ${operationName} 的 task_id 与当前任务不一致。`)
    }
    const status = normalized(operation.status)
    const compensationStatus = normalized(operation.compensation_status)
    if (!KNOWN_OPERATION_STATUSES.has(status)) {
      blockers.push(`外部操作 ${operationName} 的状态缺失或未知。`)
    } else if (blockingOperationStatuses.has(status)) {
      blockers.push(`外部操作 ${operationName} 仍为 ${status}，结果尚未收口。`)
    }
    if (!KNOWN_COMPENSATION_STATUSES.has(compensationStatus)) {
      blockers.push(`外部操作 ${operationName} 的补偿状态缺失或未知。`)
    } else if (blockingCompensationStatuses.has(compensationStatus)) {
      blockers.push(`外部操作 ${operationName} 的补偿状态为 ${compensationStatus}。`)
    }
  }

  const uniqueBlockers = [...new Set(blockers)]
  return {
    allowed: uniqueBlockers.length === 0,
    receipt,
    currentReceipt,
    currentFacts,
    blockers: uniqueBlockers,
  }
}

export type ManagementDutyEmployee = {
  employee_id: string
  name: string
  area?: string
  employee_partition: 'management_duty'
  manifest_registered?: boolean
  runtime_executable?: boolean
  primary_assignable?: boolean
  runtime_issues?: string[]
}

export type ManagementWorkSummary = {
  by_status: Record<string, number>
  active: number
  pending_decisions: number
  accepted: number
  blocked: number
}

export const managementWorkApi = {
  list(params: { status?: string; owner_employee_id?: string; limit?: number } = {}) {
    return api.get<{
      items: ManagementWorkItem[]
      count: number
      summary: ManagementWorkSummary
    }>('/api/xcmax/employee-work', params)
  },
  summary() {
    return api.get<ManagementWorkSummary>('/api/xcmax/employee-work/summary')
  },
  employees() {
    return api.get<{
      employee_partition: 'management_duty'
      employees: ManagementDutyEmployee[]
      count: number
    }>('/api/xcmax/employee-work/employees')
  },
  detail(taskId: string) {
    return api.get<ManagementWorkItem>(
      `/api/xcmax/employee-work/${encodeURIComponent(taskId)}`,
    )
  },
  create(payload: Record<string, unknown>) {
    return api.post<{ created: boolean; item: ManagementWorkItem }>(
      '/api/xcmax/employee-work',
      payload,
    )
  },
  resolveDecision(decisionId: string, decision: string, note = '') {
    return api.post(
      `/api/xcmax/employee-work/decisions/${encodeURIComponent(decisionId)}/resolve`,
      { decision, note },
    )
  },
  review(taskId: string, accepted: boolean, feedback = '') {
    return api.post<ManagementWorkItem>(
      `/api/xcmax/employee-work/${encodeURIComponent(taskId)}/review`,
      { accepted, feedback },
    )
  },
  retry(taskId: string, note = '') {
    return api.post<ManagementWorkItem>(
      `/api/xcmax/employee-work/${encodeURIComponent(taskId)}/retry`,
      { note },
    )
  },
  cancel(taskId: string, reason = '') {
    return api.post<ManagementWorkItem>(
      `/api/xcmax/employee-work/${encodeURIComponent(taskId)}/cancel`,
      { reason },
    )
  },
  reassign(taskId: string, newEmployeeId: string, reason = '') {
    return api.post<ManagementWorkItem>(
      `/api/xcmax/employee-work/${encodeURIComponent(taskId)}/reassign`,
      { new_employee_id: newEmployeeId, reason },
    )
  },
}
