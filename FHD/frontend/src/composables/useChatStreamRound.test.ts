import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref } from 'vue'
import { useChatStreamRound } from './useChatStreamRound'
import { parseChatStreamErrorResponse } from '@/api/chat'

const sendChatStream = vi.fn()
const readPlannerSseResponse = vi.fn()

vi.mock('@/api/chat', () => ({
  default: {
    sendChatStream: (...args: unknown[]) => sendChatStream(...args),
  },
  parseChatStreamErrorResponse: vi.fn(),
}))

vi.mock('@/utils/chatSseStream', () => ({
  readPlannerSseResponse: (...args: unknown[]) => readPlannerSseResponse(...args),
}))

function buildDeps(overrides: Partial<Parameters<typeof useChatStreamRound>[0]> = {}) {
  const isLoading = ref(false)
  const isStreamingReply = ref(false)
  const plannerWriteUnlockResumeDraft = ref('')
  const ttsEnabled = ref(false)

  const deps = {
    pushStreamingAiShell: vi.fn(() => 0),
    applyPlainTextToMessageIndex: vi.fn(),
    patchMessageAtIndex: vi.fn(),
    saveMessage: vi.fn().mockResolvedValue(undefined),
    persistMessagesCache: vi.fn(),
    scrollToBottom: vi.fn(),
    setLoadingProgress: vi.fn(),
    startWaitProgressTimer: vi.fn(),
    stopLoadingProgress: vi.fn(),
    queueVoice: vi.fn(),
    clearVoiceQueue: vi.fn(),
    ttsEnabled,
    buildPlannerChatRequestPayload: vi.fn(() => ({ body: { message: 'hi' } })),
    resolveChatTimeoutMs: vi.fn(() => 60000),
    handleChatRequiresToken: vi.fn(),
    onStreamDone: vi.fn().mockResolvedValue(undefined),
    plannerWriteUnlockResumeDraft,
    isLoading,
    isStreamingReply,
    ...overrides,
  }

  return { deps, isLoading, isStreamingReply }
}

describe('useChatStreamRound', () => {
  afterEach(() => vi.useRealTimers())
  beforeEach(() => {
    vi.clearAllMocks()
    sendChatStream.mockResolvedValue({ ok: true })
    readPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({ type: 'token', text: '部分' })
      onEvent({ type: 'done', result: { success: true, response: '部分回复' } })
    })
  })

  it('preserves partial text when user aborts mid-stream', async () => {
    let abortSignal: AbortSignal | undefined
    sendChatStream.mockImplementation((_body, opts) => {
      abortSignal = opts?.signal
      return Promise.resolve({ ok: true })
    })
    readPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({ type: 'token', text: '已生成一半' })
      await new Promise<void>((_resolve, reject) => {
        abortSignal?.addEventListener('abort', () => {
          reject(new DOMException('Aborted', 'AbortError'))
        })
      })
    })

    const { deps } = buildDeps()
    const { runPlannerSseStream, stopStreamingReply } = useChatStreamRound(deps)

    const streamPromise = runPlannerSseStream('hello', [])
    await vi.waitFor(() => {
      expect(deps.applyPlainTextToMessageIndex).toHaveBeenCalledWith(0, '已生成一半')
    })
    stopStreamingReply()
    const ok = await streamPromise

    expect(ok).toBe(true)
    expect(deps.clearVoiceQueue).toHaveBeenCalled()
    expect(deps.saveMessage).toHaveBeenCalledWith('ai', '已生成一半')
    expect(deps.onStreamDone).not.toHaveBeenCalled()
  })

  it('shows stopped placeholder when abort with no partial text', async () => {
    let abortSignal: AbortSignal | undefined
    sendChatStream.mockImplementation((_body, opts) => {
      abortSignal = opts?.signal
      return Promise.resolve({ ok: true })
    })
    readPlannerSseResponse.mockImplementation(async () => {
      await new Promise<void>((_resolve, reject) => {
        abortSignal?.addEventListener('abort', () => {
          reject(new DOMException('Aborted', 'AbortError'))
        })
      })
    })

    const { deps } = buildDeps()
    const { runPlannerSseStream, stopStreamingReply } = useChatStreamRound(deps)

    const streamPromise = runPlannerSseStream('hello', [])
    await vi.waitFor(() => expect(sendChatStream).toHaveBeenCalled())
    stopStreamingReply()
    await streamPromise

    expect(deps.applyPlainTextToMessageIndex).toHaveBeenCalledWith(0, '（已停止生成）')
    expect(deps.saveMessage).toHaveBeenCalledWith('ai', '（已停止生成）')
  })

  it.each([true, false])('persists completed replies and speaks only enabled sentence chunks, tts=%s', async (tts) => {
    const { deps } = buildDeps({ ttsEnabled: ref(tts) })
    readPlannerSseResponse.mockImplementation(async (_response, emit) => {
      emit({ type: 'token', text: 'private', ephemeral: true })
      emit({ type: 'token', text: 'hello' })
      emit({ type: 'token', text: '。tail' })
      emit({ type: 'token' })
      emit({ type: 'done', result: { success: true, response: 'hello。tail' } })
    })
    expect(await useChatStreamRound(deps).runPlannerSseStream('request', [], { fromWriteUnlock: true })).toBe(true)
    expect(deps.saveMessage).toHaveBeenCalledWith('ai', 'hello。tail')
    expect(deps.onStreamDone).toHaveBeenCalledWith({ success: true, response: 'hello。tail' }, 'request', 0)
    expect(deps.buildPlannerChatRequestPayload).toHaveBeenCalledWith('request', { fromWriteUnlock: true })
    expect(deps.queueVoice.mock.calls).toEqual(tts ? [['hello。'], ['tail']] : [])
    expect(deps.persistMessagesCache).toHaveBeenCalledOnce()
    expect(deps.isLoading.value).toBe(false); expect(deps.isStreamingReply.value).toBe(false)
    expect(deps.stopLoadingProgress).toHaveBeenCalledOnce()
  })
  it.each([
    [[], '（无内容）'], [[{ type: 'token', text: 'fallback' }], 'fallback'],
    [[{ type: 'done', result: [] }], '（无内容）'],
  ])('completes missing-result stream %j with a readable fallback', async (events, expected) => {
    const { deps } = buildDeps({ buildPlannerChatRequestPayload: vi.fn(() => ({ body: { runtime_context: { keep: true } } })) })
    readPlannerSseResponse.mockImplementation(async (_response, emit) => { events.forEach(emit) })
    await useChatStreamRound(deps).runPlannerSseStream('primary', [])
    expect(sendChatStream).toHaveBeenCalledWith(expect.objectContaining({ message: 'primary', runtime_context: expect.objectContaining({ keep: true }) }), expect.anything())
    expect(deps.saveMessage).toHaveBeenCalledWith('ai', expected)
    expect(deps.onStreamDone).toHaveBeenCalledWith(events.some((event) => event.type === 'done') ? {} : { success: true, response: expected }, 'primary', 0)
  })
  it('retains only the latest twelve progress stages and resumes write-token requests with the partial draft', async () => {
    const { deps } = buildDeps()
    readPlannerSseResponse.mockImplementation(async (_response, emit) => {
      emit({ type: 'token', text: 'draft' })
      emit({ type: 'requires_token', token_name: 'DB_WRITE', token_description: 'write' })
      for (let i = 0; i < 14; i++) emit({ type: 'tool_progress', phase: `step-${i}`, label: `task-${i}` })
      emit({ type: 'tool_progress', phase: 'step-13', label: 'task-13' })
      emit({ type: 'tool_progress', phase: 'accepted', text: 'accepted' })
      emit({ type: 'tool_progress', text: ' ' })
      emit({ type: 'tool_progress' })
    })
    await useChatStreamRound(deps).runPlannerSseStream('request', ['remote'])
    expect(deps.handleChatRequiresToken).toHaveBeenCalledWith('DB_WRITE', 'write', ['remote'])
    expect(deps.plannerWriteUnlockResumeDraft.value).toBe('draft')
    const progress = deps.patchMessageAtIndex.mock.calls.filter(([, patch]) => patch.executionProgress).at(-1)![1].executionProgress
    expect(progress).toHaveLength(12)
    expect(progress.at(-1)).toMatchObject({ phase: 'completed', status: 'success' })
    expect(progress.filter((item) => item.phase === 'step-13')).toHaveLength(1)
    expect(deps.setLoadingProgress).toHaveBeenCalledWith('正在调用工具…')
  })
  it.each([{}, { token_description: '数据库写入权限' }])('handles missing token fields %j', async (token) => {
    const { deps } = buildDeps()
    readPlannerSseResponse.mockImplementation(async (_response, emit) => { emit({ type: 'token', text: 'partial' }); emit({ type: 'requires_token', ...token }) })
    await useChatStreamRound(deps).runPlannerSseStream('request', [])
    expect(deps.handleChatRequiresToken).toHaveBeenCalledWith('', token.token_description || '', [])
    expect(deps.plannerWriteUnlockResumeDraft.value).toBe(token.token_description ? 'partial' : '')
  })
  it.each(['HTTP', 'SSE', 'empty SSE', 'unknown', 'timeout'])('records %s failures and clears busy state', async (mode) => {
    const { deps } = buildDeps({ resolveChatTimeoutMs: () => 1000 })
    if (mode === 'HTTP') { sendChatStream.mockResolvedValue({ ok: false }); vi.mocked(parseChatStreamErrorResponse).mockResolvedValue('HTTP error') }
    else if (mode === 'SSE' || mode === 'empty SSE') readPlannerSseResponse.mockImplementation(async (_response, emit) => emit({ type: 'error', message: mode === 'SSE' ? 'SSE error' : '' }))
    else if (mode === 'unknown') sendChatStream.mockRejectedValue(null)
    else {
      vi.useFakeTimers()
      sendChatStream.mockImplementation((_body, { signal }) => new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))))
    }
    const promise = useChatStreamRound(deps).runPlannerSseStream('request', [])
    if (mode === 'timeout') await vi.advanceTimersByTimeAsync(1000)
    expect(await promise).toBe(false)
    const expected = { HTTP: 'HTTP error', SSE: 'SSE error', 'empty SSE': '流式接口错误', unknown: '流式对话失败', timeout: '请求超时（>1s）或已中断' }[mode]
    expect(deps.saveMessage).toHaveBeenCalledWith('ai', `处理失败：${expected}`)
    expect(deps.isLoading.value).toBe(false); expect(deps.isStreamingReply.value).toBe(false)
    expect(deps.onStreamDone).not.toHaveBeenCalled()
  })
})
