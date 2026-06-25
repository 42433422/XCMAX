import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useMarketAdminGraphAuth } from './useMarketAdminGraphAuth'

describe('useMarketAdminGraphAuth', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    // 重置模块级 currentMode
    const { setAdminMode } = useMarketAdminGraphAuth()
    setAdminMode()
  })

  it('initializes with admin mode', () => {
    const auth = useMarketAdminGraphAuth()
    expect(auth.currentMode.value).toBe('admin')
  })

  it('setClientMode switches currentMode to client', () => {
    const auth = useMarketAdminGraphAuth()
    auth.setClientMode()
    expect(auth.currentMode.value).toBe('client')
  })

  it('setAdminMode switches currentMode back to admin', () => {
    const auth = useMarketAdminGraphAuth()
    auth.setClientMode()
    expect(auth.currentMode.value).toBe('client')
    auth.setAdminMode()
    expect(auth.currentMode.value).toBe('admin')
  })

  it('shares state across multiple composable instances', () => {
    const a = useMarketAdminGraphAuth()
    const b = useMarketAdminGraphAuth()
    a.setClientMode()
    expect(b.currentMode.value).toBe('client')
  })

  it('toggling between modes repeatedly keeps consistent', () => {
    const auth = useMarketAdminGraphAuth()
    auth.setClientMode()
    auth.setClientMode()
    expect(auth.currentMode.value).toBe('client')
    auth.setAdminMode()
    expect(auth.currentMode.value).toBe('admin')
  })
})
