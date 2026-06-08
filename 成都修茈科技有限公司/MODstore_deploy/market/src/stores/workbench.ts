import { computed, reactive, ref } from 'vue'
import { defineStore } from 'pinia'
import { createEmptyEmployeeConfigV2 } from '../employeeConfigV2'
import { api } from '../api'
import { getAccessToken } from '../infrastructure/storage/tokenStore'
import {
  applyEmployeeDraftPipelineEvent as applyEmployeeDraftPipelineEventCore,
  makePipelineStatus,
  makeStages,
  type EmployeeDraftReviewMessage,
  type PipelineStages,
  type PipelineStatus,
} from '../domain/employeeDraftPipeline'

// Use generic shapes to avoid @vue-flow/core deep-generic TS2589 errors
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type FlowNode = any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type FlowEdge = any

// ─── Target kinds ───────────────────────────────────────────────────────────

export type TargetKind = 'employee' | 'workflow' | 'mod' | 'skill'

export interface WorkbenchTarget {
  kind: TargetKind
  id: string | null
  manifest: Record<string, unknown>
  name: string
}

// ─── Chat ────────────────────────────────────────────────────────────────────

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  ts: number
}

// ─── Agent loop runs ─────────────────────────────────────────────────────────

export type AgentEventStatus = 'running' | 'done' | 'error' | 'idle'

export interface AgentEvent {
  id: string
  stage: string
  label: string
  payload: unknown
  status: AgentEventStatus
  ts: number
}

export type AgentRunSource = 'employee-draft' | 'script-workflow' | 'vibe-code' | 'mod-session'

export interface AgentRun {
  id: string
  source: AgentRunSource
  brief: string
  status: AgentEventStatus
  events: AgentEvent[]
  manifest: Record<string, unknown> | null
  startedAt: number
  endedAt: number | null
}

// ─── Inspector ───────────────────────────────────────────────────────────────

export type InspectorMode = 'node' | 'library' | 'run' | 'diff' | 'publish'

// ─── Store ───────────────────────────────────────────────────────────────────

export const useWorkbenchStore = defineStore('workbench', () => {
  // Current editing target
  const target = ref<WorkbenchTarget>({
    kind: 'employee',
    id: null,
    manifest: createEmptyEmployeeConfigV2() as Record<string, unknown>,
    name: '新员工',
  })

  // Vue Flow canvas state (source of truth driven by manifest via useWorkbenchManifest)
  const canvasNodes = ref<FlowNode[]>([])
  const canvasEdges = ref<FlowEdge[]>([])
  const selectedNodeId = ref<string | null>(null)

  // Chat (left rail)
  const chatMessages = ref<ChatMessage[]>([])
  const chatStreaming = ref(false)
  let chatAborter: AbortController | null = null

  // Agent runs (left rail timeline)
  const agentRuns = ref<AgentRun[]>([])
  const currentRunId = ref<string | null>(null)

  /** Employee draft SSE pipeline — shared with EmployeeAiDraftReview (single SSE via useAgentLoop). */
  const employeeDraftStages = reactive<PipelineStages>(makeStages())
  const employeeDraftStatus = reactive<PipelineStatus>(makePipelineStatus())
  const employeeDraftProgressMessages = ref<string[]>([])
  const employeeDraftReviewMessages = ref<EmployeeDraftReviewMessage[]>([])
  const employeeDraftReviewSending = ref(false)

  function reviewDraftMsgId(): string {
    return `edr-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`
  }

  function resetEmployeeDraftPipeline(): void {
    Object.assign(employeeDraftStages, makeStages())
    Object.assign(employeeDraftStatus, makePipelineStatus())
    employeeDraftProgressMessages.value = []
    employeeDraftReviewMessages.value = []
  }

  function markEmployeeDraftPipelineAborted(): void {
    if (employeeDraftStatus.phase === 'running') {
      employeeDraftStatus.phase = 'error'
      employeeDraftStatus.fatalError = '已取消'
    }
  }

  /**
   * Handles SSE payload from `/api/workbench/employee-ai/draft` plus optional future events:
   * `review_reply`, `clarification_question` (append to review thread).
   */
  function applyEmployeeDraftSseEvent(ev: Record<string, unknown>): void {
    const event = String(ev.event ?? '')
    if (event === 'review_reply' || event === 'clarification_question') {
      const text = String(ev.message ?? ev.content ?? '').trim()
      if (text) {
        employeeDraftReviewMessages.value.push({
          id: reviewDraftMsgId(),
          role: 'assistant',
          kind: event,
          content: text,
          ts: Date.now(),
        })
      }
      return
    }
    applyEmployeeDraftPipelineEventCore(
      employeeDraftStages,
      employeeDraftStatus,
      employeeDraftProgressMessages,
      ev,
    )
  }

  /** POST /api/workbench/employee-ai/draft/review-chat — backend optional; falls back to UX hint on failure. */
  async function submitEmployeeDraftReviewChat(text: string): Promise<void> {
    const trimmed = text.trim()
    if (!trimmed || employeeDraftReviewSending.value) return
    employeeDraftReviewSending.value = true
    employeeDraftReviewMessages.value.push({
      id: reviewDraftMsgId(),
      role: 'user',
      content: trimmed,
      ts: Date.now(),
    })
    const token = getAccessToken()
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (token) headers.Authorization = `Bearer ${token}`
    try {
      const res = await fetch('/api/workbench/employee-ai/draft/review-chat', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          message: trimmed,
          run_id: currentRunId.value,
        }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error((body as { detail?: string }).detail || `HTTP ${res.status}`)
      }
      const data = (await res.json().catch(() => ({}))) as { reply?: string; message?: string }
      const reply =
        typeof data.reply === 'string' ? data.reply : typeof data.message === 'string' ? data.message : ''
      if (reply) {
        employeeDraftReviewMessages.value.push({
          id: reviewDraftMsgId(),
          role: 'assistant',
          kind: 'review_reply',
          content: reply,
          ts: Date.now(),
        })
      }
    } catch {
      employeeDraftReviewMessages.value.push({
        id: reviewDraftMsgId(),
        role: 'assistant',
        kind: 'system',
        content:
          '审核对话接口暂未就绪（需后端实现 POST /api/workbench/employee-ai/draft/review-chat）。流水线若推送 review_reply / clarification_question，仍会显示在此。',
        ts: Date.now(),
      })
    } finally {
      employeeDraftReviewSending.value = false
    }
  }

  // Inspector (right rail)
  const inspectorMode = ref<InspectorMode>('library')

  // Research context cache
  const researchContext = ref<string>('')
  const researchSources = ref<string[]>([])

  // Unsaved state
  const dirty = ref(false)
  const lastSavedAt = ref<number | null>(null)

  // Workflow gate (for employee canvas: selected workflow sandbox status)
  const eligibleWorkflows = ref<unknown[]>([])
  const allWorkflowOptions = ref<unknown[]>([])
  const workflowGateLoading = ref(false)

  // ── Computed ──────────────────────────────────────────────────────────────

  function getSelectedNode() {
    return canvasNodes.value.find((n) => n.id === selectedNodeId.value) ?? null
  }
  const selectedNode = computed(getSelectedNode)

  const currentRun = computed<AgentRun | null>(() =>
    agentRuns.value.find((r) => r.id === currentRunId.value) ?? null,
  )

  // ── Actions ───────────────────────────────────────────────────────────────

  function setTarget(kind: TargetKind, id: string | null, manifest?: Record<string, unknown>, name?: string) {
    target.value = {
      kind,
      id: id ?? null,
      manifest: manifest ?? (createEmptyEmployeeConfigV2() as Record<string, unknown>),
      name: name ?? '新员工',
    }
    selectedNodeId.value = null
    inspectorMode.value = 'library'
    dirty.value = false
  }

  function patchManifest(path: string, value: unknown) {
    const keys = path.split('.')
    let obj: Record<string, unknown> = target.value.manifest
    for (let i = 0; i < keys.length - 1; i++) {
      const k = keys[i]
      if (obj[k] == null || typeof obj[k] !== 'object') {
        obj[k] = {}
      }
      obj = obj[k] as Record<string, unknown>
    }
    obj[keys[keys.length - 1]] = value
    dirty.value = true
  }

  function selectNode(id: string | null) {
    selectedNodeId.value = id
    inspectorMode.value = id ? 'node' : 'library'
  }

  function setCanvasGraph(nodes: FlowNode[], edges: FlowEdge[]) {
    canvasNodes.value = nodes
    canvasEdges.value = edges
  }

  // Chat helpers
  function pushChatMessage(msg: ChatMessage) {
    chatMessages.value.push(msg)
  }

  function appendChatChunk(id: string, chunk: string) {
    const msg = chatMessages.value.find((m) => m.id === id)
    if (msg) msg.content += chunk
  }

  function setChatStreaming(v: boolean, ctrl?: AbortController | null) {
    chatStreaming.value = v
    if (ctrl !== undefined) chatAborter = ctrl
  }

  function abortChat() {
    chatAborter?.abort()
    chatAborter = null
    chatStreaming.value = false
  }

  // Agent run helpers
  function startRun(run: AgentRun) {
    agentRuns.value.unshift(run)
    currentRunId.value = run.id
    inspectorMode.value = 'run'
  }

  function pushRunEvent(runId: string, ev: AgentEvent) {
    const run = agentRuns.value.find((r) => r.id === runId)
    if (!run) return
    const existing = run.events.findIndex((e) => e.stage === ev.stage)
    if (existing >= 0) {
      run.events[existing] = ev
    } else {
      run.events.push(ev)
    }
  }

  function finishRun(runId: string, status: AgentEventStatus, manifest?: Record<string, unknown> | null) {
    const run = agentRuns.value.find((r) => r.id === runId)
    if (!run) return
    run.status = status
    run.endedAt = Date.now()
    if (manifest) {
      run.manifest = manifest
      // Auto-apply manifest to current target when run is done
      if (status === 'done') {
        target.value.manifest = manifest
        dirty.value = true
      }
    }
  }

  // Research context
  function setResearch(context: string, sources: string[]) {
    researchContext.value = context
    researchSources.value = sources
  }

  // Workflow gate
  async function loadEligibleWorkflows() {
    workflowGateLoading.value = true
    try {
      const res = (await api.listEmployeeEligibleWorkflows()) as { workflows?: unknown[]; all_workflows?: unknown[] }
      eligibleWorkflows.value = Array.isArray(res?.workflows) ? res.workflows : []
      allWorkflowOptions.value = Array.isArray(res?.all_workflows)
        ? res.all_workflows
        : eligibleWorkflows.value
    } catch {
      eligibleWorkflows.value = []
      allWorkflowOptions.value = []
    } finally {
      workflowGateLoading.value = false
    }
  }

  return {
    // State
    target,
    canvasNodes,
    canvasEdges,
    selectedNodeId,
    chatMessages,
    chatStreaming,
    agentRuns,
    currentRunId,
    employeeDraftStages,
    employeeDraftStatus,
    employeeDraftProgressMessages,
    employeeDraftReviewMessages,
    employeeDraftReviewSending,
    inspectorMode,
    researchContext,
    researchSources,
    dirty,
    lastSavedAt,
    eligibleWorkflows,
    allWorkflowOptions,
    workflowGateLoading,
    // Computed
    selectedNode,
    currentRun,
    // Actions
    setTarget,
    patchManifest,
    selectNode,
    setCanvasGraph,
    pushChatMessage,
    appendChatChunk,
    setChatStreaming,
    abortChat,
    startRun,
    pushRunEvent,
    finishRun,
    setResearch,
    loadEligibleWorkflows,
    resetEmployeeDraftPipeline,
    markEmployeeDraftPipelineAborted,
    applyEmployeeDraftSseEvent,
    submitEmployeeDraftReviewChat,
  }
})
