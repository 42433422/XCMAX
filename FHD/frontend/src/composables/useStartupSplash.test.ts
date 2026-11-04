import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { STARTUP_READY_TIMEOUT_MS, useStartupSplash } from './useStartupSplash'

function deferred() {
  let resolve!: () => void
  const promise = new Promise<void>((done) => { resolve = done })
  return { promise, resolve }
}

describe('startup readiness lifecycle', () => {
  let splash: ReturnType<typeof useStartupSplash>
  beforeEach(() => { vi.useFakeTimers(); splash = useStartupSplash() })
  afterEach(() => { splash.teardownOnUnmount(); vi.useRealTimers() })

  it('protects the workspace until the required work completes, without a minimum sleep', async () => {
    expect(splash.startupVisible.value).toBe(true)
    expect(splash.appReady.value).toBe(false)
    const task = deferred()
    const run = splash.runStartup(async (_current, stage) => {
      stage('正在准备关键资源…')
      await task.promise
    })
    expect(splash.startupStage.value).toBe('正在准备关键资源…')
    await vi.advanceTimersByTimeAsync(6000)
    expect(splash.appReady.value).toBe(false)
    expect(splash.startupVisible.value).toBe(true)
    task.resolve()
    await run
    expect(splash.appReady.value).toBe(true)
    expect(splash.startupVisible.value).toBe(false)
    expect(splash.startupError.value).toBe('')
  })

  it('keeps optional successful-attempt work current until the next attempt retires it', async () => {
    let current!: () => boolean
    let signal!: AbortSignal
    await splash.runStartup(async (check, _stage, attempt) => { current = check; signal = attempt })
    expect(splash.appReady.value).toBe(true)
    expect(current()).toBe(true)
    expect(signal.aborted).toBe(false)
    splash.cancelStartup()
    expect(current()).toBe(false)
    expect(signal.aborted).toBe(true)
  })

  it('keeps failures visible and allows a successful retry', async () => {
    await splash.runStartup(async () => { throw new Error('行业资料未就绪') })
    expect(splash.startupError.value).toContain('行业资料未就绪')
    expect(splash.appReady.value).toBe(false)
    expect(splash.startupVisible.value).toBe(true)
    const retry = deferred()
    const run = splash.runStartup(async () => { await retry.promise })
    expect(splash.startupError.value).toBe('')
    retry.resolve()
    await run
    expect(splash.appReady.value).toBe(true)
  })

  it('reports a timeout and retires the late successful result', async () => {
    const task = deferred()
    let isCurrent!: () => boolean
    let signal!: AbortSignal
    const run = splash.runStartup(async (current, _stage, attempt) => { isCurrent = current; signal = attempt; await task.promise })
    await vi.advanceTimersByTimeAsync(STARTUP_READY_TIMEOUT_MS)
    expect(splash.startupError.value).toBeTruthy()
    expect(splash.appReady.value).toBe(false)
    expect(splash.startupVisible.value).toBe(true)
    expect(isCurrent()).toBe(false)
    expect(signal.aborted).toBe(true)
    task.resolve()
    await run
    expect(splash.appReady.value).toBe(false)
    expect(splash.startupError.value).toBeTruthy()
  })

  it('does not let either an old success or error finish a newer retry', async () => {
    const first = deferred(), second = deferred(), third = deferred()
    let firstCurrent!: () => boolean
    let oldStage!: (text: string) => void
    const old = splash.runStartup(async (current, stage) => { firstCurrent = current; oldStage = stage; await first.promise })
    const middle = splash.runStartup(async () => { await second.promise; throw new Error('旧错误') })
    const latest = splash.runStartup(async (_current, stage) => { stage('最新一轮'); await third.promise })
    expect(firstCurrent()).toBe(false)
    oldStage('过期阶段')
    first.resolve(); second.resolve()
    await Promise.all([old, middle])
    expect(splash.startupStage.value).toBe('最新一轮')
    expect(splash.startupError.value).toBe('')
    expect(splash.appReady.value).toBe(false)
    third.resolve()
    await latest
    expect(splash.appReady.value).toBe(true)
  })

  it.each(['cancel', 'unmount'] as const)('retires pending work on %s', async (action) => {
    const task = deferred()
    let isCurrent!: () => boolean
    let signal!: AbortSignal
    const run = splash.runStartup(async (current, _stage, attempt) => { isCurrent = current; signal = attempt; await task.promise })
    if (action === 'cancel') splash.cancelStartup()
    else splash.teardownOnUnmount()
    expect(isCurrent()).toBe(false)
    expect(signal.aborted).toBe(true)
    task.resolve()
    await run
    await vi.advanceTimersByTimeAsync(STARTUP_READY_TIMEOUT_MS)
    expect(splash.appReady.value).toBe(false)
  })

  it('dismisses for a public route and retires a pending protected startup', async () => {
    const task = deferred()
    const run = splash.runStartup(async () => { await task.promise; throw new Error('retired') })
    splash.dismissStartupSplashImmediate()
    expect(splash.appReady.value).toBe(true)
    expect(splash.startupVisible.value).toBe(false)
    task.resolve()
    await run
    await vi.advanceTimersByTimeAsync(STARTUP_READY_TIMEOUT_MS)
    expect(splash.startupError.value).toBe('')
    expect(splash.appReady.value).toBe(true)
  })
})
