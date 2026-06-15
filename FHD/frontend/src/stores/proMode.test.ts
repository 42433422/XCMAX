import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useProModeStore } from './proMode'

describe('useProModeStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('initializes with default state', () => {
    const store = useProModeStore()
    expect(store.isActive).toBe(false)
    expect(store.isTransitioning).toBe(false)
    expect(store.isWorkMode).toBe(false)
    expect(store.isMonitorMode).toBe(false)
    expect(store.currentStage).toBe('idle')
    expect(store.selectedCompany).toBeNull()
    expect(store.selectedProduct).toBeNull()
    expect(store.coreScale).toBe(1)
    expect(store.orbitLayerScale).toBe(1)
    expect(store.stageHistory).toEqual([])
  })

  it('enterProMode sets isActive and isTransitioning', () => {
    const store = useProModeStore()
    store.enterProMode()
    expect(store.isActive).toBe(true)
    expect(store.isTransitioning).toBe(true)
    vi.advanceTimersByTime(500)
    expect(store.isTransitioning).toBe(false)
  })

  it('exitProMode resets state', () => {
    const store = useProModeStore()
    store.enterProMode()
    store.exitProMode()
    expect(store.isActive).toBe(false)
    expect(store.isWorkMode).toBe(false)
    expect(store.isMonitorMode).toBe(false)
    expect(store.currentStage).toBe('idle')
    expect(store.selectedCompany).toBeNull()
    expect(store.selectedProduct).toBeNull()
    expect(store.coreScale).toBe(1)
    expect(store.orbitLayerScale).toBe(1)
    expect(store.stageHistory).toEqual([])
  })

  it('toggleProMode enters when inactive', () => {
    const store = useProModeStore()
    store.toggleProMode()
    expect(store.isActive).toBe(true)
  })

  it('toggleProMode exits when active', () => {
    const store = useProModeStore()
    store.enterProMode()
    store.toggleProMode()
    expect(store.isActive).toBe(false)
  })

  it('enterWorkMode sets isWorkMode', () => {
    const store = useProModeStore()
    store.enterWorkMode()
    expect(store.isWorkMode).toBe(true)
  })

  it('exitWorkMode clears isWorkMode', () => {
    const store = useProModeStore()
    store.enterWorkMode()
    store.exitWorkMode()
    expect(store.isWorkMode).toBe(false)
  })

  it('enterMonitorMode sets isMonitorMode', () => {
    const store = useProModeStore()
    store.enterMonitorMode()
    expect(store.isMonitorMode).toBe(true)
  })

  it('exitMonitorMode clears isMonitorMode', () => {
    const store = useProModeStore()
    store.enterMonitorMode()
    store.exitMonitorMode()
    expect(store.isMonitorMode).toBe(false)
  })

  it('setStage updates currentStage and scales', () => {
    const store = useProModeStore()
    store.setStage('companies')
    expect(store.currentStage).toBe('companies')
    expect(store.coreScale).toBe(0.82)
    expect(store.orbitLayerScale).toBe(0.86)
  })

  it('setStage companies_selected sets correct scales', () => {
    const store = useProModeStore()
    store.setStage('company_selected')
    expect(store.coreScale).toBe(0.68)
    expect(store.orbitLayerScale).toBe(0.74)
  })

  it('setStage product_selected sets correct scales', () => {
    const store = useProModeStore()
    store.setStage('product_selected')
    expect(store.coreScale).toBe(0.54)
    expect(store.orbitLayerScale).toBe(0.62)
  })

  it('setStage pushes to history when not idle and different', () => {
    const store = useProModeStore()
    // Initial stage is 'idle', setting 'companies' pushes 'idle' to history
    store.setStage('companies')
    expect(store.stageHistory).toEqual(['idle'])
    // Setting 'company_selected' pushes 'companies' to history
    store.setStage('company_selected')
    expect(store.stageHistory).toEqual(['idle', 'companies'])
  })

  it('setStage does not push same stage to history', () => {
    const store = useProModeStore()
    store.setStage('companies')
    store.setStage('companies')
    // Only the initial 'idle' was pushed when first setting 'companies'
    expect(store.stageHistory).toEqual(['idle'])
  })

  it('setStage limits history to 10 entries', () => {
    const store = useProModeStore()
    for (let i = 0; i < 12; i++) {
      store.setStage(`stage-${i}`)
    }
    expect(store.stageHistory.length).toBeLessThanOrEqual(10)
  })

  it('setStage sets company payload', () => {
    const store = useProModeStore()
    store.setStage('companies', { company: { name: 'TestCo' } })
    expect(store.selectedCompany).toEqual({ name: 'TestCo' })
  })

  it('setStage sets product payload', () => {
    const store = useProModeStore()
    store.setStage('product_selected', { product: { id: 1 } })
    expect(store.selectedProduct).toEqual({ id: 1 })
  })

  it('stepBack goes to previous stage', () => {
    const store = useProModeStore()
    store.setStage('companies')
    store.setStage('company_selected')
    store.stepBack()
    expect(store.currentStage).toBe('companies')
  })

  it('stepBack exits pro mode when no history', () => {
    const store = useProModeStore()
    store.enterProMode()
    store.stepBack()
    expect(store.isActive).toBe(false)
  })

  it('resetTransientState resets to idle', () => {
    const store = useProModeStore()
    store.setStage('companies', { company: { name: 'TestCo' } })
    store.resetTransientState()
    expect(store.currentStage).toBe('idle')
    expect(store.selectedCompany).toBeNull()
    expect(store.selectedProduct).toBeNull()
    expect(store.coreScale).toBe(1)
    expect(store.orbitLayerScale).toBe(1)
  })
})
