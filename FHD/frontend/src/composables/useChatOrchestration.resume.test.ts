import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { useChatOrchestration } from './useChatOrchestration'
import { resetChatMessageStores } from './useChatMessages'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'

function eventStream() {
  let controller: ReadableStreamDefaultController<Uint8Array>
  let open = true
  const body = new ReadableStream<Uint8Array>({
    start(value) { controller = value },
    cancel() { open = false },
  })
  return {
    response: new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }),
    emit(event: unknown, type = '', id = '') {
      if (open) controller.enqueue(new TextEncoder().encode(`${id ? `id: ${id}\n` : ''}${type ? `event: ${type}\n` : ''}data: ${JSON.stringify(event)}\n\n`))
    },
    close() { if (open) { open = false; controller.close() } },
  }
}

function conversation(id = 'original') {
  return {
    success: true, id, durable: true, revision: 1,
    messages: [{ id: id === 'original' ? 1 : 2, role: 'user', content: `请求 ${id}`, metadata: { ui: { turnId: `${id}-turn` } } }],
    ...(id === 'original' ? {
      active_turn: { turn_id: 'original-turn', run_id: 'original-run', task_id: 'original-task', status: 'running' },
    } : {}),
  }
}

describe('persisted chat turn observation through the real SDK and task workspace', () => {
  let wrapper: VueWrapper
  let api: ReturnType<typeof useChatOrchestration>
  let sessionId: ReturnType<typeof ref<string>>
  let taskStatus: string
  let readReceipt: () => Promise<unknown>
  let receiptHttpStatus: number
  let fetchMock: ReturnType<typeof vi.fn<typeof fetch>>
  let resumed: Array<ReturnType<typeof eventStream> & { signal?: AbortSignal | null }>
  let otherStreams: Array<ReturnType<typeof eventStream>>
  let runStreams: Array<ReturnType<typeof eventStream>>
  let mountChat: () => void

  beforeEach(async () => {
    vi.useFakeTimers()
    localStorage.clear()
    localStorage.setItem('xcagi_chat_tts_enabled', '0')
    resetChatMessageStores()
    const pinia = createPinia()
    setActivePinia(pinia)
    sessionId = ref('original')
    taskStatus = 'running'
    resumed = []
    otherStreams = []
    runStreams = []
    readReceipt = async () => ({ success: true, id: 'original', durable: true, revision: 1, messages: [] })
    receiptHttpStatus = 200
    const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
    // Only the HTTP boundary is replaced. Message storage, task projection,
    // SSE parsing and AI SDK assembly all use their production implementations.
    fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), window.location.origin)
      if (url.pathname === '/api/conversations/sessions') return json({ success: true, sessions: [{ session_id: 'original', message_count: 2 }] })
      if (url.pathname.startsWith('/api/conversations/')) {
        return url.searchParams.has('turn_id') ? json(await readReceipt(), receiptHttpStatus) : json(conversation(url.pathname.split('/').at(-1)))
      }
      if (url.pathname === '/api/ai/chat/stream/resume') {
        const stream = { ...eventStream(), signal: init?.signal }
        resumed.push(stream)
        return stream.response
      }
      if (url.pathname === '/api/agent/tasks') {
        return json({ success: true, data: [{
          task_id: 'original-task', active_run_id: 'original-run', status: taskStatus,
          conversation_id: 'original', title: '核对已提交的附件',
        }] })
      }
      if (url.pathname.endsWith('/events/stream')) {
        const stream = eventStream()
        otherStreams.push(stream)
        if (url.pathname.includes('/api/agent/runs/')) runStreams.push(stream)
        init?.signal?.addEventListener('abort', () => stream.close(), { once: true })
        return stream.response
      }
      return json({ success: true, data: [] })
    })
    vi.stubGlobal('fetch', fetchMock)
    mountChat = () => {
      wrapper = mount(defineComponent({
        setup() { api = useChatOrchestration({ sessionId }); return () => h('div') },
      }), { global: { plugins: [pinia] } })
    }
    mountChat()
    await flushPromises()
    await api.syncSessionMessages({ required: true })
    await api.refreshHistorySessions()
    await flushPromises()
    expect(resumed).toHaveLength(1)
    expect(api.messages.value.filter(message => message.role === 'ai')).toHaveLength(1)
  })

  afterEach(async () => {
    wrapper?.unmount()
    for (const stream of [...resumed, ...otherStreams]) stream.close()
    await flushPromises()
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
    vi.useRealTimers()
    resetChatMessageStores()
  })

  const receiptReads = () => fetchMock.mock.calls.filter(([url]) => String(url).includes('turn_id=original-turn') && String(url).includes('/api/conversations/'))
  const originalReply = () => api.messages.value.find(message => message.role === 'ai' && message.turnId === 'original-turn')!
  const terminalHistory = (status = 'completed', id = 'original', turnId = 'original-turn') => ({
    success: true, id, durable: true, revision: 1,
    turn_receipt: { turn_id: turnId, run_id: 'original-run', status, message_id: 8 },
    messages: [{ id: 8, role: 'assistant', content: '原文件交付已恢复', metadata: {
      summary: { status, turn_id: turnId }, ui: { turnId, outputArtifacts: [{
        run_id: 'original-run', artifact_id: 'xlsx_result', artifact_type: 'file', name: '结果.xlsx',
        uri: '/api/agent/runs/original-run/artifacts/xlsx_result', metadata: { sha256: 'a'.repeat(64), size_bytes: 123 },
      }] },
    } }],
  })

  async function beginQueuedTurn(transport: 'stream' | 'json', backfilledHistory = false) {
    sessionId.value = 'fresh'
    await api.syncSessionMessages({ required: true })
    vi.stubEnv('VITE_CHAT_STREAM', transport === 'stream' ? 'true' : 'false')
    const originalFetch = fetchMock.getMockImplementation()!
    let turnId = ''
    taskStatus = 'queued'
    fetchMock.mockImplementation(async (input, init) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname === '/api/conversations/fresh' && !url.searchParams.has('turn_id') && turnId) {
        return Response.json({ success: true, id: 'fresh', durable: true, revision: 1, messages: [
          ...conversation('fresh').messages,
          ...(backfilledHistory ? [{ id: 72, role: 'assistant', content: '已保存的上一轮答复' }] : []),
          { id: 73, role: 'user', content: '请整理本次资料', metadata: { ui: { turnId } } },
          { id: 74, role: 'assistant', content: '等待后台执行', metadata: {
            business_harness: { queued_reply: true },
            summary: { turn_id: turnId, run_id: 'original-run', status: 'queued' },
            ui: { turnId, workflowAction: 'queued' },
          } },
        ] })
      }
      if (['/api/ai/chat/stream', '/api/ai/unified_chat'].includes(url.pathname) && init?.method === 'POST') {
        turnId = JSON.parse(String(init.body)).context.turn_id
        const result = { success: false, runtime: 'xiaox', execution_state: 'queued',
          run_id: 'original-run', response: '等待后台执行',
          history_persistence: { status: 'saved', turn_id: turnId, revision: 1, message_ids: [73, 74] },
        }
        return transport === 'stream'
          ? new Response(`data: ${JSON.stringify({ type: 'done', result })}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } })
          : Response.json(result)
      }
      return originalFetch(input, init)
    })
    await api.sendMessage('请整理本次资料')
    await api.refreshTasks()
    await flushPromises()
    const reply = api.messages.value.find(message => message.role === 'ai' && message.turnId === turnId)!
    expect(reply.workflowAction).toBe('queued')
    const publishReceipt = async (receipt: unknown) => {
      readReceipt = async () => receipt
      taskStatus = 'completed'
      await api.refreshTasks()
      await flushPromises()
    }
    return { turnId, reply, publishReceipt }
  }

  it.each(['stream', 'json'] as const)('replaces the original queued turn with its persisted %s reply without another send', async transport => {
    const { turnId, reply, publishReceipt } = await beginQueuedTurn(transport)
    const content = transport === 'stream' ? '本轮正式结果' : '原任务的持久化答复'
    await publishReceipt({ success: true, id: 'fresh', durable: true, revision: 1,
      turn_receipt: { turn_id: turnId, run_id: 'original-run', status: 'completed', message_id: 74 },
      messages: [{ id: 74, role: 'assistant', content }],
    })
    await flushPromises()
    expect(reply).toMatchObject({ content, serverMessageId: 74, workflowAction: 'completed',
      persistence: { id: 'server:74', status: 'saved', durable: true } })
    expect(api.messages.value.filter(message => message.role === 'ai' && message.turnId === turnId)).toEqual([reply])
    const reads = fetchMock.mock.calls.filter(([url]) => String(url).includes(`/conversations/fresh?turn_id=${turnId}`))
    expect(reads).toHaveLength(1)
    const writes = fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')
    expect(writes).toHaveLength(1)
    expect(String(writes[0][0])).toContain(transport === 'stream' ? '/api/ai/chat/stream' : '/api/ai/unified_chat')
  })

  it.each(['stream', 'json'] as const)('rebinds %s observation after SQL refresh replaces the queued message', async transport => {
    const { turnId, publishReceipt } = await beginQueuedTurn(transport, true)
    await publishReceipt({ success: true, id: 'fresh', durable: true, revision: 1,
      turn_receipt: { turn_id: turnId, run_id: 'original-run', status: 'completed', message_id: 74 },
      messages: [{ id: 74, role: 'assistant', content: 'Word 原文已核验并完成概述' }],
    })
    const replies = api.messages.value.filter(message => message.role === 'ai' && message.turnId === turnId)
    expect(replies).toHaveLength(1)
    expect(replies[0]).toMatchObject({ content: 'Word 原文已核验并完成概述', workflowAction: 'completed' })
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
    expect(resumed).toHaveLength(1)
  })

  it('shows the bound persisted run-only reconciliation receipt in the original queued bubble', async () => {
    const { turnId, reply, publishReceipt } = await beginQueuedTurn('stream')
    await publishReceipt({ success: true, id: 'fresh', durable: true, revision: 1,
      turn_receipt: { turn_id: turnId, run_id: 'original-run', status: 'unknown', receipt_kind: 'run',
        durable: true, requires_reconciliation: true, message: '原任务结果尚待核对，请勿重复提交。' },
      messages: [{ id: 74, role: 'assistant', content: '等待后台执行' }],
    })
    await flushPromises()
    expect(reply).toMatchObject({ turnId, workflowAction: 'unknown', content: '原任务结果尚待核对，请勿重复提交。' })
    expect(api.messages.value.filter(message => message.role === 'ai' && message.turnId === turnId)).toEqual([reply])
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
  })

  it.each(['missing', 'queued', 'queued_row'])('keeps a newly queued turn observed while its original history is %s beyond 30 seconds', async pending => {
    sessionId.value = 'fresh'
    await api.syncSessionMessages({ required: true })
    const originalFetch = fetchMock.getMockImplementation()!
    let turnId = ''
    taskStatus = 'completed'
    fetchMock.mockImplementation(async (input, init) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname === '/api/ai/chat/stream' && init?.method === 'POST') {
        turnId = JSON.parse(String(init.body)).context.turn_id
        return new Response(`data: ${JSON.stringify({ type: 'done', result: { success: false, runtime: 'xiaox',
          execution_state: 'queued', run_id: 'original-run', response: '任务已受理',
          history_persistence: { status: 'saved', turn_id: turnId, revision: 1, message_ids: [1, 8] },
        } })}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } })
      }
      return originalFetch(input, init)
    })
    readReceipt = async () => ({ success: true, id: 'fresh', durable: true, revision: 1, messages: [],
      ...(pending === 'queued' ? { active_turn: { turn_id: turnId, run_id: 'original-run', status: 'queued' } } : {}),
      ...(pending === 'queued_row' ? { turn_receipt: { turn_id: turnId, run_id: 'original-run', status: 'queued', message_id: 8 },
        messages: [{ id: 8, role: 'assistant', content: '旧排队回执' }] } : {}),
    })
    await api.sendMessage('请整理本次资料')
    await vi.advanceTimersByTimeAsync(31_000)
    const reply = api.messages.value.find(message => message.role === 'ai' && message.turnId === turnId)!
    expect(reply.workflowAction).toBe('unknown')
    expect(reply.toolProgressLabel).toBeUndefined()
    readReceipt = async () => terminalHistory('completed', 'fresh', turnId)
    await vi.advanceTimersByTimeAsync(45_000)
    expect(reply.workflowAction).toBe('completed')
    expect(reply.content).toContain('原文件交付已恢复')
    expect(reply.outputArtifacts?.[0].metadata).toEqual({ sha256: 'a'.repeat(64), size_bytes: 123 })
    expect(api.messages.value.filter(message => message.role === 'ai' && message.turnId === turnId)).toEqual([reply])
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1)
    expect(resumed).toHaveLength(1)
  })

  it('reopens an undelivered SQL queue row even when no active_turn remains', async () => {
    wrapper.unmount()
    taskStatus = 'completed'
    const originalFetch = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation(async (input, init) => {
      const url = new URL(String(input), window.location.origin)
      if (url.pathname === '/api/conversations/original' && !url.searchParams.has('turn_id')) {
        return new Response(JSON.stringify({ success: true, id: 'original', durable: true, revision: 1,
          messages: [{ id: 8, role: 'assistant', content: '原任务已受理', metadata: JSON.stringify({
            business_harness: { queued_reply: true, turn_id: 'original-turn', run_id: 'original-run' },
            summary: { turn_id: 'original-turn', run_id: 'original-run', status: 'queued' },
          }) }],
        }), { headers: { 'Content-Type': 'application/json' } })
      }
      return originalFetch(input, init)
    })
    mountChat()
    await api.syncSessionMessages({ required: true })
    await vi.advanceTimersByTimeAsync(31_000)
    const reply = originalReply()
    expect(reply.workflowAction).toBe('unknown')
    readReceipt = async () => terminalHistory()
    await vi.advanceTimersByTimeAsync(45_000)
    expect(originalReply()).toBe(reply)
    expect(reply.workflowAction).toBe('completed')
    expect(reply.serverMessageId).toBe(8)
    expect(reply.outputArtifacts).toHaveLength(1)
    expect(resumed).toHaveLength(1)
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  })

  it.each([401, 403, 404, 410])('stops read-only delivery observation after HTTP %i', async status => {
    taskStatus = 'completed'
    receiptHttpStatus = status
    await api.refreshTasks()
    await vi.advanceTimersByTimeAsync(1000)
    const reads = receiptReads().length
    expect(reads).toBe(1)
    expect(resumed[0].signal?.aborted).toBe(true)
    receiptHttpStatus = 200
    readReceipt = async () => terminalHistory()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(receiptReads()).toHaveLength(reads)
    expect(originalReply().workflowAction).toBe([401, 403].includes(status) ? 'waiting_auth' : 'unknown')
  })

  it.each(['session', 'revision', 'turn', 'run', 'deleted'])('retires delivery when the original %s binding changes', async field => {
    taskStatus = 'completed'
    readReceipt = async () => {
      const data = terminalHistory()
      if (field === 'session') data.id = 'other'
      if (field === 'revision') data.revision = 2
      if (field === 'deleted') return { ...data, revision: null, messages: [] }
      if (field === 'turn') data.turn_receipt.turn_id = 'other-turn'
      if (field === 'run') data.turn_receipt.run_id = 'other-run'
      return data
    }
    await api.refreshTasks()
    await vi.advanceTimersByTimeAsync(1000)
    expect(originalReply().workflowAction).toBe('unknown')
    expect(originalReply().content).not.toContain('原文件交付已恢复')
    expect(resumed[0].signal?.aborted).toBe(true)
    const reads = receiptReads().length
    readReceipt = async () => terminalHistory()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(receiptReads()).toHaveLength(reads)
  })

  it.each([['failed', 'error'], ['cancelled', 'stopped']] as const)('finishes %s with the matching session activity', async (status, activity) => {
    taskStatus = status
    readReceipt = async () => terminalHistory(status)
    await api.refreshTasks()
    await vi.advanceTimersByTimeAsync(1000)
    expect(originalReply().workflowAction).toBe(status)
    expect(api.historySessions.value.find(session => session.session_id === 'original')?.activity).toBe(activity)
  })

  it.each(['open', 'reopened'])('delivers the original row and files after more than 30 seconds with the chat %s', async mode => {
    taskStatus = 'completed'
    if (mode === 'reopened') {
      wrapper.unmount()
      mountChat()
      await api.syncSessionMessages({ required: true })
    }
    const reply = originalReply()
    await api.refreshTasks()
    await vi.advanceTimersByTimeAsync(31_000)
    expect(reply.workflowAction).toBe('unknown')
    expect(reply.toolProgressLabel).toBeUndefined()
    const file = { run_id: 'original-run', artifact_id: 'xlsx_result', artifact_type: 'file', name: '结果.xlsx',
      uri: '/api/agent/runs/original-run/artifacts/xlsx_result', metadata: { sha256: 'a'.repeat(64), size_bytes: 123 } }
    readReceipt = async () => ({ success: true, id: 'original', durable: true, revision: 1,
      turn_receipt: { turn_id: 'original-turn', run_id: 'original-run', status: 'completed', message_id: 8 },
      messages: [{ id: 8, role: 'assistant', content: '原文件交付已恢复', metadata: {
        summary: { status: 'completed', turn_id: 'original-turn' }, ui: { turnId: 'original-turn', outputArtifacts: [file] },
      } }],
    })
    await vi.advanceTimersByTimeAsync(45_000)
    expect(originalReply()).toBe(reply)
    expect(reply.workflowAction).toBe('completed')
    expect(reply.content).toContain('原文件交付已恢复')
    expect(reply.outputArtifacts).toEqual([file])
    expect(reply.serverMessageId).toBe(8)
    await api.refreshHistorySessions()
    expect(api.historySessions.value.find(session => session.session_id === 'original')?.activity).toBe('ready')
    expect(api.messages.value.filter(message => message.role === 'ai')).toEqual([reply])
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  })

  it.each(['stream', 'history'])('restores delivered files from the %s receipt without another page reload', async source => {
    const reply = originalReply()
    const file = { run_id: 'original-run', artifact_id: 'xlsx_result', artifact_type: 'file', name: '结果.xlsx',
      uri: '/api/agent/runs/original-run/artifacts/xlsx_result', metadata: { sha256: 'a'.repeat(64), size_bytes: 123 } }
    if (source === 'stream') {
      resumed[0].emit({ type: 'done', result: { success: true, response: '结果文件已保存', data: { output_artifacts: [file] } } })
      resumed[0].close()
    } else {
      readReceipt = async () => ({ success: true, id: 'original', durable: true, revision: 1,
        turn_receipt: { turn_id: 'original-turn', run_id: 'original-run', status: 'completed', message: '结果文件已保存', message_id: 8 },
        messages: [{ id: 8, role: 'assistant', content: '结果文件已保存', metadata: { ui: { turnId: 'original-turn', outputArtifacts: [file] } } }],
      })
      taskStatus = 'completed'
      await api.refreshTasks()
    }
    await vi.waitFor(() => expect(reply.workflowAction).toBe('completed'))
    expect(reply.outputArtifacts).toEqual([expect.objectContaining({ run_id: 'original-run', artifact_id: 'xlsx_result', uri: file.uri })])
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  })

  it('resumes one existing turn, renders native tool progress and finishes the same message', async () => {
    const reply = originalReply()
    await api.syncSessionMessages({ required: true })
    await flushPromises()
    expect(resumed).toHaveLength(1)
    expect(originalReply()).toBe(reply)
    expect(resumed[0].signal?.aborted).toBe(false)
    resumed[0].emit({ type: 'tool_call', node_id: 'import', tool_id: 'elt_import', action: 'preview', phase: 'started', label: '核对附件' })
    await flushPromises()
    expect(reply.toolProgressLabel).toBe('核对附件')
    expect(reply.liveSteps?.some(step => step.id === 'import')).toBe(true)
    resumed[0].emit({ type: 'tool_progress', label: '读取原任务回执' })
    await flushPromises()
    expect(reply.toolProgressLabel).toBe('读取原任务回执')
    resumed[0].emit({ type: 'done', result: { success: true, response: '原任务已经完成，未重复提交。' } })
    resumed[0].close()
    await vi.waitFor(() => expect(reply.workflowAction).toBe('completed'))
    expect(reply.content).toContain('原任务已经完成，未重复提交。')
    expect(reply.toolProgressLabel).toBeUndefined()
    expect(reply.recoveryTaskId).toBe('original-task')
    expect(resumed[0].signal?.aborted).toBe(true)
    expect(api.messages.value.filter(message => message.role === 'ai')).toEqual([reply])
    expect(fetchMock.mock.calls.filter(([url]) => /\/api\/ai\/chat(?:\/stream)?(?:\?|$)/.test(String(url)))).toHaveLength(0)
  })

  it.each(['waiting_auth', 'unknown'])('keeps %s when observing an authorization pause', async expectedState => {
    const reply = originalReply()
    resumed[0].emit({ type: 'requires_token', token_name: 'write', token_description: '批准原任务' })
    if (expectedState === 'unknown') {
      resumed[0].emit({ type: 'done', result: { success: true, execution_state: 'unknown', response: '原任务结果待核对。' } })
    }
    resumed[0].close()
    await vi.waitFor(() => expect(reply.workflowAction).toBe(expectedState))
    expect(reply.content).not.toContain('已经完成')
    expect(resumed[0].signal?.aborted).toBe(true)
    expect(receiptReads()).toHaveLength(0)
  })

  it.each(['child_approval', 'authorization'])('keeps %s ahead of a runtime completion envelope when observing the original turn', async kind => {
    const reply = originalReply()
    resumed[0].emit({ type: 'done', result: {
      success: true, response: '原任务仍在等待授权。', runtime: 'codex', run_id: 'original-run', execution_state: 'completed',
      runtime_context_update: { agent_runtime_run_id: 'original-run', conversation_id: 'original', status: 'waiting_approval' },
      ...(kind === 'child_approval'
        ? { data: { action: 'approval_pending', data: { approval_card: { run_id: 'original-child', approval_required: true } } } }
        : { requires_token: true }),
    } })
    resumed[0].close()
    await vi.waitFor(() => expect(reply.workflowAction).toBe(kind === 'child_approval' ? 'waiting_approval' : 'waiting_auth'))
    expect(reply.runtimeContinuation).toEqual({ runId: 'original-run', status: 'waiting_approval', sessionId: 'original' })
    if (kind === 'child_approval') expect(reply.approvalCard?.run_id).toBe('original-child')
    else expect(reply.approvalCard).toBeUndefined()
    expect(api.messages.value.filter(message => message.role === 'ai')).toEqual([reply])
    expect(resumed[0].signal?.aborted).toBe(true)
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
    expect(receiptReads()).toHaveLength(0)
  })

  it.each(['waiting_auth', 'unknown'])(
    'keeps %s without posting after a retired unlock event or sending password authorization',
    async expectedState => {
      sessionId.value = 'fresh'
      await api.syncSessionMessages({ required: true })
      await flushPromises()
      const originalFetch = fetchMock.getMockImplementation()!
      fetchMock.mockImplementation(async (input, init) => {
        const url = new URL(input instanceof Request ? input.url : String(input), window.location.origin)
        if (url.pathname === '/api/ai/chat/stream' && init?.method === 'POST') {
          const result = expectedState === 'unknown'
            ? { success: true, execution_state: 'unknown', requires_reconciliation: true, response: '原任务结果待核对。' }
            : { success: true, response: '' }
          return new Response(
            'data: {"type":"requires_token","token_name":"DB_WRITE_TOKEN","run_id":"waiting-original-run"}\n\n'
            + `data: ${JSON.stringify({ type: 'done', result })}\n\n`,
            { headers: { 'Content-Type': 'text/event-stream' } },
          )
        }
        return originalFetch(input, init)
      })
      localStorage.setItem('xcagi_db_read_token', 'retired-read-secret')
      localStorage.setItem('xcagi_db_write_token', 'retired-write-secret')
      const prompt = vi.fn()
      window.addEventListener('xcagi:prompt-db-write-token', prompt)
      try {
        await api.sendMessage('请核对本轮资料')
        const chatPosts = () => fetchMock.mock.calls.filter(([url, init]) =>
          String(url).includes('/api/ai/chat/stream') && init?.method === 'POST')
        expect(chatPosts()).toHaveLength(1)
        const body = JSON.parse(String(chatPosts()[0][1]?.body))
        expect(body.context.turn_id).toBeTruthy()
        expect(JSON.stringify(body)).not.toMatch(/db_read_token|db_write_token|chat_db_write_authorized|db_write_stream_resume|retired-/)
        const postsBeforeUnlock = fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST').length
        window.dispatchEvent(new CustomEvent('fhd-db-write-unlocked'))
        window.dispatchEvent(new CustomEvent('fhd-db-write-unlocked'))
        await flushPromises()
        expect(chatPosts()).toHaveLength(1)
        expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(postsBeforeUnlock)
        expect(prompt).not.toHaveBeenCalled()
        expect(api.messages.value.filter(message => message.role === 'ai').at(-1)?.workflowAction).toBe(expectedState)
      } finally {
        window.removeEventListener('xcagi:prompt-db-write-token', prompt)
      }
    },
  )

  it('reads a saved blocked receipt instead of leaving only the progress note', async () => {
    const reply = originalReply()
    taskStatus = 'waiting_user'
    await api.refreshTasks()
    await flushPromises()
    expect(reply.workflowAction).toBe('waiting_approval')
    expect(reply.content).toContain('等待确认')
    taskStatus = 'blocked'
    readReceipt = async () => ({ ...terminalHistory('blocked'), messages: [{
      id: 8, role: 'assistant', content: '15 题未完成，原任务已阻断。',
      metadata: { summary: { status: 'blocked', turn_id: 'original-turn' } },
    }] })
    await api.refreshTasks()
    await flushPromises()
    expect(reply.workflowAction).toBe('blocked')
    expect(reply.content).toContain('15 题未完成')
    expect(resumed[0].signal?.aborted).toBe(true)
    expect(receiptReads()).toHaveLength(1)
  })

  it('keeps one observer and receipt backoff while a blocked turn has no saved reply yet', async () => {
    const reply = originalReply()
    let resolveReceipt!: (value: unknown) => void
    readReceipt = () => new Promise(resolve => { resolveReceipt = resolve })
    taskStatus = 'blocked'
    await api.refreshTasks()
    await flushPromises()
    await api.refreshTasks()
    await flushPromises()
    expect(receiptReads()).toHaveLength(1)
    const blocked = { success: true, id: 'original', durable: true, revision: 1, messages: [],
      active_turn: { turn_id: 'original-turn', run_id: 'original-run', task_id: 'original-task', status: 'blocked' },
    }
    resolveReceipt(blocked)
    await flushPromises()
    expect(runStreams).toHaveLength(1)
    expect(resumed).toHaveLength(1)
    expect(originalReply()).toBe(reply)
    readReceipt = async () => blocked
    await api.refreshTasks()
    await vi.advanceTimersByTimeAsync(1999)
    await api.refreshTasks()
    await flushPromises()
    expect(receiptReads()).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(1)
    await api.refreshTasks()
    await flushPromises()
    expect(receiptReads()).toHaveLength(2)
    readReceipt = async () => terminalHistory('blocked')
    await vi.advanceTimersByTimeAsync(3999)
    await api.refreshTasks()
    await flushPromises()
    expect(receiptReads()).toHaveLength(2)
    await vi.advanceTimersByTimeAsync(1)
    await api.refreshTasks()
    await flushPromises()
    expect(receiptReads()).toHaveLength(3)
    expect(reply.workflowAction).toBe('blocked')
    expect(reply.content).toContain('原文件交付已恢复')
    expect(runStreams).toHaveLength(1)
    expect(resumed).toHaveLength(1)
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  })

  it.each(['blocked', 'completed'])('clears active model and tool indicators after a saved %s receipt', async status => {
    const reply = originalReply()
    runStreams[0].emit({ event_id: 'tool-start', run_id: 'original-run', event_type: 'runtime.xiaox.item.started',
      data: { item_type: 'mcpToolCall', item_id: 'tool-1', tool_id: 'elt_import', action: 'preview' } }, 'runtime.xiaox.item.started', 'tool-start')
    runStreams[0].emit({ event_id: 'model-start', run_id: 'original-run', event_type: 'runtime.model.started',
      data: { request_id: 'model-1' } }, 'runtime.model.started', 'model-start')
    resumed[0].emit({ type: 'tool_call', node_id: 'import', tool_id: 'elt_import', action: 'preview', phase: 'started', label: '核对附件' })
    await flushPromises()
    expect(reply.waitingHint).toContain('模型正在分析')
    expect(reply.liveSteps?.some(step => step.state === 'running')).toBe(true)
    taskStatus = status
    readReceipt = async () => terminalHistory(status)
    await api.refreshTasks()
    await flushPromises()
    expect(reply.workflowAction).toBe(status)
    expect(reply.content).toContain('原文件交付已恢复')
    expect(reply.waitingHint).toBeUndefined()
    expect(reply.toolProgressLabel).toBeUndefined()
    expect(reply.liveSteps?.some(step => step.state === 'running')).toBe(false)
    expect(reply.agentRunTrace?.status).toBe(status === 'completed' ? 'success' : 'blocked')
    expect(reply.agentRunTrace?.phases.some(phase => phase.status === 'running')).toBe(false)
    expect(reply.agentRunTrace?.phases.find(phase => phase.kind === 'tool')?.status).toBe('waiting')
    expect(resumed[0].signal?.aborted).toBe(true)
  })

  it('projects durable model and tool events onto the original chat message', async () => {
    const reply = originalReply()
    expect(runStreams).toHaveLength(1)
    const emit = (type: string, data: Record<string, unknown>, id: string) =>
      runStreams[0].emit({ event_id: id, run_id: 'original-run', event_type: type, data }, type, id)
    emit('runtime.model.started', { request_id: 'model-1' }, 'e1')
    await flushPromises()
    expect(reply.waitingHint).toContain('模型正在分析')
    emit('runtime.model.completed', { request_id: 'model-1' }, 'e1b')
    await flushPromises()
    expect(reply.waitingHint).toBeUndefined()
    expect(reply.toolProgressLabel).toContain('模型响应已完成')
    emit('runtime.xiaox.item.started', { item_type: 'mcpToolCall', item_id: 'call-1',
      tool_id: 'excel_analysis', action: 'read' }, 'e2')
    await flushPromises()
    expect(reply.agentRunTrace?.phases).toEqual(expect.arrayContaining([
      expect.objectContaining({ kind: 'tool', status: 'running', node_id: 'call-1' }),
    ]))
    emit('runtime.xiaox.item.completed', { item_type: 'mcpToolCall', item_id: 'call-1',
      status: 'completed' }, 'e3')
    await flushPromises()
    expect(reply.agentRunTrace?.phases).toEqual(expect.arrayContaining([
      expect.objectContaining({ kind: 'tool', status: 'waiting', node_id: 'call-1' }),
    ]))
    taskStatus = 'blocked'
    readReceipt = async () => ({ ...terminalHistory('blocked'), messages: [{
      id: 8, role: 'assistant', content: '原任务核验未通过。',
      metadata: { summary: { status: 'blocked', turn_id: 'original-turn' } },
    }] })
    emit('runtime.xiaox.finished', {}, 'e4')
    await flushPromises()
    expect(reply.workflowAction).toBe('blocked')
    expect(reply.content).toContain('原任务核验未通过')
  })

  it('reads the original turn receipt when the task finishes and ignores another turn receipt', async () => {
    const reply = originalReply()
    readReceipt = async () => ({
      success: true, id: 'original', durable: true, revision: 1,
      turn_receipt: { turn_id: 'original-turn', run_id: 'original-run', status: 'completed', message_id: 8, message: '原会话保存的完成回执' },
      messages: [
        { id: 8, role: 'assistant', content: '原会话保存的完成回执', metadata: { summary: { turn_id: 'original-turn', success: true } } },
        { id: 9, role: 'assistant', content: '别的轮次', metadata: { summary: { turn_id: 'other-turn', success: true } } },
      ],
    })
    taskStatus = 'completed'
    await api.refreshTasks()
    await vi.waitFor(() => expect(reply.workflowAction).toBe('completed'))
    expect(reply.content).toContain('原会话保存的完成回执')
    expect(reply.content).not.toContain('别的轮次')
    expect(receiptReads()).toHaveLength(1)
    expect(resumed[0].signal?.aborted).toBe(true)
  })

  it.each(['missing', 'unavailable'])('keeps the business outcome unknown when the terminal task receipt is %s', async mode => {
    const reply = originalReply()
    readReceipt = async () => {
      if (mode === 'unavailable') throw new TypeError('connection unavailable')
      return { success: true, turn_receipt: { turn_id: 'other-turn', run_id: 'other-run', status: 'completed', message: '不能使用别的轮次回执' } }
    }
    taskStatus = 'completed'
    await api.refreshTasks()
    await vi.waitFor(() => expect(reply.workflowAction).toBe('unknown'))
    expect(reply.content).toContain(mode === 'missing' ? '原会话或任务回执已改变' : '业务结果请在原任务中核对')
    expect(reply.content).not.toContain('不能使用别的轮次回执')
    expect(resumed[0].signal?.aborted).toBe(mode === 'missing')
  })

  it.each(['switch', 'unmount', 'account', 'stop'])('isolates a late receipt after a session %s', async action => {
    const reply = originalReply()
    let resolveReceipt!: (value: unknown) => void
    readReceipt = () => new Promise(resolve => { resolveReceipt = resolve })
    taskStatus = 'completed'
    await api.refreshTasks()
    await vi.waitFor(() => expect(receiptReads()).toHaveLength(1))
    // A second task update while the read is pending must not issue another read.
    await api.refreshTasks()
    await flushPromises()
    expect(receiptReads()).toHaveLength(1)
    if (action === 'switch') {
      sessionId.value = 'new-session'
      await api.syncSessionMessages({ required: true })
    } else if (action === 'account') productReadAccountEpoch.value++
    else if (action === 'stop') api.stopReply()
    else wrapper.unmount()
    expect(resumed[0].signal?.aborted).toBe(true)
    resolveReceipt({ success: true, turn_receipt: { turn_id: 'original-turn', run_id: 'original-run', status: 'completed', message: '迟到的旧回执' } })
    await flushPromises()
    expect(reply.workflowAction).not.toBe('completed')
    expect(reply.content).not.toContain('迟到的旧回执')
    if (action === 'switch') {
      expect(api.messages.value.some(message => message.content.includes('请求 new-session'))).toBe(true)
      expect(api.messages.value.some(message => message.content.includes('迟到的旧回执'))).toBe(false)
    }
    expect(resumed).toHaveLength(1)
  })
})
