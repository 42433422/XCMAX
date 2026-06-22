import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  clearVoiceLatencyMarks,
  markVoiceLatency,
  reportVoiceLatencyIfComplete,
} from './composables/voiceLatency'
import { executeVoiceBargeIn, shouldTriggerVoiceBargeIn } from './composables/voiceBargeIn'
import { isCatalogSaved, toggleCatalogSaved } from './utils/catalogSaved'
import {
  DEFAULT_XCAGI_DOWNLOAD_VERSION,
  detectMacDownloadArch,
  macArchFromQuery,
  macDownloadArchLabel,
  normalizeXcagiDownloadBase,
  xcagiDownloadFileName,
  xcagiDownloadUrl,
} from './utils/xcagiDownloadLinks'
import { desktopOpsDeepLink } from './utils/opsDeepLinks'

let mockMobileVoice = false

vi.mock('./composables/voiceDevice', () => ({
  isMobileVoiceDevice: () => mockMobileVoice,
}))

afterEach(() => {
  mockMobileVoice = false
  clearVoiceLatencyMarks()
  localStorage.clear()
  window.history.pushState(null, '', '/')
  vi.restoreAllMocks()
})

describe('voice and link utility coverage', () => {
  it('marks and reports voice latency only when the chain is complete', () => {
    const mark = vi.spyOn(performance, 'mark').mockImplementation(() => undefined)
    vi.spyOn(performance, 'now')
      .mockReturnValueOnce(100)
      .mockReturnValueOnce(180)
      .mockReturnValueOnce(260)
      .mockReturnValueOnce(410)

    expect(reportVoiceLatencyIfComplete()).toBeNull()
    markVoiceLatency('speech_end')
    markVoiceLatency('asr_final')
    markVoiceLatency('llm_first_token')
    expect(reportVoiceLatencyIfComplete()).toBeNull()
    markVoiceLatency('tts_first_audio')

    expect(reportVoiceLatencyIfComplete()).toEqual({
      speech_to_asr_ms: 80,
      speech_to_llm_ms: 160,
      speech_to_tts_ms: 310,
    })
    expect(mark).toHaveBeenCalledWith('voice_speech_end')

    clearVoiceLatencyMarks()
    expect(reportVoiceLatencyIfComplete()).toBeNull()
  })

  it('evaluates voice barge-in thresholds and executes all targets', () => {
    expect(shouldTriggerVoiceBargeIn(0.4, 0.5, false)).toBe(false)
    expect(shouldTriggerVoiceBargeIn(0.5, 0.5, false)).toBe(true)
    expect(shouldTriggerVoiceBargeIn(1.39, 0.5, true)).toBe(false)
    expect(shouldTriggerVoiceBargeIn(1.4, 0.5, true)).toBe(true)

    mockMobileVoice = true
    expect(shouldTriggerVoiceBargeIn(1.69, 0.5, true)).toBe(false)
    expect(shouldTriggerVoiceBargeIn(1.7, 0.5, true)).toBe(true)

    const targets = {
      stopS2s: vi.fn(),
      stopCascadeTts: vi.fn(),
      abortLlmStream: vi.fn(),
      setIdle: vi.fn(),
    }
    executeVoiceBargeIn(targets)
    expect(targets.stopS2s).toHaveBeenCalled()
    expect(targets.stopCascadeTts).toHaveBeenCalled()
    expect(targets.abortLlmStream).toHaveBeenCalled()
    expect(targets.setIdle).toHaveBeenCalled()
  })

  it('persists catalog saved state defensively in localStorage', () => {
    expect(isCatalogSaved(null)).toBe(false)
    expect(isCatalogSaved(undefined)).toBe(false)
    expect(isCatalogSaved('')).toBe(false)

    localStorage.setItem('market_catalog_saved_v1', '{bad json')
    expect(isCatalogSaved('a')).toBe(false)

    localStorage.setItem('market_catalog_saved_v1', JSON.stringify({ a: 1 }))
    expect(isCatalogSaved('a')).toBe(false)

    expect(toggleCatalogSaved(42)).toBe(true)
    expect(isCatalogSaved('42')).toBe(true)
    expect(toggleCatalogSaved('42')).toBe(false)
    expect(isCatalogSaved(42)).toBe(false)
  })

  it('builds XCAGI download names, URLs, mac architecture labels, and ops deep links', () => {
    expect(DEFAULT_XCAGI_DOWNLOAD_VERSION).toBe('10.0.0')
    expect(normalizeXcagiDownloadBase(undefined, '11.0.0')).toBe('https://dl.xiu-ci.com/xcagi-v11.0.0')
    expect(normalizeXcagiDownloadBase('https://cdn.example.com/root/')).toBe('https://cdn.example.com/root')

    expect(xcagiDownloadFileName('personal', 'win', '1.2.3')).toBe('XCAGI-Personal-Setup-1.2.3-x64.exe')
    expect(xcagiDownloadFileName('enterprise', 'mac', '1.2.3', '9.9.9', 'x64')).toBe('XCAGI-Enterprise-1.2.3-mac-x64.dmg')
    expect(xcagiDownloadFileName('personal', 'android', '1.2.3', '9.9.9')).toBe('XCAGI-Personal-Android-9.9.9.apk')
    expect(xcagiDownloadUrl('enterprise', 'android', 'https://cdn', '1', '2')).toBe('https://cdn/enterprise/XCAGI-Enterprise-Android-2.apk')

    window.history.pushState(null, '', '/download?macArch=intel')
    expect(macArchFromQuery()).toBe('x64')
    expect(detectMacDownloadArch()).toBe('x64')
    expect(macDownloadArchLabel('arm64')).toBe('Apple Silicon')
    expect(macDownloadArchLabel('x64')).toBe('Intel')

    window.history.pushState(null, '', '/download?macArch=aarch64')
    expect(macArchFromQuery()).toBe('arm64')

    window.history.pushState(null, '', '/download')
    vi.spyOn(document, 'createElement').mockReturnValue({
      getContext: () => null,
    } as unknown as HTMLElement)
    Object.defineProperty(navigator, 'userAgentData', {
      value: { architecture: 'x86' },
      configurable: true,
    })
    expect(detectMacDownloadArch()).toBe('arm64')

    expect(desktopOpsDeepLink()).toBe('xcagi://ops/duty')
    expect(desktopOpsDeepLink(' emp 1 ')).toBe('xcagi://ops/duty?employee=emp%201')
  })
})
