import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
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
    messages: ref([
      { role: 'user', content: 'previous message', time: '10:00' },
    ]),
    proIntentExperienceEnabled: ref(false),
    isProMode: ref(false),
    lastRequestContextSummary: ref(''),
    plannerWriteUnlockResumeDraft: ref(''),
    resolveEffectiveProModeState: () => false,
    getModeScopedUserId: (proEnabled: boolean) => proEnabled ? 'pro-user-1' : 'basic-user-1',
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

  it('buildPlannerChatRequestPayload builds basic mode payload', () => {
    const { body, proIntentEnabled } = request.buildPlannerChatRequestPayload('hello')
    expect(proIntentEnabled).toBe(false)
    expect(body.message).toBe('hello')
    expect(body.source).toBe('normal')
    expect(body.mode).toBe('basic')
    expect(body.user_id).toBe('basic-user-1')
  })

  it('buildPlannerChatRequestPayload builds pro mode payload', () => {
    const deps = makeDeps()
    deps.resolveEffectiveProModeState = () => true
    const req = useChatRequest(deps)
    const { body, proIntentEnabled } = req.buildPlannerChatRequestPayload('hello')
    expect(proIntentEnabled).toBe(true)
    expect(body.source).toBe('pro')
    expect(body.mode).toBe('professional')
    expect(body.user_id).toBe('pro-user-1')
  })

  it('buildPlannerChatRequestPayload includes context with recent messages', () => {
    const { body } = request.buildPlannerChatRequestPayload('hello')
    const ctx = body.context as Record<string, unknown>
    expect(Array.isArray(ctx.recent_messages)).toBe(true)
    expect((ctx.recent_messages as unknown[]).length).toBeGreaterThan(0)
  })

  it('buildPlannerChatRequestPayload strips HTML from history', () => {
    const deps = makeDeps()
    deps.messages.value = [
      { role: 'user', content: '<b>bold</b> text', time: '10:00' },
    ]
    const req = useChatRequest(deps)
    const { body } = req.buildPlannerChatRequestPayload('hello')
    const ctx = body.context as Record<string, unknown>
    const history = ctx.recent_messages as Array<{ content: string }>
    expect(history[0].content).not.toContain('<b>')
  })

  it('buildPlannerChatRequestPayload limits history to 6 messages', () => {
    const deps = makeDeps()
    deps.messages.value = Array.from({ length: 10 }, (_, i) => ({
      role: 'user' as const,
      content: `msg ${i}`,
      time: '10:00',
    }))
    const req = useChatRequest(deps)
    const { body } = req.buildPlannerChatRequestPayload('hello')
    const ctx = body.context as Record<string, unknown>
    const history = ctx.recent_messages as unknown[]
    expect(history.length).toBeLessThanOrEqual(6)
  })

  it('buildPlannerChatRequestPayload with proIntentExperienceEnabled but not pro mode', () => {
    const deps = makeDeps()
    deps.proIntentExperienceEnabled.value = true
    deps.resolveEffectiveProModeState = () => false
    const req = useChatRequest(deps)
    const { body, proIntentEnabled } = req.buildPlannerChatRequestPayload('hello')
    expect(proIntentEnabled).toBe(true)
    const ctx = body.context as Record<string, unknown>
    expect(ctx.ui_surface).toBe('normal')
    expect(ctx.intent_channel).toBe('pro')
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

  it('requestChatByMode calls sendUnifiedChat in basic mode', async () => {
    const chatApi = (await import('@/api/chat')).default
    await request.requestChatByMode('hello')
    expect(chatApi.sendUnifiedChat).toHaveBeenCalled()
  })

  it('requestChatByMode calls sendChat in pro mode', async () => {
    const deps = makeDeps()
    deps.resolveEffectiveProModeState = () => true
    const req = useChatRequest(deps)
    const chatApi = (await import('@/api/chat')).default
    await req.requestChatByMode('hello')
    expect(chatApi.sendChat).toHaveBeenCalled()
  })

  it('requestChatByModeBatch calls sendUnifiedChatBatch in basic mode', async () => {
    const chatApi = (await import('@/api/chat')).default
    await request.requestChatByModeBatch(['msg1', 'msg2'])
    expect(chatApi.sendUnifiedChatBatch).toHaveBeenCalled()
  })

  it('requestChatByModeBatch calls sendChatBatch in pro mode', async () => {
    const deps = makeDeps()
    deps.resolveEffectiveProModeState = () => true
    const req = useChatRequest(deps)
    const chatApi = (await import('@/api/chat')).default
    await req.requestChatByModeBatch(['msg1', 'msg2'])
    expect(chatApi.sendChatBatch).toHaveBeenCalled()
  })

  it('getChatBatchDebounceMs returns 0 by default', () => {
    expect(request.getChatBatchDebounceMs()).toBe(0)
  })

  it('startWaitProgressTimer updates loadingProgressText', () => {
    vi.useFakeTimers()
    request.startWaitProgressTimer()
    vi.advanceTimersByTime(2000)
    expect(request.loadingProgressText.value).toContain('已发送请求')
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

  it('resolveChatTimeoutMs returns 90000 for complex tasks', () => {
    expect(request.resolveChatTimeoutMs('导入数据库')).toBe(90000)
    expect(request.resolveChatTimeoutMs('批量excel上传')).toBe(90000)
    expect(request.resolveChatTimeoutMs('执行工作流')).toBe(90000)
  })

  it('resolveChatTimeoutMs returns 30000 for simple tasks', () => {
    expect(request.resolveChatTimeoutMs('你好')).toBe(30000)
    expect(request.resolveChatTimeoutMs('简单问题')).toBe(30000)
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
    vi.mocked(chatApi.sendUnifiedChat).mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve({} as any), 60000)),
    )
    const promise = request.requestChatByModeWithTimeout('hello', 100)
    vi.advanceTimersByTime(200)
    await expect(promise).rejects.toThrow('请求超时')
    vi.useRealTimers()
  })

  it('requestChatByModeBatchWithTimeout rejects on timeout', async () => {
    vi.useFakeTimers()
    const chatApi = (await import('@/api/chat')).default
    vi.mocked(chatApi.sendUnifiedChatBatch).mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve({} as any), 60000)),
    )
    const promise = request.requestChatByModeBatchWithTimeout(['msg1'], 100)
    vi.advanceTimersByTime(200)
    await expect(promise).rejects.toThrow('批量请求超时')
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

  it('resolveChatDbTokensForPayload is called in buildPlannerChatRequestPayload', () => {
    const deps = makeDeps()
    deps.resolveChatDbTokensForPayload = () => ({ db_read_token: 'token123' })
    const req = useChatRequest(deps)
    const { body } = req.buildPlannerChatRequestPayload('hello')
    expect(body.db_read_token).toBe('token123')
  })
})
