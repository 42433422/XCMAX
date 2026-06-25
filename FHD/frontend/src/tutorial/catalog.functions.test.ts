import { describe, it, expect, vi } from 'vitest'

vi.mock('./buildModSteps', () => ({
  collectModTutorialTracks: vi.fn(() => []),
}))

import { getTrackMetas, getTrackLabel, formatAdvancedTrackHint } from './catalog'
import { collectModTutorialTracks } from './buildModSteps'
import type { TutorialBuildContext } from './types'

function makeCtx(overrides: Partial<TutorialBuildContext> = {}): TutorialBuildContext {
  return {
    industryId: 'retail',
    mods: [],
    visibleNav: [],
    isProMode: false,
    modMenuKeys: new Set(),
    ...overrides,
  }
}

describe('tutorial/catalog', () => {
  describe('getTrackMetas', () => {
    it('returns host tracks when no mods contribute tracks', () => {
      vi.mocked(collectModTutorialTracks).mockReturnValueOnce([])
      const result = getTrackMetas(makeCtx())
      expect(result).toHaveLength(2)
      expect(result[0].id).toBe('basic')
      expect(result[0].kind).toBe('curated')
      expect(result[0].recommended).toBe(true)
      expect(result[1].id).toBe('advanced')
      expect(result[1].kind).toBe('nav')
    })

    it('includes mod tracks after host tracks', () => {
      vi.mocked(collectModTutorialTracks).mockReturnValueOnce([
        {
          id: 'mod-track-1',
          title: 'Mod Track',
          summary: 'A mod track',
          description: 'desc',
          kind: 'mod',
          recommended: false,
          modId: 'mod-1',
        },
      ])
      const result = getTrackMetas(makeCtx())
      expect(result).toHaveLength(3)
      expect(result[2].id).toBe('mod-track-1')
      expect(result[2].kind).toBe('mod')
    })

    it('passes ctx mods and modMenuKeys to collectModTutorialTracks', () => {
      vi.mocked(collectModTutorialTracks).mockReturnValueOnce([])
      const ctx = makeCtx({ industryId: 'food', modMenuKeys: new Set(['mod-a']) })
      getTrackMetas(ctx)
      expect(collectModTutorialTracks).toHaveBeenCalledWith(ctx.mods, ctx.modMenuKeys)
    })
  })

  describe('getTrackLabel', () => {
    it('returns empty string for null trackId', () => {
      expect(getTrackLabel(null, makeCtx())).toBe('')
    })

    it('returns empty string for undefined trackId', () => {
      expect(getTrackLabel(undefined, makeCtx())).toBe('')
    })

    it('returns empty string for empty string trackId', () => {
      expect(getTrackLabel('', makeCtx())).toBe('')
    })

    it('returns title for known basic track', () => {
      vi.mocked(collectModTutorialTracks).mockReturnValueOnce([])
      expect(getTrackLabel('basic', makeCtx())).toBe('宿主入门')
    })

    it('returns title for known advanced track', () => {
      vi.mocked(collectModTutorialTracks).mockReturnValueOnce([])
      expect(getTrackLabel('advanced', makeCtx())).toBe('进阶教程')
    })

    it('returns the trackId itself for unknown track', () => {
      vi.mocked(collectModTutorialTracks).mockReturnValueOnce([])
      expect(getTrackLabel('unknown-track', makeCtx())).toBe('unknown-track')
    })

    it('returns title for mod-contributed track', () => {
      vi.mocked(collectModTutorialTracks).mockReturnValueOnce([
        {
          id: 'mod-x',
          title: 'Mod X Track',
          summary: '',
          description: '',
          kind: 'mod',
          recommended: false,
          modId: 'mod-x',
        },
      ])
      expect(getTrackLabel('mod-x', makeCtx())).toBe('Mod X Track')
    })
  })

  describe('formatAdvancedTrackHint', () => {
    it('returns default hint when visibleNames is empty', () => {
      expect(formatAdvancedTrackHint([])).toBe('按侧栏生成步骤。')
    })

    it('returns count hint when visibleNames has items', () => {
      expect(formatAdvancedTrackHint(['a', 'b', 'c'])).toBe('含 3 个菜单项。')
    })

    it('returns count hint for single item', () => {
      expect(formatAdvancedTrackHint(['only'])).toBe('含 1 个菜单项。')
    })

    it('accepts custom max parameter without changing output format', () => {
      expect(formatAdvancedTrackHint(['a', 'b'], 1)).toBe('含 2 个菜单项。')
    })
  })
})
