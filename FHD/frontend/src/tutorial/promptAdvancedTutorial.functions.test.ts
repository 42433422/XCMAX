import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const { mockAppConfirm } = vi.hoisted(() => ({
  mockAppConfirm: vi.fn(),
}))

vi.mock('@/utils/appDialog', () => ({
  appConfirm: mockAppConfirm,
}))

import { resolveRouteNameFromPath, launchAdvancedDriverTour, promptAdvancedTutorialAfterInstall } from './promptAdvancedTutorial'

function makeRouter(resolveResult: { name?: string } = { name: 'chat' }) {
  return {
    push: vi.fn().mockResolvedValue(undefined),
    resolve: vi.fn().mockReturnValue(resolveResult),
  } as unknown as Parameters<typeof resolveRouteNameFromPath>[0]
}

describe('promptAdvancedTutorial', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockAppConfirm.mockReset()
  })

  describe('resolveRouteNameFromPath', () => {
    it('returns "chat" for empty path', () => {
      expect(resolveRouteNameFromPath(makeRouter(), '')).toBe('chat')
    })

    it('returns "chat" for whitespace-only path', () => {
      expect(resolveRouteNameFromPath(makeRouter(), '   ')).toBe('chat')
    })

    it('returns "chat" for null/undefined path', () => {
      expect(resolveRouteNameFromPath(makeRouter(), null as unknown as string)).toBe('chat')
      expect(resolveRouteNameFromPath(makeRouter(), undefined as unknown as string)).toBe('chat')
    })

    it('returns resolved route name from router', () => {
      const router = makeRouter({ name: 'settings' })
      expect(resolveRouteNameFromPath(router, '/settings')).toBe('settings')
    })

    it('returns "chat" when router.resolve throws', () => {
      const router = {
        resolve: vi.fn().mockImplementation(() => {
          throw new Error('resolve failed')
        }),
      } as unknown as Parameters<typeof resolveRouteNameFromPath>[0]
      expect(resolveRouteNameFromPath(router, '/unknown')).toBe('chat')
    })

    it('returns "chat" when resolved name is empty', () => {
      const router = makeRouter({ name: '' })
      expect(resolveRouteNameFromPath(router, '/some-path')).toBe('chat')
    })

    it('returns "chat" when resolved name is undefined', () => {
      const router = makeRouter({})
      expect(resolveRouteNameFromPath(router, '/some-path')).toBe('chat')
    })

    it('trims whitespace in path before resolving', () => {
      const router = makeRouter({ name: 'chat' })
      resolveRouteNameFromPath(router, '  /chat  ')
      expect(router.resolve).toHaveBeenCalledWith('/chat')
    })
  })

  describe('launchAdvancedDriverTour', () => {
    it('opens the V2 course catalog without starting the timed driver tour', async () => {
      const router = makeRouter()
      const buildContext = { industryId: 'retail', mods: [], visibleNav: [], modMenuKeys: new Set() }
      const listener = vi.fn()
      window.addEventListener('xcagi:open-assistant-float', listener)

      await launchAdvancedDriverTour({ router, buildContext, skipNavigation: true })

      expect(router.push).not.toHaveBeenCalled()
      expect(listener).toHaveBeenCalledOnce()
      expect((listener.mock.calls[0][0] as CustomEvent).detail).toEqual({
        feature: 'tutorial',
        advanced: true,
      })
      window.removeEventListener('xcagi:open-assistant-float', listener)
    })

    it('returns store.active value', async () => {
      const buildContext = { industryId: 'retail', mods: [], visibleNav: [], modMenuKeys: new Set() }
      const result = await launchAdvancedDriverTour({
        router: makeRouter(),
        buildContext,
        skipNavigation: true,
      })
      expect(typeof result).toBe('boolean')
    })

    it('does not synthesize clicks or timed navigation when return context is absent', async () => {
      const buildContext = { industryId: 'retail', mods: [], visibleNav: [], modMenuKeys: new Set() }
      const router = makeRouter()
      await launchAdvancedDriverTour({
        router,
        buildContext,
        skipNavigation: true,
      })
      expect(router.push).not.toHaveBeenCalled()
    })
  })

  describe('promptAdvancedTutorialAfterInstall', () => {
    it('ignores the old local completion boolean because it is not V2 evidence', async () => {
      mockAppConfirm.mockResolvedValueOnce(false)
      const buildContext = { industryId: 'retail', mods: [], visibleNav: [], modMenuKeys: new Set() }
      const result = await promptAdvancedTutorialAfterInstall({
        router: makeRouter(),
        buildContext,
      })
      expect(result).toBe('dismissed')
      expect(mockAppConfirm).toHaveBeenCalled()
    })

    it('returns "dismissed" when user declines confirm', async () => {
      mockAppConfirm.mockResolvedValueOnce(false)
      const buildContext = { industryId: 'retail', mods: [], visibleNav: [], modMenuKeys: new Set() }
      const result = await promptAdvancedTutorialAfterInstall({
        router: makeRouter(),
        buildContext,
      })
      expect(result).toBe('dismissed')
    })

    it('calls appConfirm with default message', async () => {
      mockAppConfirm.mockResolvedValueOnce(false)
      const buildContext = { industryId: 'retail', mods: [], visibleNav: [], modMenuKeys: new Set() }
      await promptAdvancedTutorialAfterInstall({
        router: makeRouter(),
        buildContext,
      })
      expect(mockAppConfirm).toHaveBeenCalledWith(
        expect.stringContaining('安装已完成'),
        expect.objectContaining({
          title: '安装完成',
          confirmText: '观看教程',
          cancelText: '稍后再说',
        }),
      )
    })

    it('calls appConfirm with custom message when provided', async () => {
      mockAppConfirm.mockResolvedValueOnce(false)
      const buildContext = { industryId: 'retail', mods: [], visibleNav: [], modMenuKeys: new Set() }
      await promptAdvancedTutorialAfterInstall({
        router: makeRouter(),
        buildContext,
        message: 'Custom message',
      })
      expect(mockAppConfirm).toHaveBeenCalledWith('Custom message', expect.any(Object))
    })

    it('does not skip when skipIfCompleted is false', async () => {
      mockAppConfirm.mockResolvedValueOnce(false)
      const buildContext = { industryId: 'retail', mods: [], visibleNav: [], modMenuKeys: new Set() }
      const result = await promptAdvancedTutorialAfterInstall({
        router: makeRouter(),
        buildContext,
        skipIfCompleted: false,
      })
      expect(result).toBe('dismissed')
      expect(mockAppConfirm).toHaveBeenCalled()
    })
  })
})
