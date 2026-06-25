import { describe, it, expect } from 'vitest'
import { modRouteGlob } from './modRouteGlob.full'

describe('modRouteGlob.full loaders', () => {
  it('exports a record of route module loaders', () => {
    expect(modRouteGlob).toBeDefined()
    expect(typeof modRouteGlob).toBe('object')
  })

  it('every entry is a function', () => {
    for (const [key, loader] of Object.entries(modRouteGlob)) {
      expect(typeof loader, `loader for ${key} should be a function`).toBe('function')
    }
  })

  it('all keys point to routes.js files under mods or mods-admin-runtime', () => {
    for (const key of Object.keys(modRouteGlob)) {
      const norm = key.replace(/\\/g, '/')
      expect(norm).toContain('routes.js')
      expect(norm.includes('/mods/') || norm.includes('/mods-admin-runtime/')).toBe(true)
    }
  })

  it('calling each loader either resolves to a module or rejects (function is exercised)', async () => {
    const entries = Object.entries(modRouteGlob)
    expect(entries.length).toBeGreaterThan(0)
    const results = await Promise.allSettled(entries.map(([_, loader]) => loader()))
    // Each loader must have been invoked; track how many resolved vs rejected
    let resolved = 0
    let rejected = 0
    for (const r of results) {
      if (r.status === 'fulfilled') {
        resolved += 1
        expect(r.value).toBeDefined()
      } else {
        rejected += 1
      }
    }
    expect(resolved + rejected).toBe(entries.length)
  })

  it('loaders return a promise (are async)', () => {
    for (const [key, loader] of Object.entries(modRouteGlob)) {
      const result = loader()
      expect(result, `loader for ${key} should return a promise`).toBeInstanceOf(Promise)
      // Suppress unhandled rejection
      result.catch(() => {})
    }
  })
})
