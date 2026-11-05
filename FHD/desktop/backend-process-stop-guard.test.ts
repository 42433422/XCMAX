import { afterEach, describe, expect, it, vi } from 'vitest'
import { clearBackendStopRequest, markBackendStopRequested, shouldRestartBackendAfterExit } from './backend-process-stop-guard.js'

afterEach(() => vi.useRealTimers())

describe('Windows updater backend stop lifecycle', () => {
  it('does not count or schedule restart for an intentional stop, while ordinary crashes still restart', () => {
    vi.useFakeTimers()
    const intentionalChild = {}
    let restartCount = 0
    let scheduledRestarts = 0
    const onExit = (child: object) => {
      if (!shouldRestartBackendAfterExit(child, false, false)) return
      restartCount += 1
      setTimeout(() => { scheduledRestarts += 1 }, 1500)
    }

    markBackendStopRequested(intentionalChild)
    onExit(intentionalChild)
    vi.advanceTimersByTime(2000)
    expect(restartCount).toBe(0)
    expect(scheduledRestarts).toBe(0)

    const crashedChild = {}
    onExit(crashedChild)
    expect(restartCount).toBe(1)
    vi.advanceTimersByTime(1500)
    expect(scheduledRestarts).toBe(1)

    clearBackendStopRequest(intentionalChild)
    expect(shouldRestartBackendAfterExit(intentionalChild, false, false)).toBe(true)
    expect(shouldRestartBackendAfterExit({}, true, false)).toBe(false)
    expect(shouldRestartBackendAfterExit({}, false, true)).toBe(false)
  })
})
