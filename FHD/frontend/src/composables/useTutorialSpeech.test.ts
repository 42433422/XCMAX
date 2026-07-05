import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest'

const mockApiFetch = vi.hoisted(() => vi.fn())
const mockReadCsrfTokenFromCookie = vi.hoisted(() => vi.fn(() => 'csrf-token'))

vi.mock('@/utils/apiBase', () => ({
  apiFetch: mockApiFetch,
}))

vi.mock('@/utils/csrfCookie', () => ({
  readCsrfTokenFromCookie: mockReadCsrfTokenFromCookie,
}))

import { createTutorialSpeech } from './useTutorialSpeech'

function mockOnlineTtsFetch() {
  mockApiFetch.mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({
      success: true,
      data: { audioBase64: 'data:audio/mp3;base64,abc' },
    }),
  })
}

function mockAudioWithDuration(durationSec: number) {
  vi.stubGlobal(
    'Audio',
    class MockAudio {
      uri = ''
      onended: (() => void) | null = null
      addEventListener(event: string, cb: () => void) {
        if (event === 'loadedmetadata') {
          queueMicrotask(() => {
            Object.defineProperty(this, 'duration', { value: durationSec })
            cb()
          })
        }
        if (event === 'ended') this.onended = cb
        if (event === 'error') this.onended = cb
      }
      set src(v: string) {
        this.uri = v
      }
      play = vi.fn().mockImplementation(async () => {
        queueMicrotask(() => this.onended?.())
      })
    },
  )
}

describe('createTutorialSpeech', () => {
  beforeEach(() => {
    mockApiFetch.mockReset()
    mockReadCsrfTokenFromCookie.mockReset()
    mockReadCsrfTokenFromCookie.mockReturnValue('csrf-token')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('uses online audio only without browser speechSynthesis', async () => {
    mockOnlineTtsFetch()
    mockAudioWithDuration(2)
    const speech = createTutorialSpeech()
    await speech.speak('教程步骤说明')
    expect(mockApiFetch).toHaveBeenCalledWith('/api/tts', expect.objectContaining({ method: 'POST' }))
    expect(globalThis.Audio).toBeTruthy()
  })

  it('stepHoldMs respects cached audio duration', async () => {
    mockOnlineTtsFetch()
    mockAudioWithDuration(5)
    const speech = createTutorialSpeech()
    await speech.prefetchAll(['一段较长的教程说明'])
    expect(speech.getCachedDuration('一段较长的教程说明')).toBe(5000)
    expect(speech.stepHoldMs('一段较长的教程说明', 2800)).toBe(5450)
  })

  it('primes csrf cookie before tutorial tts post when missing', async () => {
    mockReadCsrfTokenFromCookie.mockReturnValueOnce('').mockReturnValue('csrf-token')
    mockApiFetch
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ success: true }) })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          success: true,
          data: { audioBase64: 'data:audio/mp3;base64,abc' },
        }),
      })
    mockAudioWithDuration(2)

    const speech = createTutorialSpeech()
    await speech.speak('冷启动教程说明')

    expect(mockApiFetch.mock.calls[0]?.[0]).toBe('/api/health')
    expect(mockApiFetch.mock.calls[1]?.[0]).toBe('/api/tts')
  })
})
