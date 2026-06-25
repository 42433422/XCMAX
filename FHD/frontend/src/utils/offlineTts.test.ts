import { describe, it, expect, beforeEach, vi } from 'vitest'
import {
  isOfflineReady,
  isOfflineLoading,
  getOfflineProgress,
  getOfflineError,
  synthesizeOffline,
  playOfflinePcm,
  stopOffline,
} from './offlineTts'

describe('offlineTts', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('state accessors', () => {
    it('isOfflineReady returns boolean', () => {
      expect(typeof isOfflineReady()).toBe('boolean')
    })

    it('isOfflineLoading returns boolean', () => {
      expect(typeof isOfflineLoading()).toBe('boolean')
    })

    it('getOfflineProgress returns number', () => {
      expect(typeof getOfflineProgress()).toBe('number')
    })

    it('getOfflineProgress is between 0 and 1', () => {
      const p = getOfflineProgress()
      expect(p).toBeGreaterThanOrEqual(0)
      expect(p).toBeLessThanOrEqual(1)
    })

    it('getOfflineError returns null or unknown', () => {
      // 初始状态应为 null
      expect(getOfflineError()).toBeNull()
    })
  })

  describe('synthesizeOffline', () => {
    it('throws when pipeline not loaded', async () => {
      await expect(synthesizeOffline('hello')).rejects.toThrow(
        '离线 TTS 尚未加载，请先调用 ensureOfflineReady()',
      )
    })

    it('throws with empty string when pipeline not loaded', async () => {
      await expect(synthesizeOffline('')).rejects.toThrow(
        '离线 TTS 尚未加载',
      )
    })
  })

  describe('playOfflinePcm', () => {
    it('resolves immediately for empty Float32Array', async () => {
      await expect(playOfflinePcm(new Float32Array(0), 16000)).resolves.toBeUndefined()
    })

    it('resolves immediately for null-like input', async () => {
      // null is passed as Float32Array with length 0
      await expect(playOfflinePcm(new Float32Array(0), 16000)).resolves.toBeUndefined()
    })

    it('does not throw with valid PCM data', async () => {
      // Mock AudioContext to avoid real audio
      const mockCtx = {
        createBuffer: vi.fn(() => ({
          copyToChannel: vi.fn(),
        })),
        createBufferSource: vi.fn(() => ({
          buffer: null as unknown,
          connect: vi.fn(),
          start: vi.fn(),
          onended: null as ((e: Event) => void) | null,
          stop: vi.fn(),
          disconnect: vi.fn(),
        })),
        destination: {},
      }
      const original = window.AudioContext
      // @ts-expect-error mock
      window.AudioContext = vi.fn(() => mockCtx)
      // @ts-expect-error mock
      window.webkitAudioContext = undefined

      const pcm = new Float32Array([0.1, 0.2, 0.3])
      // Will resolve via onended or catch
      const promise = playOfflinePcm(pcm, 16000)
      // Manually trigger onended to resolve
      const source = mockCtx.createBufferSource.mock.results[0].value
      if (source.onended) source.onended(new Event('ended'))
      await expect(promise).resolves.toBeUndefined()

      window.AudioContext = original
    })
  })

  describe('stopOffline', () => {
    it('does not throw when nothing is playing', () => {
      expect(() => stopOffline()).not.toThrow()
    })

    it('can be called multiple times safely', () => {
      expect(() => {
        stopOffline()
        stopOffline()
        stopOffline()
      }).not.toThrow()
    })
  })
})
