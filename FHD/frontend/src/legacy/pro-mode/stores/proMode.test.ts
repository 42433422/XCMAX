import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useProModeStore } from '@/legacy/pro-mode/stores/proMode'

describe('useProModeStore', () => {
  let store: ReturnType<typeof useProModeStore>

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useProModeStore()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('initializes with default state', () => {
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
    store.enterProMode()
    expect(store.isActive).toBe(true)
    expect(store.isTransitioning).toBe(true)
  })

  it('enterProMode clears isTransitioning after timeout', () => {
    store.enterProMode()
    vi.advanceTimersByTime(500)
    expect(store.isTransitioning).toBe(false)
  })

  it('exitProMode resets all state', () => {
    store.enterProMode()
    store.enterWorkMode()
    store.enterMonitorMode()
    store.setStage('companies', { company: { id: 1 } })

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

  it('exitProMode clears isTransitioning after timeout', () => {
    store.exitProMode()
    expect(store.isTransitioning).toBe(true)
    vi.advanceTimersByTime(500)
    expect(store.isTransitioning).toBe(false)
  })

  it('toggleProMode enters when inactive', () => {
    store.toggleProMode()
    expect(store.isActive).toBe(true)
  })

  it('toggleProMode exits when active', () => {
    store.enterProMode()
    vi.advanceTimersByTime(500)
    store.toggleProMode()
    expect(store.isActive).toBe(false)
  })

  it('enterWorkMode sets isWorkMode', () => {
    store.enterWorkMode()
    expect(store.isWorkMode).toBe(true)
  })

  it('exitWorkMode clears isWorkMode', () => {
    store.enterWorkMode()
    store.exitWorkMode()
    expect(store.isWorkMode).toBe(false)
  })

  it('enterMonitorMode sets isMonitorMode', () => {
    store.enterMonitorMode()
    expect(store.isMonitorMode).toBe(true)
  })

  it('exitMonitorMode clears isMonitorMode', () => {
    store.enterMonitorMode()
    store.exitMonitorMode()
    expect(store.isMonitorMode).toBe(false)
  })

  it('setStage pushes to history when stage changes', () => {
    store.setStage('companies')
    expect(store.currentStage).toBe('companies')
    expect(store.stageHistory).toEqual(['idle'])
  })

  it('setStage does not push idle to history', () => {
    store.setStage('idle')
    expect(store.stageHistory).toEqual([])
  })

  it('setStage limits history to 10 entries', () => {
    for (let i = 0; i < 12; i++) {
      store.setStage(`stage_${i}`)
    }
    expect(store.stageHistory.length).toBeLessThanOrEqual(10)
  })

  it('setStage sets coreScale and orbitLayerScale for companies', () => {
    store.setStage('companies')
    expect(store.coreScale).toBe(0.82)
    expect(store.orbitLayerScale).toBe(0.86)
  })

  it('setStage sets coreScale and orbitLayerScale for company_selected', () => {
    store.setStage('company_selected')
    expect(store.coreScale).toBe(0.68)
    expect(store.orbitLayerScale).toBe(0.74)
  })

  it('setStage sets coreScale and orbitLayerScale for product_selected', () => {
    store.setStage('product_selected')
    expect(store.coreScale).toBe(0.54)
    expect(store.orbitLayerScale).toBe(0.62)
  })

  it('setStage sets payload company', () => {
    const company = { id: 1, name: 'Test' }
    store.setStage('companies', { company })
    expect(store.selectedCompany).toEqual(company)
  })

  it('setStage sets payload product', () => {
    const product = { id: 1, name: 'Product' }
    store.setStage('product_selected', { product })
    expect(store.selectedProduct).toEqual(product)
  })

  it('stepBack goes to previous stage', () => {
    store.setStage('companies')
    store.setStage('company_selected')
    store.stepBack()
    expect(store.currentStage).toBe('companies')
  })

  it('stepBack exits pro mode when no history', () => {
    store.enterProMode()
    store.stepBack()
    expect(store.isActive).toBe(false)
  })

  it('resetTransientState resets to idle', () => {
    store.setStage('companies', { company: { id: 1 } })
    store.setStage('company_selected', { product: { id: 2 } })
    store.resetTransientState()
    expect(store.currentStage).toBe('idle')
    expect(store.selectedCompany).toBeNull()
    expect(store.selectedProduct).toBeNull()
    expect(store.coreScale).toBe(1)
    expect(store.orbitLayerScale).toBe(1)
  })
})
