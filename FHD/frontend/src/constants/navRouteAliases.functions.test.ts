import { describe, it, expect } from 'vitest'
import { SIDEBAR_ROUTE_ALIASES, resolveNavRouteName } from './navRouteAliases'

describe('navRouteAliases constants and functions', () => {
  describe('SIDEBAR_ROUTE_ALIASES', () => {
    it('is a non-empty record', () => {
      expect(typeof SIDEBAR_ROUTE_ALIASES).toBe('object')
      expect(Object.keys(SIDEBAR_ROUTE_ALIASES).length).toBeGreaterThan(0)
    })

    it('maps approval-hub to approval-workspace', () => {
      expect(SIDEBAR_ROUTE_ALIASES['approval-hub']).toBe('approval-workspace')
    })

    it('maps mod-approval-hub to approval-workspace', () => {
      expect(SIDEBAR_ROUTE_ALIASES['mod-approval-hub']).toBe('approval-workspace')
    })
  })

  describe('resolveNavRouteName', () => {
    it('returns aliased route name for known view key', () => {
      expect(resolveNavRouteName('approval-hub')).toBe('approval-workspace')
    })

    it('returns aliased route name for mod-approval-hub', () => {
      expect(resolveNavRouteName('mod-approval-hub')).toBe('approval-workspace')
    })

    it('returns the view key itself for unknown key without modPath', () => {
      expect(resolveNavRouteName('unknown-key')).toBe('unknown-key')
    })

    it('returns empty string for empty view key', () => {
      expect(resolveNavRouteName('')).toBe('')
    })

    it('returns empty string for whitespace-only view key', () => {
      expect(resolveNavRouteName('   ')).toBe('')
    })

    it('trims whitespace from view key before lookup', () => {
      expect(resolveNavRouteName('  approval-hub  ')).toBe('approval-workspace')
    })

    it('returns approval-workspace for mod- key with approval-hub/workspace path', () => {
      expect(resolveNavRouteName('mod-something', '/approval-hub/workspace')).toBe('approval-workspace')
    })

    it('returns last path segment for mod- key with a path', () => {
      expect(resolveNavRouteName('mod-custom', '/some/deep/path/segment')).toBe('segment')
    })

    it('returns the mod- key itself when modPath is empty', () => {
      expect(resolveNavRouteName('mod-custom', '')).toBe('mod-custom')
    })

    it('returns the mod- key itself when modPath is undefined', () => {
      expect(resolveNavRouteName('mod-custom')).toBe('mod-custom')
    })

    it('strips query string from modPath before extracting segment', () => {
      expect(resolveNavRouteName('mod-x', '/path/seg?foo=bar')).toBe('seg')
    })

    it('strips hash from modPath before extracting segment', () => {
      expect(resolveNavRouteName('mod-x', '/path/seg#anchor')).toBe('seg')
    })

    it('returns mod- key when path has no segments after split', () => {
      expect(resolveNavRouteName('mod-x', '/')).toBe('mod-x')
    })

    it('returns mod- key when path is only slashes', () => {
      expect(resolveNavRouteName('mod-x', '///')).toBe('mod-x')
    })

    it('returns null/undefined input as empty string', () => {
      expect(resolveNavRouteName(null as unknown as string)).toBe('')
    })
  })
})
