import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { nextTick, ref } from 'vue'
import { apiFetch } from '@/utils/apiBase'
import { speakText } from '@/utils/tts'
import { voiceCallActive } from '@/composables/voiceCallHost'

const sendMessageMock = vi.fn()
const messagesMock = ref<Array<{ role: string; content: string; time: string }>>([])

vi.mock('@/composables/useChatView', () => ({
  useChatView: () => ({
    messages: messagesMock,
    isLoading: ref(false),
    isStreamingReply: ref(false),
    loadingProgressText: ref(''),
    sendMessage: sendMessageMock,
  }),
}))

vi.mock('@/utils/sanitizeHtml', () => ({
  sanitizeChatBubbleHtml: vi.fn((html: string) => html),
  plainTextFromChatHtml: vi.fn((html: string) => html),
}))

vi.mock('@/utils/chatStorageKeys', async importOriginal => ({
  ...await importOriginal<typeof import('@/utils/chatStorageKeys')>(),
  readAiSessionIdFromStorage: vi.fn(() => 'voice-call-session'),
  writeAiSessionIdToStorage: vi.fn(),
}))

vi.mock('@/utils/tts', () => ({
  speakText: vi.fn(),
  stopSpeaking: vi.fn(),
  createChineseUtterance: vi.fn(() => ({})),
}))

vi.mock('@/utils/apiBase', () => ({
  apiFetch: vi.fn(),
}))

import FloatingChatAssistant from '@/components/FloatingChatAssistant.vue'
enableAutoUnmount(afterEach)

/** 可控麦克风能量：0 表示静音，>0 表示有人说话。 */
let micLevel = 0

class MockAnalyser {
  fftSize = 1024
  getFloatTimeDomainData(buffer: Float32Array) {
    buffer.fill(micLevel)
  }
}

class MockAudioContext {
  createMediaStreamSource() {
    return { connect: vi.fn() }
  }
  createGain() {
    return { gain: { value: 0 }, connect: vi.fn() }
  }
  createAnalyser() {
    return new MockAnalyser()
  }
  resume() {
    return Promise.resolve()
  }
  close() {
    return Promise.resolve()
  }
}

class MockMediaRecorder {
  static isTypeSupported = vi.fn(() => true)
  state: 'inactive' | 'recording' = 'inactive'
  mimeType = 'audio/webm'
  private listeners: Record<string, Array<(event?: unknown) => void>> = {}

  addEventListener(type: string, callback: (event?: unknown) => void) {
    ;(this.listeners[type] ||= []).push(callback)
  }

  start() {
    this.state = 'recording'
  }

  stop() {
    if (this.state === 'inactive') return
    this.state = 'inactive'
    this.listeners.dataavailable?.forEach(callback => callback({ data: new Blob(['voice'], { type: 'audio/webm' }) }))
    this.listeners.stop?.forEach(callback => callback())
  }
}

const originalMediaDevices = Object.getOwnPropertyDescriptor(navigator, 'mediaDevices')
const originalMediaRecorder = Object.getOwnPropertyDescriptor(window, 'MediaRecorder')

function installMicrophone(getUserMedia: () => Promise<MediaStream>) {
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: vi.fn(getUserMedia) },
  })
  Object.defineProperty(window, 'MediaRecorder', { configurable: true, value: MockMediaRecorder })
  vi.stubGlobal('AudioContext', MockAudioContext)
}

function mockStream(): MediaStream {
  const track = { stop: vi.fn(), readyState: 'live' }
  return {
    getTracks: () => [track],
    getAudioTracks: () => [track],
  } as unknown as MediaStream
}

function mountAssistant() {
  return mount(FloatingChatAssistant, { props: { visible: true }, attachTo: document.body })
}

async function openAssistant() {
  const wrapper = mountAssistant()
  await wrapper.get('.floating-chat-toggle').trigger('click')
  return wrapper
}

describe('FloatingChatAssistant 语音通话', () => {
  beforeEach(() => {
    sendMessageMock.mockReset()
    messagesMock.value = []
    voiceCallActive.value = false
    micLevel = 0
    vi.mocked(apiFetch).mockReset()
    vi.mocked(speakText).mockReset().mockResolvedValue(undefined)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    if (originalMediaDevices) Object.defineProperty(navigator, 'mediaDevices', originalMediaDevices)
    else delete (navigator as unknown as { mediaDevices?: unknown }).mediaDevices
    if (originalMediaRecorder) Object.defineProperty(window, 'MediaRecorder', originalMediaRecorder)
    else delete (window as unknown as { MediaRecorder?: unknown }).MediaRecorder
  })

  it('进入通话界面并让宿主保持可见', async () => {
    const wrapper = await openAssistant()
    expect(wrapper.find('.floating-chat-call-entry').attributes('title')).toBe('语音通话')

    await wrapper.get('.floating-chat-call-entry').trigger('click')
    await nextTick()

    expect(wrapper.find('.floating-chat-call').exists()).toBe(true)
    expect(wrapper.find('.floating-chat-messages').exists()).toBe(false)
    expect(voiceCallActive.value).toBe(true)
    expect(wrapper.get('.floating-chat-call-stage').text()).toBe('正在接通…')
    expect(wrapper.get('.floating-chat-call-hangup').text()).toContain('挂断')
  })

  it('按 聆听 → 思考 → 说话 推进阶段并在挂断后释放通话状态', async () => {
    vi.useFakeTimers()
    installMicrophone(async () => mockStream())
    let resolveTranscription: (value: Response) => void = () => {}
    vi.mocked(apiFetch).mockImplementation(() => new Promise<Response>((resolve) => {
      resolveTranscription = resolve
    }))
    let resolveSpeak: () => void = () => {}
    vi.mocked(speakText).mockImplementation(() => new Promise<void>((resolve) => {
      resolveSpeak = resolve
    }))
    sendMessageMock.mockImplementation(async () => {
      messagesMock.value = [
        ...messagesMock.value,
        { role: 'ai', content: '库存还有 12 件', time: '10:00' },
      ]
    })

    const wrapper = await openAssistant()
    await wrapper.get('.floating-chat-call-entry').trigger('click')
    await nextTick()
    await vi.advanceTimersByTimeAsync(400)
    expect(wrapper.get('.floating-chat-call-stage').text()).toBe('正在聆听…')

    micLevel = 0.25
    await vi.advanceTimersByTimeAsync(1_500)
    micLevel = 0
    await vi.advanceTimersByTimeAsync(900)
    expect(wrapper.get('.floating-chat-call-stage').text()).toBe('正在思考…')

    resolveTranscription({
      ok: true,
      text: async () => JSON.stringify({ success: true, data: { text: '帮我查下库存' } }),
    } as Response)
    await flushPromises()
    await nextTick()

    expect(sendMessageMock).toHaveBeenCalledWith('帮我查下库存')
    expect(wrapper.get('.floating-chat-call-caption.user').text()).toContain('帮我查下库存')
    expect(wrapper.get('.floating-chat-call-caption.ai').text()).toContain('库存还有 12 件')
    expect(wrapper.get('.floating-chat-call-stage').text()).toBe('正在说话…')

    resolveSpeak()
    await vi.advanceTimersByTimeAsync(300)
    expect(wrapper.get('.floating-chat-call-stage').text()).toBe('正在聆听…')

    await wrapper.get('.floating-chat-call-hangup').trigger('click')
    await nextTick()
    expect(voiceCallActive.value).toBe(false)
    expect(wrapper.find('.floating-chat-call').exists()).toBe(false)
    expect(wrapper.find('.floating-chat-call-entry').exists()).toBe(true)
  })

  it('支持静音、恢复聆听与免提切换', async () => {
    vi.useFakeTimers()
    installMicrophone(async () => mockStream())

    const wrapper = await openAssistant()
    await wrapper.get('.floating-chat-call-entry').trigger('click')
    await nextTick()
    await vi.advanceTimersByTimeAsync(400)
    expect(wrapper.get('.floating-chat-call-stage').text()).toBe('正在聆听…')

    await wrapper.findAll('.floating-chat-call-action').find(button => button.text().includes('静音'))!.trigger('click')
    await nextTick()
    expect(wrapper.get('.floating-chat-call-stage').text()).toBe('已静音')

    await wrapper.findAll('.floating-chat-call-action').find(button => button.text().includes('取消静音'))!.trigger('click')
    await vi.advanceTimersByTimeAsync(400)
    expect(wrapper.get('.floating-chat-call-stage').text()).toBe('正在聆听…')

    await wrapper.findAll('.floating-chat-call-action').find(button => button.text().includes('免提开'))!.trigger('click')
    await nextTick()
    expect(wrapper.findAll('.floating-chat-call-action').some(button => button.text().includes('免提关'))).toBe(true)
  })

  it('合成语音失败时回退系统语音播报', async () => {
    vi.useFakeTimers()
    installMicrophone(async () => mockStream())
    const synthSpeak = vi.fn(() => { throw new Error('系统语音不可用') })
    vi.stubGlobal('speechSynthesis', { speak: synthSpeak, cancel: vi.fn() })
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      text: async () => JSON.stringify({ success: true, data: { text: '你好' } }),
    } as Response)
    sendMessageMock.mockImplementation(async () => {
      messagesMock.value = [{ role: 'ai', content: '您好，有什么可以帮您', time: '10:00' }]
    })
    vi.mocked(speakText).mockImplementation(async (_text, options) => {
      ;(options as { onError?: () => void } | undefined)?.onError?.()
    })

    const wrapper = await openAssistant()
    await wrapper.get('.floating-chat-call-entry').trigger('click')
    await nextTick()
    await vi.advanceTimersByTimeAsync(400)
    micLevel = 0.3
    await vi.advanceTimersByTimeAsync(1_500)
    micLevel = 0
    await vi.advanceTimersByTimeAsync(900)
    await flushPromises()
    await vi.advanceTimersByTimeAsync(50)

    expect(synthSpeak).toHaveBeenCalled()
  })

  it('麦克风权限被拒时给出可见提示', async () => {
    vi.useFakeTimers()
    installMicrophone(() => Promise.reject(Object.assign(new Error('denied'), { name: 'NotAllowedError' })))

    const wrapper = await openAssistant()
    await wrapper.get('.floating-chat-call-entry').trigger('click')
    await nextTick()
    await vi.advanceTimersByTimeAsync(400)
    await flushPromises()

    expect(wrapper.get('.floating-chat-call-caption.error').text()).toContain('麦克风权限被拒绝')
    expect(wrapper.get('.floating-chat-call-stage').text()).toContain('麦克风权限被拒绝')
  })

  it('对话失败时给出可见错误并继续聆听', async () => {
    vi.useFakeTimers()
    installMicrophone(async () => mockStream())
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      text: async () => JSON.stringify({ success: true, data: { text: '你好' } }),
    } as Response)
    sendMessageMock.mockRejectedValue(new Error('网络连接中断，请稍后再试'))

    const wrapper = await openAssistant()
    await wrapper.get('.floating-chat-call-entry').trigger('click')
    await nextTick()
    await vi.advanceTimersByTimeAsync(400)
    micLevel = 0.3
    await vi.advanceTimersByTimeAsync(1_500)
    micLevel = 0
    await vi.advanceTimersByTimeAsync(900)
    await flushPromises()

    expect(wrapper.get('.floating-chat-call-caption.error').text()).toContain('网络连接中断')
    await vi.advanceTimersByTimeAsync(300)
    expect(wrapper.get('.floating-chat-call-stage').text()).toBe('正在聆听…')
  })

  it('没有拿到回复时改用口语提示重说', async () => {
    vi.useFakeTimers()
    installMicrophone(async () => mockStream())
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      text: async () => JSON.stringify({ success: true, data: { text: '你好' } }),
    } as Response)
    sendMessageMock.mockResolvedValue(undefined)

    const wrapper = await openAssistant()
    await wrapper.get('.floating-chat-call-entry').trigger('click')
    await nextTick()
    await vi.advanceTimersByTimeAsync(400)
    micLevel = 0.3
    await vi.advanceTimersByTimeAsync(1_500)
    micLevel = 0
    await vi.advanceTimersByTimeAsync(900)
    await flushPromises()

    expect(wrapper.get('.floating-chat-call-caption.error').text()).toContain('网络有点慢')
    expect(wrapper.find('.floating-chat-call-caption.ai').exists()).toBe(false)
    expect(vi.mocked(speakText)).toHaveBeenCalledWith(
      '网络有点慢，我没收到回复，请再说一次。',
      expect.anything(),
    )
  })

  it('语音识别失败后回到聆听而不是中断通话', async () => {
    vi.useFakeTimers()
    installMicrophone(async () => mockStream())
    vi.mocked(apiFetch).mockResolvedValue({
      ok: false,
      status: 503,
      text: async () => JSON.stringify({ success: false, detail: '识别服务暂不可用' }),
    } as Response)

    const wrapper = await openAssistant()
    await wrapper.get('.floating-chat-call-entry').trigger('click')
    await nextTick()
    await vi.advanceTimersByTimeAsync(400)
    micLevel = 0.3
    await vi.advanceTimersByTimeAsync(1_500)
    micLevel = 0
    await vi.advanceTimersByTimeAsync(900)
    await flushPromises()

    expect(vi.mocked(apiFetch)).toHaveBeenCalledTimes(1)
    expect(wrapper.get('.floating-chat-call-stage').text()).toBe('正在聆听…')
    expect(wrapper.find('.floating-chat-call-caption.ai').exists()).toBe(false)
  })

  it('响应 xcagi:start-voice-call 事件并在卸载时移除监听', async () => {
    const wrapper = mountAssistant()
    window.dispatchEvent(new Event('xcagi:start-voice-call'))
    await nextTick()
    await nextTick()
    expect(voiceCallActive.value).toBe(true)

    const remove = vi.spyOn(window, 'removeEventListener')
    wrapper.unmount()
    expect(remove).toHaveBeenCalledWith('xcagi:start-voice-call', expect.any(Function))

    voiceCallActive.value = false
    window.dispatchEvent(new Event('xcagi:start-voice-call'))
    await nextTick()
    expect(voiceCallActive.value).toBe(false)
  })
})
