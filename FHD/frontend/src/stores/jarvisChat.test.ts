import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('../utils/tts', () => ({
  speakText: vi.fn().mockResolvedValue(undefined),
  stopSpeaking: vi.fn(),
  cleanTextForSpeech: (t: string) => t,
}))

vi.mock('./proMode', () => ({
  useProModeStore: () => ({
    enterMonitorMode: vi.fn(),
    exitMonitorMode: vi.fn(),
    enterWorkMode: vi.fn(),
    exitWorkMode: vi.fn(),
  }),
}))

import { useJarvisChatStore } from './jarvisChat'

describe('useJarvisChatStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
  })

  it('addMessage appends to messages', () => {
    const store = useJarvisChatStore()
    store.addMessage('hello', 'user')
    expect(store.messages).toHaveLength(1)
    expect(store.messages[0].content).toBe('hello')
    expect(store.lastMessage?.content).toBe('hello')
  })

  it('addTaskMessage includes taskData', () => {
    const store = useJarvisChatStore()
    store.addTaskMessage('task', { id: 1 })
    expect(store.messages[0].type).toBe('task')
    expect(store.messages[0].taskData).toEqual({ id: 1 })
  })

  it('generateResponse handles product keyword', () => {
    const store = useJarvisChatStore()
    expect(store.generateResponse('查产品')).toContain('产品')
  })

  it('generateResponse handles default', () => {
    const store = useJarvisChatStore()
    expect(store.generateResponse('随便')).toContain('收到')
  })

  it('sendMessage handles monitor mode command', async () => {
    const store = useJarvisChatStore()
    const reply = await store.sendMessage('进入监控模式')
    expect(reply).toContain('监控')
    expect(store.messages.length).toBeGreaterThanOrEqual(2)
  })

  it('clearMessages resets state', () => {
    const store = useJarvisChatStore()
    store.addMessage('x')
    store.clearMessages()
    expect(store.messages).toHaveLength(0)
  })

  it('clearVoiceQueue stops playback flags', () => {
    const store = useJarvisChatStore()
    store.voiceQueue.push('a')
    store.isPlaying = true
    store.clearVoiceQueue()
    expect(store.voiceQueue).toHaveLength(0)
    expect(store.isPlaying).toBe(false)
  })

  it('startRecording and stopRecording update status', () => {
    const store = useJarvisChatStore()
    store.startRecording()
    expect(store.isRecording).toBe(true)
    store.stopRecording()
    expect(store.isRecording).toBe(false)
    vi.advanceTimersByTime(1100)
    expect(store.statusText).toBe('准备就绪')
  })
})
