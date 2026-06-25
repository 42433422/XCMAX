import { describe, it, expect, beforeEach, vi } from 'vitest'

const apiPostMock = vi.fn()
const patchWorkspacePrefsMock = vi.fn()

vi.mock('@/api', () => ({
  default: {
    post: (...a: unknown[]) => apiPostMock(...a),
  },
}))

vi.mock('@/utils/workspacePrefsApi', () => ({
  patchWorkspacePrefs: (...a: unknown[]) => patchWorkspacePrefsMock(...a),
}))

import {
  resetHostOnboardingForTest,
  bootstrapDesktopDatabase,
  openAssistantTutorialTab,
} from './devTestInit'

describe('devTestInit', () => {
  beforeEach(() => {
    apiPostMock.mockReset()
    patchWorkspacePrefsMock.mockReset()
    localStorage.clear()
  })

  describe('resetHostOnboardingForTest', () => {
    it('removes onboarding key from localStorage', async () => {
      localStorage.setItem('xcagi_onboarding_driver_tutorial_completed', '1')
      patchWorkspacePrefsMock.mockResolvedValue({})
      await resetHostOnboardingForTest()
      expect(localStorage.getItem('xcagi_onboarding_driver_tutorial_completed')).toBeNull()
    })

    it('calls patchWorkspacePrefs with reset flags', async () => {
      patchWorkspacePrefsMock.mockResolvedValue({})
      await resetHostOnboardingForTest()
      expect(patchWorkspacePrefsMock).toHaveBeenCalledWith({
        product_flow_completed: false,
        host_pack_acknowledged: false,
      })
    })

    it('does not throw when patchWorkspacePrefs fails', async () => {
      patchWorkspacePrefsMock.mockRejectedValue(new Error('not logged in'))
      await expect(resetHostOnboardingForTest()).resolves.toBeUndefined()
    })

    it('does not throw when localStorage throws', async () => {
      patchWorkspacePrefsMock.mockResolvedValue({})
      const original = localStorage.removeItem
      localStorage.removeItem = vi.fn(() => {
        throw new Error('quota')
      })
      await expect(resetHostOnboardingForTest()).resolves.toBeUndefined()
      localStorage.removeItem = original
    })
  })

  describe('bootstrapDesktopDatabase', () => {
    it('posts to bootstrap-db endpoint', async () => {
      apiPostMock.mockResolvedValue({
        success: true,
        steps: ['step1', 'step2'],
        message: 'ok',
      })
      const result = await bootstrapDesktopDatabase()
      expect(apiPostMock).toHaveBeenCalledWith('/api/desktop/bootstrap-db')
      expect(result.steps).toEqual(['step1', 'step2'])
      expect(result.message).toBe('ok')
    })

    it('throws when success is false', async () => {
      apiPostMock.mockResolvedValue({
        success: false,
        message: 'init failed',
      })
      await expect(bootstrapDesktopDatabase()).rejects.toThrow('init failed')
    })

    it('throws default message when success is false and no message', async () => {
      apiPostMock.mockResolvedValue({ success: false })
      await expect(bootstrapDesktopDatabase()).rejects.toThrow('初始化失败')
    })

    it('uses detail field when message is missing', async () => {
      apiPostMock.mockResolvedValue({
        success: false,
        detail: 'detailed error',
      })
      await expect(bootstrapDesktopDatabase()).rejects.toThrow('detailed error')
    })

    it('returns steps and message when success', async () => {
      apiPostMock.mockResolvedValue({
        success: true,
        steps: ['a'],
        message: 'done',
      })
      const result = await bootstrapDesktopDatabase()
      expect(result.steps).toEqual(['a'])
      expect(result.message).toBe('done')
    })

    it('handles response without steps or message', async () => {
      apiPostMock.mockResolvedValue({ success: true })
      const result = await bootstrapDesktopDatabase()
      expect(result.steps).toBeUndefined()
      expect(result.message).toBeUndefined()
    })
  })

  describe('openAssistantTutorialTab', () => {
    it('dispatches custom event on window', () => {
      const handler = vi.fn()
      window.addEventListener('xcagi:tutorial:set-assistant-tab', handler)
      openAssistantTutorialTab()
      expect(handler).toHaveBeenCalledTimes(1)
      const event = handler.mock.calls[0][0] as CustomEvent
      expect(event.detail).toEqual({ open: true, tab: 'tutorial' })
      window.removeEventListener('xcagi:tutorial:set-assistant-tab', handler)
    })

    it('does not throw', () => {
      expect(() => openAssistantTutorialTab()).not.toThrow()
    })
  })
})
