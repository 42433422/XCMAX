import { describe, it, expect, vi } from 'vitest'

const { mockReadBuildEdition } = vi.hoisted(() => ({
  mockReadBuildEdition: vi.fn(),
}))

vi.mock('@/constants/genericModPack', () => ({
  readBuildEdition: mockReadBuildEdition,
}))

import {
  buildTimeEdition,
  isMinimalBuild,
  isGenericBuild,
  MINIMAL_BUILD_MOD_IDS,
} from './buildEdition'

describe('buildEdition constants and functions', () => {
  describe('MINIMAL_BUILD_MOD_IDS', () => {
    it('is a non-empty array', () => {
      expect(MINIMAL_BUILD_MOD_IDS.length).toBeGreaterThan(0)
    })

    it('contains planner bridge mod id', () => {
      expect(MINIMAL_BUILD_MOD_IDS).toContain('xcagi-planner-bridge')
    })

    it('contains neuro bus bridge mod id', () => {
      expect(MINIMAL_BUILD_MOD_IDS).toContain('xcagi-neuro-bus-bridge')
    })

    it('contains office employee pack bridge mod id', () => {
      expect(MINIMAL_BUILD_MOD_IDS).toContain('xcagi-office-employee-pack-bridge')
    })
  })

  describe('buildTimeEdition', () => {
    it('returns the edition from readBuildEdition', () => {
      mockReadBuildEdition.mockReturnValue('full')
      expect(buildTimeEdition()).toBe('full')
    })

    it('returns minimal when readBuildEdition returns minimal', () => {
      mockReadBuildEdition.mockReturnValue('minimal')
      expect(buildTimeEdition()).toBe('minimal')
    })

    it('returns generic when readBuildEdition returns generic', () => {
      mockReadBuildEdition.mockReturnValue('generic')
      expect(buildTimeEdition()).toBe('generic')
    })
  })

  describe('isMinimalBuild', () => {
    it('returns true when edition is minimal', () => {
      mockReadBuildEdition.mockReturnValue('minimal')
      expect(isMinimalBuild()).toBe(true)
    })

    it('returns false when edition is full', () => {
      mockReadBuildEdition.mockReturnValue('full')
      expect(isMinimalBuild()).toBe(false)
    })

    it('returns false when edition is generic', () => {
      mockReadBuildEdition.mockReturnValue('generic')
      expect(isMinimalBuild()).toBe(false)
    })
  })

  describe('isGenericBuild', () => {
    it('returns true when edition is generic', () => {
      mockReadBuildEdition.mockReturnValue('generic')
      expect(isGenericBuild()).toBe(true)
    })

    it('returns false when edition is full', () => {
      mockReadBuildEdition.mockReturnValue('full')
      expect(isGenericBuild()).toBe(false)
    })

    it('returns false when edition is minimal', () => {
      mockReadBuildEdition.mockReturnValue('minimal')
      expect(isGenericBuild()).toBe(false)
    })
  })
})
