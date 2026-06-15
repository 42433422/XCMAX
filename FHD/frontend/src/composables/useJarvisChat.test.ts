import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const mockStore = {
  messages: [],
  isRecording: false,
  isPlaying: false,
  statusText: '准备就绪',
  isCoreSpeaking: false,
  sendMessage: vi.fn(async (msg: string) => `回复: ${msg}`),
  addMessage: vi.fn(),
  addTaskMessage: vi.fn(),
  startRecording: vi.fn(),
  stopRecording: vi.fn(),
  queueVoice: vi.fn(),
  setStatus: vi.fn(),
  setCoreSpeaking: vi.fn(),
  clearMessages: vi.fn(),
  clearVoiceQueue: vi.fn(),
}

vi.mock('@/stores/jarvisChat', () => ({
  useJarvisChatStore: vi.fn(() => mockStore),
}))

vi.mock('@/utils/typeGuards', () => ({
  asRecord: vi.fn((v) => v || {}),
  asArray: vi.fn((v) => (Array.isArray(v) ? v : [])),
  asString: vi.fn((v) => String(v ?? '')),
  asBoolean: vi.fn((v) => !!v),
  asDisposable: vi.fn(),
}))

import { useJarvisChat } from './useJarvisChat'

describe('useJarvisChat', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('returns composable API', () => {
    const chat = useJarvisChat()
    expect(typeof chat.sendMessage).toBe('function')
    expect(typeof chat.addMessage).toBe('function')
    expect(typeof chat.addTaskMessage).toBe('function')
    expect(typeof chat.startRecording).toBe('function')
    expect(typeof chat.stopRecording).toBe('function')
    expect(typeof chat.queueVoice).toBe('function')
    expect(typeof chat.speak).toBe('function')
    expect(typeof chat.setStatus).toBe('function')
    expect(typeof chat.setCoreSpeaking).toBe('function')
    expect(typeof chat.clearMessages).toBe('function')
    expect(typeof chat.clearVoiceQueue).toBe('function')
  })

  it('messages is a computed ref from store', () => {
    const chat = useJarvisChat()
    expect(chat.messages).toBeDefined()
  })

  it('isRecording is a computed ref from store', () => {
    const chat = useJarvisChat()
    expect(chat.isRecording).toBeDefined()
  })

  it('isPlaying is a computed ref from store', () => {
    const chat = useJarvisChat()
    expect(chat.isPlaying).toBeDefined()
  })

  it('statusText is a computed ref from store', () => {
    const chat = useJarvisChat()
    expect(chat.statusText).toBeDefined()
  })

  it('isCoreSpeaking is a computed ref from store', () => {
    const chat = useJarvisChat()
    expect(chat.isCoreSpeaking).toBeDefined()
  })

  it('isListening is a ref initialized to false', () => {
    const chat = useJarvisChat()
    expect(chat.isListening.value).toBe(false)
  })

  it('sendMessage delegates to store', async () => {
    const chat = useJarvisChat()
    await chat.sendMessage('hello')
    expect(mockStore.sendMessage).toHaveBeenCalledWith('hello')
  })

  it('addMessage delegates to store with default type', () => {
    const chat = useJarvisChat()
    chat.addMessage('test message')
    expect(mockStore.addMessage).toHaveBeenCalledWith('test message', 'ai')
  })

  it('addMessage delegates to store with specified type', () => {
    const chat = useJarvisChat()
    chat.addMessage('user message', 'user')
    expect(mockStore.addMessage).toHaveBeenCalledWith('user message', 'user')
  })

  it('addTaskMessage delegates to store', () => {
    const chat = useJarvisChat()
    const taskData = { id: 1, name: 'task' }
    chat.addTaskMessage('task message', taskData)
    expect(mockStore.addTaskMessage).toHaveBeenCalledWith('task message', taskData)
  })

  it('startRecording warns when speech recognition not supported', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const chat = useJarvisChat()
    chat.startRecording()
    expect(warnSpy).toHaveBeenCalledWith('Speech recognition not supported')
    warnSpy.mockRestore()
  })

  it('startRecording does nothing when SpeechRecognition constructor is missing', () => {
    const win = window as Window & {
      SpeechRecognition?: unknown
      webkitSpeechRecognition?: unknown
    }
    const origSR = win.SpeechRecognition
    const origWkSR = win.webkitSpeechRecognition
    win.SpeechRecognition = undefined
    win.webkitSpeechRecognition = undefined
    const chat = useJarvisChat()
    chat.startRecording()
    expect(chat.isListening.value).toBe(false)
    win.SpeechRecognition = origSR
    win.webkitSpeechRecognition = origWkSR
  })

  it('stopRecording resets isListening and calls store stopRecording', () => {
    const chat = useJarvisChat()
    chat.isListening.value = true
    chat.stopRecording()
    expect(chat.isListening.value).toBe(false)
    expect(mockStore.stopRecording).toHaveBeenCalled()
  })

  it('queueVoice delegates to store', () => {
    const chat = useJarvisChat()
    chat.queueVoice('hello voice')
    expect(mockStore.queueVoice).toHaveBeenCalledWith('hello voice')
  })

  it('speak delegates to store queueVoice', () => {
    const chat = useJarvisChat()
    chat.speak('hello speak')
    expect(mockStore.queueVoice).toHaveBeenCalledWith('hello speak')
  })

  it('setStatus delegates to store', () => {
    const chat = useJarvisChat()
    chat.setStatus('new status')
    expect(mockStore.setStatus).toHaveBeenCalledWith('new status')
  })

  it('setCoreSpeaking delegates to store', () => {
    const chat = useJarvisChat()
    chat.setCoreSpeaking(true)
    expect(mockStore.setCoreSpeaking).toHaveBeenCalledWith(true)
  })

  it('clearMessages delegates to store', () => {
    const chat = useJarvisChat()
    chat.clearMessages()
    expect(mockStore.clearMessages).toHaveBeenCalled()
  })

  it('clearVoiceQueue delegates to store', () => {
    const chat = useJarvisChat()
    chat.clearVoiceQueue()
    expect(mockStore.clearVoiceQueue).toHaveBeenCalled()
  })
})
