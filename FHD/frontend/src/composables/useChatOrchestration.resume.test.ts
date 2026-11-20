import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { useChatOrchestration } from './useChatOrchestration'
import { resetChatMessageStores } from './useChatMessages'

function eventStream() {
  let controller: ReadableStreamDefaultController<Uint8Array>
  let open = true
  const body = new ReadableStream<Uint8Array>({
    start(value) { controller = value },
    cancel() { open = false },
  })
  return {
    response: new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }),
    emit(event: unknown) {
      if (open) controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`))
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
  let fetchMock: ReturnType<typeof vi.fn<typeof fetch>>
  let resumed: Array<ReturnType<typeof eventStream> & { signal?: AbortSignal | null }>
  let otherStreams: Array<ReturnType<typeof eventStream>>

  beforeEach(async () => {
    localStorage.clear()
    localStorage.setItem('xcagi_chat_tts_enabled', '0')
    resetChatMessageStores()
    const pinia = createPinia()
    setActivePinia(pinia)
    sessionId = ref('original')
    taskStatus = 'running'
    resumed = []
    otherStreams = []
    readReceipt = async () => ({ success: true, messages: [] })
    const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })
    // Only the HTTP boundary is replaced. Message storage, task projection,
    // SSE parsing and AI SDK assembly all use their production implementations.
    fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), window.location.origin)
      if (url.pathname.startsWith('/api/conversations/')) {
        return json(url.searchParams.has('turn_id') ? await readReceipt() : conversation(url.pathname.split('/').at(-1)))
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
        init?.signal?.addEventListener('abort', () => stream.close(), { once: true })
        return stream.response
      }
      return json({ success: true, data: [] })
    })
    vi.stubGlobal('fetch', fetchMock)
    wrapper = mount(defineComponent({
      setup() { api = useChatOrchestration({ sessionId }); return () => h('div') },
    }), { global: { plugins: [pinia] } })
    await flushPromises()
    await api.syncSessionMessages({ required: true })
    await flushPromises()
    expect(resumed).toHaveLength(1)
    expect(api.messages.value.filter(message => message.role === 'ai')).toHaveLength(1)
  })

  afterEach(async () => {
    wrapper?.unmount()
    for (const stream of [...resumed, ...otherStreams]) stream.close()
    await flushPromises()
    vi.unstubAllGlobals()
    resetChatMessageStores()
  })

  const receiptReads = () => fetchMock.mock.calls.filter(([url]) => String(url).includes('turn_id=original-turn') && String(url).includes('/api/conversations/'))
  const originalReply = () => api.messages.value.find(message => message.role === 'ai' && message.turnId === 'original-turn')!

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

  it('keeps an explicit authorization pause instead of claiming a completed answer', async () => {
    const reply = originalReply()
    resumed[0].emit({ type: 'requires_token', token_name: 'write', token_description: '批准原任务' })
    resumed[0].close()
    await vi.waitFor(() => expect(reply.workflowAction).toBe('waiting_approval'))
    expect(reply.content).not.toContain('已经完成')
    expect(resumed[0].signal?.aborted).toBe(true)
    expect(receiptReads()).toHaveLength(0)
  })

  it('reflects waiting and blocked task states without replaying or completing the turn', async () => {
    const reply = originalReply()
    taskStatus = 'waiting_user'
    await api.refreshTasks()
    await flushPromises()
    expect(reply.workflowAction).toBe('waiting_approval')
    expect(reply.content).toContain('等待确认')
    taskStatus = 'blocked'
    await api.refreshTasks()
    await flushPromises()
    expect(reply.workflowAction).toBe('blocked')
    expect(reply.content).toContain('核对原任务的回执')
    expect(resumed[0].signal?.aborted).toBe(true)
    expect(receiptReads()).toHaveLength(0)
  })

  it('reads the original turn receipt when the task finishes and ignores another turn receipt', async () => {
    const reply = originalReply()
    readReceipt = async () => ({
      success: true, turn_receipt: { turn_id: 'original-turn', run_id: 'original-run', status: 'completed', message: '原会话保存的完成回执' },
      messages: [{ role: 'assistant', content: '别的轮次', metadata: { summary: { turn_id: 'other-turn', success: true } } }],
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
    expect(reply.content).toContain('业务结果请在原任务中核对')
    expect(reply.content).not.toContain('不能使用别的轮次回执')
    expect(resumed[0].signal?.aborted).toBe(true)
  })

  it.each(['switch', 'unmount'])('isolates a late receipt after a session %s', async action => {
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
    } else wrapper.unmount()
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
