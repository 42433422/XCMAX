import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { defineComponent, ref, h } from 'vue'
import { mount } from '@vue/test-utils'
import {
  useAnimation,
  useCSSAnimation,
  useTransition,
  easingFunctions,
} from './useAnimations'

let frames: Array<(t: number) => void> = []

function flushFrame(t: number) {
  const fns = frames
  frames = []
  for (const fn of fns) fn(t)
}

beforeEach(() => {
  frames = []
  vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation((cb: FrameRequestCallback) => {
    frames.push(cb as (t: number) => void)
    return frames.length
  })
  vi.spyOn(globalThis, 'cancelAnimationFrame').mockImplementation(() => {})
  vi.spyOn(performance, 'now').mockReturnValue(0)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('easingFunctions', () => {
  it('covers all easing branches', () => {
    expect(easingFunctions.linear(0.5)).toBe(0.5)
    expect(easingFunctions.easeInQuad(2)).toBe(4)
    expect(easingFunctions.easeOutQuad(0.5)).toBeCloseTo(0.75)
    expect(easingFunctions.easeInOutQuad(0.25)).toBeCloseTo(0.125)
    expect(easingFunctions.easeInOutQuad(0.75)).toBeGreaterThan(0.5)
    expect(easingFunctions.easeInCubic(2)).toBe(8)
    expect(easingFunctions.easeOutCubic(1)).toBe(1)
    expect(easingFunctions.easeInOutCubic(0.25)).toBeLessThan(0.5)
    expect(easingFunctions.easeInOutCubic(0.75)).toBeGreaterThan(0.5)
    expect(easingFunctions.easeInElastic(0)).toBe(0)
    expect(easingFunctions.easeInElastic(1)).toBe(1)
    expect(easingFunctions.easeInElastic(0.5)).not.toBeNaN()
    expect(easingFunctions.easeOutElastic(0)).toBe(0)
    expect(easingFunctions.easeOutElastic(1)).toBe(1)
    expect(easingFunctions.easeOutElastic(0.5)).not.toBeNaN()
    expect(easingFunctions.easeOutBounce(0.1)).toBeGreaterThan(0)
    expect(easingFunctions.easeOutBounce(0.5)).toBeGreaterThan(0)
    expect(easingFunctions.easeOutBounce(0.8)).toBeGreaterThan(0)
    expect(easingFunctions.easeOutBounce(0.99)).toBeGreaterThan(0)
  })
})

function withComponent(setup: () => Record<string, unknown>) {
  const Comp = defineComponent({
    setup() {
      const api = setup()
      return () => h('div')
    },
  })
  return mount(Comp)
}

describe('useAnimation', () => {
  it('runs start to completion calling frame and complete', () => {
    const el = ref<HTMLElement | null>(document.createElement('div'))
    const onFrame = vi.fn()
    const onComplete = vi.fn()
    let api: ReturnType<typeof useAnimation>
    withComponent(() => {
      api = useAnimation(el, { duration: 100, onFrame, onComplete, easing: easingFunctions.linear })
      return {}
    })
    api!.startAnimation()
    expect(api!.isAnimating.value).toBe(true)
    api!.startAnimation()
    flushFrame(50)
    expect(onFrame).toHaveBeenCalled()
    flushFrame(100)
    expect(onComplete).toHaveBeenCalled()
    expect(api!.isAnimating.value).toBe(false)
  })

  it('stop and reset clear state', () => {
    const el = ref<HTMLElement | null>(null)
    let api: ReturnType<typeof useAnimation>
    withComponent(() => {
      api = useAnimation(el, {})
      return {}
    })
    api!.startAnimation()
    api!.stopAnimation()
    expect(api!.isAnimating.value).toBe(false)
    api!.progress.value = 0.5
    api!.resetAnimation()
    expect(api!.progress.value).toBe(0)
  })

  it('animateTo resolves with target value', async () => {
    const el = ref<HTMLElement | null>(null)
    const onFrame = vi.fn()
    let api: ReturnType<typeof useAnimation>
    withComponent(() => {
      api = useAnimation(el, { startValue: 0, onFrame })
      return {}
    })
    const p = api!.animateTo(10, 100, easingFunctions.linear)
    flushFrame(100)
    await expect(p).resolves.toBe(10)
    expect(onFrame).toHaveBeenCalled()
  })

  it('animateLoop calls callback each frame', () => {
    const el = ref<HTMLElement | null>(null)
    const cb = vi.fn()
    let api: ReturnType<typeof useAnimation>
    withComponent(() => {
      api = useAnimation(el, {})
      return {}
    })
    api!.animateLoop(cb, 100)
    flushFrame(50)
    expect(cb).toHaveBeenCalled()
  })
})

describe('useCSSAnimation', () => {
  it('play sets animation style and completes via timer', () => {
    vi.useFakeTimers()
    const el = ref<HTMLElement | null>(document.createElement('div'))
    const onComplete = vi.fn()
    let api: ReturnType<typeof useCSSAnimation>
    withComponent(() => {
      api = useCSSAnimation(el, 'fade', { duration: 0.1, onComplete })
      return {}
    })
    api!.play()
    expect(el.value!.style.animation).toContain('fade')
    vi.advanceTimersByTime(200)
    expect(onComplete).toHaveBeenCalled()
    api!.pause()
    expect(el.value!.style.animationPlayState).toBe('paused')
    api!.resume()
    expect(el.value!.style.animationPlayState).toBe('running')
    api!.reset()
    expect(el.value!.style.animation).toBe('none')
    vi.useRealTimers()
  })

  it('play no-op without element', () => {
    const el = ref<HTMLElement | null>(null)
    let api: ReturnType<typeof useCSSAnimation>
    withComponent(() => {
      api = useCSSAnimation(el, 'fade', {})
      return {}
    })
    api!.play()
    expect(api!.isAnimating.value).toBe(false)
  })
})

describe('useTransition', () => {
  it('transition animates a property to value', () => {
    const el = ref<HTMLElement | null>(document.createElement('div'))
    const onComplete = vi.fn()
    let api: ReturnType<typeof useTransition>
    withComponent(() => {
      api = useTransition(el, { property: 'opacity', unit: '', easing: easingFunctions.linear, onComplete })
      return {}
    })
    api!.transition(1, 100)
    expect(api!.isTransitioning.value).toBe(true)
    flushFrame(100)
    expect(onComplete).toHaveBeenCalled()
    expect(api!.isTransitioning.value).toBe(false)
  })

  it('transition no-op without property', () => {
    const el = ref<HTMLElement | null>(document.createElement('div'))
    let api: ReturnType<typeof useTransition>
    withComponent(() => {
      api = useTransition(el, {})
      return {}
    })
    api!.transition(1)
    expect(api!.isTransitioning.value).toBe(false)
  })
})
