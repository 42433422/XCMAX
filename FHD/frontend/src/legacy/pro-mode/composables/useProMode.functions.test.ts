import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useProMode } from './useProMode'
import { useProModeStore } from '../stores/proMode'

describe('useProMode composable', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('returns reactive state from store', () => {
    const composable = useProMode()
    expect(composable.isActive.value).toBe(false)
    expect(composable.isTransitioning.value).toBe(false)
    expect(composable.isWorkMode.value).toBe(false)
    expect(composable.isMonitorMode.value).toBe(false)
    expect(composable.currentStage.value).toBe('idle')
    expect(composable.selectedCompany.value).toBeNull()
    expect(composable.selectedProduct.value).toBeNull()
    expect(composable.coreScale.value).toBe(1)
    expect(composable.orbitLayerScale.value).toBe(1)
  })

  it('toggleProMode delegates to store', () => {
    const composable = useProMode()
    const store = useProModeStore()
    const spy = vi.spyOn(store, 'toggleProMode')
    composable.toggleProMode()
    expect(spy).toHaveBeenCalledOnce()
  })

  it('enterProMode delegates to store', () => {
    const composable = useProMode()
    const store = useProModeStore()
    const spy = vi.spyOn(store, 'enterProMode')
    composable.enterProMode()
    expect(spy).toHaveBeenCalledOnce()
  })

  it('exitProMode delegates to store', () => {
    const composable = useProMode()
    const store = useProModeStore()
    const spy = vi.spyOn(store, 'exitProMode')
    composable.exitProMode()
    expect(spy).toHaveBeenCalledOnce()
  })

  it('enterWorkMode delegates to store', () => {
    const composable = useProMode()
    const store = useProModeStore()
    const spy = vi.spyOn(store, 'enterWorkMode')
    composable.enterWorkMode()
    expect(spy).toHaveBeenCalledOnce()
  })

  it('exitWorkMode delegates to store', () => {
    const composable = useProMode()
    const store = useProModeStore()
    const spy = vi.spyOn(store, 'exitWorkMode')
    composable.exitWorkMode()
    expect(spy).toHaveBeenCalledOnce()
  })

  it('enterMonitorMode delegates to store', () => {
    const composable = useProMode()
    const store = useProModeStore()
    const spy = vi.spyOn(store, 'enterMonitorMode')
    composable.enterMonitorMode()
    expect(spy).toHaveBeenCalledOnce()
  })

  it('exitMonitorMode delegates to store', () => {
    const composable = useProMode()
    const store = useProModeStore()
    const spy = vi.spyOn(store, 'exitMonitorMode')
    composable.exitMonitorMode()
    expect(spy).toHaveBeenCalledOnce()
  })

  it('setStage delegates to store with stage and payload', () => {
    const composable = useProMode()
    const store = useProModeStore()
    const spy = vi.spyOn(store, 'setStage')
    composable.setStage('companies', { company: { id: 1 } })
    expect(spy).toHaveBeenCalledWith('companies', { company: { id: 1 } })
  })

  it('setStage uses default empty payload', () => {
    const composable = useProMode()
    const store = useProModeStore()
    const spy = vi.spyOn(store, 'setStage')
    composable.setStage('idle')
    expect(spy).toHaveBeenCalledWith('idle', {})
  })

  it('resetTransientState delegates to store', () => {
    const composable = useProMode()
    const store = useProModeStore()
    const spy = vi.spyOn(store, 'resetTransientState')
    composable.resetTransientState()
    expect(spy).toHaveBeenCalledOnce()
  })

  it('stepBack delegates to store', () => {
    const composable = useProMode()
    const store = useProModeStore()
    const spy = vi.spyOn(store, 'stepBack')
    composable.stepBack()
    expect(spy).toHaveBeenCalledOnce()
  })

  it('computed values reflect store state changes', () => {
    const composable = useProMode()
    const store = useProModeStore()
    store.enterProMode()
    expect(composable.isActive.value).toBe(true)
    store.enterWorkMode()
    expect(composable.isWorkMode.value).toBe(true)
    store.setStage('companies')
    expect(composable.currentStage.value).toBe('companies')
  })
})
