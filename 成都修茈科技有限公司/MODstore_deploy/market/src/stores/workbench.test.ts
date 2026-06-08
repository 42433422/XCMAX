import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useWorkbenchStore } from './workbench'
import { createEmptyEmployeeConfigV2 } from '../employeeConfigV2'
import { api } from '../api'

vi.mock('../api', () => ({
  api: {
    listEmployeeEligibleWorkflows: vi.fn(),
  },
}))

describe('useWorkbenchStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('initialises with employee target kind and empty manifest', () => {
    const store = useWorkbenchStore()
    expect(store.target.kind).toBe('employee')
    expect(store.target.id).toBeNull()
    expect(store.target.manifest).toBeDefined()
  })

  it('setTarget updates kind, id, manifest and resets selection', () => {
    const store = useWorkbenchStore()
    const manifest = createEmptyEmployeeConfigV2() as Record<string, unknown>
    store.setTarget('workflow', '42', manifest, '测试工作流')
    expect(store.target.kind).toBe('workflow')
    expect(store.target.id).toBe('42')
    expect(store.target.name).toBe('测试工作流')
    expect(store.selectedNodeId).toBeNull()
    expect(store.dirty).toBe(false)
  })

  it('patchManifest writes deeply nested value and marks dirty', () => {
    const store = useWorkbenchStore()
    store.patchManifest('identity.name', '客服助手')
    expect((store.target.manifest.identity as Record<string, unknown>).name).toBe('客服助手')
    expect(store.dirty).toBe(true)
  })

  it('patchManifest creates intermediate objects when missing', () => {
    const store = useWorkbenchStore()
    store.setTarget('employee', null, {}, '测试')
    store.patchManifest('cognition.agent.system_prompt', '你好')
    const cog = store.target.manifest.cognition as Record<string, unknown>
    const agent = cog.agent as Record<string, unknown>
    expect(agent.system_prompt).toBe('你好')
  })

  it('selectNode sets selectedNodeId and switches inspector to node mode', () => {
    const store = useWorkbenchStore()
    store.selectNode('emp-identity')
    expect(store.selectedNodeId).toBe('emp-identity')
    expect(store.inspectorMode).toBe('node')
  })

  it('selectNode(null) switches inspector to library mode', () => {
    const store = useWorkbenchStore()
    store.selectNode('emp-identity')
    store.selectNode(null)
    expect(store.selectedNodeId).toBeNull()
    expect(store.inspectorMode).toBe('library')
  })

  it('chat message push and chunk append', () => {
    const store = useWorkbenchStore()
    store.pushChatMessage({ id: 'msg-1', role: 'user', content: 'hello', ts: Date.now() })
    store.pushChatMessage({ id: 'msg-2', role: 'assistant', content: '', ts: Date.now() })
    store.appendChatChunk('msg-2', '你好')
    store.appendChatChunk('msg-2', '！')
    expect(store.chatMessages[1].content).toBe('你好！')
  })

  it('employee draft pipeline: reset, SSE reducer, review_reply, pipeline_done', () => {
    const store = useWorkbenchStore()
    store.resetEmployeeDraftPipeline()
    expect(store.employeeDraftStatus.phase).toBe('idle')

    store.applyEmployeeDraftSseEvent({ event: 'stage_start', stage: 'parse_intent' })
    expect(store.employeeDraftStages.parse_intent.status).toBe('running')

    store.applyEmployeeDraftSseEvent({ event: 'review_reply', message: '请确认行业字段' })
    expect(store.employeeDraftReviewMessages).toHaveLength(1)
    expect(store.employeeDraftReviewMessages[0].content).toContain('行业')

    store.applyEmployeeDraftSseEvent({ event: 'pipeline_done', manifest: { ok: true } })
    expect(store.employeeDraftStatus.phase).toBe('done')
    expect(store.employeeDraftStatus.manifest).toEqual({ ok: true })
  })

  it('agent run lifecycle: start → pushEvent → finish', () => {
    const store = useWorkbenchStore()
    const run = {
      id: 'run-1',
      source: 'employee-draft' as const,
      brief: '测试员工',
      status: 'running' as const,
      events: [],
      manifest: null,
      startedAt: Date.now(),
      endedAt: null,
    }
    store.startRun(run)
    expect(store.currentRunId).toBe('run-1')
    expect(store.inspectorMode).toBe('run')

    store.pushRunEvent('run-1', { id: 'ev-1', stage: 'parse_intent', label: '解析意图', payload: null, status: 'done', ts: Date.now() })
    expect(store.agentRuns[0].events[0].stage).toBe('parse_intent')

    const manifest = { identity: { id: 'x', name: '测试' } }
    store.finishRun('run-1', 'done', manifest as Record<string, unknown>)
    expect(store.agentRuns[0].status).toBe('done')
    expect(store.agentRuns[0].manifest).toEqual(manifest)
    // manifest auto-applied to target
    expect(store.target.manifest).toEqual(manifest)
    expect(store.dirty).toBe(true)
  })

  it('setTarget with null id defaults to null', () => {
    const store = useWorkbenchStore()
    store.setTarget('employee', undefined as any, undefined, undefined)
    expect(store.target.id).toBeNull()
    expect(store.target.name).toBe('新员工')
  })

  it('setCanvasGraph sets nodes and edges', () => {
    const store = useWorkbenchStore()
    const nodes = [{ id: 'n1' }]
    const edges = [{ id: 'e1' }]
    store.setCanvasGraph(nodes, edges)
    expect(store.canvasNodes).toEqual(nodes)
    expect(store.canvasEdges).toEqual(edges)
  })

  it('setChatStreaming sets streaming state and abort controller', () => {
    const store = useWorkbenchStore()
    const ctrl = new AbortController()
    store.setChatStreaming(true, ctrl)
    expect(store.chatStreaming).toBe(true)
    store.setChatStreaming(false)
    expect(store.chatStreaming).toBe(false)
  })

  it('abortChat stops streaming', () => {
    const store = useWorkbenchStore()
    store.setChatStreaming(true, new AbortController())
    store.abortChat()
    expect(store.chatStreaming).toBe(false)
  })

  it('appendChatChunk does nothing for non-existent message id', () => {
    const store = useWorkbenchStore()
    store.pushChatMessage({ id: 'msg-1', role: 'user', content: 'hello', ts: Date.now() })
    store.appendChatChunk('non-existent', 'chunk')
    expect(store.chatMessages[0].content).toBe('hello')
  })

  it('pushRunEvent updates existing event with same stage', () => {
    const store = useWorkbenchStore()
    const run = {
      id: 'run-1',
      source: 'employee-draft' as const,
      brief: 'test',
      status: 'running' as const,
      events: [],
      manifest: null,
      startedAt: Date.now(),
      endedAt: null,
    }
    store.startRun(run)
    store.pushRunEvent('run-1', { id: 'ev-1', stage: 'parse_intent', label: '解析', payload: null, status: 'running' as const, ts: Date.now() })
    store.pushRunEvent('run-1', { id: 'ev-2', stage: 'parse_intent', label: '解析完成', payload: { data: 1 }, status: 'done' as const, ts: Date.now() })
    expect(store.agentRuns[0].events).toHaveLength(1)
    expect(store.agentRuns[0].events[0].status).toBe('done')
  })

  it('pushRunEvent ignores non-existent run', () => {
    const store = useWorkbenchStore()
    store.pushRunEvent('non-existent', { id: 'ev-1', stage: 's', label: 'l', payload: null, status: 'done' as const, ts: Date.now() })
    expect(store.agentRuns).toHaveLength(0)
  })

  it('finishRun ignores non-existent run', () => {
    const store = useWorkbenchStore()
    store.finishRun('non-existent', 'done', null)
    expect(store.agentRuns).toHaveLength(0)
  })

  it('finishRun without manifest does not auto-apply', () => {
    const store = useWorkbenchStore()
    const originalManifest = { ...store.target.manifest }
    const run = {
      id: 'run-1',
      source: 'employee-draft' as const,
      brief: 'test',
      status: 'running' as const,
      events: [],
      manifest: null,
      startedAt: Date.now(),
      endedAt: null,
    }
    store.startRun(run)
    store.finishRun('run-1', 'done', null)
    expect(store.agentRuns[0].endedAt).not.toBeNull()
  })

  it('finishRun with error status does not auto-apply manifest', () => {
    const store = useWorkbenchStore()
    const run = {
      id: 'run-1',
      source: 'employee-draft' as const,
      brief: 'test',
      status: 'running' as const,
      events: [],
      manifest: null,
      startedAt: Date.now(),
      endedAt: null,
    }
    store.startRun(run)
    const manifest = { identity: { id: 'x' } }
    store.finishRun('run-1', 'error', manifest as Record<string, unknown>)
    expect(store.agentRuns[0].manifest).toEqual(manifest)
  })

  it('setResearch updates context and sources', () => {
    const store = useWorkbenchStore()
    store.setResearch('context text', ['source1', 'source2'])
    expect(store.researchContext).toBe('context text')
    expect(store.researchSources).toEqual(['source1', 'source2'])
  })

  it('markEmployeeDraftPipelineAborted sets error when running', () => {
    const store = useWorkbenchStore()
    store.employeeDraftStatus.phase = 'running'
    store.markEmployeeDraftPipelineAborted()
    expect(store.employeeDraftStatus.phase).toBe('error')
    expect(store.employeeDraftStatus.fatalError).toBe('已取消')
  })

  it('markEmployeeDraftPipelineAborted does nothing when not running', () => {
    const store = useWorkbenchStore()
    store.employeeDraftStatus.phase = 'idle'
    store.markEmployeeDraftPipelineAborted()
    expect(store.employeeDraftStatus.phase).toBe('idle')
  })

  it('applyEmployeeDraftSseEvent handles clarification_question', () => {
    const store = useWorkbenchStore()
    store.applyEmployeeDraftSseEvent({ event: 'clarification_question', message: '请确认' })
    expect(store.employeeDraftReviewMessages).toHaveLength(1)
    expect(store.employeeDraftReviewMessages[0].kind).toBe('clarification_question')
  })

  it('applyEmployeeDraftSseEvent ignores empty message', () => {
    const store = useWorkbenchStore()
    store.applyEmployeeDraftSseEvent({ event: 'review_reply', message: '' })
    expect(store.employeeDraftReviewMessages).toHaveLength(0)
  })

  it('loadEligibleWorkflows populates workflows on success', async () => {
    vi.mocked(api.listEmployeeEligibleWorkflows).mockResolvedValue({
      workflows: [{ id: 1 }],
      all_workflows: [{ id: 1 }, { id: 2 }],
    })
    const store = useWorkbenchStore()
    await store.loadEligibleWorkflows()
    expect(store.eligibleWorkflows).toEqual([{ id: 1 }])
    expect(store.allWorkflowOptions).toEqual([{ id: 1 }, { id: 2 }])
    expect(store.workflowGateLoading).toBe(false)
  })

  it('loadEligibleWorkflows falls back to eligible when all_workflows missing', async () => {
    vi.mocked(api.listEmployeeEligibleWorkflows).mockResolvedValue({
      workflows: [{ id: 1 }],
    })
    const store = useWorkbenchStore()
    await store.loadEligibleWorkflows()
    expect(store.allWorkflowOptions).toEqual([{ id: 1 }])
  })

  it('loadEligibleWorkflows clears workflows on error', async () => {
    vi.mocked(api.listEmployeeEligibleWorkflows).mockRejectedValue(new Error('fail'))
    const store = useWorkbenchStore()
    await store.loadEligibleWorkflows()
    expect(store.eligibleWorkflows).toEqual([])
    expect(store.allWorkflowOptions).toEqual([])
    expect(store.workflowGateLoading).toBe(false)
  })

  it('selectedNode returns null when no node selected', () => {
    const store = useWorkbenchStore()
    expect(store.selectedNode).toBeNull()
  })

  it('selectedNode returns matching node', () => {
    const store = useWorkbenchStore()
    store.setCanvasGraph([{ id: 'n1' }, { id: 'n2' }], [])
    store.selectNode('n1')
    expect(store.selectedNode).toEqual({ id: 'n1' })
  })

  it('currentRun returns null when no run', () => {
    const store = useWorkbenchStore()
    expect(store.currentRun).toBeNull()
  })
})
