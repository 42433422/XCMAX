import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const {
  mockSpeakText,
  mockStopSpeaking,
  mockCleanText,
  mockEnterMonitor,
  mockExitMonitor,
  mockEnterWork,
  mockExitWork,
} = vi.hoisted(() => ({
  mockSpeakText: vi.fn(() => Promise.resolve()),
  mockStopSpeaking: vi.fn(),
  mockCleanText: vi.fn((text: string) => text),
  mockEnterMonitor: vi.fn(),
  mockExitMonitor: vi.fn(),
  mockEnterWork: vi.fn(),
  mockExitWork: vi.fn(),
}))

vi.mock('@/utils/tts', () => ({
  speakText: mockSpeakText,
  stopSpeaking: mockStopSpeaking,
  cleanTextForSpeech: mockCleanText,
}))

vi.mock('@/stores/proMode', () => ({
  useProModeStore: () => ({
    enterMonitorMode: mockEnterMonitor,
    exitMonitorMode: mockExitMonitor,
    enterWorkMode: mockEnterWork,
    exitWorkMode: mockExitWork,
  }),
}))

import { useJarvisChat } from './useJarvisChat'

describe('useJarvisChat', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockSpeakText.mockClear()
    mockStopSpeaking.mockClear()
    mockCleanText.mockClear()
    mockEnterMonitor.mockClear()
    mockExitMonitor.mockClear()
    mockEnterWork.mockClear()
    mockExitWork.mockClear()
    mockSpeakText.mockResolvedValue(undefined)
    mockCleanText.mockImplementation((text: string) => text)
  })

  describe('initial state', () => {
    it('returns messages as empty array initially', () => {
      const { messages } = useJarvisChat()
      expect(messages.value).toEqual([])
    })

    it('returns isRecording as false initially', () => {
      const { isRecording } = useJarvisChat()
      expect(isRecording.value).toBe(false)
    })

    it('returns isPlaying as false initially', () => {
      const { isPlaying } = useJarvisChat()
      expect(isPlaying.value).toBe(false)
    })

    it('returns isListening as false initially', () => {
      const { isListening } = useJarvisChat()
      expect(isListening.value).toBe(false)
    })

    it('returns statusText as "准备就绪" initially', () => {
      const { statusText } = useJarvisChat()
      expect(statusText.value).toBe('准备就绪')
    })

    it('returns isCoreSpeaking as false initially', () => {
      const { isCoreSpeaking } = useJarvisChat()
      expect(isCoreSpeaking.value).toBe(false)
    })
  })

  describe('addMessage', () => {
    it('adds message with default type "ai"', () => {
      const { messages, addMessage } = useJarvisChat()
      addMessage('hello')
      expect(messages.value).toHaveLength(1)
      expect(messages.value[0].content).toBe('hello')
      expect(messages.value[0].type).toBe('ai')
    })

    it('adds message with type "user"', () => {
      const { messages, addMessage } = useJarvisChat()
      addMessage('hi', 'user')
      expect(messages.value[0].type).toBe('user')
    })

    it('adds message with type "task"', () => {
      const { messages, addMessage } = useJarvisChat()
      addMessage('task', 'task')
      expect(messages.value[0].type).toBe('task')
    })

    it('adds multiple messages preserving order', () => {
      const { messages, addMessage } = useJarvisChat()
      addMessage('first', 'user')
      addMessage('second', 'ai')
      addMessage('third', 'task')
      expect(messages.value.map((m) => m.content)).toEqual(['first', 'second', 'third'])
    })

    it('sets timestamp on message', () => {
      const { messages, addMessage } = useJarvisChat()
      addMessage('hello')
      expect(messages.value[0].timestamp).toBeTruthy()
      expect(typeof messages.value[0].timestamp).toBe('string')
    })

    it('sets id on message', () => {
      const { messages, addMessage } = useJarvisChat()
      addMessage('hello')
      expect(messages.value[0].id).toBeTruthy()
    })
  })

  describe('addTaskMessage', () => {
    it('adds task message with taskData', () => {
      const { messages, addTaskMessage } = useJarvisChat()
      const taskData = { id: 1, name: 'task1' }
      addTaskMessage('task content', taskData)
      expect(messages.value).toHaveLength(1)
      expect(messages.value[0].type).toBe('task')
      expect(messages.value[0].content).toBe('task content')
      expect(messages.value[0].taskData).toEqual(taskData)
    })

    it('adds task message with null taskData', () => {
      const { messages, addTaskMessage } = useJarvisChat()
      addTaskMessage('task content', null)
      expect(messages.value[0].taskData).toBeNull()
    })

    it('adds task message with undefined taskData', () => {
      const { messages, addTaskMessage } = useJarvisChat()
      addTaskMessage('task content', undefined)
      expect(messages.value[0].taskData).toBeUndefined()
    })

    it('adds task message with complex taskData', () => {
      const { messages, addTaskMessage } = useJarvisChat()
      const taskData = { nested: { deep: [1, 2, 3] } }
      addTaskMessage('complex', taskData)
      expect(messages.value[0].taskData).toEqual(taskData)
    })
  })

  describe('sendMessage', () => {
    it('sends message and returns response', async () => {
      const { sendMessage, messages } = useJarvisChat()
      const response = await sendMessage('产品查询')
      expect(response).toBe('正在为您查询产品信息...')
      expect(messages.value).toHaveLength(2)
      expect(messages.value[0].type).toBe('user')
      expect(messages.value[1].type).toBe('ai')
    })

    it('handles 监控模式 message', async () => {
      const { sendMessage, messages } = useJarvisChat()
      const response = await sendMessage('请切换到监控模式')
      expect(response).toBe('正在切换到监控模式...')
      expect(mockEnterMonitor).toHaveBeenCalled()
      expect(messages.value.some((m) => m.content === '正在切换到监控模式...')).toBe(true)
    })

    it('handles 工作模式 message', async () => {
      const { sendMessage } = useJarvisChat()
      const response = await sendMessage('请切换到工作模式')
      expect(response).toBe('正在切换到工作模式...')
      expect(mockEnterWork).toHaveBeenCalled()
    })

    it('handles work mode (English) message', async () => {
      const { sendMessage } = useJarvisChat()
      const response = await sendMessage('enter work mode')
      expect(response).toBe('正在切换到工作模式...')
      expect(mockEnterWork).toHaveBeenCalled()
    })

    it('handles 客户 message', async () => {
      const { sendMessage } = useJarvisChat()
      const response = await sendMessage('客户信息')
      expect(response).toBe('正在为您查询客户信息...')
    })

    it('handles 订单 message', async () => {
      const { sendMessage } = useJarvisChat()
      const response = await sendMessage('订单状态')
      expect(response).toBe('正在为您查询订单信息...')
    })

    it('handles unknown message with default response', async () => {
      const { sendMessage } = useJarvisChat()
      const response = await sendMessage('hello world')
      expect(response).toBe('我已收到您的消息，正在处理中...')
    })
  })

  describe('startRecording', () => {
    it('warns when SpeechRecognition is not supported', () => {
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      const { startRecording, isListening } = useJarvisChat()
      startRecording()
      expect(warnSpy).toHaveBeenCalledWith('Speech recognition not supported')
      expect(isListening.value).toBe(false)
    })

    it('does not set isListening when SpeechRecognition not supported', () => {
      vi.spyOn(console, 'warn').mockImplementation(() => {})
      const { startRecording, isListening } = useJarvisChat()
      startRecording()
      expect(isListening.value).toBe(false)
    })
  })

  describe('startRecording with SpeechRecognition', () => {
    let mockRecognition: {
      lang: string
      continuous: boolean
      interimResults: boolean
      onstart: (() => void) | null
      onresult: ((event: unknown) => void) | null
      onerror: ((event: unknown) => void) | null
      onend: (() => void) | null
      start: ReturnType<typeof vi.fn>
      stop: ReturnType<typeof vi.fn>
    }

    beforeEach(() => {
      mockRecognition = {
        lang: '',
        continuous: false,
        interimResults: false,
        onstart: null,
        onresult: null,
        onerror: null,
        onend: null,
        start: vi.fn(),
        stop: vi.fn(),
      }
      // Define SpeechRecognition on window
      Object.defineProperty(window, 'SpeechRecognition', {
        configurable: true,
        writable: true,
        value: vi.fn(() => mockRecognition),
      })
    })

    afterEach(() => {
      // Clean up
      // @ts-expect-error - delete non-standard property
      delete window.SpeechRecognition
    })

    it('creates SpeechRecognition instance and starts recording', () => {
      const { startRecording } = useJarvisChat()
      startRecording()

      expect(mockRecognition.start).toHaveBeenCalled()
      expect(mockRecognition.lang).toBe('zh-CN')
      expect(mockRecognition.continuous).toBe(false)
      expect(mockRecognition.interimResults).toBe(false)
    })

    it('sets isListening to true on onstart', () => {
      const { startRecording, isListening, isRecording } = useJarvisChat()
      startRecording()

      mockRecognition.onstart?.()

      expect(isListening.value).toBe(true)
      expect(isRecording.value).toBe(true)
    })

    it('handles onresult with transcript and sends message (synchronous mode switch)', () => {
      const { startRecording, messages } = useJarvisChat()
      startRecording()

      // Event structure must match typeGuards: asRecord requires non-array objects,
      // asArray requires true arrays. Structure: results[0] is object with key 0 -> array -> string
      const event = {
        results: [{ 0: ['监控模式'] }],
      }
      mockRecognition.onresult?.(event)

      // 监控模式 is handled synchronously in sendMessage
      expect(messages.value.some((m) => m.content === '监控模式')).toBe(true)
      expect(messages.value.some((m) => m.content === '正在切换到监控模式...')).toBe(true)
    })

    it('handles onresult with empty transcript (does not send)', () => {
      const { startRecording, messages } = useJarvisChat()
      startRecording()

      const event = {
        results: [{ 0: [''] }],
      }
      mockRecognition.onresult?.(event)

      expect(messages.value).toHaveLength(0)
    })

    it('handles onerror and stops recording', () => {
      const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const { startRecording, isListening, isRecording } = useJarvisChat()
      startRecording()

      mockRecognition.onerror?.({ error: 'network' })

      expect(errSpy).toHaveBeenCalled()
      expect(isListening.value).toBe(false)
      expect(isRecording.value).toBe(false)
    })

    it('handles onend and resets isListening', () => {
      const { startRecording, isListening } = useJarvisChat()
      startRecording()
      mockRecognition.onstart?.()
      expect(isListening.value).toBe(true)

      mockRecognition.onend?.()

      expect(isListening.value).toBe(false)
    })

    it('uses webkitSpeechRecognition when SpeechRecognition is not available', () => {
      // @ts-expect-error - delete non-standard property
      delete window.SpeechRecognition
      Object.defineProperty(window, 'webkitSpeechRecognition', {
        configurable: true,
        writable: true,
        value: vi.fn(() => mockRecognition),
      })

      const { startRecording } = useJarvisChat()
      startRecording()

      expect(mockRecognition.start).toHaveBeenCalled()

      // @ts-expect-error - delete non-standard property
      delete window.webkitSpeechRecognition
    })
  })

  describe('stopRecording', () => {
    it('sets isListening to false', () => {
      const { stopRecording, isListening } = useJarvisChat()
      isListening.value = true
      stopRecording()
      expect(isListening.value).toBe(false)
    })

    it('sets isRecording to false via store', () => {
      const { stopRecording, isRecording } = useJarvisChat()
      stopRecording()
      expect(isRecording.value).toBe(false)
    })

    it('does not throw when recognition is null', () => {
      const { stopRecording } = useJarvisChat()
      expect(() => stopRecording()).not.toThrow()
    })

    it('stops recognition when active', () => {
      const mockStop = vi.fn()
      const mockRecognition = {
        lang: '',
        continuous: false,
        interimResults: false,
        onstart: null,
        onresult: null,
        onerror: null,
        onend: null,
        start: vi.fn(),
        stop: mockStop,
      }
      Object.defineProperty(window, 'SpeechRecognition', {
        configurable: true,
        writable: true,
        value: vi.fn(() => mockRecognition),
      })

      const { startRecording, stopRecording } = useJarvisChat()
      startRecording()
      stopRecording()

      expect(mockStop).toHaveBeenCalled()

      // @ts-expect-error - delete non-standard property
      delete window.SpeechRecognition
    })
  })

  describe('queueVoice', () => {
    it('queues voice text and starts playing', () => {
      const { queueVoice, isPlaying } = useJarvisChat()
      queueVoice('hello')
      expect(isPlaying.value).toBe(true)
    })

    it('calls cleanTextForSpeech via speakText', () => {
      const { queueVoice } = useJarvisChat()
      queueVoice('hello world')
      // speakText is called asynchronously via speak()
      expect(mockCleanText).toHaveBeenCalledWith('hello world')
    })
  })

  describe('speak', () => {
    it('queues voice text (alias for queueVoice)', () => {
      const { speak, isPlaying } = useJarvisChat()
      speak('test text')
      expect(isPlaying.value).toBe(true)
    })

    it('calls cleanTextForSpeech', () => {
      const { speak } = useJarvisChat()
      speak('test text')
      expect(mockCleanText).toHaveBeenCalledWith('test text')
    })
  })

  describe('setStatus', () => {
    it('sets statusText in store', () => {
      const { setStatus, statusText } = useJarvisChat()
      setStatus('custom status')
      expect(statusText.value).toBe('custom status')
    })

    it('sets empty status', () => {
      const { setStatus, statusText } = useJarvisChat()
      setStatus('')
      expect(statusText.value).toBe('')
    })
  })

  describe('setCoreSpeaking', () => {
    it('sets isCoreSpeaking to true', () => {
      const { setCoreSpeaking, isCoreSpeaking } = useJarvisChat()
      setCoreSpeaking(true)
      expect(isCoreSpeaking.value).toBe(true)
    })

    it('sets isCoreSpeaking to false', () => {
      const { setCoreSpeaking, isCoreSpeaking } = useJarvisChat()
      setCoreSpeaking(true)
      setCoreSpeaking(false)
      expect(isCoreSpeaking.value).toBe(false)
    })
  })

  describe('clearMessages', () => {
    it('clears all messages', () => {
      const { addMessage, clearMessages, messages } = useJarvisChat()
      addMessage('first')
      addMessage('second')
      expect(messages.value).toHaveLength(2)

      clearMessages()
      expect(messages.value).toEqual([])
    })
  })

  describe('clearVoiceQueue', () => {
    it('clears voice queue and stops speaking', () => {
      const { queueVoice, clearVoiceQueue, isPlaying } = useJarvisChat()
      queueVoice('hello')
      expect(isPlaying.value).toBe(true)

      clearVoiceQueue()
      expect(isPlaying.value).toBe(false)
      expect(mockStopSpeaking).toHaveBeenCalled()
    })

    it('does not throw when queue is already empty', () => {
      const { clearVoiceQueue } = useJarvisChat()
      expect(() => clearVoiceQueue()).not.toThrow()
    })
  })

  describe('return value shape', () => {
    it('returns all expected properties', () => {
      const result = useJarvisChat()
      expect(result).toHaveProperty('messages')
      expect(result).toHaveProperty('isRecording')
      expect(result).toHaveProperty('isPlaying')
      expect(result).toHaveProperty('isListening')
      expect(result).toHaveProperty('statusText')
      expect(result).toHaveProperty('isCoreSpeaking')
      expect(result).toHaveProperty('sendMessage')
      expect(result).toHaveProperty('addMessage')
      expect(result).toHaveProperty('addTaskMessage')
      expect(result).toHaveProperty('startRecording')
      expect(result).toHaveProperty('stopRecording')
      expect(result).toHaveProperty('queueVoice')
      expect(result).toHaveProperty('speak')
      expect(result).toHaveProperty('setStatus')
      expect(result).toHaveProperty('setCoreSpeaking')
      expect(result).toHaveProperty('clearMessages')
      expect(result).toHaveProperty('clearVoiceQueue')
    })

    it('returns functions for methods', () => {
      const result = useJarvisChat()
      expect(typeof result.sendMessage).toBe('function')
      expect(typeof result.addMessage).toBe('function')
      expect(typeof result.addTaskMessage).toBe('function')
      expect(typeof result.startRecording).toBe('function')
      expect(typeof result.stopRecording).toBe('function')
      expect(typeof result.queueVoice).toBe('function')
      expect(typeof result.speak).toBe('function')
      expect(typeof result.setStatus).toBe('function')
      expect(typeof result.setCoreSpeaking).toBe('function')
      expect(typeof result.clearMessages).toBe('function')
      expect(typeof result.clearVoiceQueue).toBe('function')
    })
  })
})
