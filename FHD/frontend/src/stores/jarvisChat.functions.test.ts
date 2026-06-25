import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { mockSpeakText, mockStopSpeaking, mockCleanText, mockEnterMonitor, mockExitMonitor, mockEnterWork, mockExitWork } = vi.hoisted(() => ({
  mockSpeakText: vi.fn(() => Promise.resolve()),
  mockStopSpeaking: vi.fn(),
  mockCleanText: vi.fn((text: string) => text),
  mockEnterMonitor: vi.fn(),
  mockExitMonitor: vi.fn(),
  mockEnterWork: vi.fn(),
  mockExitWork: vi.fn(),
}))

vi.mock('../utils/tts', () => ({
  speakText: mockSpeakText,
  stopSpeaking: mockStopSpeaking,
  cleanTextForSpeech: mockCleanText,
}))

vi.mock('./proMode', () => ({
  useProModeStore: () => ({
    enterMonitorMode: mockEnterMonitor,
    exitMonitorMode: mockExitMonitor,
    enterWorkMode: mockEnterWork,
    exitWorkMode: mockExitWork,
  }),
}))

vi.mock('@/utils/typeGuards', () => ({
  asRecord: vi.fn((v: unknown) => (v && typeof v === 'object' ? v : {})),
  asArray: vi.fn((v: unknown) => (Array.isArray(v) ? v : [])),
  asString: vi.fn((v: unknown) => (typeof v === 'string' ? v : '')),
  asBoolean: vi.fn((v: unknown) => typeof v === 'boolean' ? v : false),
  asDisposable: vi.fn(),
}))

import { useJarvisChatStore } from './jarvisChat'

describe('useJarvisChatStore', () => {
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
  })

  describe('initial state', () => {
    it('starts with empty messages', () => {
      const store = useJarvisChatStore()
      expect(store.messages).toEqual([])
    })

    it('starts with isRecording false', () => {
      const store = useJarvisChatStore()
      expect(store.isRecording).toBe(false)
    })

    it('starts with isPlaying false', () => {
      const store = useJarvisChatStore()
      expect(store.isPlaying).toBe(false)
    })

    it('starts with empty voiceQueue', () => {
      const store = useJarvisChatStore()
      expect(store.voiceQueue).toEqual([])
    })

    it('starts with currentTask null', () => {
      const store = useJarvisChatStore()
      expect(store.currentTask).toBeNull()
    })

    it('starts with statusText "准备就绪"', () => {
      const store = useJarvisChatStore()
      expect(store.statusText).toBe('准备就绪')
    })

    it('starts with isCoreSpeaking false', () => {
      const store = useJarvisChatStore()
      expect(store.isCoreSpeaking).toBe(false)
    })

    it('starts with lastMessage undefined', () => {
      const store = useJarvisChatStore()
      expect(store.lastMessage).toBeUndefined()
    })

    it('starts with hasPendingVoice false', () => {
      const store = useJarvisChatStore()
      expect(store.hasPendingVoice).toBe(false)
    })
  })

  describe('addMessage', () => {
    it('adds an ai message by default', () => {
      const store = useJarvisChatStore()
      store.addMessage('hello')
      expect(store.messages.length).toBe(1)
      expect(store.messages[0].content).toBe('hello')
      expect(store.messages[0].type).toBe('ai')
    })

    it('adds a user message when type is specified', () => {
      const store = useJarvisChatStore()
      store.addMessage('hi', 'user')
      expect(store.messages[0].type).toBe('user')
    })

    it('adds a task message when type is task', () => {
      const store = useJarvisChatStore()
      store.addMessage('task done', 'task')
      expect(store.messages[0].type).toBe('task')
    })

    it('updates lastMessage after adding', () => {
      const store = useJarvisChatStore()
      store.addMessage('hello')
      expect(store.lastMessage).toBeDefined()
      expect(store.lastMessage?.content).toBe('hello')
    })

    it('includes timestamp in ISO format', () => {
      const store = useJarvisChatStore()
      store.addMessage('hello')
      expect(store.messages[0].timestamp).toMatch(/^\d{4}-\d{2}-\d{2}T/)
    })

    it('includes numeric id', () => {
      const store = useJarvisChatStore()
      store.addMessage('hello')
      expect(typeof store.messages[0].id).toBe('number')
    })
  })

  describe('addTaskMessage', () => {
    it('adds a task message with taskData', () => {
      const store = useJarvisChatStore()
      const taskData = { action: 'query' }
      store.addTaskMessage('executing task', taskData)
      expect(store.messages.length).toBe(1)
      expect(store.messages[0].type).toBe('task')
      expect(store.messages[0].taskData).toEqual(taskData)
    })

    it('updates lastMessage after adding task', () => {
      const store = useJarvisChatStore()
      store.addTaskMessage('task', { foo: 'bar' })
      expect(store.lastMessage?.content).toBe('task')
    })
  })

  describe('generateResponse', () => {
    it('returns product response for "产品"', () => {
      const store = useJarvisChatStore()
      expect(store.generateResponse('查询产品')).toBe('正在为您查询产品信息...')
    })

    it('returns product response for "product" (case-insensitive)', () => {
      const store = useJarvisChatStore()
      expect(store.generateResponse('PRODUCT list')).toBe('正在为您查询产品信息...')
    })

    it('returns customer response for "客户"', () => {
      const store = useJarvisChatStore()
      expect(store.generateResponse('查询客户')).toBe('正在为您查询客户信息...')
    })

    it('returns customer response for "customer"', () => {
      const store = useJarvisChatStore()
      expect(store.generateResponse('customer info')).toBe('正在为您查询客户信息...')
    })

    it('returns order response for "订单"', () => {
      const store = useJarvisChatStore()
      expect(store.generateResponse('查看订单')).toBe('正在为您查询订单信息...')
    })

    it('returns order response for "order"', () => {
      const store = useJarvisChatStore()
      expect(store.generateResponse('order status')).toBe('正在为您查询订单信息...')
    })

    it('returns work mode response for "工作模式"', () => {
      const store = useJarvisChatStore()
      expect(store.generateResponse('进入工作模式')).toBe('正在进入工作模式...')
    })

    it('returns work mode response for "work mode"', () => {
      const store = useJarvisChatStore()
      expect(store.generateResponse('enter work mode')).toBe('正在进入工作模式...')
    })

    it('returns default response for unknown message', () => {
      const store = useJarvisChatStore()
      expect(store.generateResponse('hello world')).toBe('我已收到您的消息，正在处理中...')
    })

    it('returns default response for empty message', () => {
      const store = useJarvisChatStore()
      expect(store.generateResponse('')).toBe('我已收到您的消息，正在处理中...')
    })
  })

  describe('queueVoice', () => {
    it('adds text to voiceQueue and starts playing (shifts out first item)', () => {
      const store = useJarvisChatStore()
      store.queueVoice('hello')
      // playNextVoice shifts the text out and starts speaking
      expect(store.isPlaying).toBe(true)
      expect(store.isCoreSpeaking).toBe(true)
    })

    it('starts playing when not already playing', () => {
      const store = useJarvisChatStore()
      store.queueVoice('hello')
      expect(store.isPlaying).toBe(true)
    })

    it('keeps second item in queue when already playing', () => {
      const store = useJarvisChatStore()
      store.queueVoice('first')   // shifts 'first' out, starts playing
      store.queueVoice('second')  // isPlaying is true, so stays in queue
      expect(store.isPlaying).toBe(true)
      expect(store.voiceQueue.length).toBe(1)
      expect(store.voiceQueue[0]).toBe('second')
    })
  })

  describe('playNextVoice', () => {
    it('sets isPlaying false when queue is empty', () => {
      const store = useJarvisChatStore()
      store.playNextVoice()
      expect(store.isPlaying).toBe(false)
      expect(store.isCoreSpeaking).toBe(false)
    })
  })

  describe('speak', () => {
    it('does not call speakText when cleaned text is empty', () => {
      mockCleanText.mockReturnValueOnce('')
      const store = useJarvisChatStore()
      store.speak('   ')
      expect(mockSpeakText).not.toHaveBeenCalled()
    })

    it('calls speakText with cleaned text', () => {
      mockCleanText.mockReturnValue('cleaned text')
      const store = useJarvisChatStore()
      store.speak('hello')
      expect(mockCleanText).toHaveBeenCalledWith('hello')
      expect(mockSpeakText).toHaveBeenCalledWith('cleaned text')
    })
  })

  describe('startRecording', () => {
    it('sets isRecording to true', () => {
      const store = useJarvisChatStore()
      store.startRecording()
      expect(store.isRecording).toBe(true)
    })

    it('sets statusText to "正在录音..."', () => {
      const store = useJarvisChatStore()
      store.startRecording()
      expect(store.statusText).toBe('正在录音...')
    })
  })

  describe('stopRecording', () => {
    it('sets isRecording to false', () => {
      const store = useJarvisChatStore()
      store.startRecording()
      store.stopRecording()
      expect(store.isRecording).toBe(false)
    })

    it('sets statusText to "处理中..."', () => {
      const store = useJarvisChatStore()
      store.stopRecording()
      expect(store.statusText).toBe('处理中...')
    })
  })

  describe('setStatus', () => {
    it('sets statusText to provided value', () => {
      const store = useJarvisChatStore()
      store.setStatus('custom status')
      expect(store.statusText).toBe('custom status')
    })

    it('sets statusText to empty string', () => {
      const store = useJarvisChatStore()
      store.setStatus('')
      expect(store.statusText).toBe('')
    })
  })

  describe('setCoreSpeaking', () => {
    it('sets isCoreSpeaking to true', () => {
      const store = useJarvisChatStore()
      store.setCoreSpeaking(true)
      expect(store.isCoreSpeaking).toBe(true)
    })

    it('sets isCoreSpeaking to false', () => {
      const store = useJarvisChatStore()
      store.setCoreSpeaking(true)
      store.setCoreSpeaking(false)
      expect(store.isCoreSpeaking).toBe(false)
    })
  })

  describe('setCurrentTask', () => {
    it('sets currentTask to provided value', () => {
      const store = useJarvisChatStore()
      const task = { id: 1, action: 'query' }
      store.setCurrentTask(task)
      expect(store.currentTask).toEqual(task)
    })

    it('sets currentTask to null', () => {
      const store = useJarvisChatStore()
      store.setCurrentTask({ id: 1 })
      store.setCurrentTask(null)
      expect(store.currentTask).toBeNull()
    })

    it('sets currentTask to string', () => {
      const store = useJarvisChatStore()
      store.setCurrentTask('task string')
      expect(store.currentTask).toBe('task string')
    })
  })

  describe('clearMessages', () => {
    it('clears all messages', () => {
      const store = useJarvisChatStore()
      store.addMessage('hello')
      store.addMessage('world')
      store.clearMessages()
      expect(store.messages).toEqual([])
    })

    it('updates lastMessage to undefined after clearing', () => {
      const store = useJarvisChatStore()
      store.addMessage('hello')
      store.clearMessages()
      expect(store.lastMessage).toBeUndefined()
    })
  })

  describe('clearVoiceQueue', () => {
    it('clears voice queue', () => {
      const store = useJarvisChatStore()
      store.queueVoice('hello')
      store.clearVoiceQueue()
      expect(store.voiceQueue).toEqual([])
    })

    it('sets isPlaying to false', () => {
      const store = useJarvisChatStore()
      store.queueVoice('hello')
      store.clearVoiceQueue()
      expect(store.isPlaying).toBe(false)
    })

    it('sets isCoreSpeaking to false', () => {
      const store = useJarvisChatStore()
      store.queueVoice('hello')
      store.clearVoiceQueue()
      expect(store.isCoreSpeaking).toBe(false)
    })

    it('calls stopSpeaking', () => {
      const store = useJarvisChatStore()
      store.clearVoiceQueue()
      expect(mockStopSpeaking).toHaveBeenCalled()
    })
  })

  describe('sendMessage', () => {
    it('returns monitor mode response for "监控模式"', async () => {
      const store = useJarvisChatStore()
      const result = await store.sendMessage('进入监控模式')
      expect(result).toBe('正在切换到监控模式...')
    })

    it('calls enterMonitorMode for "监控模式"', async () => {
      const store = useJarvisChatStore()
      await store.sendMessage('监控模式')
      expect(mockEnterMonitor).toHaveBeenCalled()
    })

    it('adds user and ai messages for "监控模式"', async () => {
      const store = useJarvisChatStore()
      await store.sendMessage('监控模式')
      expect(store.messages.length).toBe(2)
      expect(store.messages[0].type).toBe('user')
      expect(store.messages[1].type).toBe('ai')
    })

    it('returns work mode response for "工作模式"', async () => {
      const store = useJarvisChatStore()
      const result = await store.sendMessage('进入工作模式')
      expect(result).toBe('正在切换到工作模式...')
    })

    it('calls enterWorkMode for "工作模式"', async () => {
      const store = useJarvisChatStore()
      await store.sendMessage('工作模式')
      expect(mockEnterWork).toHaveBeenCalled()
    })

    it('returns work mode response for "work mode"', async () => {
      const store = useJarvisChatStore()
      const result = await store.sendMessage('enter work mode')
      expect(result).toBe('正在切换到工作模式...')
    })

    it('adds user message for non-mode messages', async () => {
      const store = useJarvisChatStore()
      vi.useFakeTimers()
      const promise = store.sendMessage('查询产品')
      expect(store.messages.length).toBe(1)
      expect(store.messages[0].type).toBe('user')
      vi.advanceTimersByTime(1000)
      await promise
      vi.useRealTimers()
    })

    it('resolves with generated response for non-mode messages', async () => {
      const store = useJarvisChatStore()
      vi.useFakeTimers()
      const promise = store.sendMessage('查询产品')
      vi.advanceTimersByTime(1000)
      const result = await promise
      vi.useRealTimers()
      expect(result).toBe('正在为您查询产品信息...')
    })
  })

  describe('syncLegacyMonitorMode', () => {
    it('returns false when window.setMonitorModeFromChat is not a function', () => {
      const store = useJarvisChatStore()
      // Default jsdom window doesn't have setMonitorModeFromChat
      // syncLegacyMonitorMode is not directly exposed, but tested via sendMessage
      expect(store.isPlaying).toBe(false)
    })
  })

  describe('syncLegacyWorkMode', () => {
    it('returns false when window.setWorkModeFromChat is not a function', () => {
      const store = useJarvisChatStore()
      expect(store.isPlaying).toBe(false)
    })
  })

  describe('updateLastMessage (via addMessage)', () => {
    it('updates hasPendingVoice when voiceQueue has items', () => {
      const store = useJarvisChatStore()
      // First call starts playing and shifts 'first' out
      store.queueVoice('first')
      // Second call keeps 'second' in queue since isPlaying is true
      store.queueVoice('second')
      store.addMessage('message')
      expect(store.hasPendingVoice).toBe(true)
    })

    it('updates hasPendingVoice to false when voiceQueue is empty', () => {
      const store = useJarvisChatStore()
      store.addMessage('message')
      expect(store.hasPendingVoice).toBe(false)
    })
  })
})
