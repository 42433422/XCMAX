import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import {
  StreamingTtsPlayer,
  ttsConfigFromPersonalSettings,
  useStreamingTts,
  type StreamingTtsConfig,
} from './useStreamingTts'

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

  it('uses the unified endpoint, warms once and exposes the composable facade', async () => {
    const autoCfg = (): StreamingTtsConfig => ({ ...cfg(), engine: 'auto' })
    const tts = useStreamingTts(autoCfg)
    tts.warmUp()
    tts.warmUp()
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(String(vi.mocked(fetch).mock.calls[0]?.[0])).toContain('/api/workbench/tts')

    await tts.speak('统一语音服务会朗读这一句话。')
    await tts.whenIdle(20)
    expect(tts.state.value).toBe('idle')
    tts.resetStream({ minLen: 2 })
    tts.feed('第一段。')
    tts.finish('第一段。第二段。')
    await tts.whenIdle(100)
    tts.stop()
  })

  it('fails open for missing response bodies and request errors', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce({
        ok: true,
        headers: { get: () => 'audio/mpeg' },
        body: null,
        blob: async () => new Blob(),
      } as unknown as Response)
      .mockRejectedValueOnce(new Error('tts offline'))
    const player = new StreamingTtsPlayer(cfg)
    await player.speak('第一条缺少音频正文。')
    await player.speak('第二条网络失败。')
    await player.speak('https://example.com /api/internal')
    expect(player.state.value).toBe('idle')
  })

  it('normalizes saved personal settings into supported runtime configuration', () => {
    expect(ttsConfigFromPersonalSettings({
      ttsEngine: 'browser', ttsEdgeVoice: '', ttsVoiceName: 'legacy', ttsRate: 1.2,
    })).toEqual(expect.objectContaining({
      engine: 'auto', edgeVoice: 'zh-CN-XiaoxiaoNeural', browserVoiceName: '', rate: 1.2,
    }))
    expect(ttsConfigFromPersonalSettings({
      ttsEngine: 'edge-online', ttsEdgeVoice: 'custom-voice', ttsVoiceName: '', ttsRate: 0.8,
    }).engine).toBe('edge-online')
  })
})
