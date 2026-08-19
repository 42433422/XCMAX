import { describe, expect, it, vi, beforeEach } from 'vitest'
import { useSpeechRecognition } from './useSpeechRecognition'
import type { ASRResult } from './asr/types'

const funasrStart = vi.fn()
const webspeechStart = vi.fn()
const whisperStart = vi.fn()
const signalEndOfSpeech = vi.fn()

vi.mock('./asr/FunASRBackend', () => ({
  FunASRBackend: class {
    id = 'funasr'
    label = 'FunASR'
    isAvailable() { return true }
    isLoading() { return false }
    start = funasrStart
    async stop() { return '' }
    abort() {}
    signalEndOfSpeech = signalEndOfSpeech
  },
}))

vi.mock('./asr/WebSpeechBackend', () => ({
  WebSpeechBackend: class {
    id = 'webspeech'
    label = 'WebSpeech'
    isAvailable() { return true }
    isLoading() { return false }
    start = webspeechStart
    async flushUtterance() { return '浏览器识别' }
    async stop() { return '浏览器识别' }
    abort() {}
    signalEndOfSpeech = signalEndOfSpeech
  },
}))

vi.mock('./asr/WhisperWebBackend', () => ({
  WhisperWebBackend: class {
    id = 'whisper-web'
    label = 'Whisper'
    isAvailable() { return true }
    isLoading() { return false }
    start = whisperStart
    async stop() { return '' }
    abort() {}
  },
}))

vi.mock('./asr/hfHub', () => ({
  probeWhisperHubReady: vi.fn(async () => true),
}))

describe('useSpeechRecognition', () => {
  beforeEach(() => {
    funasrStart.mockReset()
    webspeechStart.mockReset()
    whisperStart.mockReset()
    signalEndOfSpeech.mockReset()
    funasrStart.mockImplementation(async (
      _onResult: (r: ASRResult) => void,
      onError: (msg: string) => void,
    ) => {
      onError('FunASR 服务未启动')
    })
    webspeechStart.mockImplementation(async (
      _onResult: (r: ASRResult) => void,
      _onError: (msg: string) => void,
      _lvl?: (n: number) => void,
      onReady?: () => void,
    ) => {
      onReady?.()
    })
  })

  it('continuous mode does not fall back to webspeech when funasr fails', async () => {
    vi.useFakeTimers()
    const { startListening, activeBackendId, error } = useSpeechRecognition()

    const task = startListening(() => {}, () => {}, undefined, { continuous: true })
    await vi.runAllTimersAsync()
    await task

    expect(webspeechStart).not.toHaveBeenCalled()
    expect(activeBackendId.value).toBe('')
    expect(error.value).toContain('服务端语音识别不可用')
    vi.useRealTimers()
  })

  it('keeps funasr active after connect in continuous mode', async () => {
    vi.useFakeTimers()
    funasrStart.mockImplementation(async (
      _onResult: (r: ASRResult) => void,
      _onError: (msg: string) => void,
      _lvl?: (n: number) => void,
      onReady?: () => void,
    ) => {
      onReady?.()
    })

    const { startListening, activeBackendId, sessionReady } = useSpeechRecognition()
    await startListening(() => {}, () => {}, undefined, { continuous: true })
    expect(activeBackendId.value).toBe('funasr')
    expect(sessionReady.value).toBe(true)

    await vi.advanceTimersByTimeAsync(25000)
    expect(activeBackendId.value).toBe('funasr')
    vi.useRealTimers()
  })

  it('falls back to WebSpeech, forwards result/audio callbacks and flushes/stops', async () => {
    funasrStart.mockImplementation(async (
      _onResult: (r: ASRResult) => void,
      onError: (msg: string) => void,
    ) => onError('FunASR startup failed'))
    webspeechStart.mockImplementation(async (
      onResult: (r: ASRResult) => void,
      _onError: (msg: string) => void,
      onLevel?: (n: number) => void,
      onReady?: () => void,
    ) => {
      onReady?.()
      onLevel?.(0.42)
      onResult({ text: '浏览器部分结果', isFinal: false })
    })
    const onResult = vi.fn()
    const onError = vi.fn()
    const onLevel = vi.fn()
    const speech = useSpeechRecognition()

    await speech.startListening(onResult, onError, onLevel)
    expect(speech.activeBackendId.value).toBe('webspeech')
    expect(speech.interimText.value).toBe('浏览器部分结果')
    expect(speech.audioLevel.value).toBe(0.42)
    expect(onResult).toHaveBeenCalled()
    expect(onLevel).toHaveBeenCalledWith(0.42)
    speech.signalEndOfSpeech()
    expect(signalEndOfSpeech).toHaveBeenCalled()
    expect(await speech.flushListening()).toBe('浏览器识别')
    expect(await speech.stopListening()).toBe('浏览器识别')
    expect(speech.activeBackendId.value).toBe('')
  })

  it('uses FunASR results, accepts a prefetched stream and clears state on abort', async () => {
    funasrStart.mockImplementation(async (
      onResult: (r: ASRResult) => void,
      _onError: (msg: string) => void,
      onLevel?: (n: number) => void,
      onReady?: () => void,
    ) => {
      onReady?.()
      onLevel?.(0.7)
      onResult({ text: '服务端识别结果', isFinal: true })
    })
    const speech = useSpeechRecognition()
    await speech.startListening(vi.fn(), vi.fn(), vi.fn(), {
      mediaStream: Promise.reject(new Error('prefetch unavailable')),
    })
    expect(speech.activeBackendId.value).toBe('funasr')
    expect(speech.interimText.value).toBe('服务端识别结果')
    expect(await speech.flushListening()).toBe('服务端识别结果')
    speech.abort({ keepMic: true })
    expect(speech.interimText.value).toBe('')
    expect(await speech.stopListening()).toBe('服务端识别结果')
  })

  it('exhausts every non-continuous backend and reports startup failure', async () => {
    funasrStart.mockImplementation(async (
      _onResult: (r: ASRResult) => void,
      onError: (msg: string) => void,
    ) => onError('funasr failed'))
    webspeechStart.mockImplementation(async (
      _onResult: (r: ASRResult) => void,
      onError: (msg: string) => void,
    ) => onError('webspeech failed'))
    whisperStart.mockImplementation(async (
      _onResult: (r: ASRResult) => void,
      onError: (msg: string) => void,
    ) => onError('whisper failed'))
    const onError = vi.fn()
    const speech = useSpeechRecognition()
    await speech.startListening(vi.fn(), onError)
    expect(speech.error.value).toContain('whisper failed')
    expect(onError).toHaveBeenCalledWith('whisper failed')
  })
})
