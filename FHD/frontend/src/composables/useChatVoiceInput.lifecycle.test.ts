import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, onBeforeUnmount, ref, type Ref } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import { apiFetch } from '@/utils/apiBase'
import { useChatVoiceInput } from './useChatVoiceInput'

vi.mock('@/utils/apiBase', () => ({ apiFetch: vi.fn() }))

const recorderStart = vi.fn(), trackStop = vi.fn()
const wrappers: VueWrapper[] = []
class MockMediaRecorder {
  static isTypeSupported = () => true
  state = 'inactive'
  handlers: Record<string, (event?: unknown) => void> = {}
  addEventListener(name: string, cb: (event?: unknown) => void) { this.handlers[name] = cb }
  start() { this.state = 'recording'; recorderStart() }
  stop() {
    this.state = 'inactive'
    this.handlers.dataavailable?.({ data: new Blob(['controlled audio'], { type: 'audio/webm' }) })
    this.handlers.stop?.()
  }
}
const stream = { getTracks: () => [{ stop: trackStop }] } as unknown as MediaStream
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r }); return { promise, resolve } }
async function flush() { for (let i = 0; i < 8; i++) await Promise.resolve() }
function host() {
  let api!: ReturnType<typeof useChatVoiceInput>
  const messageInput: Ref<string> = ref('')
  const sessionId = ref('original-session')
  const wrapper = mount(defineComponent({
    setup() {
      api = useChatVoiceInput({ messageInput, isLoading: ref(false), sessionId })
      // ChatView's host invokes this same cleanup at onBeforeUnmount.
      onBeforeUnmount(api.cleanupVoiceInput)
      return () => h('button', {
        onMousedown: () => { void api.startVoiceRecording() },
        onMouseup: () => api.stopVoiceRecording(false),
      }, api.voiceButtonText.value)
    },
  }))
  wrappers.push(wrapper)
  return { api, wrapper, messageInput, sessionId }
}

describe('voice lifecycle regressions', () => {
  it('does not claim a skipped warm request loaded the model', async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ok: true, json: async () => ({ success: true, data: { skipped: true, model_loaded: false } }) } as Response)
    const test = host()
    await test.api.warmVoiceModel()
    expect(test.api.voiceModelWarm.value).toBe(false)
  })
  beforeEach(() => {
    vi.useFakeTimers(); vi.setSystemTime(1000); vi.clearAllMocks()
    vi.stubGlobal('MediaRecorder', MockMediaRecorder)
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue(stream) } })
    vi.mocked(apiFetch).mockResolvedValue({ ok: true, text: async () => JSON.stringify({ success: true, data: { text: 'hello' } }) } as Response)
  })
  afterEach(() => {
    wrappers.splice(0).forEach(wrapper => wrapper.unmount())
    vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals()
  })
  it('immediate grant and deliberate release fills the input', async () => {
    const test = host()
    await test.wrapper.trigger('mousedown'); await flush()
    vi.setSystemTime(1600)
    await test.wrapper.trigger('mouseup'); await flush()
    expect(test.messageInput.value).toBe('hello')
    expect(trackStop).toHaveBeenCalled()
  })
  it('does not start capture after release while microphone permission is pending', async () => {
    const permission = deferred<MediaStream>()
    vi.mocked(navigator.mediaDevices.getUserMedia).mockReturnValue(permission.promise)
    const test = host()
    await test.wrapper.trigger('mousedown')
    await test.wrapper.trigger('mouseup')
    permission.resolve(stream); await flush()
    expect(recorderStart).not.toHaveBeenCalled()
    expect(trackStop).toHaveBeenCalled()
  })
  it('does not start capture after real Vue unmount while permission is pending', async () => {
    const permission = deferred<MediaStream>()
    vi.mocked(navigator.mediaDevices.getUserMedia).mockReturnValue(permission.promise)
    const test = host()
    await test.wrapper.trigger('mousedown')
    test.wrapper.unmount()
    permission.resolve(stream); await flush()
    expect(recorderStart).not.toHaveBeenCalled()
    expect(trackStop).toHaveBeenCalled()
  })
  it('does not apply a late transcription after real Vue unmount', async () => {
    const transcription = deferred<Response>()
    vi.mocked(apiFetch).mockReturnValue(transcription.promise)
    const test = host()
    await test.wrapper.trigger('mousedown'); await flush()
    vi.setSystemTime(1600)
    await test.wrapper.trigger('mouseup'); await flush()
    test.wrapper.unmount()
    test.messageInput.value = 'new draft'
    transcription.resolve({ ok: true, text: async () => JSON.stringify({ success: true, data: { text: 'old speech' } }) } as Response)
    await flush()
    expect(test.messageInput.value).toBe('new draft')
  })
  it('invalidates pending permission even after switching away and back', async () => {
    const permission = deferred<MediaStream>()
    vi.mocked(navigator.mediaDevices.getUserMedia).mockReturnValue(permission.promise)
    const test = host()
    await test.wrapper.trigger('mousedown')
    test.sessionId.value = 'other-session'
    test.sessionId.value = 'original-session'
    permission.resolve(stream); await flush()
    expect(recorderStart).not.toHaveBeenCalled()
    expect(trackStop).toHaveBeenCalled()
  })
  it('aborts transcription on a session change and ignores an abort-insensitive late response', async () => {
    const transcription = deferred<Response>()
    vi.mocked(apiFetch).mockReturnValue(transcription.promise)
    const test = host()
    await test.wrapper.trigger('mousedown'); await flush()
    vi.setSystemTime(1600)
    await test.wrapper.trigger('mouseup'); await flush()
    const signal = vi.mocked(apiFetch).mock.calls[0][1]?.signal
    test.sessionId.value = 'other-session'
    test.messageInput.value = 'new draft'
    expect(signal?.aborted).toBe(true)
    transcription.resolve({ ok: true, text: async () => JSON.stringify({ success: true, data: { text: 'old speech' } }) } as Response)
    await flush()
    expect(test.messageInput.value).toBe('new draft')
    expect(test.api.voiceButtonDisabled.value).toBe(false)
  })
  it('ignores duplicate presses while permission is pending', async () => {
    const permission = deferred<MediaStream>()
    vi.mocked(navigator.mediaDevices.getUserMedia).mockReturnValue(permission.promise)
    const test = host()
    await test.wrapper.trigger('mousedown')
    await test.wrapper.trigger('mousedown')
    expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledTimes(1)
    await test.wrapper.trigger('mouseup')
    permission.resolve(stream); await flush()
  })
})
