import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const { mockAppConfirm, mockStoreStart, mockStoreIsCompleted, mockStoreActive } = vi.hoisted(() => ({
  mockAppConfirm: vi.fn(),
  mockStoreStart: vi.fn(),
  mockStoreIsCompleted: vi.fn(),
  mockStoreActive: false,
}))

vi.mock('@/utils/appDialog', () => ({
  appConfirm: mockAppConfirm,
}))

vi.mock('@/stores/onboardingTutorial', () => ({
  useOnboardingTutorialStore: () => ({
    start: mockStoreStart,
    isCompleted: mockStoreIsCompleted,
    get active() {
      return mockStoreActive
    },
  }),
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
    mockStoreStart.mockReset()
    mockStoreIsCompleted.mockReset()
    mockStoreIsCompleted.mockReturnValue(false)
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
    it('navigates to chat and starts advanced tour', async () => {
      const router = makeRouter()
      const buildContext = { industryId: 'retail', mods: [], visibleNav: [], isProMode: false, modMenuKeys: new Set() }

      await launchAdvancedDriverTour({ router, buildContext, skipNavigation: true })

      expect(mockStoreStart).toHaveBeenCalledWith(
        expect.objectContaining({
          track: 'advanced',
          buildContext,
        }),
      )
    })

    it('returns store.active value', async () => {
      const buildContext = { industryId: 'retail', mods: [], visibleNav: [], isProMode: false, modMenuKeys: new Set() }
      const result = await launchAdvancedDriverTour({
        router: makeRouter(),
        buildContext,
        skipNavigation: true,
      })
      expect(typeof result).toBe('boolean')
    })

    it('uses default returnContext when not provided', async () => {
      const buildContext = { industryId: 'retail', mods: [], visibleNav: [], isProMode: false, modMenuKeys: new Set() }
      await launchAdvancedDriverTour({
        router: makeRouter(),
        buildContext,
        skipNavigation: true,
      })
      expect(mockStoreStart).toHaveBeenCalledWith(
        expect.objectContaining({
          returnContext: { routeName: 'chat' },
        }),
      )
    })
  })

  describe('promptAdvancedTutorialAfterInstall', () => {
    it('returns "already_completed" when skipIfCompleted and store is completed', async () => {
      mockStoreIsCompleted.mockReturnValue(true)
      const buildContext = { industryId: 'retail', mods: [], visibleNav: [], isProMode: false, modMenuKeys: new Set() }
      const result = await promptAdvancedTutorialAfterInstall({
        router: makeRouter(),
        buildContext,
      })
      expect(result).toBe('already_completed')
    })

    it('returns "dismissed" when user declines confirm', async () => {
      mockAppConfirm.mockResolvedValueOnce(false)
      const buildContext = { industryId: 'retail', mods: [], visibleNav: [], isProMode: false, modMenuKeys: new Set() }
      const result = await promptAdvancedTutorialAfterInstall({
        router: makeRouter(),
        buildContext,
      })
      expect(result).toBe('dismissed')
    })

    it('calls appConfirm with default message', async () => {
      mockAppConfirm.mockResolvedValueOnce(false)
      const buildContext = { industryId: 'retail', mods: [], visibleNav: [], isProMode: false, modMenuKeys: new Set() }
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
      const buildContext = { industryId: 'retail', mods: [], visibleNav: [], isProMode: false, modMenuKeys: new Set() }
      await promptAdvancedTutorialAfterInstall({
        router: makeRouter(),
        buildContext,
        message: 'Custom message',
      })
      expect(mockAppConfirm).toHaveBeenCalledWith('Custom message', expect.any(Object))
    })

    it('does not skip when skipIfCompleted is false', async () => {
      mockStoreIsCompleted.mockReturnValue(true)
      mockAppConfirm.mockResolvedValueOnce(false)
      const buildContext = { industryId: 'retail', mods: [], visibleNav: [], isProMode: false, modMenuKeys: new Set() }
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
