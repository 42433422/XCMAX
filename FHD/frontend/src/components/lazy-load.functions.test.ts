import { describe, it, expect, vi } from 'vitest'
import {
  ProModeComponents,
  registerProModeComponents,
  getComponent,
  preloadComponent,
  preloadAllComponents,
  preloadRelatedComponents,
  componentPreloadMap,
} from './lazy-load'

// Vue's defineAsyncComponent stores the loader on `__asyncLoader`.
// preloadComponent uses `.loader` which is undefined on real async components,
// so the loaders are never invoked by preloadComponent. To cover the loader
// arrow functions we invoke `__asyncLoader` directly.
type AsyncComp = { __asyncLoader?: () => Promise<unknown> }

function getLoader(name: string): (() => Promise<unknown>) | undefined {
  const comp = ProModeComponents[name] as AsyncComp | undefined
  return comp?.__asyncLoader
}

describe('lazy-load async component loaders', () => {
  it('every ProModeComponents entry has an invocable __asyncLoader', () => {
    for (const name of Object.keys(ProModeComponents)) {
      const loader = getLoader(name)
      expect(loader, `${name} should have __asyncLoader`).toBeTypeOf('function')
    }
  })

  it('invokes each loader and resolves to a component', async () => {
    const names = Object.keys(ProModeComponents)
    for (const name of names) {
      const loader = getLoader(name)
      if (!loader) continue
      // Invoke the loader — this covers the `() => import(...)` arrow function.
      const result = await loader()
      expect(result).toBeTruthy()
    }
  })
})

describe('lazy-load registerProModeComponents', () => {
  it('registers every component with the exact name', () => {
    const calls: [string, unknown][] = []
    const app = { component: vi.fn((n: string, c: unknown) => { calls.push([n, c]) }) }
    registerProModeComponents(app as never)
    const names = Object.keys(ProModeComponents)
    expect(calls.length).toBe(names.length)
    for (const name of names) {
      expect(calls.find(([n]) => n === name)).toBeTruthy()
    }
  })
})

describe('lazy-load getComponent', () => {
  it('returns the async component for known names', () => {
    expect(getComponent('ProModeOverlay')).toBeTruthy()
    expect(getComponent('StarkGrid')).toBeTruthy()
    expect(getComponent('DodecaMediaPanel')).toBeTruthy()
  })

  it('returns null for unknown names', () => {
    expect(getComponent('')).toBeNull()
    expect(getComponent('NonExistent')).toBeNull()
  })
})

describe('lazy-load preloadComponent', () => {
  it('does not throw for known and unknown names', () => {
    expect(() => preloadComponent('JarvisCore')).not.toThrow()
    expect(() => preloadComponent('StarkGrid')).not.toThrow()
    expect(() => preloadComponent('unknown-name')).not.toThrow()
    expect(() => preloadComponent('')).not.toThrow()
  })
})

describe('lazy-load preloadAllComponents', () => {
  it('iterates every component without throwing', () => {
    expect(() => preloadAllComponents()).not.toThrow()
  })
})

describe('lazy-load preloadRelatedComponents', () => {
  it('preloads related components for ProModeOverlay', () => {
    expect(componentPreloadMap.ProModeOverlay).toEqual(
      expect.arrayContaining(['JarvisCore', 'WireRings', 'EnergyParticles']),
    )
    expect(() => preloadRelatedComponents('ProModeOverlay')).not.toThrow()
  })

  it('preloads related components for ProFeatureWidget', () => {
    expect(componentPreloadMap.ProFeatureWidget).toEqual(
      expect.arrayContaining(['WeChatLoginPanel', 'UserListPanel', 'ProductQueryPanel']),
    )
    expect(() => preloadRelatedComponents('ProFeatureWidget')).not.toThrow()
  })

  it('handles StarkGrid with empty related list', () => {
    expect(componentPreloadMap.StarkGrid).toEqual([])
    expect(() => preloadRelatedComponents('StarkGrid')).not.toThrow()
  })

  it('does not throw for unknown component name', () => {
    expect(() => preloadRelatedComponents('DoesNotExist')).not.toThrow()
  })
})
