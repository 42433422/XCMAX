import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'
import type { Ref } from 'vue'

// useBreakpoint 在 onMounted 中初始化 matchMedia 监听，必须用 mount 包装才能触发
async function loadFreshModule() {
  vi.resetModules()
  return (await import('./useBreakpoint')).useBreakpoint
}

type BreakpointRefs = {
  isMobile: Ref<boolean>
  isTablet: Ref<boolean>
  isDesktop: Ref<boolean>
}

// 包装一个测试组件，让 useBreakpoint 的 onMounted 得以执行；通过 vm.bp 直接读取 ref
function makeHarness(useBreakpoint: () => BreakpointRefs) {
  return defineComponent({
    name: 'BreakpointHarness',
    setup() {
      const bp = useBreakpoint()
      return { bp }
    },
    render() {
      return h('div')
    },
  })
}

describe('useBreakpoint', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('exports BREAKPOINTS constants', async () => {
    const mod = await import('./useBreakpoint')
    expect(mod.BREAKPOINTS.mobileMax).toBe(768)
    expect(mod.BREAKPOINTS.tabletMax).toBe(1024)
  })

  it('returns one of mobile/tablet/desktop in DOM environment', async () => {
    const useBreakpoint = await loadFreshModule()
    const Harness = makeHarness(useBreakpoint)
    const wrapper = mount(Harness)
    // happy-dom 默认窗口尺寸不固定，只验证三态互斥
    const { isMobile, isTablet, isDesktop } = wrapper.vm.bp
    const trueCount = [isMobile.value, isTablet.value, isDesktop.value].filter(Boolean).length
    expect(trueCount).toBe(1)
    if (isMobile.value) {
      expect(isDesktop.value).toBe(false)
      expect(isTablet.value).toBe(false)
    } else if (isTablet.value) {
      expect(isMobile.value).toBe(false)
      expect(isDesktop.value).toBe(false)
    } else {
      expect(isDesktop.value).toBe(true)
      expect(isMobile.value).toBe(false)
      expect(isTablet.value).toBe(false)
    }
    wrapper.unmount()
  })

  it('detects android client via URL param', async () => {
    const originalSearch = window.location.search
    try {
      window.history.replaceState({}, '', '/?client=android')
      const useBreakpoint = await loadFreshModule()
      const Harness = makeHarness(useBreakpoint)
      const wrapper = mount(Harness)
      await nextTick()
      expect(wrapper.vm.bp.isMobile.value).toBe(true)
      expect(wrapper.vm.bp.isDesktop.value).toBe(false)
      wrapper.unmount()
    } finally {
      window.history.replaceState({}, '', originalSearch || '/')
    }
  })

  it('detects android client via __XCAGI_CLIENT__ global', async () => {
    const w = window as Window & { __XCAGI_CLIENT__?: string }
    const original = w.__XCAGI_CLIENT__
    try {
      w.__XCAGI_CLIENT__ = 'android'
      const useBreakpoint = await loadFreshModule()
      const Harness = makeHarness(useBreakpoint)
      const wrapper = mount(Harness)
      await nextTick()
      expect(wrapper.vm.bp.isMobile.value).toBe(true)
      wrapper.unmount()
    } finally {
      if (original === undefined) {
        delete w.__XCAGI_CLIENT__
      } else {
        w.__XCAGI_CLIENT__ = original
      }
    }
  })

  it('adds xcagi-client-android class to documentElement when android', async () => {
    const originalSearch = window.location.search
    try {
      window.history.replaceState({}, '', '/?client=android')
      const useBreakpoint = await loadFreshModule()
      const Harness = makeHarness(useBreakpoint)
      const wrapper = mount(Harness)
      await nextTick()
      expect(document.documentElement.classList.contains('xcagi-client-android')).toBe(true)
      wrapper.unmount()
    } finally {
      document.documentElement.classList.remove('xcagi-client-android')
      window.history.replaceState({}, '', originalSearch || '/')
    }
  })

  it('matchMedia change listener updates isMobile', async () => {
    const listeners: ((e: MediaQueryListEvent) => void)[] = []
    const fakeMql = {
      matches: false,
      media: '(max-width: 768px)',
      onchange: null,
      addEventListener: vi.fn((_: string, l: (e: MediaQueryListEvent) => void) => {
        listeners.push(l)
      }),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(() => false),
    } as unknown as MediaQueryList

    const original = window.matchMedia
    window.matchMedia = vi.fn((query: string) => {
      if (query.includes('768')) return fakeMql
      return {
        ...fakeMql,
        matches: false,
        media: query,
      } as MediaQueryList
    })

    try {
      const useBreakpoint = await loadFreshModule()
      const Harness = makeHarness(useBreakpoint)
      const wrapper = mount(Harness)
      await nextTick()
      expect(wrapper.vm.bp.isMobile.value).toBe(false)

      // 模拟切到移动端
      ;(fakeMql as { matches: boolean }).matches = true
      listeners.forEach((l) => l({ matches: true, media: '(max-width: 768px)' } as MediaQueryListEvent))
      await nextTick()
      expect(wrapper.vm.bp.isMobile.value).toBe(true)
      wrapper.unmount()
    } finally {
      window.matchMedia = original
    }
  })

  it('useBreakpoint returns the same refs across calls (singleton)', async () => {
    const useBreakpoint = await loadFreshModule()
    const Harness = defineComponent({
      name: 'SingletonHarness',
      setup() {
        const r1 = useBreakpoint()
        const r2 = useBreakpoint()
        expect(r1.isMobile).toBe(r2.isMobile)
        expect(r1.isTablet).toBe(r2.isTablet)
        expect(r1.isDesktop).toBe(r2.isDesktop)
        return () => h('div')
      },
    })
    const wrapper = mount(Harness)
    wrapper.unmount()
  })

  it('BREAKPOINTS values are stable', async () => {
    const mod = await import('./useBreakpoint')
    expect(mod.BREAKPOINTS.mobileMax).toBe(768)
    expect(mod.BREAKPOINTS.tabletMax).toBe(1024)
  })
})
