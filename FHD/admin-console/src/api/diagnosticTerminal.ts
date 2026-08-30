export type DiagnosticTerminalItem = {
  kind: string
  severity: 'critical' | 'error' | 'warning' | 'info' | string
  title: string
  detail?: string
  source?: string
  reference?: string
  timestamp?: string
  data?: Record<string, unknown>
}

export type DiagnosticTerminalResult = {
  ok: boolean
  read_only: boolean
  command: string
  query: string
  status: 'healthy' | 'attention' | 'degraded' | 'info' | string
  summary: string
  metrics: Record<string, unknown>
  items: DiagnosticTerminalItem[]
  hints: string[]
  generated_at: string
  elapsed_ms: number
}
