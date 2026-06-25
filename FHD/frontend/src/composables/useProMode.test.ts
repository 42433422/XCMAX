import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

// useProMode 是从 legacy/pro-mode/composables/useProMode 重新导出
import { useProMode } from './useProMode'

describe('useProMode (re-export from legacy)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('returns expected API shape', () => {
    const pro = useProMode()
    expect(typeof pro.isActive.value).toBe('boolean')
    expect(typeof pro.isTransitioning.value).toBe('boolean')
    expect(typeof pro.isWorkMode.value).toBe('boolean')
    expect(typeof pro.isMonitorMode.value).toBe('boolean')
    expect(typeof pro.currentStage.value).toBe('string')
    expect(pro.selectedCompany.value).toBeNull()
    expect(pro.selectedProduct.value).toBeNull()
    expect(typeof pro.coreScale.value).toBe('number')
    expect(typeof pro.orbitLayerScale.value).toBe('number')
    expect(typeof pro.toggleProMode).toBe('function')
    expect(typeof pro.enterProMode).toBe('function')
    expect(typeof pro.exitProMode).toBe('function')
    expect(typeof pro.enterWorkMode).toBe('function')
    expect(typeof pro.exitWorkMode).toBe('function')
    expect(typeof pro.enterMonitorMode).toBe('function')
    expect(typeof pro.exitMonitorMode).toBe('function')
    expect(typeof pro.setStage).toBe('function')
    expect(typeof pro.resetTransientState).toBe('function')
    expect(typeof pro.stepBack).toBe('function')
  })

  it('initializes with default state', () => {
    const pro = useProMode()
    expect(pro.isActive.value).toBe(false)
    expect(pro.isTransitioning.value).toBe(false)
    expect(pro.isWorkMode.value).toBe(false)
    expect(pro.isMonitorMode.value).toBe(false)
    expect(pro.currentStage.value).toBe('idle')
    expect(pro.coreScale.value).toBe(1)
    expect(pro.orbitLayerScale.value).toBe(1)
  })

  it('enterProMode activates pro mode', () => {
    const pro = useProMode()
    pro.enterProMode()
    expect(pro.isActive.value).toBe(true)
    expect(pro.isTransitioning.value).toBe(true)
  })

  it('exitProMode deactivates pro mode and resets state', () => {
    const pro = useProMode()
    pro.enterProMode()
    pro.exitProMode()
    expect(pro.isActive.value).toBe(false)
    expect(pro.isWorkMode.value).toBe(false)
    expect(pro.isMonitorMode.value).toBe(false)
    expect(pro.currentStage.value).toBe('idle')
    expect(pro.selectedCompany.value).toBeNull()
    expect(pro.selectedProduct.value).toBeNull()
    expect(pro.coreScale.value).toBe(1)
    expect(pro.orbitLayerScale.value).toBe(1)
  })

  it('toggleProMode toggles between active and inactive', () => {
    const pro = useProMode()
    expect(pro.isActive.value).toBe(false)
    pro.toggleProMode()
    expect(pro.isActive.value).toBe(true)
    pro.toggleProMode()
    expect(pro.isActive.value).toBe(false)
  })

  it('enterWorkMode / exitWorkMode toggles isWorkMode', () => {
    const pro = useProMode()
    pro.enterWorkMode()
    expect(pro.isWorkMode.value).toBe(true)
    pro.exitWorkMode()
    expect(pro.isWorkMode.value).toBe(false)
  })

  it('enterMonitorMode / exitMonitorMode toggles isMonitorMode', () => {
    const pro = useProMode()
    pro.enterMonitorMode()
    expect(pro.isMonitorMode.value).toBe(true)
    pro.exitMonitorMode()
    expect(pro.isMonitorMode.value).toBe(false)
  })

  it('setStage updates currentStage and scales', () => {
    const pro = useProMode()
    pro.setStage('companies')
    expect(pro.currentStage.value).toBe('companies')
    expect(pro.coreScale.value).toBe(0.82)
    expect(pro.orbitLayerScale.value).toBe(0.86)
  })

  it('setStage with payload sets selectedCompany', () => {
    const pro = useProMode()
    pro.setStage('company_selected', { company: { id: 1, name: 'ACME' } })
    expect(pro.selectedCompany.value).toEqual({ id: 1, name: 'ACME' })
  })

  it('setStage with payload sets selectedProduct', () => {
    const pro = useProMode()
    pro.setStage('product_selected', { product: { id: 9, name: 'Widget' } })
    expect(pro.selectedProduct.value).toEqual({ id: 9, name: 'Widget' })
  })

  it('resetTransientState resets to idle', () => {
    const pro = useProMode()
    pro.setStage('companies', { company: { id: 1 } })
    pro.resetTransientState()
    expect(pro.currentStage.value).toBe('idle')
    expect(pro.selectedCompany.value).toBeNull()
    expect(pro.selectedProduct.value).toBeNull()
    expect(pro.coreScale.value).toBe(1)
    expect(pro.orbitLayerScale.value).toBe(1)
  })

  it('stepBack with empty history exits pro mode', () => {
    const pro = useProMode()
    pro.enterProMode()
    pro.stepBack()
    expect(pro.isActive.value).toBe(false)
  })

  it('stepBack with history returns to previous stage', () => {
    const pro = useProMode()
    pro.setStage('companies')
    pro.setStage('company_selected')
    expect(pro.currentStage.value).toBe('company_selected')
    pro.stepBack()
    expect(pro.currentStage.value).toBe('companies')
  })
})
