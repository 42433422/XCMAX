/**
 * useImSounds 函数补全测试
 * 覆盖：playFile、beepFallback、getAudio、ensureNotificationPermission、
 * showBrowserNotification、playIncoming('notify-only')、playIncoming('all')、
 * playOutgoing('all')、readMode 边界
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useImSounds, type ImSoundMode } from './useImSounds'

// ── Mocks ─────────────────────────────────────────────────

const mockAudioPlay = vi.fn()
const mockAudioCatch = vi.fn()
const mockAudioInstance = {
  preload: '',
  currentTime: 0,
  play: () => {
    const p: any = Promise.resolve()
    p.catch = mockAudioCatch
    mockAudioPlay()
    return p
  },
}

vi.stubGlobal('Audio', vi.fn(() => mockAudioInstance))

const mockOscillatorStart = vi.fn()
const mockOscillatorStop = vi.fn()
const mockOscillatorConnect = vi.fn()
const mockGainConnect = vi.fn()
const mockGainValue = { value: 0 }
const mockCtxClose = vi.fn()
const mockCtxCreateOscillator = vi.fn(() => ({
  connect: mockOscillatorConnect,
  frequency: { value: 0 },
  start: mockOscillatorStart,
  stop: mockOscillatorStop,
  onended: null,
}))
const mockCtxCreateGain = vi.fn(() => ({
  connect: mockGainConnect,
  gain: mockGainValue,
}))
const mockCtxDestination = {}
const mockAudioContext = vi.fn(() => ({
  createOscillator: mockCtxCreateOscillator,
  createGain: mockCtxCreateGain,
  destination: mockCtxDestination,
  currentTime: 0,
  close: mockCtxClose,
}))

vi.stubGlobal('AudioContext', mockAudioContext)

const mockNotificationRequestPermission = vi.fn()
const mockNotificationClose = vi.fn()
const mockNotificationInstance = {
  onclick: null as ((this: Notification, ev: Event) => any) | null,
  close: mockNotificationClose,
}
const MockNotification = vi.fn(() => mockNotificationInstance) as any
MockNotification.permission = 'default'
MockNotification.requestPermission = mockNotificationRequestPermission
vi.stubGlobal('Notification', MockNotification)

// ── Tests ─────────────────────────────────────────────────

describe('useImSounds additional functions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    // Reset module state by re-importing
    vi.resetModules()
    MockNotification.permission = 'default'
    mockAudioPlay.mockClear()
    mockAudioCatch.mockClear()
  })

  afterEach(() => {
    localStorage.clear()
  })

  // --- readMode edge cases ---

  it('readMode returns stored mute value', async () => {
    localStorage.setItem('xcagi.im.soundMode', 'mute')
    const { useImSounds } = await import('./useImSounds')
    const { mode } = useImSounds()
    expect(mode.value).toBe('mute')
  })

  it('readMode returns stored notify-only value', async () => {
    localStorage.setItem('xcagi.im.soundMode', 'notify-only')
    const { useImSounds } = await import('./useImSounds')
    const { mode } = useImSounds()
    expect(mode.value).toBe('notify-only')
  })

  it('readMode returns all for invalid stored value', async () => {
    localStorage.setItem('xcagi.im.soundMode', 'invalid')
    const { useImSounds } = await import('./useImSounds')
    const { mode } = useImSounds()
    expect(mode.value).toBe('all')
  })

  it('readMode returns all when localStorage throws', async () => {
    const origGetItem = localStorage.getItem
    Object.defineProperty(localStorage, 'getItem', {
      configurable: true,
      value: vi.fn(() => {
        throw new Error('access denied')
      }),
    })
    const { useImSounds } = await import('./useImSounds')
    const { mode } = useImSounds()
    expect(mode.value).toBe('all')
    Object.defineProperty(localStorage, 'getItem', {
      configurable: true,
      value: origGetItem,
    })
  })

  // --- setMode ---

  it('setMode persists to localStorage', async () => {
    const { useImSounds } = await import('./useImSounds')
    const { setMode } = useImSounds()
    setMode('notify-only')
    expect(localStorage.getItem('xcagi.im.soundMode')).toBe('notify-only')
  })

  it('setMode does not throw when localStorage fails', async () => {
    const origSetItem = localStorage.setItem
    Object.defineProperty(localStorage, 'setItem', {
      configurable: true,
      value: vi.fn(() => {
        throw new Error('quota exceeded')
      }),
    })
    const { useImSounds } = await import('./useImSounds')
    const { setMode, mode } = useImSounds()
    expect(() => setMode('mute')).not.toThrow()
    expect(mode.value).toBe('mute')
    Object.defineProperty(localStorage, 'setItem', {
      configurable: true,
      value: origSetItem,
    })
  })

  // --- playOutgoing in 'all' mode ---

  it('playOutgoing plays audio in all mode', async () => {
    const { useImSounds } = await import('./useImSounds')
    const { setMode, playOutgoing } = useImSounds()
    setMode('all')
    playOutgoing()
    expect(mockAudioPlay).toHaveBeenCalled()
  })

  it('playOutgoing does not play in notify-only mode', async () => {
    const { useImSounds } = await import('./useImSounds')
    const { setMode, playOutgoing } = useImSounds()
    setMode('notify-only')
    playOutgoing()
    expect(mockAudioPlay).not.toHaveBeenCalled()
  })

  // --- playIncoming in 'all' mode ---

  it('playIncoming plays audio in all mode', async () => {
    const { useImSounds } = await import('./useImSounds')
    const { setMode, playIncoming } = useImSounds()
    setMode('all')
    await playIncoming('hello')
    expect(mockAudioPlay).toHaveBeenCalled()
  })

  // --- playIncoming in 'notify-only' mode ---

  it('playIncoming shows browser notification in notify-only mode', async () => {
    MockNotification.permission = 'granted'
    const { useImSounds } = await import('./useImSounds')
    const { setMode, playIncoming } = useImSounds()
    setMode('notify-only')
    await playIncoming('New message preview')
    expect(MockNotification).toHaveBeenCalledWith('新消息', {
      body: 'New message preview',
      tag: 'xcagi-im',
    })
  })

  it('playIncoming uses default body when no preview', async () => {
    MockNotification.permission = 'granted'
    const { useImSounds } = await import('./useImSounds')
    const { setMode, playIncoming } = useImSounds()
    setMode('notify-only')
    await playIncoming()
    expect(MockNotification).toHaveBeenCalledWith('新消息', {
      body: '您有一条新消息',
      tag: 'xcagi-im',
    })
  })

  it('playIncoming notification onclick focuses window and closes', async () => {
    MockNotification.permission = 'granted'
    const { useImSounds } = await import('./useImSounds')
    const { setMode, playIncoming } = useImSounds()
    setMode('notify-only')
    await playIncoming('test')
    expect(mockNotificationInstance.onclick).toBeTruthy()
    // Simulate click
    const focusSpy = vi.spyOn(window, 'focus').mockImplementation(() => {})
    mockNotificationInstance.onclick?.call(mockNotificationInstance as any, new Event('click'))
    expect(focusSpy).toHaveBeenCalled()
    expect(mockNotificationClose).toHaveBeenCalled()
    focusSpy.mockRestore()
  })

  // --- ensureNotificationPermission ---

  it('requests permission when default and user grants', async () => {
    MockNotification.permission = 'default'
    mockNotificationRequestPermission.mockResolvedValue('granted')
    const { useImSounds } = await import('./useImSounds')
    const { setMode, playIncoming } = useImSounds()
    setMode('notify-only')
    await playIncoming('test')
    expect(mockNotificationRequestPermission).toHaveBeenCalled()
  })

  it('does not show notification when permission denied', async () => {
    MockNotification.permission = 'denied'
    const { useImSounds } = await import('./useImSounds')
    const { setMode, playIncoming } = useImSounds()
    setMode('notify-only')
    await playIncoming('test')
    expect(MockNotification).not.toHaveBeenCalled()
  })

  it('does not show notification when requestPermission returns default', async () => {
    MockNotification.permission = 'default'
    mockNotificationRequestPermission.mockResolvedValue('default')
    const { useImSounds } = await import('./useImSounds')
    const { setMode, playIncoming } = useImSounds()
    setMode('notify-only')
    await playIncoming('test')
    expect(MockNotification).not.toHaveBeenCalled()
  })

  // --- playFile with audio.play() rejection → beepFallback ---

  it('falls back to beep when audio.play() rejects', async () => {
    const failingPlay = vi.fn(() => {
      const p: any = Promise.reject(new Error('not allowed'))
      p.catch = vi.fn((cb: any) => {
        // Immediately call the callback to simulate rejection
        cb(new Error('not allowed'))
        return p
      })
      return p
    })
    const failingAudio = {
      preload: '',
      currentTime: 0,
      play: failingPlay,
    }
    vi.mocked(Audio).mockReturnValue(failingAudio as any)

    const { useImSounds } = await import('./useImSounds')
    const { setMode, playOutgoing } = useImSounds()
    setMode('all')
    playOutgoing()
    // beepFallback should have been called via AudioContext
    expect(mockAudioContext).toHaveBeenCalled()
  })

  // --- Notification undefined ---

  it('handles gracefully when Notification is undefined', async () => {
    const origNotification = (window as any).Notification
    delete (window as any).Notification
    const { useImSounds } = await import('./useImSounds')
    const { setMode, playIncoming } = useImSounds()
    setMode('notify-only')
    await expect(playIncoming('test')).resolves.toBeUndefined()
    ;(window as any).Notification = origNotification
  })
})
