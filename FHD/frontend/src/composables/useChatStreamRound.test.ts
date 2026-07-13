import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { useChatStreamRound } from './useChatStreamRound'

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
    acknowledgeMultimodalRequest: vi.fn(),
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
    const result = await streamPromise

    expect(result).toMatchObject({ success: false, cancelled: true, response: '已生成一半' })
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

  it('never renders or persists ephemeral tokens and exposes tool progress only as a sidecar', async () => {
    readPlannerSseResponse.mockImplementation(async (_res, onEvent) => {
      onEvent({ type: 'token', text: 'internal trace', ephemeral: true })
      onEvent({ type: 'tool_progress', label: 'Excel 解析' })
      onEvent({ type: 'token', text: '用户可见' })
      onEvent({ type: 'done', result: { success: true, response: '最终回复' } })
    })
    const { deps } = buildDeps()
    const { runPlannerSseStream } = useChatStreamRound(deps)

    const result = await runPlannerSseStream('hello', [])

    expect(result).toMatchObject({ success: true, response: '最终回复' })
    expect(deps.applyPlainTextToMessageIndex).not.toHaveBeenCalledWith(0, expect.stringContaining('internal trace'))
    expect(deps.patchMessageAtIndex).toHaveBeenCalledWith(0, {
      toolProgressLabel: '正在调用 Excel 解析…',
    })
    expect(deps.saveMessage).toHaveBeenCalledWith('ai', '最终回复')
  })

  it('keeps an attachment staged when the request fails before acceptance', async () => {
    sendChatStream.mockRejectedValueOnce(new Error('offline'))
    const snapshot = { sessionId: 's1', rows: [{ filename: 'report.xlsx' }] }
    const { deps } = buildDeps({
      buildPlannerChatRequestPayload: vi.fn(() => ({ body: { message: 'hi' }, multimodalSnapshot: snapshot })),
    })
    const { runPlannerSseStream } = useChatStreamRound(deps)

    const result = await runPlannerSseStream('hello', [])

    expect(result.success).toBe(false)
    expect(deps.acknowledgeMultimodalRequest).not.toHaveBeenCalled()
  })

  it('acknowledges exactly the accepted attachment snapshot before a user abort', async () => {
    let abortSignal: AbortSignal | undefined
    const snapshot = { sessionId: 's1', rows: [{ filename: 'report.xlsx' }] }
    sendChatStream.mockImplementation((_body, opts) => {
      abortSignal = opts?.signal
      return Promise.resolve({ ok: true })
    })
    readPlannerSseResponse.mockImplementation(async () => {
      await new Promise<void>((_resolve, reject) => {
        abortSignal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
      })
    })
    const { deps } = buildDeps({
      buildPlannerChatRequestPayload: vi.fn(() => ({ body: { message: 'hi' }, multimodalSnapshot: snapshot })),
    })
    const { runPlannerSseStream, stopStreamingReply } = useChatStreamRound(deps)

    const pending = runPlannerSseStream('hello', [])
    await vi.waitFor(() => expect(deps.acknowledgeMultimodalRequest).toHaveBeenCalledWith(snapshot))
    stopStreamingReply()
    await pending

    expect(deps.acknowledgeMultimodalRequest).toHaveBeenCalledTimes(1)
  })
})
