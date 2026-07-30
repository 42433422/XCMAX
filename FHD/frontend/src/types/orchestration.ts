/**
 * Safe, user-facing projection of one AgentRun tool call.
 *
 * This intentionally does not model raw tool params or outputs. The backend
 * sends only the allow-listed fields needed to explain an operation in chat.
 */
export type OrchestrationEvidenceKind =
  | 'employee'
  | 'print'
  | 'database_write'
  | 'database_read'
  | 'tool'

export interface OrchestrationDatabase {
  database_id?: string
  database_name?: string
  runtime_database?: string
  storage_mode?: string
  role?: string
  tables?: string
  active_mod_id?: string
}

export interface OrchestrationChange {
  database_id?: string
  database_name?: string
  runtime_database?: string
  entity?: string
  operation?: string
  label?: string
  counts?: Record<string, number>
  items?: Array<Record<string, unknown>>
  field_changes?: Array<{ field?: string; before?: string; after?: string }>
}

export interface OrchestrationEmployee {
  employee_id?: string
  employee_name?: string
  task?: string
  status?: string
}

export interface OrchestrationPrint {
  kind?: string
  printer_name?: string
  copies?: number
  template?: string
  file_name?: string
  job_id?: string
}

export interface OrchestrationEvidence {
  schema_version?: string
  kind: OrchestrationEvidenceKind
  label?: string
  status?: string
  tool_id?: string
  action?: string
  databases: OrchestrationDatabase[]
  changes: OrchestrationChange[]
  employees: OrchestrationEmployee[]
  print?: OrchestrationPrint
  query?: string
  result_count?: number
}

export interface OrchestrationVerification {
  accepted?: boolean
  verified?: boolean
  status?: string
  verifier?: string
  reason?: string
  evidence?: Record<string, unknown>
  recovery_hint?: string
}

export interface OrchestrationTraceStep {
  id: string
  eventId: string
  firstEventId?: string
  eventType: string
  createdAt?: string
  stepId?: string
  nodeId?: string
  status: string
  message?: string
  evidence: OrchestrationEvidence
  verification?: OrchestrationVerification
}
