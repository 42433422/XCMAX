import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  bindTutorialRouter,
  shouldNeverAutoSkipStep,
  resolveElementRect,
  getTutorialFallbackHighlightRect,
  resolveStepHighlightRect,
  dispatchAssistantTab,
  afterAssistantTabLayout,
  ensureRouteForStepThen,
  TUTORIAL_SET_ASSISTANT_TAB,
} from './runtime'
import type { TutorialStep } from './types'

function sizedEl(setup: (el: HTMLDivElement) => void): HTMLDivElement {
  const el = document.createElement('div')
  setup(el)
  el.getBoundingClientRect = () => ({ top: 10, left: 20, width: 100, height: 50 }) as DOMRect
  document.body.appendChild(el)
  return el
}

beforeEach(() => {
  document.body.innerHTML = ''
})

describe('tutorial runtime (router-less branch first)', () => {
  it('ensureRouteForStepThen runs fn when no router is bound', () => {
    const fn = vi.fn()
    ensureRouteForStepThen({ id: 's', routeName: 'orders' } as TutorialStep, fn)
    expect(fn).toHaveBeenCalled()
  })
})

describe('tutorial runtime pure helpers', () => {
  it('shouldNeverAutoSkipStep matches the protected id', () => {
    expect(shouldNeverAutoSkipStep({ id: 'starter-pack-demo-3-start-print' } as TutorialStep)).toBe(true)
    expect(shouldNeverAutoSkipStep({ id: 'other' } as TutorialStep)).toBe(false)
    expect(shouldNeverAutoSkipStep(null)).toBe(false)
  })

  it('getTutorialFallbackHighlightRect returns a centered box', () => {
    const r = getTutorialFallbackHighlightRect()
    expect(r.width).toBe(320)
    expect(r.height).toBe(160)
  })

  it('resolveElementRect returns null for missing or zero-size elements', () => {
    expect(resolveElementRect('#nope')).toBeNull()
    const zero = document.createElement('div')
    zero.id = 'zero'
    zero.getBoundingClientRect = () => ({ width: 0, height: 0 }) as DOMRect
    document.body.appendChild(zero)
    expect(resolveElementRect('#zero')).toBeNull()
  })

  it('resolveElementRect returns rect for sized elements', () => {
    sizedEl((el) => (el.id = 'sized'))
    expect(resolveElementRect('#sized')).toEqual({ top: 10, left: 20, width: 100, height: 50 })
  })
})

describe('resolveStepHighlightRect branches', () => {
  it('returns null for null step', () => {
    expect(resolveStepHighlightRect(null)).toBeNull()
  })

  it('pads assistant-panel selectors', () => {
    sizedEl((el) => (el.className = 'assistant-panel'))
    const r = resolveStepHighlightRect({ id: 's', highlightSelector: '.assistant-panel' } as TutorialStep)
    expect(r).toEqual({ top: 4, left: 14, width: 112, height: 62 })
  })

  it('pads page-content selectors', () => {
    sizedEl((el) => (el.className = 'page-content'))
    const r = resolveStepHighlightRect({ id: 's', targetSelector: '.page-content' } as TutorialStep)
    expect(r).toEqual({ top: 6, left: 16, width: 108, height: 58 })
  })

  it('returns base rect for plain selectors', () => {
    sizedEl((el) => (el.id = 'plain'))
    const r = resolveStepHighlightRect({ id: 's', targetSelector: '#plain' } as TutorialStep)
    expect(r).toEqual({ top: 10, left: 20, width: 100, height: 50 })
  })
})

describe('dispatchAssistantTab', () => {
  it('ignores blank tab and dispatches valid tab', () => {
    const handler = vi.fn()
    window.addEventListener(TUTORIAL_SET_ASSISTANT_TAB, handler)
    dispatchAssistantTab('   ')
    expect(handler).not.toHaveBeenCalled()
    dispatchAssistantTab('starterPack')
    expect(handler).toHaveBeenCalled()
    window.removeEventListener(TUTORIAL_SET_ASSISTANT_TAB, handler)
  })
})

describe('afterAssistantTabLayout', () => {
  it('invokes fn after nextTick + double rAF', async () => {
    await new Promise<void>((resolve) => {
      afterAssistantTabLayout(() => resolve())
    })
    expect(true).toBe(true)
  })
})

describe('ensureRouteForStepThen with bound router', () => {
  it('runs fn immediately when route already matches or no routeName', () => {
    const router = {
      currentRoute: { value: { name: 'chat' } },
      push: vi.fn().mockResolvedValue(undefined),
    }
    bindTutorialRouter(router as never)
    const fn1 = vi.fn()
    ensureRouteForStepThen({ id: 's' } as TutorialStep, fn1)
    expect(fn1).toHaveBeenCalled()
    const fn2 = vi.fn()
    ensureRouteForStepThen({ id: 's', routeName: 'chat' } as TutorialStep, fn2)
    expect(fn2).toHaveBeenCalled()
    expect(router.push).not.toHaveBeenCalled()
  })

  it('pushes route then runs fn on success', async () => {
    const router = {
      currentRoute: { value: { name: 'chat' } },
      push: vi.fn().mockResolvedValue(undefined),
    }
    bindTutorialRouter(router as never)
    const fn = vi.fn()
    ensureRouteForStepThen({ id: 's', routeName: 'orders' } as TutorialStep, fn)
    await Promise.resolve()
    await Promise.resolve()
    expect(router.push).toHaveBeenCalledWith({ name: 'orders' })
    expect(fn).toHaveBeenCalled()
  })

  it('runs fn even when push rejects', async () => {
    const router = {
      currentRoute: { value: { name: 'chat' } },
      push: vi.fn().mockRejectedValue(new Error('nav')),
    }
    bindTutorialRouter(router as never)
    const fn = vi.fn()
    ensureRouteForStepThen({ id: 's', routeName: 'orders' } as TutorialStep, fn)
    await Promise.resolve()
    await Promise.resolve()
    expect(fn).toHaveBeenCalled()
  })
})
