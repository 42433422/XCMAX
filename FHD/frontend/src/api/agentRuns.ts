import { api } from './core'
import type { ApiResponse } from '@/types/api'

export interface AgentRunEvent {
  event_id: string
  run_id: string
  event_type: string
  message?: string
  data?: Record<string, unknown>
  created_at?: string
}

export interface AgentRunStep {
  step_id: string
  node_id: string
  tool_id: string
  action: string
  params?: Record<string, unknown>
  risk?: string
  idempotent?: boolean
  description?: string
  depends_on?: string[]
  status?: string
  output?: Record<string, unknown>
  error?: string
  started_at?: string
  finished_at?: string
  duration_ms?: number
  attempt_count?: number
}

export interface AgentToolCall {
  call_id: string
  step_id?: string
  node_id?: string
  tool_id?: string
  action?: string
  status?: string
  started_at?: string
  finished_at?: string
  duration_ms?: number
  cost_units?: number
  metadata?: Record<string, unknown>
}

export interface AgentArtifact {
  artifact_id: string
  artifact_type?: string
  name?: string
  source?: string
  uri?: string
  mime_type?: string
  summary?: string
  created_at?: string
  metadata?: Record<string, unknown>
}

export interface AgentRun {
  run_id: string
  user_id: string
  message: string
  status: string
  plan_id?: string
  intent?: string
  steps?: AgentRunStep[]
  tool_calls?: AgentToolCall[]
  artifacts?: AgentArtifact[]
  events?: AgentRunEvent[]
  final_output?: Record<string, unknown>
  error?: string
  metadata?: Record<string, unknown>
  created_at?: string
  updated_at?: string
}

export interface AgentRunEventsResponse {
  success: boolean
  data: AgentRunEvent[]
  count?: number
  message?: string
}

export interface CreateAgentRunPayload {
  message: string
  runtime_context?: Record<string, unknown>
  auto_execute?: boolean
}

export interface ContinueAgentRunPayload {
  approval_grant: string
  runtime_context?: Record<string, unknown>
}

export interface ObserveAgentToolPayload {
  message: string
  tool_id: string
  action: string
  params: Record<string, unknown>
  output: Record<string, unknown>
  response?: string
  source?: string
  runtime_context?: Record<string, unknown>
}

export interface AgentRunReference {
  run_id: string
  status: string
  task_id: string
}

export const agentRunsApi = {
  createRun(payload: CreateAgentRunPayload): Promise<ApiResponse<AgentRun>> {
    return api.post<ApiResponse<AgentRun>>('/api/agent/runs', payload)
  },

  observeTool(payload: ObserveAgentToolPayload): Promise<ApiResponse<AgentRunReference>> {
    return api.post<ApiResponse<AgentRunReference>>('/api/agent/runs/observed-tool', payload)
  },

  continueRun(
    runId: string,
    payload: ContinueAgentRunPayload,
  ): Promise<ApiResponse<AgentRun>> {
    return api.post<ApiResponse<AgentRun>>(
      `/api/agent/runs/${encodeURIComponent(runId)}/continue`,
      payload,
    )
  },

  pauseRun(runId: string): Promise<ApiResponse<AgentRun>> {
    return api.post<ApiResponse<AgentRun>>(
      `/api/agent/runs/${encodeURIComponent(runId)}/pause`,
      {},
    )
  },

  cancelRun(runId: string): Promise<ApiResponse<AgentRun>> {
    return api.post<ApiResponse<AgentRun>>(
      `/api/agent/runs/${encodeURIComponent(runId)}/cancel`,
      {},
    )
  },

  resumeRun(
    runId: string,
    runtimeContext: Record<string, unknown> = {},
  ): Promise<ApiResponse<AgentRun>> {
    return api.post<ApiResponse<AgentRun>>(
      `/api/agent/runs/${encodeURIComponent(runId)}/resume`,
      { runtime_context: runtimeContext },
    )
  },

  retryRun(runId: string): Promise<ApiResponse<AgentRunReference>> {
    return api.post<ApiResponse<AgentRunReference>>(
      `/api/agent/runs/${encodeURIComponent(runId)}/retry`,
      {},
    )
  },

  getRun(runId: string): Promise<ApiResponse<AgentRun>> {
    return api.get<ApiResponse<AgentRun>>(`/api/agent/runs/${encodeURIComponent(runId)}`)
  },

  listRuns(params: { limit?: number } = {}): Promise<ApiResponse<AgentRun[]>> {
    return api.get<ApiResponse<AgentRun[]>>('/api/agent/runs', params)
  },

  listEvents(
    runId: string,
    params: { after_event_id?: string } = {},
  ): Promise<AgentRunEventsResponse> {
    return api.get<AgentRunEventsResponse>(
      `/api/agent/runs/${encodeURIComponent(runId)}/events`,
      params,
    )
  },

  eventStreamPath(runId: string, afterEventId?: string): string {
    const base = `/api/agent/runs/${encodeURIComponent(runId)}/events/stream`
    return afterEventId
      ? `${base}?after_event_id=${encodeURIComponent(afterEventId)}`
      : base
  },
}

export default agentRunsApi
