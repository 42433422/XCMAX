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

describe('lazy-load pro mode components', () => {
  it('ProModeComponents map exposes async components', () => {
    expect(Object.keys(ProModeComponents).length).toBeGreaterThan(10)
    expect(ProModeComponents.ProModeOverlay).toBeTruthy()
  })

  it('registerProModeComponents registers every entry on app', () => {
    const app = { component: vi.fn() }
    registerProModeComponents(app as never)
    expect(app.component).toHaveBeenCalledTimes(Object.keys(ProModeComponents).length)
    expect(app.component).toHaveBeenCalledWith('ProModeOverlay', expect.anything())
  })

  it('getComponent returns component or null', () => {
    expect(getComponent('JarvisCore')).toBeTruthy()
    expect(getComponent('NotARealComponent')).toBeNull()
  })

  it('preloadComponent and preloadAllComponents do not throw', () => {
    expect(() => preloadComponent('JarvisCore')).not.toThrow()
    expect(() => preloadComponent('missing')).not.toThrow()
    expect(() => preloadAllComponents()).not.toThrow()
  })

  it('preloadRelatedComponents uses preload map', () => {
    expect(componentPreloadMap.ProModeOverlay).toContain('JarvisCore')
    expect(() => preloadRelatedComponents('ProModeOverlay')).not.toThrow()
    expect(() => preloadRelatedComponents('unknown')).not.toThrow()
  })
})
