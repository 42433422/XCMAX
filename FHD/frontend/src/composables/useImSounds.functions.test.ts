import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useImSounds } from './useImSounds'

describe('useImSounds', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  describe('setMode', () => {
    it('sets mode to all and persists to localStorage', () => {
      const { mode, setMode } = useImSounds()
      setMode('all')
      expect(mode.value).toBe('all')
      expect(localStorage.getItem('xcagi.im.soundMode')).toBe('all')
    })

    it('sets mode to mute and persists to localStorage', () => {
      const { mode, setMode } = useImSounds()
      setMode('mute')
      expect(mode.value).toBe('mute')
      expect(localStorage.getItem('xcagi.im.soundMode')).toBe('mute')
    })

    it('sets mode to notify-only and persists to localStorage', () => {
      const { mode, setMode } = useImSounds()
      setMode('notify-only')
      expect(mode.value).toBe('notify-only')
      expect(localStorage.getItem('xcagi.im.soundMode')).toBe('notify-only')
    })

    it('does not throw when localStorage is unavailable', () => {
      const orig = Object.getOwnPropertyDescriptor(window, 'localStorage')
      try {
        Object.defineProperty(window, 'localStorage', {
          get: () => {
            throw new Error('unavailable')
          },
        })
        const { setMode } = useImSounds()
        expect(() => setMode('all')).not.toThrow()
      } finally {
        if (orig) Object.defineProperty(window, 'localStorage', orig)
      }
    })
  })

  describe('playIncoming', () => {
    it('returns early when mode is mute', async () => {
      const { setMode, playIncoming } = useImSounds()
      setMode('mute')
      await expect(playIncoming('hello')).resolves.toBeUndefined()
    })

    it('plays file when mode is all', async () => {
      const playSpy = vi.fn().mockReturnValue(undefined)
      const fakeAudio = {
        currentTime: 0,
        play: playSpy,
        preload: '',
      }
      const origAudio = global.Audio
      global.Audio = vi.fn(() => fakeAudio as unknown as HTMLAudioElement) as unknown as typeof Audio
      try {
        const { setMode, playIncoming } = useImSounds()
        setMode('all')
        await expect(playIncoming('hello')).resolves.toBeUndefined()
      } finally {
        global.Audio = origAudio
      }
    })

    it('uses beepFallback when play() rejects (mode all)', async () => {
      let rejectPlay: (e: Error) => void = () => {}
      const playSpy = vi.fn().mockImplementation(() => {
        return new Promise<void>((_, reject) => {
          rejectPlay = reject
        })
      })
      const fakeAudio = {
        currentTime: 0,
        play: playSpy,
        preload: '',
      }
      const origAudio = global.Audio
      global.Audio = vi.fn(() => fakeAudio as unknown as HTMLAudioElement) as unknown as typeof Audio
      const origAudioContext = global.AudioContext
      const closeSpy = vi.fn()
      const startSpy = vi.fn()
      const stopSpy = vi.fn()
      const connectSpy = vi.fn()
      global.AudioContext = vi.fn(() => ({
        createOscillator: () => ({
          connect: connectSpy,
          frequency: { value: 0 },
          start: startSpy,
          stop: stopSpy,
          onended: null,
        }),
        createGain: () => ({
          connect: connectSpy,
          gain: { value: 0 },
        }),
        destination: {},
        currentTime: 0,
        close: closeSpy,
      })) as unknown as typeof AudioContext
      try {
        const { setMode, playIncoming } = useImSounds()
        setMode('all')
        const p = playIncoming('hello')
        rejectPlay(new Error('not allowed'))
        await p
        await new Promise((r) => setTimeout(r, 50))
      } finally {
        global.Audio = origAudio
        global.AudioContext = origAudioContext
      }
    })

    it('shows browser notification when mode is notify-only', async () => {
      const origNotification = global.Notification
      global.Notification = {
        permission: 'granted',
        requestPermission: vi.fn().mockResolvedValue('granted'),
      } as unknown as typeof Notification
      const notifInstance = { onclick: null, close: vi.fn() }
      global.Notification = vi.fn(() => notifInstance as unknown as Notification) as unknown as typeof Notification
      ;(global.Notification as unknown as { permission: string }).permission = 'granted'
      try {
        const { setMode, playIncoming } = useImSounds()
        setMode('notify-only')
        await expect(playIncoming('preview text')).resolves.toBeUndefined()
      } finally {
        global.Notification = origNotification
      }
    })

    it('uses default message when preview is empty (notify-only)', async () => {
      const origNotification = global.Notification
      const notifInstance = { onclick: null, close: vi.fn() }
      const notifCtor = vi.fn(() => notifInstance as unknown as Notification)
      global.Notification = notifCtor as unknown as typeof Notification
      ;(global.Notification as unknown as { permission: string }).permission = 'granted'
      try {
        const { setMode, playIncoming } = useImSounds()
        setMode('notify-only')
        await playIncoming()
        expect(notifCtor).toHaveBeenCalledWith('新消息', expect.objectContaining({ body: '您有一条新消息' }))
      } finally {
        global.Notification = origNotification
      }
    })

    it('calls desktop showNotification when available (notify-only)', async () => {
      const origNotification = global.Notification
      global.Notification = { permission: 'denied' } as unknown as typeof Notification
      const desktopNotif = vi.fn().mockResolvedValue(undefined)
      const origDesktop = (window as unknown as { xcagiDesktop?: unknown }).xcagiDesktop
      ;(window as unknown as { xcagiDesktop?: unknown }).xcagiDesktop = { showNotification: desktopNotif }
      try {
        const { setMode, playIncoming } = useImSounds()
        setMode('notify-only')
        await playIncoming('preview')
        expect(desktopNotif).toHaveBeenCalledWith('新消息', 'preview')
      } finally {
        global.Notification = origNotification
        ;(window as unknown as { xcagiDesktop?: unknown }).xcagiDesktop = origDesktop
      }
    })
  })

  describe('playOutgoing', () => {
    it('returns early when mode is mute', () => {
      const { setMode, playOutgoing } = useImSounds()
      setMode('mute')
      expect(() => playOutgoing()).not.toThrow()
    })

    it('returns early when mode is notify-only', () => {
      const { setMode, playOutgoing } = useImSounds()
      setMode('notify-only')
      expect(() => playOutgoing()).not.toThrow()
    })

    it('plays file when mode is all', () => {
      const playSpy = vi.fn().mockReturnValue(undefined)
      const fakeAudio = {
        currentTime: 0,
        play: playSpy,
        preload: '',
      }
      const origAudio = global.Audio
      global.Audio = vi.fn(() => fakeAudio as unknown as HTMLAudioElement) as unknown as typeof Audio
      try {
        const { setMode, playOutgoing } = useImSounds()
        setMode('all')
        playOutgoing()
        expect(playSpy).toHaveBeenCalled()
      } finally {
        global.Audio = origAudio
      }
    })
  })

  describe('mode initial value', () => {
    it('reads initial mode from localStorage', async () => {
      localStorage.setItem('xcagi.im.soundMode', 'mute')
      vi.resetModules()
      const { useImSounds: freshUseImSounds } = await import('./useImSounds')
      const { mode } = freshUseImSounds()
      expect(mode.value).toBe('mute')
    })

    it('defaults to all when localStorage is empty', async () => {
      localStorage.clear()
      vi.resetModules()
      const { useImSounds: freshUseImSounds } = await import('./useImSounds')
      const { mode } = freshUseImSounds()
      expect(mode.value).toBe('all')
    })

    it('defaults to all when localStorage has invalid value', async () => {
      localStorage.setItem('xcagi.im.soundMode', 'invalid')
      vi.resetModules()
      const { useImSounds: freshUseImSounds } = await import('./useImSounds')
      const { mode } = freshUseImSounds()
      expect(mode.value).toBe('all')
    })
  })
})
