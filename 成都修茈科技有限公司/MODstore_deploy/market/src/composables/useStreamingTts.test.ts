import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { StreamingTtsPlayer, type StreamingTtsConfig } from './useStreamingTts'

const cfg = (): StreamingTtsConfig => ({
  engine: 'edge-online',
  edgeVoice: 'zh-CN-XiaoxiaoNeural',
  browserVoiceName: '',
  rate: 1,
})

describe('StreamingTtsPlayer', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      headers: { get: () => 'audio/mpeg' },
      body: {
        getReader: () => ({
          read: async () => ({ done: true, value: new Uint8Array([1, 2, 3]) }),
          releaseLock: () => {},
        }),
      },
      blob: async () => new Blob([new Uint8Array([1, 2, 3])], { type: 'audio/mpeg' }),
    })))
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:test'),
      revokeObjectURL: vi.fn(),
    })
    class MockAudio {
      onended: (() => void) | null = null
      addEventListener(ev: string, fn: () => void) {
        if (ev === 'ended') this.onended = fn
      }
      play = vi.fn(async () => {
        this.onended?.()
      })
      pause = vi.fn()
      removeAttribute = vi.fn()
      load = vi.fn()
    }
    vi.stubGlobal('Audio', MockAudio as unknown as typeof Audio)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('queues sentences in order', async () => {
    const player = new StreamingTtsPlayer(cfg)
    await player.speak('第一句。第二句。')
    expect(fetch).toHaveBeenCalled()
    expect(player.state.value).toBe('idle')
  })

  it('stop aborts playback queue', async () => {
    const player = new StreamingTtsPlayer(cfg)
    const p = player.speak('第一句。第二句。第三句。')
    player.stop()
    await p
    expect(player.state.value).toBe('idle')
  })

  it('feed and finish stream incrementally without duplicate enqueue', async () => {
    const player = new StreamingTtsPlayer(cfg)
    player.resetStream({ minLen: 4, earlyClause: true, earlyClauseMinLen: 8 })
    player.feed('这是一段足够长的问候前缀，后面的内容继续')
    player.finish('这是一段足够长的问候前缀，后面的内容继续。')
    await new Promise((r) => setTimeout(r, 50))
    expect(player.state.value).toBe('idle')
  })
})
