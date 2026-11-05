import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, nextTick, ref } from 'vue'
import { useChatVirtualScroll } from './useChatVirtualScroll'

describe('useChatVirtualScroll', () => {
  it('renders all indices below threshold', () => {
    const messages = ref(Array.from({ length: 10 }, (_, i) => ({ role: 'ai' as const, content: `m${i}`, time: '' })))
    const scrollEl = ref<HTMLElement | null>(null)
    const vs = useChatVirtualScroll({
      messages,
      scrollEl,
      estimateHeight: () => 96,
      threshold: 50,
    })
    expect(vs.enabled.value).toBe(false)
    expect(vs.renderIndices.value).toHaveLength(10)
  })

  it('windows long lists', () => {
    const messages = ref(Array.from({ length: 80 }, (_, i) => ({ role: 'ai' as const, content: `m${i}`, time: '' })))
    const scrollEl = ref<HTMLElement | null>(null)
    const vs = useChatVirtualScroll({
      messages,
      scrollEl,
      estimateHeight: () => 96,
      threshold: 50,
    })
    expect(vs.enabled.value).toBe(true)
    expect(vs.renderIndices.value.length).toBeLessThan(80)
    expect(vs.renderIndices.value[0]).toBe(0)
  })
})

it('tracks real scroll and resize events, preserves spacers, and releases replaced elements', async () => {
  const messages = ref(Array.from({ length: 80 }, (_, i) => ({ role: 'ai' as const, content: `m${i}`, time: '' })))
  const element = document.createElement('div'), scrollEl = ref<HTMLElement | null>(element)
  let height = 224, resize!: ResizeObserverCallback
  Object.defineProperty(element, 'clientHeight', { get: () => height })
  const disconnect = vi.fn(), observe = vi.fn(), remove = vi.spyOn(element, 'removeEventListener')
  vi.stubGlobal('ResizeObserver', class { constructor(cb: ResizeObserverCallback) { resize = cb } observe = observe; disconnect = disconnect })
  let api!: ReturnType<typeof useChatVirtualScroll>
  const wrapper = mount(defineComponent({ setup() { api = useChatVirtualScroll({ messages, scrollEl, estimateHeight: () => 96 }); return () => null } }))
  try {
    expect(observe).toHaveBeenCalledWith(element)
    element.scrollTop = 2240; element.dispatchEvent(new Event('scroll'))
    expect(api.renderIndices.value).toEqual(Array.from({ length: 22 }, (_, i) => i + 10))
    expect(api.topSpacer.value).toBe(1120); expect(api.bottomSpacer.value).toBe(5376)
    height = 336; resize([], {} as ResizeObserver)
    expect(api.renderIndices.value.slice(-1)[0]).toBe(32)
    element.scrollTop = 10000; api.onScroll()
    expect(api.renderIndices.value).toHaveLength(10); expect(api.bottomSpacer.value).toBe(0)
    messages.value = []; await nextTick()
    expect(api.enabled.value).toBe(false); expect(api.renderIndices.value).toEqual([])
    expect(api.topSpacer.value).toBe(0); expect(api.bottomSpacer.value).toBe(0)
    scrollEl.value = null; await nextTick(); api.refreshViewport()
    expect(remove).toHaveBeenCalledWith('scroll', expect.any(Function)); expect(disconnect).toHaveBeenCalledOnce()
    scrollEl.value = document.createElement('div'); await nextTick()
    expect(observe).toHaveBeenCalledTimes(2)
    wrapper.unmount(); expect(disconnect).toHaveBeenCalledTimes(2)
  } finally { wrapper.unmount(); vi.unstubAllGlobals() }
})
