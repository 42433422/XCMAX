import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, h, KeepAlive, nextTick, onMounted, provide, ref } from 'vue'
import { invalidateEnterpriseSessionCache } from '@/utils/authSessionCache'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { startupPageReadyKey, useStartupPageReady } from './useStartupSplash'

type Prepare = (signal: AbortSignal) => Promise<void>
function deferred() {
  let resolve!: () => void
  const promise = new Promise<void>(done => { resolve = done })
  return { promise, resolve }
}
const wrappers: VueWrapper[] = []
afterEach(() => { for (const wrapper of wrappers.splice(0)) wrapper.unmount() })

function mountPage(load: (current: () => boolean) => Promise<void>, cached = false, scopeKey?: () => unknown) {
  const registry = new Set<Prepare>()
  const active = ref(true)
  const unregister = vi.fn()
  let mountedRead!: Promise<void>
  const page = defineComponent({
    name: 'RequiredPage',
    setup() {
      const preparePage = useStartupPageReady(load, scopeKey)
      onMounted(() => { mountedRead = preparePage(); void mountedRead.catch(() => {}) })
      return () => h('section', 'current page')
    },
  })
  const wrapper = mount(defineComponent({
    setup() {
      provide(startupPageReadyKey, prepare => {
        registry.add(prepare)
        return () => { registry.delete(prepare); unregister() }
      })
      const render = () => active.value ? h(page) : h('section', 'other page')
      return () => cached ? h(KeepAlive, null, { default: render }) : render()
    },
  }))
  wrappers.push(wrapper)
  return { wrapper, registry, active, unregister, mountedRead: () => mountedRead,
    prepare: () => { const value = registry.values().next().value; if (!value) throw new Error('no current page registered'); return value } }
}

describe('current page startup data readiness', () => {
  it('waits on the real mounted read and reuses it for the first startup attempt', async () => {
    const data = deferred()
    const load = vi.fn(async () => { await data.promise })
    const page = mountPage(load)
    await flushPromises()
    let ready = false
    const pending = page.prepare()(new AbortController().signal).then(() => { ready = true })
    await flushPromises()
    expect(load).toHaveBeenCalledOnce()
    expect(ready).toBe(false)
    expect(page.wrapper.text()).toContain('current page')
    data.resolve()
    await pending
    expect(ready).toBe(true)
  })

  it('propagates the mounted read failure, then starts a fresh explicit retry', async () => {
    const load = vi.fn().mockRejectedValueOnce(new Error('synthetic page read failed')).mockResolvedValueOnce(undefined)
    const page = mountPage(load)
    await flushPromises()
    await expect(page.prepare()(new AbortController().signal)).rejects.toThrow('synthetic page read failed')
    expect(load).toHaveBeenCalledOnce()
    await expect(page.prepare()(new AbortController().signal)).resolves.toBeUndefined()
    expect(load).toHaveBeenCalledTimes(2)
  })

  it('retires an aborted read and keeps a newer retry pending until its own response', async () => {
    const old = deferred(), latest = deferred()
    const current: Array<() => boolean> = []
    const load = vi.fn(async isCurrent => { current.push(isCurrent); await (current.length === 1 ? old.promise : latest.promise) })
    const page = mountPage(load)
    await flushPromises()
    const first = new AbortController()
    const oldOutcome = page.prepare()(first.signal).then(() => 'ready', () => 'retired')
    first.abort()
    expect(current[0]()).toBe(false)
    let latestReady = false
    const retry = page.prepare()(new AbortController().signal).then(() => { latestReady = true })
    await flushPromises()
    expect(load).toHaveBeenCalledTimes(2)
    old.resolve()
    expect(await oldOutcome).toBe('retired')
    expect(latestReady).toBe(false)
    expect(current[1]()).toBe(true)
    latest.resolve()
    await retry
    expect(latestReady).toBe(true)
  })

  it('does not start the queued read for an already aborted startup attempt', async () => {
    const load = vi.fn().mockResolvedValue(undefined)
    const controller = new AbortController()
    controller.abort()
    const page = mountPage(load)
    await expect(page.prepare()(controller.signal)).rejects.toThrow()
    expect(load).not.toHaveBeenCalled()
  })

  it('does not let an older attempt abort retire the current retry', async () => {
    const old = deferred(), fresh = deferred()
    const current: Array<() => boolean> = []
    const load = vi.fn(async isCurrent => { current.push(isCurrent); await (current.length === 1 ? old.promise : fresh.promise) })
    const page = mountPage(load)
    await flushPromises()
    const first = new AbortController()
    const oldOutcome = page.prepare()(first.signal).then(() => 'ready', () => 'retired')
    const retry = page.prepare()(new AbortController().signal)
    await flushPromises()
    first.abort()
    expect(current[1]()).toBe(true)
    old.resolve()
    expect(await oldOutcome).toBe('retired')
    fresh.resolve()
    await expect(retry).resolves.toBeUndefined()
  })

  it.each(['authentication', 'account'] as const)('replaces the mounted promise after its %s scope changes', async scope => {
    const old = deferred(), fresh = deferred()
    const current: Array<() => boolean> = []
    const load = vi.fn(async isCurrent => { current.push(isCurrent); await (current.length === 1 ? old.promise : fresh.promise) })
    const page = mountPage(load)
    await flushPromises()
    if (scope === 'authentication') invalidateEnterpriseSessionCache()
    else productReadAccountEpoch.value++
    expect(current[0]()).toBe(false)
    let ready = false
    const pending = page.prepare()(new AbortController().signal).then(() => { ready = true })
    await flushPromises()
    expect(load).toHaveBeenCalledTimes(2)
    old.resolve()
    await flushPromises()
    expect(ready).toBe(false)
    fresh.resolve()
    await pending
    expect(ready).toBe(true)
  })

  it('reads the current page again when mount-time Mod selection changes its data scope', async () => {
    const old = deferred(), fresh = deferred()
    let scope = 'session:one/mod:a'
    const current: Array<() => boolean> = []
    const applied: string[] = []
    const load = vi.fn(async isCurrent => {
      const captured = scope
      current.push(isCurrent)
      await (current.length === 1 ? old.promise : fresh.promise)
      if (isCurrent()) applied.push(captured)
    })
    const page = mountPage(load, false, () => scope)
    await flushPromises()
    scope = 'session:one/mod:b'
    expect(current[0]()).toBe(false)
    const pending = page.prepare()(new AbortController().signal)
    await flushPromises()
    expect(load).toHaveBeenCalledTimes(2)
    old.resolve()
    await flushPromises()
    expect(applied).toEqual([])
    fresh.resolve()
    await pending
    expect(applied).toEqual(['session:one/mod:b'])
  })

  it('unregisters and retires its read on unmount without applying the late result', async () => {
    const data = deferred()
    const applied = vi.fn()
    let current!: () => boolean
    const page = mountPage(async isCurrent => { current = isCurrent; await data.promise; if (isCurrent()) applied() })
    await flushPromises()
    expect(page.registry.size).toBe(1)
    page.wrapper.unmount()
    expect(current()).toBe(false)
    expect(page.registry.size).toBe(0)
    expect(page.unregister).toHaveBeenCalledOnce()
    data.resolve()
    await expect(page.mountedRead()).rejects.toThrow()
    expect(applied).not.toHaveBeenCalled()
    wrappers.splice(wrappers.indexOf(page.wrapper), 1)
  })

  it('registers only the active cached page and refreshes it when a later gate needs it', async () => {
    const load = vi.fn().mockResolvedValue(undefined)
    const page = mountPage(load, true)
    await flushPromises()
    expect(page.registry.size).toBe(1)
    page.active.value = false
    await nextTick()
    expect(page.registry.size).toBe(0)
    page.active.value = true
    await nextTick()
    expect(page.registry.size).toBe(1)
    await page.prepare()(new AbortController().signal)
    expect(load).toHaveBeenCalledTimes(2)
  })

  it('still performs an ordinary page read when no startup provider is present', async () => {
    const load = vi.fn().mockResolvedValue(undefined)
    let read!: Promise<void>
    const wrapper = mount(defineComponent({
      setup() { const preparePage = useStartupPageReady(load); onMounted(() => { read = preparePage() }); return () => h('section') },
    }))
    wrappers.push(wrapper)
    await read
    expect(load).toHaveBeenCalledOnce()
  })
})
