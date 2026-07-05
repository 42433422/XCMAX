import { describe, it, expect, vi } from 'vitest'
import { ref } from 'vue'
import { apiFetch } from '@/utils/apiBase'
import { useChatVoiceInput } from './useChatVoiceInput'

vi.mock('@/utils/apiBase', () => ({
  apiFetch: vi.fn(),
}))

describe('useChatVoiceInput', () => {
  it('exposes idle voice button state', () => {
    const api = useChatVoiceInput({
      messageInput: ref(''),
      isLoading: ref(false),
    })
    expect(api.voiceButtonText.value).toContain('按住说话')
    expect(api.voiceButtonDisabled.value).toBe(false)
    expect(api.voiceButtonIcon.value).toBe('fa-microphone')
  })

  it('disables button while loading', () => {
    const api = useChatVoiceInput({
      messageInput: ref(''),
      isLoading: ref(true),
    })
    expect(api.voiceButtonDisabled.value).toBe(true)
  })

  it('pickSupportedMimeType returns empty without MediaRecorder', () => {
    const orig = (window as unknown as { MediaRecorder?: typeof MediaRecorder }).MediaRecorder
    // @ts-expect-error test
    delete window.MediaRecorder
    const api = useChatVoiceInput({
      messageInput: ref(''),
      isLoading: ref(false),
    })
    expect(api.voiceButtonIcon.value).toBe('fa-microphone')
    Object.defineProperty(window, 'MediaRecorder', { configurable: true, value: orig })
  })

  it('startVoiceRecording returns early when disabled', async () => {
    const api = useChatVoiceInput({
      messageInput: ref(''),
      isLoading: ref(true),
    })
    await api.startVoiceRecording()
    expect(api.voiceButtonDisabled.value).toBe(true)
    expect(api.voiceButtonText.value).toContain('按住说话')
  })

  it('submits recorded audio through apiFetch so CSRF headers are attached', async () => {
    vi.useFakeTimers()
    try {
      const messageInput = ref('')
      const stream = {
        getTracks: () => [{ stop: vi.fn() }],
      } as unknown as MediaStream

      class MockMediaRecorder {
        static isTypeSupported = vi.fn(() => true)
        state: RecordingState = 'inactive'
        listeners: Record<string, (event?: unknown) => void> = {}

        addEventListener(type: string, cb: (event?: unknown) => void) {
          this.listeners[type] = cb
        }

        start() {
          this.state = 'recording'
        }

        stop() {
          this.state = 'inactive'
          this.listeners.dataavailable?.({
            data: new Blob(['voice'], { type: 'audio/webm' }),
          })
          this.listeners.stop?.()
        }
      }

      Object.defineProperty(navigator, 'mediaDevices', {
        configurable: true,
        value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      })
      Object.defineProperty(window, 'MediaRecorder', {
        configurable: true,
        value: MockMediaRecorder,
      })
      vi.mocked(apiFetch).mockResolvedValue({
        ok: true,
        text: async () => JSON.stringify({ success: true, data: { text: '你好' } }),
      } as Response)
      document.body.innerHTML = '<textarea id="messageInput"></textarea>'

      const api = useChatVoiceInput({ messageInput, isLoading: ref(false) })
      vi.setSystemTime(1_000)
      await api.startVoiceRecording()
      expect(api.voiceButtonIcon.value).toBe('fa-stop-circle')

      vi.setSystemTime(1_500)
      api.stopVoiceRecording(false)
      await Promise.resolve()
      await Promise.resolve()

      expect(apiFetch).toHaveBeenCalledWith('/api/voice/transcribe', {
        method: 'POST',
        body: expect.any(FormData),
      })
      expect(messageInput.value).toBe('你好')
    } finally {
      vi.useRealTimers()
    }
  })
})
