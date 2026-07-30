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
}

export interface AgentRun {
  run_id: string
  user_id: string
  message: string
  status: string
  plan_id?: string
  intent?: string
  steps?: AgentRunStep[]
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

export interface AgentToolContract {
  tool_id: string
  action: string
  description?: string
  input_schema?: Record<string, unknown>
  output_schema?: Record<string, unknown>
  risk?: string
  permission?: string
  idempotent?: boolean
  required_params?: string[]
  verification?: Record<string, unknown>
  rollback?: Record<string, unknown>
}

export interface CreateAgentRunPayload {
  message: string
  user_id?: string
  runtime_context?: Record<string, unknown>
  auto_execute?: boolean
  background?: boolean
}

export interface ContinueAgentRunPayload {
  approved_by?: string
  step_id?: string
  node_id?: string
  runtime_context?: Record<string, unknown>
  background?: boolean
}

export interface AgentRunControlPayload {
  requested_by?: string
}

export const agentRunsApi = {
  createRun(payload: CreateAgentRunPayload): Promise<ApiResponse<AgentRun>> {
    return api.post<ApiResponse<AgentRun>>('/api/agent/runs', payload)
  },

  continueRun(
    runId: string,
    payload: ContinueAgentRunPayload = {},
  ): Promise<ApiResponse<AgentRun>> {
    return api.post<ApiResponse<AgentRun>>(
      `/api/agent/runs/${encodeURIComponent(runId)}/continue`,
      payload,
    )
  },

  pauseRun(
    runId: string,
    payload: AgentRunControlPayload = {},
  ): Promise<ApiResponse<AgentRun>> {
    return api.post<ApiResponse<AgentRun>>(
      `/api/agent/runs/${encodeURIComponent(runId)}/pause`,
      payload,
    )
  },

  resumeRun(
    runId: string,
    payload: AgentRunControlPayload = {},
  ): Promise<ApiResponse<AgentRun>> {
    return api.post<ApiResponse<AgentRun>>(
      `/api/agent/runs/${encodeURIComponent(runId)}/resume`,
      payload,
    )
  },

  cancelRun(
    runId: string,
    payload: AgentRunControlPayload = {},
  ): Promise<ApiResponse<AgentRun>> {
    return api.post<ApiResponse<AgentRun>>(
      `/api/agent/runs/${encodeURIComponent(runId)}/cancel`,
      payload,
    )
  },

  retryRun(
    runId: string,
    payload: AgentRunControlPayload = {},
  ): Promise<ApiResponse<AgentRun>> {
    return api.post<ApiResponse<AgentRun>>(
      `/api/agent/runs/${encodeURIComponent(runId)}/retry`,
      payload,
    )
  },

  getRun(runId: string): Promise<ApiResponse<AgentRun>> {
    return api.get<ApiResponse<AgentRun>>(`/api/agent/runs/${encodeURIComponent(runId)}`)
  },

  listRuns(params: { user_id?: string; limit?: number } = {}): Promise<ApiResponse<AgentRun[]>> {
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

  listToolContracts(): Promise<ApiResponse<AgentToolContract[]>> {
    return api.get<ApiResponse<AgentToolContract[]>>('/api/agent/tools/contracts')
  },
}

export default agentRunsApi
