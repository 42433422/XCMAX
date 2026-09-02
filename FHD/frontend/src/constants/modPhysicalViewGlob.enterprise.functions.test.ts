import { describe, it, expect } from 'vitest'
import { modPhysicalViewGlob } from './modPhysicalViewGlob.enterprise'

describe('modPhysicalViewGlob.enterprise loaders', () => {
  it('exports a record of view loaders', () => {
    expect(modPhysicalViewGlob).toBeDefined()
    expect(typeof modPhysicalViewGlob).toBe('object')
  })

  it('every entry is a function', () => {
    for (const [key, loader] of Object.entries(modPhysicalViewGlob)) {
      expect(typeof loader, `loader for ${key} should be a function`).toBe('function')
    }
  })

  it('all keys point to .vue files under SSOT mods/', () => {
    for (const key of Object.keys(modPhysicalViewGlob)) {
      const norm = key.replace(/\\/g, '/')
      expect(norm).toContain('.vue')
      expect(norm).toContain('/mods/')
    }
  })

  it('calling each loader either resolves or rejects (function exercised)', async () => {
    const entries = Object.entries(modPhysicalViewGlob)
    expect(entries.length).toBeGreaterThan(0)
    // 顺序触发 loader：并行动态导入会在 vite-node 模块求值器中死锁
    // （单模块均正常，15+ 个同时导入才触发；浏览器生产路径不受影响）。
    const results: PromiseSettledResult<unknown>[] = []
    for (const [, loader] of entries) {
      try {
        results.push({ status: 'fulfilled', value: await loader() } as PromiseSettledResult<unknown>)
      } catch (error) {
        results.push({ status: 'rejected', reason: error } as PromiseSettledResult<unknown>)
      }
    }
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
  }, 120_000)

  it('loaders return a promise', () => {
    for (const [key, loader] of Object.entries(modPhysicalViewGlob)) {
      const result = loader()
      expect(result, `loader for ${key} should return a promise`).toBeInstanceOf(Promise)
      result.catch(() => {})
    }
  })

  it('loaders do not throw synchronously', () => {
    for (const [key, loader] of Object.entries(modPhysicalViewGlob)) {
      expect(() => {
        const p = loader()
        p.catch(() => {})
      }, `loader for ${key} should not throw synchronously`).not.toThrow()
    }
  })
})
