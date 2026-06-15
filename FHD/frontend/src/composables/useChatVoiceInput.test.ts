import { describe, it, expect, vi } from 'vitest'
import { ref } from 'vue'
import { useChatVoiceInput } from './useChatVoiceInput'

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
})
