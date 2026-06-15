import { describe, it, expect, vi, beforeEach } from 'vitest'
import { extractModNames, useStartupSplash, STARTUP_SPLASH_MS, STARTUP_FAILSAFE_MS } from './useStartupSplash'

vi.mock('@/utils/apiBase', () => ({
  isApiFetchTimeoutError: (e: unknown) => e instanceof Error && e.message.includes('timeout'),
}))

vi.mock('@/utils/modLoadingStatusShared', () => ({
  fetchModLoadingStatusShared: vi.fn().mockResolvedValue(null),
}))

vi.mock('@/utils/modLoadingStatus', () => ({
  summarizeModLoadingData: vi.fn().mockReturnValue(''),
}))

vi.mock('@/stores/mods', () => ({
  CLIENT_MODS_UI_OFF_KEY: 'xcagi_client_mods_ui_off',
}))

describe('extractModNames', () => {
  it('extracts names from mod list', () => {
    const result = extractModNames([{ name: 'Mod A' }, { name: 'Mod B' }])
    expect(result).toEqual(['Mod A', 'Mod B'])
  })

  it('falls back to id when name is empty', () => {
    const result = extractModNames([{ name: '', id: 'mod-x' }])
    expect(result).toEqual(['mod-x'])
  })

  it('deduplicates names', () => {
    const result = extractModNames([{ name: 'A' }, { name: 'A' }])
    expect(result).toEqual(['A'])
  })

  it('returns empty for null input', () => {
    expect(extractModNames(null as unknown as unknown[])).toEqual([])
  })

  it('returns empty for undefined input', () => {
    expect(extractModNames(undefined as unknown as unknown[])).toEqual([])
  })

  it('filters out empty strings', () => {
    const result = extractModNames([{ name: ' ' }, { name: 'A' }])
    expect(result).toEqual(['A'])
  })

  it('handles non-array input', () => {
    const result = extractModNames('not an array' as unknown as unknown[])
    expect(result).toEqual([])
  })
})

describe('useStartupSplash', () => {
  let splash: ReturnType<typeof useStartupSplash>

  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
    localStorage.clear()
    splash = useStartupSplash()
  })

  afterEach(() => {
    splash.teardownOnUnmount()
    vi.useRealTimers()
  })

  it('exports constants', () => {
    expect(STARTUP_SPLASH_MS).toBe(1200)
    expect(STARTUP_FAILSAFE_MS).toBe(6000)
  })

  it('initializes with correct defaults', () => {
    expect(splash.startupVisible.value).toBe(false)
    expect(splash.appReady.value).toBe(true)
    expect(splash.startupProgressPct.value).toBe(0)
    expect(splash.modsLoading.value).toBe(false)
    expect(splash.modsLoadError.value).toBeNull()
  })

  it('dismissStartupSplashImmediate hides splash and sets progress to 100', () => {
    splash.startupVisible.value = true
    splash.dismissStartupSplashImmediate()
    expect(splash.startupVisible.value).toBe(false)
    expect(splash.appReady.value).toBe(true)
    expect(splash.startupProgressPct.value).toBe(100)
  })

  it('dismissStartupSplashImmediate is idempotent', () => {
    splash.startupVisible.value = true
    splash.dismissStartupSplashImmediate()
    splash.dismissStartupSplashImmediate()
    expect(splash.startupVisible.value).toBe(false)
  })

  it('skipStartupSplash calls complete callback when visible', () => {
    const complete = vi.fn()
    splash.startupVisible.value = true
    splash.skipStartupSplash(complete)
    expect(complete).toHaveBeenCalled()
  })

  it('skipStartupSplash does nothing when not visible', () => {
    const complete = vi.fn()
    splash.startupVisible.value = false
    splash.skipStartupSplash(complete)
    expect(complete).not.toHaveBeenCalled()
  })

  it('scheduleFailsafe triggers complete after timeout', () => {
    const complete = vi.fn()
    splash.appReady.value = false
    splash.scheduleFailsafe(complete)
    vi.advanceTimersByTime(STARTUP_FAILSAFE_MS)
    expect(complete).toHaveBeenCalled()
  })

  it('scheduleFailsafe does not trigger when appReady', () => {
    const complete = vi.fn()
    splash.appReady.value = true
    splash.scheduleFailsafe(complete)
    vi.advanceTimersByTime(STARTUP_FAILSAFE_MS)
    expect(complete).not.toHaveBeenCalled()
  })

  it('clearFailsafeTimer cancels the failsafe', () => {
    const complete = vi.fn()
    splash.appReady.value = false
    splash.scheduleFailsafe(complete)
    splash.clearFailsafeTimer()
    vi.advanceTimersByTime(STARTUP_FAILSAFE_MS)
    expect(complete).not.toHaveBeenCalled()
  })

  it('createMinSplashElapsed resolves after STARTUP_SPLASH_MS', async () => {
    const promise = splash.createMinSplashElapsed()
    vi.advanceTimersByTime(STARTUP_SPLASH_MS)
    await expect(promise).resolves.toBeUndefined()
  })

  it('completeStartupSplash hides splash on second call', async () => {
    const ensureAuth = vi.fn().mockResolvedValue({ ok: true })
    // First call
    splash.completeStartupSplash(ensureAuth)
    expect(splash.startupProgressPct.value).toBe(100)
    // Second call should just finish UI
    splash.startupVisible.value = true
    splash.completeStartupSplash(ensureAuth)
    expect(splash.startupVisible.value).toBe(false)
  })

  it('loadModsForStartup skips when CLIENT_MODS_UI_OFF_KEY is set', async () => {
    localStorage.setItem('xcagi_client_mods_ui_off', '1')
    await splash.loadModsForStartup()
    expect(splash.modsLoading.value).toBe(false)
    expect(splash.startupModPreview.value).toEqual([])
  })

  it('loadModsForStartup sets modsLoading during fetch', async () => {
    const { fetchModLoadingStatusShared } = await import('@/utils/modLoadingStatusShared')
    vi.mocked(fetchModLoadingStatusShared).mockResolvedValueOnce({ mods: [{ name: 'Test' }] })
    const promise = splash.loadModsForStartup()
    expect(splash.modsLoading.value).toBe(true)
    await promise
    expect(splash.modsLoading.value).toBe(false)
    expect(splash.startupModPreview.value).toEqual([{ name: 'Test' }])
  })

  it('loadModsForStartup handles null response', async () => {
    const { fetchModLoadingStatusShared } = await import('@/utils/modLoadingStatusShared')
    vi.mocked(fetchModLoadingStatusShared).mockResolvedValueOnce(null)
    await splash.loadModsForStartup()
    expect(splash.startupModPreview.value).toEqual([])
  })

  it('loadModsForStartup handles error gracefully', async () => {
    const { fetchModLoadingStatusShared } = await import('@/utils/modLoadingStatusShared')
    vi.mocked(fetchModLoadingStatusShared).mockRejectedValueOnce(new Error('fail'))
    await splash.loadModsForStartup()
    expect(splash.startupModPreview.value).toEqual([])
    expect(splash.modsLoading.value).toBe(false)
  })

  it('startupPreviewModNames computed extracts names', async () => {
    const { fetchModLoadingStatusShared } = await import('@/utils/modLoadingStatusShared')
    vi.mocked(fetchModLoadingStatusShared).mockResolvedValueOnce({ mods: [{ name: 'Alpha' }, { name: 'Beta' }] })
    await splash.loadModsForStartup()
    expect(splash.startupPreviewModNames.value).toEqual(['Alpha', 'Beta'])
  })

  it('teardownOnUnmount cleans up timers', () => {
    splash.appReady.value = false
    splash.scheduleFailsafe(() => {})
    splash.teardownOnUnmount()
    // No crash, and failsafe timer should be cleared
    vi.advanceTimersByTime(STARTUP_FAILSAFE_MS)
    // No error thrown
  })

  it('getFailsafeTimer returns null initially', () => {
    expect(splash.getFailsafeTimer()).toBeNull()
  })

  it('getFailsafeTimer returns timer after scheduleFailsafe', () => {
    splash.scheduleFailsafe(() => {})
    expect(splash.getFailsafeTimer()).not.toBeNull()
  })
})
