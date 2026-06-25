import { describe, it, expect, beforeEach, vi } from 'vitest'

const { mockModPhysicalViewGlob, mockHostViewGlob } = vi.hoisted(() => ({
  mockModPhysicalViewGlob: {} as Record<string, () => Promise<unknown>>,
  mockHostViewGlob: {} as Record<string, () => Promise<unknown>>,
}))

vi.mock('@/constants/modPhysicalViewGlob', () => ({
  modPhysicalViewGlob: mockModPhysicalViewGlob,
}))

vi.mock('@/constants/hostViewGlob', () => ({
  hostViewGlob: mockHostViewGlob,
}))

import {
  modView,
  hostView,
  resolveModPageView,
  listPhysicalViewGlobKeys,
  physicalViewExists,
} from './modViews'

describe('modViews', () => {
  beforeEach(() => {
    for (const k of Object.keys(mockModPhysicalViewGlob)) {
      delete mockModPhysicalViewGlob[k]
    }
    for (const k of Object.keys(mockHostViewGlob)) {
      delete mockHostViewGlob[k]
    }
  })

  describe('modView', () => {
    it('returns loader from modPhysicalViewGlob when key matches mods/<id>/frontend/views/<file>', async () => {
      const loader = async () => ({ default: { template: '<div>mod</div>' } })
      mockModPhysicalViewGlob['./mods/m1/frontend/views/ProductsView.vue'] = loader

      const result = modView('m1', 'ProductsView.vue')
      expect(result).toBe(loader)

      const mod = await result()
      expect((mod as { default: unknown }).default).toEqual({ template: '<div>mod</div>' })
    })

    it('returns loader when key matches mods-admin-runtime/<id>/frontend/views/<file>', async () => {
      const loader = async () => ({ default: { template: '<div>admin</div>' } })
      mockModPhysicalViewGlob['./mods-admin-runtime/m2/frontend/views/SettingsView.vue'] = loader

      const result = modView('m2', 'SettingsView.vue')
      expect(result).toBe(loader)
    })

    it('normalizes backslashes in glob keys when matching', async () => {
      const loader = async () => ({ default: {} })
      mockModPhysicalViewGlob['.\\mods\\m3\\frontend\\views\\Foo.vue'] = loader

      const result = modView('m3', 'Foo.vue')
      expect(result).toBe(loader)
    })

    it('falls back to hostView when mod key is missing', async () => {
      const hostLoader = async () => ({ default: { template: '<div>host</div>' } })
      mockHostViewGlob['./views/FooView.vue'] = hostLoader

      const result = modView('unknown-mod', 'FooView.vue')
      expect(result).toBe(hostLoader)
    })

    it('falls back to hostView when mod key is missing (with backslash host key)', async () => {
      const hostLoader = async () => ({ default: {} })
      mockHostViewGlob['.\\views\\BarView.vue'] = hostLoader

      const result = modView('unknown-mod', 'BarView.vue')
      expect(result).toBe(hostLoader)
    })

    it('returns fallback div loader when neither mod nor host key matches', async () => {
      const result = modView('unknown-mod', 'MissingView.vue')
      const mod = (await result()) as { default: { template: string } }
      expect(mod.default.template).toBe('<div />')
    })

    it('prefers mod view over host view when both exist', () => {
      const modLoader = async () => ({ default: { template: '<div>mod</div>' } })
      const hostLoader = async () => ({ default: { template: '<div>host</div>' } })
      mockModPhysicalViewGlob['./mods/m1/frontend/views/Dual.vue'] = modLoader
      mockHostViewGlob['./views/Dual.vue'] = hostLoader

      const result = modView('m1', 'Dual.vue')
      expect(result).toBe(modLoader)
    })

    it('matches first mod key when multiple match suffix', () => {
      const loader1 = async () => ({ default: {} })
      const loader2 = async () => ({ default: {} })
      mockModPhysicalViewGlob['./mods/m1/frontend/views/Same.vue'] = loader1
      mockModPhysicalViewGlob['./mods-admin-runtime/m1/frontend/views/Same.vue'] = loader2

      const result = modView('m1', 'Same.vue')
      expect(result).toBe(loader1)
    })

    it('handles empty modId', () => {
      const loader = async () => ({ default: {} })
      mockModPhysicalViewGlob['./mods//frontend/views/X.vue'] = loader

      const result = modView('', 'X.vue')
      expect(result).toBe(loader)
    })

    it('handles empty viewFile', () => {
      const loader = async () => ({ default: {} })
      mockModPhysicalViewGlob['./mods/m1/frontend/views/'] = loader

      const result = modView('m1', '')
      expect(result).toBe(loader)
    })

    it('returns a function (ViewLoader) in all cases', () => {
      const result1 = modView('m1', 'X.vue')
      const result2 = modView('unknown', 'Missing.vue')
      expect(typeof result1).toBe('function')
      expect(typeof result2).toBe('function')
    })
  })

  describe('hostView', () => {
    it('returns loader from hostViewGlob when key matches views/<file>', async () => {
      const loader = async () => ({ default: { template: '<div>host</div>' } })
      mockHostViewGlob['./views/SettingsView.vue'] = loader

      const result = hostView('SettingsView.vue')
      expect(result).toBe(loader)
    })

    it('normalizes backslashes in host keys', async () => {
      const loader = async () => ({ default: {} })
      mockHostViewGlob['.\\views\\BackslashView.vue'] = loader

      const result = hostView('BackslashView.vue')
      expect(result).toBe(loader)
    })

    it('returns fallback div loader when host key is missing', async () => {
      const result = hostView('MissingView.vue')
      const mod = (await result()) as { default: { template: string } }
      expect(mod.default.template).toBe('<div />')
    })

    it('matches first host key when multiple match suffix', () => {
      const loader1 = async () => ({ default: {} })
      const loader2 = async () => ({ default: {} })
      mockHostViewGlob['./views/Dup.vue'] = loader1
      mockHostViewGlob['./other/views/Dup.vue'] = loader2

      const result = hostView('Dup.vue')
      expect(result).toBe(loader1)
    })

    it('handles empty viewFile', () => {
      const loader = async () => ({ default: {} })
      mockHostViewGlob['./views/'] = loader

      const result = hostView('')
      expect(result).toBe(loader)
    })

    it('returns a function (ViewLoader) when key missing', () => {
      const result = hostView('MissingView.vue')
      expect(typeof result).toBe('function')
    })
  })

  describe('resolveModPageView', () => {
    it('returns modView when physical=true (default)', () => {
      const modLoader = async () => ({ default: {} })
      mockModPhysicalViewGlob['./mods/m1/frontend/views/Products.vue'] = modLoader

      const result = resolveModPageView('m1', 'Products.vue')
      expect(result).toBe(modLoader)
    })

    it('returns modView when physical=true explicitly', () => {
      const modLoader = async () => ({ default: {} })
      mockModPhysicalViewGlob['./mods/m1/frontend/views/Products.vue'] = modLoader

      const result = resolveModPageView('m1', 'Products.vue', true)
      expect(result).toBe(modLoader)
    })

    it('returns hostView when physical=false', () => {
      const hostLoader = async () => ({ default: {} })
      mockHostViewGlob['./views/Products.vue'] = hostLoader

      const result = resolveModPageView('m1', 'Products.vue', false)
      expect(result).toBe(hostLoader)
    })

    it('returns fallback when physical=true but mod missing and host missing', async () => {
      const result = resolveModPageView('unknown', 'Missing.vue', true)
      const mod = (await result()) as { default: { template: string } }
      expect(mod.default.template).toBe('<div />')
    })

    it('returns fallback when physical=false and host missing', async () => {
      const result = resolveModPageView('unknown', 'Missing.vue', false)
      const mod = (await result()) as { default: { template: string } }
      expect(mod.default.template).toBe('<div />')
    })

    it('returns host fallback when physical=true but mod missing', () => {
      const hostLoader = async () => ({ default: {} })
      mockHostViewGlob['./views/Fallback.vue'] = hostLoader

      const result = resolveModPageView('unknown', 'Fallback.vue', true)
      expect(result).toBe(hostLoader)
    })
  })

  describe('listPhysicalViewGlobKeys', () => {
    it('returns empty array when no keys', () => {
      expect(listPhysicalViewGlobKeys()).toEqual([])
    })

    it('returns all keys from modPhysicalViewGlob', () => {
      mockModPhysicalViewGlob['./mods/m1/frontend/views/A.vue'] = async () => ({ default: {} })
      mockModPhysicalViewGlob['./mods/m2/frontend/views/B.vue'] = async () => ({ default: {} })

      const keys = listPhysicalViewGlobKeys()
      expect(keys).toHaveLength(2)
      expect(keys).toContain('./mods/m1/frontend/views/A.vue')
      expect(keys).toContain('./mods/m2/frontend/views/B.vue')
    })

    it('returns keys in original form (with backslashes if present)', () => {
      mockModPhysicalViewGlob['./mods/m1/frontend/views/A.vue'] = async () => ({ default: {} })
      mockModPhysicalViewGlob['.\\mods\\m2\\frontend\\views\\B.vue'] = async () => ({ default: {} })

      const keys = listPhysicalViewGlobKeys()
      expect(keys).toContain('.\\mods\\m2\\frontend\\views\\B.vue')
    })
  })

  describe('physicalViewExists', () => {
    it('returns true when mod view exists in mods/<id>/frontend/views/<file>', () => {
      mockModPhysicalViewGlob['./mods/m1/frontend/views/Products.vue'] = async () => ({ default: {} })

      expect(physicalViewExists('m1', 'Products.vue')).toBe(true)
    })

    it('returns true when mod view exists in mods-admin-runtime/<id>/frontend/views/<file>', () => {
      mockModPhysicalViewGlob['./mods-admin-runtime/m2/frontend/views/Settings.vue'] = async () => ({ default: {} })

      expect(physicalViewExists('m2', 'Settings.vue')).toBe(true)
    })

    it('returns false when mod view does not exist', () => {
      expect(physicalViewExists('unknown', 'Missing.vue')).toBe(false)
    })

    it('returns false when only host view exists', () => {
      mockHostViewGlob['./views/OnlyHost.vue'] = async () => ({ default: {} })

      expect(physicalViewExists('m1', 'OnlyHost.vue')).toBe(false)
    })

    it('normalizes backslashes when checking existence', () => {
      mockModPhysicalViewGlob['.\\mods\\m3\\frontend\\views\\Backslash.vue'] = async () => ({ default: {} })

      expect(physicalViewExists('m3', 'Backslash.vue')).toBe(true)
    })

    it('handles empty modId', () => {
      mockModPhysicalViewGlob['./mods//frontend/views/X.vue'] = async () => ({ default: {} })
      expect(physicalViewExists('', 'X.vue')).toBe(true)
    })

    it('handles empty viewFile', () => {
      mockModPhysicalViewGlob['./mods/m1/frontend/views/'] = async () => ({ default: {} })
      expect(physicalViewExists('m1', '')).toBe(true)
    })

    it('does not match partial mod id', () => {
      mockModPhysicalViewGlob['./mods/m1extra/frontend/views/X.vue'] = async () => ({ default: {} })

      expect(physicalViewExists('m1', 'X.vue')).toBe(false)
    })

    it('does not match partial viewFile', () => {
      mockModPhysicalViewGlob['./mods/m1/frontend/views/ProductsViewExtra.vue'] = async () => ({ default: {} })

      expect(physicalViewExists('m1', 'ProductsView.vue')).toBe(false)
    })
  })
})
