import { describe, expect, it, vi, beforeEach } from 'vitest'
import { useSpeechRecognition } from './useSpeechRecognition'
import type { ASRResult } from './asr/types'

const funasrStart = vi.fn()
const webspeechStart = vi.fn()

vi.mock('./asr/FunASRBackend', () => ({
  FunASRBackend: class {
    id = 'funasr'
    label = 'FunASR'
    isAvailable() { return true }
    isLoading() { return false }
    start = funasrStart
    async stop() { return '' }
    abort() {}
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
  },
}))

vi.mock('./asr/WhisperWebBackend', () => ({
  WhisperWebBackend: class {
    id = 'whisper-web'
    label = 'Whisper'
    isAvailable() { return true }
    isLoading() { return false }
    start = vi.fn()
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
})
