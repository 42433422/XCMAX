/**
 * 统一 SSE Agent 循环消费层。
 *
 * 把四种后端事件源（employee-draft / script-workflow / vibe-code / mod-session）
 * 抽象为统一的 AgentRun，写入 useWorkbenchStore。
 *
 * 每种 source 有不同的 endpoint 和事件 schema，内部分流解析后对外暴露一致的接口。
 */

import { getAccessToken } from '../infrastructure/storage/tokenStore'
import { useWorkbenchStore } from '../stores/workbench'
import type { AgentRun, AgentEvent, AgentEventStatus, AgentRunSource } from '../stores/workbench'

function uid(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36)
}

function nowEvent(stage: string, label: string, payload: unknown, status: AgentEventStatus): AgentEvent {
  return { id: uid(), stage, label, payload, status, ts: Date.now() }
}

// ─── Employee-draft (6-stage SSE) ────────────────────────────────────────────

const STAGE_LABELS: Record<string, string> = {
  parse_intent: '解析意图',
  resolve_workflow: '绑定工作流',
  design_v2: '设计员工配置',
  suggest_skills: '推荐技能',
  suggest_pricing: '定价建议',
  assemble: '组装 Manifest',
}

function applyEmployeeDraftEvent(
  store: ReturnType<typeof useWorkbenchStore>,
  runId: string,
  ev: Record<string, unknown>,
) {
  store.applyEmployeeDraftSseEvent(ev)

  const event = ev.event as string
  const stage = ev.stage as string
  const label = STAGE_LABELS[stage] ?? stage

  if (event === 'review_reply' || event === 'clarification_question') {
    return
  }

  if (event === 'stage_start') {
    store.pushRunEvent(runId, nowEvent(stage, label, null, 'running'))
    return
  }
  if (event === 'stage_progress') {
    // Progress messages are non-structural; update event payload
    store.pushRunEvent(runId, nowEvent(stage, label, { message: ev.message }, 'running'))
    return
  }
  if (event === 'stage_done') {
    store.pushRunEvent(runId, nowEvent(stage, label, ev.data ?? null, 'done'))
    return
  }
  if (event === 'stage_error') {
    store.pushRunEvent(runId, nowEvent(stage, label, { error: ev.error }, 'error'))
    return
  }
  if (event === 'pipeline_done') {
    const manifest = (ev.manifest as Record<string, unknown>) ?? null
    store.finishRun(runId, 'done', manifest)
    return
  }
  if (event === 'pipeline_error') {
    store.pushRunEvent(runId, nowEvent('pipeline', '流水线错误', { error: ev.error }, 'error'))
    store.finishRun(runId, 'error', null)
  }
}

// ─── Script-workflow SSE ─────────────────────────────────────────────────────

const SCRIPT_STAGE_LABELS: Record<string, string> = {
  context: '上下文分析',
  plan: '生成计划',
  code: '编写代码',
  check: '代码检查',
  run: '执行运行',
  observe: '观察输出',
  repair: '修复错误',
  done: '完成',
  error: '错误',
}

function applyScriptWorkflowEvent(
  store: ReturnType<typeof useWorkbenchStore>,
  runId: string,
  ev: Record<string, unknown>,
) {
  const event = String(ev.event ?? ev.type ?? '')
  const label = SCRIPT_STAGE_LABELS[event] ?? event
  const status: AgentEventStatus =
    event === 'done' ? 'done' : event === 'error' ? 'error' : 'running'

  if (event === 'done') {
    store.pushRunEvent(runId, nowEvent(event, label, ev, 'done'))
    store.finishRun(runId, 'done', null)
    return
  }
  if (event === 'error') {
    store.pushRunEvent(runId, nowEvent(event, label, ev, 'error'))
    store.finishRun(runId, 'error', null)
    return
  }
  store.pushRunEvent(runId, nowEvent(event, label, ev, status))
}

// ─── Generic SSE reader ───────────────────────────────────────────────────────

async function consumeSse(
  url: string,
  body: unknown,
  signal: AbortSignal,
  onEvent: (ev: Record<string, unknown>) => void,
) {
  const token = getAccessToken()
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const response = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal,
  })

  if (!response.ok) {
    let msg = `HTTP ${response.status}`
    try {
      const b = await response.json()
      msg = b?.detail || b?.error || msg
    } catch { /* ignore */ }
    throw new Error(msg)
  }

  const reader = response.body?.getReader()
  if (!reader) throw new Error('无法读取 SSE 流')

  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const ev = JSON.parse(line.slice(6))
            onEvent(ev)
          } catch { /* ignore malformed */ }
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

// ─── Public API ──────────────────────────────────────────────────────────────

export function useAgentLoop() {
  const store = useWorkbenchStore()

  async function runEmployeeDraft(brief: string, opts?: { provider?: string; model?: string; suggestedId?: string }) {
    const runId = uid()
    const run: AgentRun = {
      id: runId,
      source: 'employee-draft' as AgentRunSource,
      brief,
      status: 'running',
      events: [],
      manifest: null,
      startedAt: Date.now(),
      endedAt: null,
    }
    store.startRun(run)
    store.resetEmployeeDraftPipeline()
    store.employeeDraftStatus.phase = 'running'

    const ctrl = new AbortController()
    try {
      await consumeSse(
        '/api/workbench/employee-ai/draft',
        {
          brief,
          provider: opts?.provider || undefined,
          model: opts?.model || undefined,
          suggested_id: opts?.suggestedId || undefined,
        },
        ctrl.signal,
        (ev) => applyEmployeeDraftEvent(store, runId, ev),
      )
      if (store.employeeDraftStatus.phase === 'running') {
        store.employeeDraftStatus.phase = 'error'
        store.employeeDraftStatus.fatalError = '流意外结束'
        store.pushRunEvent(runId, nowEvent('pipeline', '流意外结束', {}, 'error'))
        store.finishRun(runId, 'error', null)
      }
    } catch (e: unknown) {
      if ((e as Error)?.name === 'AbortError') {
        store.markEmployeeDraftPipelineAborted()
        store.finishRun(runId, 'error', null)
      } else {
        if (store.employeeDraftStatus.phase === 'running') {
          store.employeeDraftStatus.phase = 'error'
          store.employeeDraftStatus.fatalError = (e as Error)?.message || String(e)
        }
        store.pushRunEvent(runId, nowEvent('network', '网络错误', { error: String(e) }, 'error'))
        store.finishRun(runId, 'error', null)
      }
    }

    return { runId, abort: () => ctrl.abort() }
  }

  async function runScriptWorkflow(payload: Record<string, unknown>) {
    const runId = uid()
    const run: AgentRun = {
      id: runId,
      source: 'script-workflow' as AgentRunSource,
      brief: String(payload.description || payload.brief || '脚本工作流'),
      status: 'running',
      events: [],
      manifest: null,
      startedAt: Date.now(),
      endedAt: null,
    }
    store.startRun(run)

    const ctrl = new AbortController()
    try {
      await consumeSse(
        '/api/script-workflows/sessions',
        payload,
        ctrl.signal,
        (ev) => applyScriptWorkflowEvent(store, runId, ev),
      )
    } catch (e: unknown) {
      if ((e as Error)?.name !== 'AbortError') {
        store.pushRunEvent(runId, nowEvent('network', '网络错误', { error: String(e) }, 'error'))
        store.finishRun(runId, 'error', null)
      }
    }

    return { runId, abort: () => ctrl.abort() }
  }

  return { runEmployeeDraft, runScriptWorkflow }
}
