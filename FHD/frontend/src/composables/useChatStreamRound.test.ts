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
})
