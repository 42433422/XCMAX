import { afterEach, describe, expect, it, vi } from 'vitest'
import { activateWaitingWorker } from './serviceWorker'

function fixture() {
  const old = { postMessage: vi.fn() } as unknown as ServiceWorker
  const candidate = { postMessage: vi.fn() } as unknown as ServiceWorker
  const events = Object.assign(new EventTarget(), { controller: old })
  const container = events as unknown as ServiceWorkerContainer
  const activate = (worker: ServiceWorker) => {
    events.controller = worker
    events.dispatchEvent(new Event('controllerchange'))
  }
  return { old, candidate, container, activate }
}

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks() })

describe('release candidate service worker handshake', () => {
  it('listens before posting and does not send activation to the old controller', async () => {
    const { old, candidate, container, activate } = fixture()
    vi.mocked(candidate.postMessage).mockImplementation(() => activate(candidate))
    await expect(activateWaitingWorker(container, candidate)).resolves.toBe(true)
    expect(candidate.postMessage).toHaveBeenCalledExactlyOnceWith({ type: 'SKIP_WAITING' })
    expect(old.postMessage).not.toHaveBeenCalled()
  })

  it('rejects a different controller and times out without reporting activation', async () => {
    vi.useFakeTimers()
    const { candidate, container, activate } = fixture()
    const remove = vi.spyOn(container, 'removeEventListener')
    const promise = activateWaitingWorker(container, candidate, 100)
    activate({ postMessage: vi.fn() } as unknown as ServiceWorker)
    await vi.advanceTimersByTimeAsync(100)
    await expect(promise).resolves.toBe(false)
    expect(remove).toHaveBeenCalledOnce()
  })

  it('does not send a stale activation message when the candidate already controls the page', async () => {
    const { candidate, container, activate } = fixture()
    activate(candidate)
    await expect(activateWaitingWorker(container, candidate)).resolves.toBe(true)
    expect(candidate.postMessage).not.toHaveBeenCalled()
  })

  it('does not report success after an activation message failure', async () => {
    const { candidate, container } = fixture()
    vi.mocked(candidate.postMessage).mockImplementation(() => { throw new Error('retired candidate') })
    await expect(activateWaitingWorker(container, candidate)).resolves.toBe(false)
  })
})
