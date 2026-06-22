import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import type { ASRResult } from './composables/asr/types'

type AsrHandlers = {
  result?: (r: ASRResult) => void
  error?: (msg: string) => void
  level?: (level: number) => void
}

function createContinuousHarness(options: {
  autoSend?: boolean
  busy?: boolean
  ttsPlaying?: boolean
  backend?: string
  flushText?: string
  stopText?: string
  ready?: boolean
  phone?: boolean
} = {}) {
  const handlers: AsrHandlers = {}
  const active = { value: false }
  const autoSend = ref(options.autoSend ?? true)
  const voiceState = ref('idle')
  const voiceChatPhase = ref('idle')
  const onUtteranceReady = vi.fn(async () => undefined)
  const onSpeculativeStart = vi.fn()
  const onSpeculativeCancel = vi.fn()
  const onBargeIn = vi.fn()
  const onAsrDuringTts = vi.fn(() => true)
  const onS2SPartialStable = vi.fn()
  const onS2SUtteranceFinalize = vi.fn()
  const signalAsrEndOfSpeech = vi.fn()
  const asr = {
    error: ref(''),
    sessionReady: ref(options.ready ?? true),
    startListening: vi.fn(async (
      onResult: (r: ASRResult) => void,
      onError: (msg: string) => void,
      onAudioLevel?: (level: number) => void,
    ) => {
      handlers.result = onResult
      handlers.error = onError
      handlers.level = onAudioLevel
    }),
    flushListening: vi.fn(async () => options.flushText ?? '这是一个足够长的问题'),
    stopListening: vi.fn(async () => options.stopText ?? '停止后的文字'),
    abort: vi.fn(),
  }

  return {
    handlers,
    active,
    deps: {
      asr,
      isAsrReady: () => asr.sessionReady.value,
      autoSend,
      voiceState,
      voiceChatPhase,
      isVoiceTargetActive: () => active.value,
      setVoiceTarget: () => { active.value = true },
      clearVoiceTarget: () => { active.value = false },
      beforeStartListening: vi.fn(),
      onUtteranceReady,
      onSpeculativeStart,
      onSpeculativeCancel,
      onBargeIn,
      isTtsPlaying: () => options.ttsPlaying ?? false,
      onAsrDuringTts,
      canSpeculate: () => true,
      isChatBusy: () => options.busy ?? false,
      getAsrBackendId: () => options.backend ?? 'funasr',
      signalAsrEndOfSpeech,
      onS2SPartialStable,
      onS2SUtteranceFinalize,
      voiceUsePhonePipeline: () => options.phone ?? true,
      usePhoneLatency: () => options.phone ?? true,
    },
  }
}

describe('useVoiceContinuousChat extra coverage', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    localStorage.setItem('modstore_token', 'coverage-token')
  })

  afterEach(() => {
    vi.useRealTimers()
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('handles phone partial stable, FunASR finalization, and utterance submission', async () => {
    const { useVoiceContinuousChat } = await import('./composables/useVoiceContinuousChat')
    const harness = createContinuousHarness({ phone: true })
    const chat = useVoiceContinuousChat(harness.deps)

    await expect(chat.startListening()).resolves.toEqual({ error: null })
    expect(harness.deps.beforeStartListening).toHaveBeenCalled()
    expect(chat.voiceListening.value).toBe(true)

    harness.handlers.result?.({ text: '这是一个足够长的问题', isFinal: false, segmentMode: 'online' })
    await vi.advanceTimersByTimeAsync(420)
    expect(harness.deps.onS2SPartialStable).toHaveBeenCalledWith('这是一个足够长的问题', expect.any(String))

    harness.handlers.level?.(0.02)
    harness.handlers.level?.(0.001)
    expect(harness.deps.signalAsrEndOfSpeech).toHaveBeenCalled()

    harness.handlers.result?.({ text: '这是一个足够长的问题', isFinal: true, segmentMode: 'offline' })
    expect(harness.deps.onS2SUtteranceFinalize).toHaveBeenCalledWith('这是一个足够长的问题', expect.any(String))

    await vi.advanceTimersByTimeAsync(260)
    await Promise.resolve()

    expect(harness.deps.asr.flushListening).toHaveBeenCalled()
    expect(harness.deps.onUtteranceReady).toHaveBeenCalledWith('这是一个足够长的问题', expect.any(Object))

    await expect(chat.stopListening()).resolves.toBe('停止后的文字')
    expect(chat.voiceListening.value).toBe(false)
  })

  it('handles barge-in, speculative cancellation, and manual interruption', async () => {
    const { useVoiceContinuousChat } = await import('./composables/useVoiceContinuousChat')
    const harness = createContinuousHarness({ busy: true, ttsPlaying: true })
    const chat = useVoiceContinuousChat(harness.deps)

    await chat.startListening()
    harness.handlers.level?.(0.08)
    expect(harness.deps.onAsrDuringTts).toHaveBeenCalledWith(0.08)

    chat.voiceTranscript.value = '正在说话时插入'
    await chat.finishUtterance()
    expect(harness.deps.onUtteranceReady).toHaveBeenCalled()

    chat.interruptCapture()
    expect(harness.deps.asr.abort).toHaveBeenCalled()
    expect(chat.voiceListening.value).toBe(false)
  })

  it('covers login, ASR error, ensure-listening, and no-autosend paths', async () => {
    const { useVoiceContinuousChat } = await import('./composables/useVoiceContinuousChat')
    localStorage.removeItem('modstore_token')
    const noTokenHarness = createContinuousHarness()
    const noTokenChat = useVoiceContinuousChat(noTokenHarness.deps)
    await expect(noTokenChat.startListening()).resolves.toEqual({ error: '请先登录后再使用语音识别。' })

    localStorage.setItem('modstore_token', 'coverage-token')
    const harness = createContinuousHarness({ autoSend: false, ready: false })
    const chat = useVoiceContinuousChat(harness.deps)
    await expect(chat.startListening()).resolves.toEqual({ error: '语音识别启动失败，请点麦克风重试。' })

    harness.deps.asr.sessionReady.value = true
    await chat.startListening()
    chat.voiceDraft.value = '手动输入内容'
    expect(chat.onAsrError('权限不足')).toEqual({ msg: '权限不足', retry: false })

    chat.ensureListening()
    chat.resetCaptureUi()
    chat.noteSubmitted('已经提交的内容')
    expect(chat.hasFreshCapture('已经提交的内容')).toBe(false)
  })

  it('reconnects stalled FunASR sessions while keeping voice UI state', async () => {
    const { useVoiceContinuousChat } = await import('./composables/useVoiceContinuousChat')
    const harness = createContinuousHarness({ backend: 'funasr' })
    const chat = useVoiceContinuousChat(harness.deps)

    await chat.startListening()
    expect(harness.deps.asr.startListening).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(12_050)

    expect(harness.deps.asr.abort).toHaveBeenCalled()
  })

  it('starts and cancels speculative partial answers for stable ASR text', async () => {
    const { useVoiceContinuousChat } = await import('./composables/useVoiceContinuousChat')
    const harness = createContinuousHarness({ autoSend: false, phone: false, backend: 'webspeech' })
    const chat = useVoiceContinuousChat(harness.deps)

    await chat.startListening()
    harness.handlers.result?.({ text: '这是一个足够长的问题', isFinal: false })
    await vi.advanceTimersByTimeAsync(1_120)

    expect(chat.partialStable.value).toBe(true)
    expect(chat.isSpeculating.value).toBe(true)
    expect(harness.deps.onSpeculativeStart).toHaveBeenCalledWith('这是一个足够长的问题')

    harness.handlers.result?.({ text: '这是另一个足够长的问题', isFinal: false })
    expect(harness.deps.onSpeculativeCancel).toHaveBeenCalled()
  })

  it('covers ASR error retry decisions with partial text and Whisper fallback', async () => {
    const { useVoiceContinuousChat } = await import('./composables/useVoiceContinuousChat')
    const harness = createContinuousHarness({ autoSend: true })
    const chat = useVoiceContinuousChat(harness.deps)

    await chat.startListening()
    harness.handlers.result?.({ text: '已经识别的内容', isFinal: false, segmentMode: 'online' })
    expect(chat.onAsrError('网络断开')).toEqual(undefined)
    await Promise.resolve()
    expect(chat.voiceTranscript.value).toBe('已经识别的内容')

    const manualHarness = createContinuousHarness({ autoSend: false })
    const manual = useVoiceContinuousChat(manualHarness.deps)
    await manual.startListening()
    manual.voiceDraft.value = '手动保留'
    expect(manual.onAsrError('网络断开')).toEqual({ msg: '网络断开', retry: false })
    expect(manual.voiceListening.value).toBe(false)

    const whisperHarness = createContinuousHarness({ autoSend: true })
    const whisper = useVoiceContinuousChat(whisperHarness.deps)
    await whisper.startListening()
    expect(whisper.onAsrError('Whisper 模型加载失败')).toEqual({ msg: '', retry: true, delayMs: 400, fresh: true })
    expect(whisperHarness.deps.asr.abort).toHaveBeenCalledWith({ keepMic: true })

    expect(whisper.onAsrError('临时网络错误')).toEqual({ msg: '临时网络错误', retry: true, delayMs: 400, fresh: true })
  })

  it('covers listener reuse, barge-in, inactive stop, and matching speculative submit', async () => {
    const { useVoiceContinuousChat } = await import('./composables/useVoiceContinuousChat')
    const harness = createContinuousHarness({ autoSend: false, phone: false, backend: 'webspeech' })
    const chat = useVoiceContinuousChat(harness.deps)

    await expect(chat.stopAsr()).resolves.toBe('')
    await chat.startListening()
    const starts = harness.deps.asr.startListening.mock.calls.length
    await chat.startListening({ fresh: false })
    expect(harness.deps.asr.startListening).toHaveBeenCalledTimes(starts)

    harness.handlers.result?.({ text: '这是一个足够长的问题', isFinal: false })
    await vi.advanceTimersByTimeAsync(1_120)
    expect(chat.isSpeculating.value).toBe(true)

    harness.deps.autoSend.value = true
    await chat.finishUtterance()
    expect(harness.deps.onUtteranceReady).toHaveBeenCalledWith(
      '这是一个足够长的问题',
      { speculativePartial: '这是一个足够长的问题' },
    )

    const busyHarness = createContinuousHarness({ busy: true, ttsPlaying: false, backend: 'webspeech' })
    const busyChat = useVoiceContinuousChat(busyHarness.deps)
    await busyChat.startListening()
    busyHarness.handlers.level?.(0.08)
    busyHarness.handlers.result?.({ text: '我正在插话提问', isFinal: false })
    expect(busyHarness.deps.onBargeIn).toHaveBeenCalled()
  })

  it('covers mic watchdog, paused ensure-listening, and stale token guards', async () => {
    const { useVoiceContinuousChat } = await import('./composables/useVoiceContinuousChat')
    const harness = createContinuousHarness({ ready: true, backend: 'funasr' })
    const chat = useVoiceContinuousChat(harness.deps)

    await chat.startListening()
    harness.deps.asr.sessionReady.value = false
    await vi.advanceTimersByTimeAsync(3_550)
    expect(harness.deps.asr.abort).toHaveBeenCalledWith({ keepMic: true })
    expect(chat.voiceListening.value).toBe(false)

    const pausedHarness = createContinuousHarness()
    const paused = useVoiceContinuousChat(pausedHarness.deps)
    paused.micPausedByUser.value = true
    paused.ensureListening()
    expect(pausedHarness.deps.asr.startListening).not.toHaveBeenCalled()

    localStorage.removeItem('modstore_token')
    paused.micPausedByUser.value = false
    paused.ensureListening()
    expect(pausedHarness.deps.asr.startListening).not.toHaveBeenCalled()
  })

  it('covers pending ensure-listening, TTS final guard, empty finish, and inactive stop branches', async () => {
    const { useVoiceContinuousChat } = await import('./composables/useVoiceContinuousChat')

    const ttsHarness = createContinuousHarness({ ttsPlaying: true, phone: false, backend: 'webspeech' })
    const ttsChat = useVoiceContinuousChat(ttsHarness.deps)
    await ttsChat.startListening()
    ttsHarness.handlers.result?.({ text: '播放中收到最终识别文本', isFinal: true })
    await vi.advanceTimersByTimeAsync(1_000)
    expect(ttsHarness.deps.onUtteranceReady).toHaveBeenCalled()

    const pendingHarness = createContinuousHarness({ phone: false, backend: 'webspeech' })
    const pending = useVoiceContinuousChat(pendingHarness.deps)
    await pending.startListening()
    pending.voiceTranscript.value = '这是一段等待自动提交的内容'
    pending.ensureListening()
    await vi.advanceTimersByTimeAsync(1_500)
    await pending.finishUtterance()
    await Promise.resolve()
    expect(pendingHarness.deps.onUtteranceReady).toHaveBeenCalledWith(
      '这是一个足够长的问题',
      expect.any(Object),
    )

    const emptyHarness = createContinuousHarness({ flushText: '', stopText: '' })
    const empty = useVoiceContinuousChat(emptyHarness.deps)
    await empty.startListening()
    await empty.finishUtterance()
    expect(emptyHarness.deps.onUtteranceReady).not.toHaveBeenCalled()
    emptyHarness.active.value = false
    await expect(empty.stopListening()).resolves.toBe('')
  })

  it('covers mobile endpoint variants, stall guards, debounce guards, and speculation skips', async () => {
    Object.defineProperty(navigator, 'userAgent', { value: 'iPhone Safari', configurable: true })
    const voice = await import('./composables/useVoiceContinuousChat')
    expect(voice.voiceEndpointForDevice().speechLevel).toBe(0.028)
    Object.defineProperty(navigator, 'userAgent', { value: 'Android Chrome', configurable: true })
    expect(voice.voiceEndpointForDevice().speechLevel).toBe(0.024)
    Object.defineProperty(navigator, 'userAgent', { value: 'Desktop Chrome', configurable: true })
    voice.refreshVoiceEndpoint()

    const webHarness = createContinuousHarness({ backend: 'webspeech' })
    const webChat = voice.useVoiceContinuousChat(webHarness.deps)
    await webChat.startListening()
    webHarness.handlers.level?.(0.02)
    await vi.advanceTimersByTimeAsync(12_050)
    expect(webHarness.deps.asr.abort).not.toHaveBeenCalled()

    const transcriptHarness = createContinuousHarness({ backend: 'funasr' })
    const transcriptChat = voice.useVoiceContinuousChat(transcriptHarness.deps)
    await transcriptChat.startListening()
    transcriptChat.voiceTranscript.value = '已经有识别文本'
    await vi.advanceTimersByTimeAsync(12_050)
    expect(transcriptHarness.deps.asr.abort).not.toHaveBeenCalled()

    const autoOffHarness = createContinuousHarness({ backend: 'funasr' })
    const autoOffChat = voice.useVoiceContinuousChat(autoOffHarness.deps)
    await autoOffChat.startListening()
    autoOffHarness.handlers.result?.({ text: '服务端最终文本', isFinal: true, segmentMode: 'offline' })
    autoOffHarness.deps.autoSend.value = false
    await vi.advanceTimersByTimeAsync(300)
    expect(autoOffHarness.deps.onUtteranceReady).not.toHaveBeenCalled()

    const speakingHarness = createContinuousHarness({ backend: 'funasr' })
    const speakingChat = voice.useVoiceContinuousChat(speakingHarness.deps)
    await speakingChat.startListening()
    speakingHarness.handlers.level?.(0.08)
    speakingHarness.handlers.result?.({ text: '服务端最终文本', isFinal: true, segmentMode: 'offline' })
    await vi.advanceTimersByTimeAsync(300)
    expect(speakingHarness.deps.onUtteranceReady).not.toHaveBeenCalled()

    const noSpecHarness = createContinuousHarness({ autoSend: false, phone: false, backend: 'webspeech' })
    noSpecHarness.deps.canSpeculate = vi.fn(() => false)
    const noSpecChat = voice.useVoiceContinuousChat(noSpecHarness.deps)
    await noSpecChat.startListening()
    noSpecHarness.handlers.result?.({ text: '这是一个足够长的问题', isFinal: false })
    noSpecHarness.handlers.result?.({ text: '这是一个足够长的问题', isFinal: false })
    await vi.advanceTimersByTimeAsync(1_200)
    expect(noSpecHarness.deps.onSpeculativeStart).not.toHaveBeenCalled()
  })
})
