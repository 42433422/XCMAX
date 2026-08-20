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
  output?: Record<string, unknown>
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

export interface AgentTaskCapabilities {
  pause: boolean
  cancel: boolean
  retry: boolean
  approve: boolean
  resume: boolean
  evidence: boolean
}

export interface AgentApprovalGrant {
  grant: string
  run_id: string
  step_id: string
  tool_id: string
  action: string
  expires_at: number
}

export interface AgentRunResponse extends ApiResponse<AgentRun> {
  approval?: AgentApprovalGrant
  capabilities?: AgentTaskCapabilities
  control_command?: AgentTaskControlCommand
  execution?: AgentTaskExecution
  deduplicated?: boolean
}

export interface AgentTaskControlCommand {
  command_id: string
  task_id: string
  run_id: string
  action: 'pause' | 'cancel' | 'resume'
  status: 'requested' | 'applied' | 'superseded' | 'rejected'
  requested_by?: string
  created_at?: string
  applied_at?: string
}

export interface AgentTaskExecution {
  run_id: string
  task_id: string
  user_id: string
  tenant_id?: string
  state: 'queued' | 'claimed' | 'paused' | 'blocked' | 'completed' | 'failed' | 'cancelled'
  priority: number
  available_at?: string
  lease_owner?: string
  lease_expires_at?: string
  heartbeat_at?: string
  execution_count: number
  recovery_count: number
  requested_by?: string
  last_error_code?: string
  created_at?: string
  updated_at?: string
  finished_at?: string
}

export interface AgentTaskRuntime {
  running: boolean
  max_workers: number
  active_count: number
  progress?: AgentTaskProgressOverview
}

export interface AgentTaskProgress {
  percent: number
  completed_units: number
  settled_units: number
  total_units: number
  current_unit: number
  stage: string
  detail: string
  status: string
  attempt: number
  indeterminate: boolean
  basis: 'steps' | 'status'
  updated_at?: string
}

export interface AgentTaskProgressOverview {
  task_count: number
  active_count: number
  attention_count: number
  completed_count: number
  overall_percent: number
}

export interface AgentTaskSummary {
  task_id: string
  user_id: string
  tenant_id?: string
  title: string
  source: string
  task_type: string
  status: string
  attention_state?: string
  unread_count?: number
  approval_required?: boolean
  active_run_id?: string
  root_run_id?: string
  conversation_id?: string
  workspace_id?: string
  workspace_path?: string
  workspace_isolation?: string
  attempt: number
  run_count: number
  progress?: AgentTaskProgress
  archived_at?: string
  metadata?: Record<string, unknown>
  created_at?: string
  updated_at?: string
  runs?: AgentRun[]
  active_run?: AgentRun
  capabilities?: AgentTaskCapabilities
  control_command?: AgentTaskControlCommand
  execution?: AgentTaskExecution
}

export interface AgentTaskListResponse extends ApiResponse<AgentTaskSummary[]> {
  count?: number
}

export interface AgentTaskResponse extends ApiResponse<AgentTaskSummary> {}

export interface CreateAgentTaskPayload {
  task_id: string
  title: string
  message?: string
  tool_id: string
  action: string
  params: Record<string, unknown>
  runtime_context?: Record<string, unknown>
}

export const agentRunsApi = {
  createRun(payload: CreateAgentRunPayload): Promise<ApiResponse<AgentRun>> {
    return api.post<ApiResponse<AgentRun>>('/api/agent/runs', payload)
  },

  createTask(payload: CreateAgentTaskPayload): Promise<AgentRunResponse> {
    return api.post<AgentRunResponse>('/api/agent/tasks', payload)
  },

  listTasks(params: { limit?: number; include_archived?: boolean } = {}): Promise<AgentTaskListResponse> {
    return api.get<AgentTaskListResponse>('/api/agent/tasks', params)
  },

  getTask(taskId: string): Promise<AgentTaskResponse> {
    return api.get<AgentTaskResponse>(`/api/agent/tasks/${encodeURIComponent(taskId)}`)
  },

  markTaskRead(taskId: string): Promise<AgentTaskResponse> {
    return api.post<AgentTaskResponse>(`/api/agent/tasks/${encodeURIComponent(taskId)}/read`, {})
  },

  getTaskRuntime(): Promise<ApiResponse<AgentTaskRuntime>> {
    return api.get<ApiResponse<AgentTaskRuntime>>('/api/agent/task-runtime')
  },

  taskEventStreamPath(): string {
    return '/api/agent/tasks/events/stream'
  },

  archiveTask(taskId: string): Promise<AgentTaskResponse> {
    return api.post<AgentTaskResponse>(`/api/agent/tasks/${encodeURIComponent(taskId)}/archive`, {})
  },

  observeTool(payload: ObserveAgentToolPayload): Promise<ApiResponse<AgentRunReference>> {
    return api.post<ApiResponse<AgentRunReference>>('/api/agent/runs/observed-tool', payload)
  },

  continueRun(runId: string, payload: ContinueAgentRunPayload): Promise<AgentRunResponse> {
    return api.post<AgentRunResponse>(`/api/agent/runs/${encodeURIComponent(runId)}/continue`, payload)
  },

  pauseRun(runId: string): Promise<ApiResponse<AgentRun>> {
    return api.post<ApiResponse<AgentRun>>(`/api/agent/runs/${encodeURIComponent(runId)}/pause`, {})
  },

  cancelRun(runId: string): Promise<ApiResponse<AgentRun>> {
    return api.post<ApiResponse<AgentRun>>(`/api/agent/runs/${encodeURIComponent(runId)}/cancel`, {})
  },

  resumeRun(runId: string, runtimeContext: Record<string, unknown> = {}): Promise<ApiResponse<AgentRun>> {
    return api.post<ApiResponse<AgentRun>>(`/api/agent/runs/${encodeURIComponent(runId)}/resume`, {
      runtime_context: runtimeContext,
    })
  },

  retryRun(runId: string): Promise<ApiResponse<AgentRunReference>> {
    return api.post<ApiResponse<AgentRunReference>>(`/api/agent/runs/${encodeURIComponent(runId)}/retry`, {})
  },

  getRun(runId: string): Promise<AgentRunResponse> {
    return api.get<AgentRunResponse>(`/api/agent/runs/${encodeURIComponent(runId)}`)
  },

  listRuns(params: { limit?: number } = {}): Promise<ApiResponse<AgentRun[]>> {
    return api.get<ApiResponse<AgentRun[]>>('/api/agent/runs', params)
  },

  listEvents(runId: string, params: { after_event_id?: string } = {}): Promise<AgentRunEventsResponse> {
    return api.get<AgentRunEventsResponse>(`/api/agent/runs/${encodeURIComponent(runId)}/events`, params)
  },

  eventStreamPath(runId: string, afterEventId?: string): string {
    const base = `/api/agent/runs/${encodeURIComponent(runId)}/events/stream`
    return afterEventId ? `${base}?after_event_id=${encodeURIComponent(afterEventId)}` : base
  },
}

export default agentRunsApi
