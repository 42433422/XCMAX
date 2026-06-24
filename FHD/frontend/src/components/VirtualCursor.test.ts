import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import VirtualCursor from '@/components/VirtualCursor.vue'

describe('VirtualCursor', () => {
  let originalVirtualCursor: unknown
  let rafSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    originalVirtualCursor = (window as unknown as { virtualCursor?: unknown }).virtualCursor
    vi.useFakeTimers()
    rafSpy = vi
      .spyOn(window, 'requestAnimationFrame')
      .mockImplementation((cb: FrameRequestCallback) => {
        cb(0)
        return 0
      })
  })

  afterEach(() => {
    vi.useRealTimers()
    rafSpy.mockRestore()
    if (originalVirtualCursor === undefined) {
      delete (window as unknown as { virtualCursor?: unknown }).virtualCursor
    } else {
      ;(window as unknown as { virtualCursor?: unknown }).virtualCursor =
        originalVirtualCursor
    }
  })

  function mountCursor() {
    return mount(VirtualCursor)
  }

  it('renders root element with virtual-cursor-root class', () => {
    const wrapper = mountCursor()
    expect(wrapper.find('.virtual-cursor-root').exists()).toBe(true)
  })

  it('is hidden by default via v-show', () => {
    const wrapper = mountCursor()
    const root = wrapper.find('.virtual-cursor-root')
    expect(root.attributes('style') || '').toContain('opacity: 0')
  })

  it('renders SVG cursor icon', () => {
    const wrapper = mountCursor()
    expect(wrapper.find('.virtual-cursor-svg').exists()).toBe(true)
  })

  it('does not render label when empty', () => {
    const wrapper = mountCursor()
    expect(wrapper.find('.virtual-cursor-label').exists()).toBe(false)
  })

  it('does not render ripple when not clicking', () => {
    const wrapper = mountCursor()
    expect(wrapper.find('.virtual-cursor-ripple').exists()).toBe(false)
  })

  it('exposes API on window.virtualCursor after mount', () => {
    mountCursor()
    expect((window as unknown as { virtualCursor?: unknown }).virtualCursor).toBeDefined()
    const api = (window as unknown as { virtualCursor: { moveTo: unknown; click: unknown; hide: unknown; show: unknown } }).virtualCursor
    expect(typeof api.moveTo).toBe('function')
    expect(typeof api.click).toBe('function')
    expect(typeof api.hide).toBe('function')
    expect(typeof api.show).toBe('function')
  })

  it('show() makes cursor visible and centers on screen', async () => {
    const wrapper = mountCursor()
    const api = (window as unknown as { virtualCursor: { show: () => void } }).virtualCursor
    api.show()
    await wrapper.vm.$nextTick()
    const root = wrapper.find('.virtual-cursor-root')
    expect(root.attributes('style') || '').toContain('opacity: 1')
  })

  it('hide() makes cursor invisible', async () => {
    const wrapper = mountCursor()
    const api = (window as unknown as { virtualCursor: { show: () => void; hide: () => void } }).virtualCursor
    api.show()
    await wrapper.vm.$nextTick()
    api.hide()
    await wrapper.vm.$nextTick()
    const root = wrapper.find('.virtual-cursor-root')
    expect(root.attributes('style') || '').toContain('opacity: 0')
  })

  it('moveTo() with point object makes cursor visible', async () => {
    const wrapper = mountCursor()
    const api = (window as unknown as { virtualCursor: { moveTo: (t: unknown, o?: unknown) => void } }).virtualCursor
    api.moveTo({ x: 100, y: 200 }, { duration: 300, label: '测试' })
    await wrapper.vm.$nextTick()
    const root = wrapper.find('.virtual-cursor-root')
    expect(root.attributes('style') || '').toContain('opacity: 1')
    expect(wrapper.find('.virtual-cursor-label').exists()).toBe(true)
    expect(wrapper.find('.virtual-cursor-label').text()).toBe('测试')
  })

  it('moveTo() with HTMLElement scrolls into view and centers', async () => {
    const wrapper = mountCursor()
    const el = document.createElement('div')
    el.getBoundingClientRect = vi.fn(() => ({
      left: 50,
      top: 60,
      width: 20,
      height: 40,
      right: 70,
      bottom: 100,
      x: 50,
      y: 60,
      toJSON: () => ({}),
    }) as DOMRect)
    el.scrollIntoView = vi.fn()
    const api = (window as unknown as { virtualCursor: { moveTo: (t: unknown, o?: unknown) => void } }).virtualCursor
    api.moveTo(el, { duration: 100 })
    await wrapper.vm.$nextTick()
    expect(el.scrollIntoView).toHaveBeenCalled()
    const root = wrapper.find('.virtual-cursor-root')
    expect(root.attributes('style') || '').toContain('opacity: 1')
  })

  it('moveTo() with click option triggers ripple after duration', async () => {
    const wrapper = mountCursor()
    const api = (window as unknown as { virtualCursor: { moveTo: (t: unknown, o?: unknown) => void } }).virtualCursor
    api.moveTo({ x: 10, y: 20 }, { duration: 500, click: true })
    await wrapper.vm.$nextTick()
    // Before duration elapses, no ripple
    expect(wrapper.find('.virtual-cursor-ripple').exists()).toBe(false)
    // Advance past duration
    vi.advanceTimersByTime(600)
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.virtual-cursor-ripple').exists()).toBe(true)
  })

  it('click() calls moveTo with click option', async () => {
    const wrapper = mountCursor()
    const el = document.createElement('div')
    el.getBoundingClientRect = vi.fn(() => ({
      left: 0,
      top: 0,
      width: 100,
      height: 100,
      right: 100,
      bottom: 100,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    }) as DOMRect)
    el.scrollIntoView = vi.fn()
    const api = (window as unknown as { virtualCursor: { click: (t: unknown, o?: unknown) => void } }).virtualCursor
    api.click(el, { duration: 200, label: '点击' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.virtual-cursor-label').text()).toBe('点击')
    // Ripple should appear after duration
    vi.advanceTimersByTime(250)
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.virtual-cursor-ripple').exists()).toBe(true)
  })

  it('clicking class is removed after ripple timeout', async () => {
    const wrapper = mountCursor()
    const api = (window as unknown as { virtualCursor: { moveTo: (t: unknown, o?: unknown) => void } }).virtualCursor
    api.moveTo({ x: 5, y: 5 }, { duration: 100, click: true })
    await wrapper.vm.$nextTick()
    vi.advanceTimersByTime(150)
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.virtual-cursor-ripple').exists()).toBe(true)
    // After 280ms ripple timeout
    vi.advanceTimersByTime(300)
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.virtual-cursor-ripple').exists()).toBe(false)
  })

  it('cleanup removes window.virtualCursor on unmount', () => {
    const wrapper = mountCursor()
    expect((window as unknown as { virtualCursor?: unknown }).virtualCursor).toBeDefined()
    wrapper.unmount()
    expect((window as unknown as { virtualCursor?: unknown }).virtualCursor).toBeUndefined()
  })

  it('uses default duration of 500ms when not specified', async () => {
    const wrapper = mountCursor()
    const api = (window as unknown as { virtualCursor: { moveTo: (t: unknown, o?: unknown) => void } }).virtualCursor
    api.moveTo({ x: 0, y: 0 })
    await wrapper.vm.$nextTick()
    const root = wrapper.find('.virtual-cursor-root')
    expect(root.attributes('style') || '').toContain('500ms')
  })

  it('moveTo without options uses defaults', async () => {
    const wrapper = mountCursor()
    const api = (window as unknown as { virtualCursor: { moveTo: (t: unknown) => void } }).virtualCursor
    api.moveTo({ x: 1, y: 2 })
    await wrapper.vm.$nextTick()
    const root = wrapper.find('.virtual-cursor-root')
    expect(root.attributes('style') || '').toContain('opacity: 1')
  })
})
