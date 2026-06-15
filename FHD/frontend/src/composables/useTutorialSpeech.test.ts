import { describe, expect, it, vi, afterEach } from 'vitest'
import { createTutorialSpeech } from './useTutorialSpeech'

function mockOnlineTtsFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        data: { audioBase64: 'data:audio/mp3;base64,abc' },
      }),
    }),
  )
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
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('uses online audio only without browser speechSynthesis', async () => {
    mockOnlineTtsFetch()
    mockAudioWithDuration(2)
    const speech = createTutorialSpeech()
    await speech.speak('教程步骤说明')
    expect(fetch).toHaveBeenCalled()
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
})
