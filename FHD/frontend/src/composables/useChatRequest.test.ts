import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { useChatRequest } from './useChatRequest'

vi.mock('@/api/chat', () => ({
  default: {
    sendChat: vi.fn().mockResolvedValue({ success: true, response: 'AI reply' }),
    sendUnifiedChat: vi.fn().mockResolvedValue({ success: true, response: 'AI reply' }),
    sendChatBatch: vi.fn().mockResolvedValue({ success: true }),
    sendUnifiedChatBatch: vi.fn().mockResolvedValue({ success: true }),
  },
}))

vi.mock('@/utils/typeGuards', () => ({
  asRecord: vi.fn((v) => v || {}),
  asArray: vi.fn((v) => (Array.isArray(v) ? v : [])),
  asString: vi.fn((v) => String(v ?? '')),
  asBoolean: vi.fn((v) => !!v),
  asDisposable: vi.fn(),
}))

function makeDeps() {
  return {
    messages: ref([{ role: 'user', content: 'previous message', time: '10:00' }]),
    sessionId: ref('session-1'),
    lastRequestContextSummary: ref(''),
    plannerWriteUnlockResumeDraft: ref(''),
    resolveChatDbTokensForPayload: () => ({}),
    injectExcelContextPayload: vi.fn(() => false),
    consumeMultimodalIntoPlannerContext: vi.fn(),
  }
}

describe('useChatRequest', () => {
  let request: ReturnType<typeof useChatRequest>

  beforeEach(() => {
    vi.clearAllMocks()
    request = useChatRequest(makeDeps())
  })

  it('returns request API', () => {
    expect(typeof request.buildPlannerChatRequestPayload).toBe('function')
    expect(typeof request.requestChatByMode).toBe('function')
    expect(typeof request.requestChatByModeBatch).toBe('function')
    expect(typeof request.getChatBatchDebounceMs).toBe('function')
    expect(typeof request.setLoadingProgress).toBe('function')
    expect(typeof request.startWaitProgressTimer).toBe('function')
    expect(typeof request.stopLoadingProgress).toBe('function')
    expect(typeof request.requestChatByModeWithTimeout).toBe('function')
    expect(typeof request.requestChatByModeBatchWithTimeout).toBe('function')
    expect(typeof request.resolveChatTimeoutMs).toBe('function')
    expect(typeof request.enqueueChatBatchMessage).toBe('function')
  })

  it('loadingProgressText has default value', () => {
    expect(request.loadingProgressText.value).toBe('处理中...')
  })

  it('setLoadingProgress updates text', () => {
    request.setLoadingProgress('正在分析...')
    expect(request.loadingProgressText.value).toBe('正在分析...')
  })

  it('setLoadingProgress uses default for empty string', () => {
    request.setLoadingProgress('')
    expect(request.loadingProgressText.value).toBe('处理中...')
  })

  it('keeps progress isolated when another task finishes in the background', () => {
    const deps = makeDeps()
    const scoped = useChatRequest(deps)
    scoped.setLoadingProgress('任务 A', 'task-a')
    deps.sessionId.value = 'task-b'
    scoped.setLoadingProgress('任务 B', 'task-b')
    scoped.stopLoadingProgress('task-a')
    expect(scoped.loadingProgressText.value).toBe('任务 B')
  })

  it('buildPlannerChatRequestPayload builds basic mode payload', () => {
    const { body } = request.buildPlannerChatRequestPayload('hello')
    expect(body.message).toBe('hello')
    expect(body.source).toBe('normal')
    expect(body.mode).toBe('basic')
    expect(body.user_id).toBe('web_normal_session-1')
  })

  it('marks auto approval mode in the planner context', async () => {
    const { useApprovalMode } = await import('./useApprovalMode')
    const mode = useApprovalMode()
    mode.setEnabled(true)
    mode.setMode('auto')
    try {
      const { body } = request.buildPlannerChatRequestPayload('清理知识库 全部')
      expect((body.context as Record<string, unknown>).chat_approval_mode).toBe('auto')
    } finally {
      mode.setEnabled(false)
      mode.setMode('manual')
    }
  })

  it('sends a model retry and a confirmed delete as separate decisions', () => {
    const retry = request.buildPlannerChatRequestPayload('清理全部客户和产品', {
      retryOf: 'turn-a',
      idempotencyKey: 'turn-a',
    }).body.context as Record<string, unknown>
    expect(retry.retry_of).toBe('turn-a')
    expect(retry.idempotency_key).toBe('turn-a')
    expect(retry.destructive_confirmed).toBeUndefined()
    const confirm = request.buildPlannerChatRequestPayload('清理全部客户和产品', {
      destructiveConfirmed: true,
      idempotencyKey: 'turn-a',
    }, { turnId: 'turn-new' }).body.context as Record<string, unknown>
    expect(confirm.destructive_confirmed).toBe(true)
    expect(confirm.idempotency_key).toBe('turn-a')
    expect(confirm.retry_of).toBeUndefined()
  })

  it('buildPlannerChatRequestPayload includes context with recent messages', () => {
    const { body } = request.buildPlannerChatRequestPayload('hello')
    const ctx = body.context as Record<string, unknown>
    expect(Array.isArray(ctx.recent_messages)).toBe(true)
    expect((ctx.recent_messages as unknown[]).length).toBeGreaterThan(0)
  })

  it('uses an immutable task scope after the visible conversation switches', () => {
    const { body } = request.buildPlannerChatRequestPayload('continue', undefined, {
      sessionId: 'task-original',
      turnId: 'turn-original',
      taskId: 'task-original',
      messages: [{ role: 'user', content: 'original context', time: '10:00' }],
    })
    const ctx = body.context as Record<string, unknown>
    expect(ctx.task_id).toBe('task-original')
    expect(ctx.turn_id).toBe('turn-original')
    expect(ctx.conversation_id).toBe('task-original')
    expect(ctx.recent_messages).toEqual([{ role: 'user', content: 'original context' }])
  })

  it('buildPlannerChatRequestPayload strips HTML from history', () => {
    const deps = makeDeps()
    deps.messages.value = [{ role: 'user', content: '<b>bold</b> text', time: '10:00' }]
    const req = useChatRequest(deps)
    const { body } = req.buildPlannerChatRequestPayload('hello')
    const ctx = body.context as Record<string, unknown>
    const history = ctx.recent_messages as Array<{ content: string }>
    expect(history[0].content).not.toContain('<b>')
  })

  it('buildPlannerChatRequestPayload keeps forty messages and does not stop at six', () => {
    const deps = makeDeps()
    deps.messages.value = Array.from({ length: 50 }, (_, i) => ({
      role: 'user' as const,
      content: `msg ${i}`,
      time: '10:00',
    }))
    const req = useChatRequest(deps)
    const { body } = req.buildPlannerChatRequestPayload('hello')
    const ctx = body.context as Record<string, unknown>
    const history = ctx.recent_messages as Array<{ content: string }>
    expect(history).toHaveLength(40)
    expect(history[0].content).toBe('msg 10')
    expect(history.at(-1)?.content).toBe('msg 49')
  })

  it('buildPlannerChatRequestPayload with fromWriteUnlock option', () => {
    const deps = makeDeps()
    deps.plannerWriteUnlockResumeDraft.value = 'draft content here'
    const req = useChatRequest(deps)
    const { body } = req.buildPlannerChatRequestPayload('hello', { fromWriteUnlock: true })
    const ctx = body.context as Record<string, unknown>
    expect(ctx.chat_db_write_authorized).toBe(true)
    expect(ctx.db_write_stream_resume).toBeDefined()
    expect(deps.plannerWriteUnlockResumeDraft.value).toBe('') // should be cleared
  })

  it('buildPlannerChatRequestPayload with fromWriteUnlock and empty draft', () => {
    const deps = makeDeps()
    deps.plannerWriteUnlockResumeDraft.value = ''
    const req = useChatRequest(deps)
    const { body } = req.buildPlannerChatRequestPayload('hello', { fromWriteUnlock: true })
    const ctx = body.context as Record<string, unknown>
    expect(ctx.db_write_stream_resume).toContain('续跑要求')
  })

  it('buildPlannerChatRequestPayload truncates long draft', () => {
    const deps = makeDeps()
    deps.plannerWriteUnlockResumeDraft.value = 'x'.repeat(10000)
    const req = useChatRequest(deps)
    const { body } = req.buildPlannerChatRequestPayload('hello', { fromWriteUnlock: true })
    const ctx = body.context as Record<string, unknown>
    const resume = String(ctx.db_write_stream_resume)
    expect(resume.length).toBeLessThan(10000)
  })

  it('buildPlannerChatRequestPayload updates lastRequestContextSummary', () => {
    const deps = makeDeps()
    const req = useChatRequest(deps)
    req.buildPlannerChatRequestPayload('hello')
    expect(deps.lastRequestContextSummary.value).toContain('已关联上下文')
  })

  it('requestChatByMode calls sendUnifiedChat', async () => {
    const chatApi = (await import('@/api/chat')).default
    await request.requestChatByMode('hello')
    expect(chatApi.sendUnifiedChat).toHaveBeenCalled()
  })

  it('sends a plan-only card control with the selected plan ID without consuming draft attachments', async () => {
    const chatApi = (await import('@/api/chat')).default
    const deps = makeDeps(), req = useChatRequest(deps)
    await req.requestChatByMode('确认', {}, { expectedWorkflowPlanId: 'clicked-plan' }, { sessionId: 'original', messages: [] })
    expect(chatApi.sendUnifiedChat).toHaveBeenCalledWith(expect.objectContaining({
      message: '确认', user_id: 'web_normal_original',
      context: expect.objectContaining({ session_id: 'original', expected_workflow_plan_id: 'clicked-plan' }),
    }), expect.anything())
    expect(deps.consumeMultimodalIntoPlannerContext).not.toHaveBeenCalled()
    expect(deps.injectExcelContextPayload).not.toHaveBeenCalled()
  })

  it('requestChatByModeBatch calls sendUnifiedChatBatch', async () => {
    const chatApi = (await import('@/api/chat')).default
    await request.requestChatByModeBatch(['msg1', 'msg2'])
    expect(chatApi.sendUnifiedChatBatch).toHaveBeenCalled()
  })

  it('getChatBatchDebounceMs returns 0 by default', () => {
    expect(request.getChatBatchDebounceMs()).toBe(0)
  })

  it('startWaitProgressTimer updates loadingProgressText', () => {
    vi.useFakeTimers()
    request.startWaitProgressTimer()
    vi.advanceTimersByTime(2000)
    expect(request.loadingProgressText.value).toContain('已发送请求')
    vi.advanceTimersByTime(8000)
    expect(request.loadingProgressText.value).toContain('停止回复')
    expect(request.loadingProgressText.value).toContain('勿重复提交')
    expect(request.loadingProgressText.value).toContain('CHAT_WAIT')
    expect(request.loadingProgressText.value).not.toContain('VITE_API_BASE_URL')
    request.stopLoadingProgress()
    vi.useRealTimers()
  })

  it('stopLoadingProgress resets text', () => {
    vi.useFakeTimers()
    request.startWaitProgressTimer()
    vi.advanceTimersByTime(2000)
    request.stopLoadingProgress()
    expect(request.loadingProgressText.value).toBe('处理中...')
    vi.useRealTimers()
  })

  it('resolveChatTimeoutMs returns 180000 for complex tasks', () => {
    expect(request.resolveChatTimeoutMs('导入数据库')).toBe(180000)
    expect(request.resolveChatTimeoutMs('批量excel上传')).toBe(180000)
    expect(request.resolveChatTimeoutMs('执行工作流')).toBe(180000)
    expect(request.resolveChatTimeoutMs('确认')).toBe(180000)
    expect(request.resolveChatTimeoutMs('取消')).toBe(180000)
  })

  it('resolveChatTimeoutMs returns 90000 for simple tasks', () => {
    expect(request.resolveChatTimeoutMs('你好')).toBe(90000)
    expect(request.resolveChatTimeoutMs('简单问题')).toBe(90000)
  })

  it('enqueueChatBatchMessage queues and flushes', () => {
    vi.useFakeTimers()
    const onFlush = vi.fn()
    request.enqueueChatBatchMessage('msg1', 100, onFlush)
    request.enqueueChatBatchMessage('msg2', 100, onFlush)
    expect(onFlush).not.toHaveBeenCalled()
    vi.advanceTimersByTime(150)
    expect(onFlush).toHaveBeenCalledWith(['msg1', 'msg2'])
    vi.useRealTimers()
  })

  it('enqueueChatBatchMessage resets timer on each enqueue', () => {
    vi.useFakeTimers()
    const onFlush = vi.fn()
    request.enqueueChatBatchMessage('msg1', 100, onFlush)
    vi.advanceTimersByTime(50)
    request.enqueueChatBatchMessage('msg2', 100, onFlush)
    vi.advanceTimersByTime(50)
    // Timer was reset, so not flushed yet
    expect(onFlush).not.toHaveBeenCalled()
    vi.advanceTimersByTime(60)
    expect(onFlush).toHaveBeenCalledWith(['msg1', 'msg2'])
    vi.useRealTimers()
  })

  it('requestChatByModeWithTimeout rejects on timeout', async () => {
    vi.useFakeTimers()
    const chatApi = (await import('@/api/chat')).default
    vi.mocked(chatApi.sendUnifiedChat).mockImplementation(() => new Promise((resolve) => setTimeout(() => resolve({} as any), 60000)))
    const promise = request.requestChatByModeWithTimeout('hello', 100)
    vi.advanceTimersByTime(200)
    await expect(promise).rejects.toThrow('请求超时')
    vi.useRealTimers()
  })

  it('requestChatByModeBatchWithTimeout rejects on timeout', async () => {
    vi.useFakeTimers()
    const chatApi = (await import('@/api/chat')).default
    vi.mocked(chatApi.sendUnifiedChatBatch).mockImplementation(() => new Promise((resolve) => setTimeout(() => resolve({} as any), 60000)))
    const promise = request.requestChatByModeBatchWithTimeout(['msg1'], 100)
    vi.advanceTimersByTime(200)
    await expect(promise).rejects.toThrow('请求超时')
    vi.useRealTimers()
  })

  it('chatBatchQueue is exposed', () => {
    expect(Array.isArray(request.chatBatchQueue)).toBe(true)
  })

  it('injectExcelContextPayload is called in buildPlannerChatRequestPayload', () => {
    const deps = makeDeps()
    const req = useChatRequest(deps)
    req.buildPlannerChatRequestPayload('hello')
    expect(deps.injectExcelContextPayload).toHaveBeenCalled()
  })

  it('consumeMultimodalIntoPlannerContext is called in buildPlannerChatRequestPayload', () => {
    const deps = makeDeps()
    const req = useChatRequest(deps)
    req.buildPlannerChatRequestPayload('hello')
    expect(deps.consumeMultimodalIntoPlannerContext).toHaveBeenCalled()
  })

  it('does not abort an office ELT import at 8s or when the chat disconnects', async () => {
    vi.useFakeTimers()
    const chatApi = (await import('@/api/chat')).default
    let release: (value: unknown) => void = () => {}
    vi.mocked(chatApi.sendUnifiedChat).mockImplementation(() => new Promise((resolve) => { release = resolve }))
    const controller = new AbortController()
    const pending = request.requestChatByModeWithTimeout(
      '@uploads/宗南.xlsx导入数据库',
      8_000,
      undefined,
      { sessionId: 's', messages: [], signal: controller.signal },
    )
    controller.abort()
    await vi.advanceTimersByTimeAsync(9_000)
    const signal = vi.mocked(chatApi.sendUnifiedChat).mock.calls.at(-1)?.[1]?.signal
    expect(signal?.aborted).not.toBe(true)
    release({ success: true, response: '已提交审批' })
    await expect(pending).resolves.toMatchObject({ success: true })
    vi.useRealTimers()
  })

  it('resolveChatDbTokensForPayload is called in buildPlannerChatRequestPayload', () => {
    const deps = makeDeps()
    deps.resolveChatDbTokensForPayload = () => ({ db_read_token: 'token123' })
    const req = useChatRequest(deps)
    const { body } = req.buildPlannerChatRequestPayload('hello')
    expect(body.db_read_token).toBe('token123')
  })
})

 it('aborts pending JSON transport and releases its timer when corrected', async () => {
  vi.useFakeTimers()
  const chatApi = (await import('@/api/chat')).default
  vi.mocked(chatApi.sendUnifiedChat).mockImplementation(() => new Promise(() => {}))
  const request = useChatRequest(makeDeps())
  const controller = new AbortController()
  const pending = request.requestChatByModeWithTimeout('synthetic', 90_000, undefined, { sessionId: 's', messages: [], signal: controller.signal })
  const rejected = expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  controller.abort()
  await rejected
  expect(vi.mocked(chatApi.sendUnifiedChat).mock.calls.at(-1)?.[1]?.signal?.aborted).toBe(true)
  expect(vi.getTimerCount()).toBe(0)
  vi.useRealTimers()
 })

describe('useChatRequest page cache', () => {
  afterEach(() => { vi.useRealTimers() })

  it('stops the wait ticker while the chat page is cached and resumes it on return', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-11-06T04:00:00Z'))
    const visible = ref(true)
    let request!: ReturnType<typeof useChatRequest>
    const Child = defineComponent({
      setup() {
        request = useChatRequest({
          messages: ref([]),
          sessionId: ref('session-1'),
          lastRequestContextSummary: ref(''),
          plannerWriteUnlockResumeDraft: ref(''),
          resolveChatDbTokensForPayload: () => ({}),
          injectExcelContextPayload: () => false,
          consumeMultimodalIntoPlannerContext: () => undefined,
        })
        request.startWaitProgressTimer()
        return () => h('div')
      },
    })
    const Root = defineComponent({
      components: { Child },
      setup() { return { visible } },
      template: '<keep-alive><Child v-if="visible" /></keep-alive>',
    })
    const wrapper = mount(Root)
    await vi.advanceTimersByTimeAsync(1000)
    const whileVisible = request.loadingProgressText.value
    expect(whileVisible).toContain('1s')
    visible.value = false
    await wrapper.vm.$nextTick()
    await vi.advanceTimersByTimeAsync(5000)
    expect(request.loadingProgressText.value).toBe(whileVisible)
    visible.value = true
    await wrapper.vm.$nextTick()
    await vi.advanceTimersByTimeAsync(2000)
    expect(request.loadingProgressText.value).toContain('2s')
    wrapper.unmount()
  })
})
