import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useChatStore } from '@/stores/chat'

const jarvisMocks = vi.hoisted(() => ({
  sendMessage: vi.fn().mockResolvedValue(undefined),
  setCurrentTask: vi.fn(),
  clearMessages: vi.fn(),
}))

vi.mock('@/stores/jarvisChat', () => ({
  useJarvisChatStore: () => ({
    messages: [{ id: 1, content: 'Hello', type: 'ai' }],
    currentTask: null,
    sendMessage: jarvisMocks.sendMessage,
    setCurrentTask: jarvisMocks.setCurrentTask,
    clearMessages: jarvisMocks.clearMessages,
  }),
}))

describe('useChatStore', () => {
  let store: ReturnType<typeof useChatStore>

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    store = useChatStore()
  })

  it('initializes with default state', () => {
    expect(store.isLoading).toBe(false)
    expect(store.isStreamingReply).toBe(false)
  })

  it('exposes messages from jarvis store', () => {
    expect(store.messages).toBeDefined()
    expect(store.messages.length).toBeGreaterThan(0)
  })

  it('exposes currentTask from jarvis store', () => {
    expect(store.currentTask).toBeDefined()
  })

  it('sendMessage sets isLoading during request', async () => {
    const promise = store.sendMessage('test')
    expect(store.isLoading).toBe(true)
    await promise
    expect(store.isLoading).toBe(false)
  })

  it('loadMoreMessages does not throw', () => {
    expect(() => store.loadMoreMessages()).not.toThrow()
  })

  it('executeTask does not throw', async () => {
    await expect(store.executeTask('task-1')).resolves.toBeUndefined()
  })

  it('clearTask calls jarvis setCurrentTask', () => {
    store.clearTask()
    expect(jarvisMocks.setCurrentTask).toHaveBeenCalledWith(null)
  })

  it('initChat calls jarvis clearMessages', () => {
    store.initChat()
    expect(jarvisMocks.clearMessages).toHaveBeenCalled()
  })
})
