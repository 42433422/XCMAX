import { mount } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  VOICE_ENDPOINT,
  VOICE_PHONE_ENDPOINT,
  refreshVoiceEndpoint,
  useVoiceContinuousChat,
  voiceEndpointForDevice,
} from './useVoiceContinuousChat'

type ResultCallback = (result: UnsafeTestValue) => void

function mountVoiceHarness(
  options: {
    autoSend?: boolean
    backend?: string
    phone?: boolean
    busy?: boolean
    tts?: boolean
    flushText?: string
  } = {},
) {
  let onResult: ResultCallback = () => undefined
  let onError: (message: string) => unknown = () => undefined
  let onLevel: (level: number) => void = () => undefined
  let targetActive = false
  const asr = {
    sessionReady: ref(true),
    error: ref(''),
    startListening: vi.fn(async (result, error, level) => {
      onResult = result
      onError = error
      onLevel = level
    }),
    stopListening: vi.fn(async () => options.flushText || ''),
    flushListening: vi.fn(async () => options.flushText || ''),
    abort: vi.fn(),
  }
  const ready = vi.fn(async () => undefined)
  const speculativeStart = vi.fn()
  const speculativeCancel = vi.fn()
  const s2sStart = vi.fn()
  const s2sFinalize = vi.fn()
  const bargeIn = vi.fn()
  const signalEnd = vi.fn()
  let voice: ReturnType<typeof useVoiceContinuousChat>
  const Harness = defineComponent({
    setup() {
      voice = useVoiceContinuousChat({
        asr: asr as never,
        isAsrReady: () => asr.sessionReady.value,
        autoSend: ref(options.autoSend ?? true),
        voiceState: ref('idle'),
        voiceChatPhase: ref('idle'),
        isVoiceTargetActive: () => targetActive,
        setVoiceTarget: () => {
          targetActive = true
        },
        clearVoiceTarget: () => {
          targetActive = false
        },
        beforeStartListening: vi.fn(),
        onUtteranceReady: ready,
        onSpeculativeStart: speculativeStart,
        onSpeculativeCancel: speculativeCancel,
        onBargeIn: bargeIn,
        isTtsPlaying: () => Boolean(options.tts),
        onAsrDuringTts: vi.fn(() => true),
        canSpeculate: () => true,
        isChatBusy: () => Boolean(options.busy),
        getAsrBackendId: () => options.backend || 'web-speech',
        signalAsrEndOfSpeech: signalEnd,
        onS2SPartialStable: s2sStart,
        onS2SUtteranceFinalize: s2sFinalize,
        voiceUsePhonePipeline: () => Boolean(options.phone),
        usePhoneLatency: () => Boolean(options.phone),
      })
      return () => h('div')
    },
  })
  const wrapper = mount(Harness)
  return {
    wrapper,
    voice: voice!,
    asr,
    ready,
    speculativeStart,
    speculativeCancel,
    s2sStart,
    s2sFinalize,
    bargeIn,
    signalEnd,
    emitResult: (result: UnsafeTestValue) => onResult(result),
    emitError: (message: string) => onError(message),
    emitLevel: (level: number) => onLevel(level),
    targetActive: () => targetActive,
  }
}

describe('VOICE_ENDPOINT', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    localStorage.clear()
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
  })

  it('uses conservative silence and partial stable thresholds', () => {
    expect(VOICE_ENDPOINT.silenceMs).toBe(700)
    expect(VOICE_ENDPOINT.partialStableMs).toBe(1100)
    expect(VOICE_ENDPOINT.partialMinChars).toBe(6)
    expect(VOICE_ENDPOINT.serverFinalDebounceMs).toBe(280)
  })

  it('phone endpoint is faster than default for call-like latency', () => {
    expect(VOICE_PHONE_ENDPOINT.silenceMs).toBeLessThan(VOICE_ENDPOINT.silenceMs)
    expect(VOICE_PHONE_ENDPOINT.partialStableS2sMs).toBeLessThan(VOICE_ENDPOINT.partialStableS2sMs)
  })

  it('selects desktop and mobile endpoint profiles', () => {
    vi.stubGlobal('navigator', { userAgent: 'Desktop Chrome' })
    expect(voiceEndpointForDevice()).toBe(VOICE_ENDPOINT)
    refreshVoiceEndpoint()
    vi.unstubAllGlobals()
  })

  it('starts capture, merges partials and submits a final utterance', async () => {
    localStorage.setItem('modstore_token', 'token')
    const h = mountVoiceHarness({ flushText: '你好，这是完整问题' })
    await h.voice.startListening({ fresh: true })
    expect(h.voice.voiceListening.value).toBe(true)
    expect(h.targetActive()).toBe(true)

    h.emitResult({ text: '你好，这是', isFinal: false })
    h.emitLevel(0.03)
    h.emitLevel(0)
    expect(h.voice.voiceTranscript.value).toContain('你好')
    await vi.advanceTimersByTimeAsync(1200)
    await h.voice.finishUtterance()

    expect(h.ready).toHaveBeenCalledWith('你好，这是完整问题', { speculativePartial: null })
    expect(h.voice.voiceTranscript.value).toBe('')
    h.voice.noteSubmitted('你好，这是完整问题')
    expect(h.voice.hasFreshCapture('你好，这是完整问题')).toBe(false)
    await h.voice.stopListening()
    expect(h.targetActive()).toBe(false)
    h.wrapper.unmount()
  })

  it('handles FunASR phone partial, offline final and end-of-speech flow', async () => {
    localStorage.setItem('modstore_token', 'token')
    const h = mountVoiceHarness({ backend: 'funasr', phone: true, flushText: '最终答案' })
    await h.voice.startListening({ fresh: true })
    h.emitResult({ text: '这是电话问题', isFinal: false, segmentMode: 'online' })
    await vi.advanceTimersByTimeAsync(400)
    expect(h.s2sStart).toHaveBeenCalled()
    h.emitLevel(0.03)
    h.emitLevel(0)
    expect(h.signalEnd).toHaveBeenCalled()
    h.emitResult({ text: '这是电话问题最终版', isFinal: true, segmentMode: 'offline' })
    expect(h.s2sFinalize).toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(600)
    expect(h.ready).toHaveBeenCalled()
    h.voice.interruptCapture()
    expect(h.asr.abort).toHaveBeenCalled()
    h.wrapper.unmount()
  })

  it('covers login, pause, retry and terminal ASR error branches', async () => {
    const h = mountVoiceHarness({ autoSend: true })
    await expect(h.voice.startListening()).resolves.toEqual({ error: '请先登录后再使用语音识别。' })

    localStorage.setItem('modstore_token', 'token')
    await h.voice.startListening({ fresh: true })
    h.voice.voiceDraft.value = '保留的内容'
    h.emitError('临时网络错误')
    await vi.runAllTimersAsync()
    expect(h.ready).toHaveBeenCalled()

    h.voice.voiceDraft.value = ''
    const retry = h.voice.onAsrError('Whisper 模型加载失败')
    expect(retry).toMatchObject({ retry: true, fresh: true })
    const terminal = h.voice.onAsrError('浏览器不支持语音识别')
    expect(terminal).toMatchObject({ retry: false })
    h.voice.ensureListening()
    h.voice.resetListenSession()
    h.voice.resetCaptureUi()
    h.wrapper.unmount()
  })

  it('keeps manual-draft mode from auto-submitting and reports errors', async () => {
    localStorage.setItem('modstore_token', 'token')
    const h = mountVoiceHarness({ autoSend: false })
    await h.voice.startListening({ fresh: true })
    h.emitResult({ text: '只转写不发送', isFinal: true })
    h.emitLevel(0.04)
    h.emitLevel(0)
    expect(h.ready).not.toHaveBeenCalled()
    const result = h.voice.onAsrError('网络中断')
    expect(result).toMatchObject({ retry: false })
    await h.voice.stopAsr()
    h.wrapper.unmount()
  })
})
