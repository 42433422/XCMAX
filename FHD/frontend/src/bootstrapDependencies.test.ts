import { describe, expect, it } from 'vitest'
import { waitForInitialBootstrapDependencies } from './bootstrapDependencies'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

describe('initial frontend bootstrap dependencies', () => {
  it.each(['route', 'i18n'])('starts both dependencies and waits when %s finishes first', async (first) => {
    const started: string[] = []
    const i18n = deferred<{ locale: string }>()
    const route = deferred<void>()
    const mounted = waitForInitialBootstrapDependencies(
      () => { started.push('i18n'); return i18n.promise },
      () => { started.push('route'); return route.promise },
    )
    let resolved = false
    void mounted.then(() => { resolved = true })

    expect(started).toEqual(['i18n', 'route'])
    if (first === 'route') route.resolve()
    else i18n.resolve({ locale: 'zh-CN' })
    await Promise.resolve()
    expect(resolved).toBe(false)

    if (first === 'route') i18n.resolve({ locale: 'zh-CN' })
    else route.resolve()
    await expect(mounted).resolves.toEqual({ locale: 'zh-CN' })
  })

  it('still returns i18n when the first navigation fails so the shell can show the error', async () => {
    const result = waitForInitialBootstrapDependencies(
      async () => ({ locale: 'zh-CN' }),
      async () => { throw new Error('initial route failed') },
    )
    await expect(result).resolves.toEqual({ locale: 'zh-CN' })
  })
})
