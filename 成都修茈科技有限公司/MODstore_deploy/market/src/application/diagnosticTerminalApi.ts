import { requestJson } from '../infrastructure/http/client'

export type DiagnosticSeverity = 'critical' | 'error' | 'warning' | 'info'
export type DiagnosticStatus = 'healthy' | 'attention' | 'degraded' | 'info' | string

export interface DiagnosticItem {
  kind: string
  severity: DiagnosticSeverity | string
  title: string
  detail?: string
  source?: string
  reference?: string
  timestamp?: string
  data?: Record<string, unknown>
}

export interface DiagnosticResult {
  ok: boolean
  read_only: boolean
  command: string
  query: string
  status: DiagnosticStatus
  summary: string
  metrics: Record<string, unknown>
  items: DiagnosticItem[]
  hints: string[]
  generated_at: string
  elapsed_ms: number
}

export async function executeDiagnosticCommand(command: string): Promise<DiagnosticResult> {
  return requestJson<DiagnosticResult>('/api/admin/diagnostic-terminal/execute', {
    method: 'POST',
    body: JSON.stringify({ command }),
    timeoutMs: 20_000,
  })
}
