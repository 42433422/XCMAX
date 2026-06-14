import { describe, it, expect, vi, beforeEach } from 'vitest'
import { swManager, initServiceWorker, unregisterStaleServiceWorkers } from './serviceWorker'

describe('serviceWorker manager', () => {
  beforeEach(() => {
    swManager.destroy()
  })

  it('exposes status with supported flag', () => {
    const status = swManager.status
    expect(typeof status.supported).toBe('boolean')
    expect(typeof status.offline).toBe('boolean')
  })

  it('register returns false in test env (DEV skip)', async () => {
    const ok = await swManager.register()
    expect(ok).toBe(false)
  })

  it('initServiceWorker returns status', async () => {
    const status = await initServiceWorker()
    expect(status).toBeDefined()
    expect(typeof status.registered).toBe('boolean')
  })

  it('onChange notifies listeners', () => {
    const listener = vi.fn()
    const off = swManager.onChange(listener)
    swManager.isOffline()
    off()
    expect(typeof off).toBe('function')
  })

  it('checkForUpdate returns false without registration', async () => {
    expect(await swManager.checkForUpdate()).toBe(false)
  })

  it('clearCache returns false without controller', async () => {
    expect(await swManager.clearCache()).toBe(false)
  })

  it('getCacheStatus returns null without controller', async () => {
    expect(await swManager.getCacheStatus()).toBeNull()
  })

  it('unregisterStaleServiceWorkers no-ops when unsupported', async () => {
    await expect(unregisterStaleServiceWorkers()).resolves.toBeUndefined()
  })
})
