/**
 * runOnboardingTour 覆盖率补充测试
 * 目标：覆盖 mountControls、navigateIfNeeded、waitWithPause、runStep 各分支
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ── 使用 vi.hoisted 创建 mock 变量，确保 vi.mock 工厂能访问到 ──
const {
  capturedDriverConfigRef,
  mockHighlight,
  mockDestroy,
  mockWaitForSelector,
  mockDemoGroupCleanup,
  mockSleep,
  mockGetVirtualCursor,
} = vi.hoisted(() => ({
  // 用 ref 对象保存 driver() 配置，避免 let 变量在 hoist 时不可用
  capturedDriverConfigRef: { value: null as any },
  mockHighlight: vi.fn(),
  mockDestroy: vi.fn(),
  mockWaitForSelector: vi.fn(),
  mockDemoGroupCleanup: vi.fn(),
  mockSleep: vi.fn().mockResolvedValue(undefined),
  mockGetVirtualCursor: vi.fn(() => ({ hide: vi.fn() })),
}))

vi.mock('driver.js', () => ({
  driver: vi.fn((config: any) => {
    capturedDriverConfigRef.value = config
    return {
      highlight: mockHighlight,
      destroy: mockDestroy,
    }
  }),
}))

vi.mock('driver.js/dist/driver.css', () => ({}))

vi.mock('@/tutorial/buildDriverSchedule', () => ({
  demoGroupCleanup: mockDemoGroupCleanup,
  waitForSelector: mockWaitForSelector,
}))

vi.mock('@/tutorial/demoHelpers', () => ({
  getVirtualCursor: mockGetVirtualCursor,
  makeTimerGroup: () => ({}),
  sleep: mockSleep,
}))

// 在 vi.mock 之后导入被测模块
import {
  runOnboardingTour,
  type RunOnboardingTourOptions,
  type OnboardingTourStoreLike,
} from './runOnboardingTour'

// ── 辅助函数 ──
function makeMockStore(overrides: Partial<OnboardingTourStoreLike> = {}): OnboardingTourStoreLike {
  return {
    paused: false,
    skipRequested: false,
    requestSkip: vi.fn(),
    togglePause: vi.fn(),
    ...overrides,
  }
}

function makeMockRouter(currentRouteName = 'home', currentQuery: Record<string, string> = {}) {
  return {
    currentRoute: { value: { name: currentRouteName, query: currentQuery } },
    push: vi.fn().mockResolvedValue(undefined),
  } as unknown as Parameters<typeof runOnboardingTour>[0]['router']
}

interface StepConfig {
  id?: string
  title?: string
  description?: string
  routeName?: string
  routeQuery?: Record<string, string>
  waitFor?: string
  actionType?: 'click' | 'observe'
  duration?: number
  isLast?: boolean
  demo?: () => { ok: boolean; fallbackMsg?: string }
}

function makeStep(overrides: StepConfig = {}): any {
  return {
    id: 'step-1',
    title: 'Test',
    description: 'Test step',
    waitFor: '.test',
    actionType: 'highlight' as const,
    duration: 0,
    isLast: true,
    demo: () => ({ ok: true }),
    ...overrides,
  }
}

function makeOptions(steps: any[], store?: OnboardingTourStoreLike): RunOnboardingTourOptions {
  return {
    steps,
    router: makeMockRouter(),
    store: store || makeMockStore(),
    onComplete: vi.fn(),
    onSkip: vi.fn(),
  }
}

// 创建带 footer 的 popover DOM 结构
function setupPopoverWithFooter(footerClass = 'driver-popover-footer'): HTMLElement {
  const popover = document.createElement('div')
  popover.className = 'driver-popover'
  const footer = document.createElement('div')
  footer.className = footerClass
  popover.appendChild(footer)
  document.body.appendChild(popover)
  return popover
}

// 创建可见的模拟元素
function makeVisibleElement(tag = 'div'): HTMLElement {
  const el = document.createElement(tag)
  el.getBoundingClientRect = () => ({ width: 100, height: 50, top: 0, left: 0 }) as DOMRect
  return el
}

beforeEach(() => {
  vi.clearAllMocks()
  capturedDriverConfigRef.value = null
  mockWaitForSelector.mockResolvedValue(null)
  mockSleep.mockResolvedValue(undefined)
  document.body.innerHTML = ''
  document.body.classList.remove('tutorial-active')
})

// 恢复 spyOn 创建的 spy（如 Date.now），避免影响其他测试
afterEach(() => {
  vi.restoreAllMocks()
})

describe('runOnboardingTour - mountControls', () => {
  it('通过 onPopoverRender 挂载控件（.driver-popover-footer）', () => {
    const cleanup = runOnboardingTour(makeOptions([makeStep()]))

    // 创建 popover 并触发 onPopoverRender
    const popover = document.createElement('div')
    const footer = document.createElement('div')
    footer.className = 'driver-popover-footer'
    popover.appendChild(footer)
    capturedDriverConfigRef.value.onPopoverRender({ wrapper: popover })

    const controls = footer.querySelector('.xcagi-tour-extra-controls')
    expect(controls).not.toBeNull()
    expect(controls?.querySelector('.xcagi-tour-btn-pause')).not.toBeNull()
    expect(controls?.querySelector('.xcagi-tour-btn-skip')).not.toBeNull()
    // 默认未暂停 → 按钮文字为"暂停"
    expect(controls?.querySelector('.xcagi-tour-btn-pause')?.textContent).toBe('暂停')

    cleanup()
  })

  it('通过 .driver-popover-navigation-btns 查找 footer', () => {
    const cleanup = runOnboardingTour(makeOptions([makeStep()]))

    const popover = document.createElement('div')
    const footer = document.createElement('div')
    footer.className = 'driver-popover-navigation-btns'
    popover.appendChild(footer)
    capturedDriverConfigRef.value.onPopoverRender({ wrapper: popover })

    expect(footer.querySelector('.xcagi-tour-extra-controls')).not.toBeNull()
    cleanup()
  })

  it('footer 不存在时不挂载控件', () => {
    const cleanup = runOnboardingTour(makeOptions([makeStep()]))

    const popover = document.createElement('div')
    capturedDriverConfigRef.value.onPopoverRender({ wrapper: popover })

    expect(popover.querySelector('.xcagi-tour-extra-controls')).toBeNull()
    cleanup()
  })

  it('已有控件时不重复挂载', () => {
    const cleanup = runOnboardingTour(makeOptions([makeStep()]))

    const popover = document.createElement('div')
    const footer = document.createElement('div')
    footer.className = 'driver-popover-footer'
    const existing = document.createElement('div')
    existing.className = 'xcagi-tour-extra-controls'
    footer.appendChild(existing)
    popover.appendChild(footer)
    capturedDriverConfigRef.value.onPopoverRender({ wrapper: popover })

    // 只有一个 .xcagi-tour-extra-controls
    expect(footer.querySelectorAll('.xcagi-tour-extra-controls')).toHaveLength(1)
    cleanup()
  })

  it('点击暂停按钮 → 调用 togglePause 并切换按钮文字', async () => {
    const store = makeMockStore({ paused: false })
    // 让 togglePause 实际翻转 paused 状态，以覆盖 click handler 中的 ternary 分支
    store.togglePause = vi.fn(() => {
      store.paused = !store.paused
    })
    const cleanup = runOnboardingTour(makeOptions([makeStep()], store))

    const popover = document.createElement('div')
    const footer = document.createElement('div')
    footer.className = 'driver-popover-footer'
    popover.appendChild(footer)
    capturedDriverConfigRef.value.onPopoverRender({ wrapper: popover })

    const pauseBtn = footer.querySelector('.xcagi-tour-btn-pause') as HTMLButtonElement
    expect(pauseBtn.textContent).toBe('暂停')

    // 模拟点击 → togglePause 被调用，paused 变为 true，按钮文字变为"继续"
    pauseBtn.click()
    expect(store.togglePause).toHaveBeenCalled()
    expect(pauseBtn.textContent).toBe('继续')

    // 再次点击 → paused 变回 false，按钮文字变回"暂停"
    pauseBtn.click()
    expect(pauseBtn.textContent).toBe('暂停')

    cleanup()
  })

  it('store.paused=true 时按钮文字为"继续"', () => {
    const store = makeMockStore({ paused: true })
    const cleanup = runOnboardingTour(makeOptions([makeStep()], store))

    const popover = document.createElement('div')
    const footer = document.createElement('div')
    footer.className = 'driver-popover-footer'
    popover.appendChild(footer)
    capturedDriverConfigRef.value.onPopoverRender({ wrapper: popover })

    const pauseBtn = footer.querySelector('.xcagi-tour-btn-pause') as HTMLButtonElement
    expect(pauseBtn.textContent).toBe('继续')

    cleanup()
  })

  it('点击跳过按钮 → 调用 requestSkip', () => {
    const store = makeMockStore()
    const cleanup = runOnboardingTour(makeOptions([makeStep()], store))

    const popover = document.createElement('div')
    const footer = document.createElement('div')
    footer.className = 'driver-popover-footer'
    popover.appendChild(footer)
    capturedDriverConfigRef.value.onPopoverRender({ wrapper: popover })

    const skipBtn = footer.querySelector('.xcagi-tour-btn-skip') as HTMLButtonElement
    skipBtn.click()
    expect(store.requestSkip).toHaveBeenCalled()

    cleanup()
  })
})

describe('runOnboardingTour - navigateIfNeeded', () => {
  it('routeName 为空时不导航', async () => {
    const router = makeMockRouter('home')
    const cleanup = runOnboardingTour({
      steps: [makeStep({ routeName: undefined, isLast: true })],
      router,
      store: makeMockStore(),
      onComplete: vi.fn(),
      onSkip: vi.fn(),
    })

    await vi.waitFor(() => expect(mockWaitForSelector).toHaveBeenCalled())
    expect(router.push).not.toHaveBeenCalled()
    cleanup()
  })

  it('相同路由和 query 时不导航', async () => {
    const router = makeMockRouter('chat', { tab: 'office' })
    const cleanup = runOnboardingTour({
      steps: [makeStep({ routeName: 'chat', routeQuery: { tab: 'office' }, isLast: true })],
      router,
      store: makeMockStore(),
      onComplete: vi.fn(),
      onSkip: vi.fn(),
    })

    await vi.waitFor(() => expect(mockWaitForSelector).toHaveBeenCalled())
    expect(router.push).not.toHaveBeenCalled()
    cleanup()
  })

  it('不同路由时执行导航', async () => {
    const router = makeMockRouter('home')
    const cleanup = runOnboardingTour({
      steps: [makeStep({ routeName: 'chat', isLast: true })],
      router,
      store: makeMockStore(),
      onComplete: vi.fn(),
      onSkip: vi.fn(),
    })

    await vi.waitFor(() => expect(router.push).toHaveBeenCalledWith({ name: 'chat', query: {} }))
    cleanup()
  })

  it('相同路由但不同 query 时执行导航', async () => {
    const router = makeMockRouter('chat', { tab: 'old' })
    const cleanup = runOnboardingTour({
      steps: [makeStep({ routeName: 'chat', routeQuery: { tab: 'new' }, isLast: true })],
      router,
      store: makeMockStore(),
      onComplete: vi.fn(),
      onSkip: vi.fn(),
    })

    await vi.waitFor(() =>
      expect(router.push).toHaveBeenCalledWith({ name: 'chat', query: { tab: 'new' } }),
    )
    cleanup()
  })

  it('router.push 抛错时不中断流程', async () => {
    const router = makeMockRouter('home')
    router.push = vi.fn().mockRejectedValue(new Error('nav error'))

    const cleanup = runOnboardingTour({
      steps: [makeStep({ routeName: 'chat', isLast: true })],
      router,
      store: makeMockStore(),
      onComplete: vi.fn(),
      onSkip: vi.fn(),
    })

    // push 抛错但流程继续（waitForSelector 仍被调用）
    await vi.waitFor(() => expect(mockWaitForSelector).toHaveBeenCalled())
    cleanup()
  })

  it('当前路由 name 为 undefined → 走 || 分支不报错', async () => {
    // router.currentRoute.value.name 为 undefined → 覆盖 line 98 的 || 分支
    const router = {
      currentRoute: { value: { name: undefined, query: {} } },
      push: vi.fn().mockResolvedValue(undefined),
    } as unknown as Parameters<typeof runOnboardingTour>[0]['router']

    const cleanup = runOnboardingTour({
      steps: [makeStep({ routeName: 'chat', isLast: true })],
      router,
      store: makeMockStore(),
      onComplete: vi.fn(),
      onSkip: vi.fn(),
    })

    await vi.waitFor(() => expect(router.push).toHaveBeenCalledWith({ name: 'chat', query: {} }))
    cleanup()
  })

  it('当前路由缺少 step 期望的 query key → 走 || 分支执行导航', async () => {
    // 当前路由 query 为空，step 期望 { tab: 'new' } → query[k] 为 undefined → 覆盖 line 102 的 || 分支
    const router = {
      currentRoute: { value: { name: 'chat', query: {} } },
      push: vi.fn().mockResolvedValue(undefined),
    } as unknown as Parameters<typeof runOnboardingTour>[0]['router']

    const cleanup = runOnboardingTour({
      steps: [makeStep({ routeName: 'chat', routeQuery: { tab: 'new' }, isLast: true })],
      router,
      store: makeMockStore(),
      onComplete: vi.fn(),
      onSkip: vi.fn(),
    })

    await vi.waitFor(() =>
      expect(router.push).toHaveBeenCalledWith({ name: 'chat', query: { tab: 'new' } }),
    )
    cleanup()
  })
})

describe('runOnboardingTour - runStep 元素查找', () => {
  it('找到元素 → 调用 highlight', async () => {
    const el = makeVisibleElement()
    mockWaitForSelector.mockResolvedValue(el)

    const cleanup = runOnboardingTour(makeOptions([makeStep({ isLast: true })]))

    await vi.waitFor(() => expect(mockHighlight).toHaveBeenCalled())
    // highlight 第一个参数应包含 element
    expect(mockHighlight).toHaveBeenCalledWith(
      expect.objectContaining({ element: el }),
    )
    cleanup()
  })

  it('未找到元素 + actionType=click → 重试等待', async () => {
    mockWaitForSelector.mockResolvedValue(null)

    const cleanup = runOnboardingTour(
      makeOptions([makeStep({ actionType: 'click', isLast: true })]),
    )

    // click 类型会先 waitForSelector，失败后 sleep(400)，再 waitForSelector(6000)
    await vi.waitFor(() => expect(mockWaitForSelector).toHaveBeenCalledTimes(2))
    // 未找到元素 → 不调用 highlight
    expect(mockHighlight).not.toHaveBeenCalled()
    cleanup()
  })

  it('未找到元素 + actionType=observe → 不重试', async () => {
    mockWaitForSelector.mockResolvedValue(null)

    const cleanup = runOnboardingTour(
      makeOptions([makeStep({ actionType: 'observe', isLast: true })]),
    )

    await vi.waitFor(() => expect(mockWaitForSelector).toHaveBeenCalled())
    // observe 类型只调用一次 waitForSelector
    await new Promise((r) => setTimeout(r, 100))
    expect(mockWaitForSelector).toHaveBeenCalledTimes(1)
    cleanup()
  })

  it('元素在 sidebar 中 → 额外 sleep + refresh highlight', async () => {
    const sidebar = document.createElement('div')
    sidebar.className = 'sidebar'
    const el = makeVisibleElement()
    sidebar.appendChild(el)
    document.body.appendChild(sidebar)

    mockWaitForSelector.mockResolvedValue(el)

    const cleanup = runOnboardingTour(makeOptions([makeStep({ isLast: true })]))

    // sidebar 元素会调用两次 highlight（初始 + refresh）
    await vi.waitFor(() => expect(mockHighlight).toHaveBeenCalledTimes(2))
    cleanup()
  })
})

describe('runOnboardingTour - demo 回退消息', () => {
  it('demo 失败且有 fallbackMsg → 用 fallback 重新 highlight', async () => {
    const el = makeVisibleElement()
    mockWaitForSelector.mockResolvedValue(el)

    const cleanup = runOnboardingTour(
      makeOptions([
        makeStep({
          isLast: true,
          demo: () => ({ ok: false, fallbackMsg: '回退提示文案' }),
        }),
      ]),
    )

    await vi.waitFor(() => {
      const calls = mockHighlight.mock.calls
      // 找到包含 fallbackMsg 的 highlight 调用
      const fallbackCall = calls.find(
        (call: any[]) => call[0]?.popover?.description === '回退提示文案',
      )
      expect(fallbackCall).toBeDefined()
    })
    cleanup()
  })

  it('demo 成功 → 不触发 fallback highlight', async () => {
    const el = makeVisibleElement()
    mockWaitForSelector.mockResolvedValue(el)

    const cleanup = runOnboardingTour(
      makeOptions([
        makeStep({
          isLast: true,
          demo: () => ({ ok: true }),
        }),
      ]),
    )

    await vi.waitFor(() => expect(mockHighlight).toHaveBeenCalled())
    // 只有初始 highlight，没有 fallback
    const calls = mockHighlight.mock.calls
    const hasFallback = calls.some(
      (call: any[]) => call[0]?.popover?.description === '回退提示文案',
    )
    expect(hasFallback).toBe(false)
    cleanup()
  })
})

describe('runOnboardingTour - isLast 步骤', () => {
  it('isLast 步骤 → 添加完成按钮', async () => {
    const el = makeVisibleElement()
    mockWaitForSelector.mockResolvedValue(el)
    // 需要有 popover footer 才能挂载控件
    setupPopoverWithFooter('driver-popover-footer')

    const onComplete = vi.fn()
    const cleanup = runOnboardingTour({
      steps: [makeStep({ isLast: true })],
      router: makeMockRouter(),
      store: makeMockStore(),
      onComplete,
      onSkip: vi.fn(),
    })

    // 等待控件被挂载
    await vi.waitFor(() => {
      const cta = document.querySelector('.xcagi-tour-extra-controls')
      expect(cta?.querySelector('.xcagi-tour-btn-finish')).not.toBeNull()
    })

    cleanup()
  })

  it('点击完成按钮 → 调用 onComplete', async () => {
    const el = makeVisibleElement()
    mockWaitForSelector.mockResolvedValue(el)
    setupPopoverWithFooter('driver-popover-footer')

    const onComplete = vi.fn()
    const cleanup = runOnboardingTour({
      steps: [makeStep({ isLast: true })],
      router: makeMockRouter(),
      store: makeMockStore(),
      onComplete,
      onSkip: vi.fn(),
    })

    // 等待完成按钮出现
    await vi.waitFor(() => {
      expect(document.querySelector('.xcagi-tour-btn-finish')).not.toBeNull()
    })

    // 点击完成按钮
    const finishBtn = document.querySelector('.xcagi-tour-btn-finish') as HTMLButtonElement
    finishBtn.click()

    expect(onComplete).toHaveBeenCalled()
  })
})

describe('runOnboardingTour - 多步骤流程', () => {
  it('两步骤流程 → 第一步完成后进入第二步', async () => {
    const el = makeVisibleElement()
    mockWaitForSelector.mockResolvedValue(el)
    setupPopoverWithFooter('driver-popover-footer')

    const onComplete = vi.fn()
    const cleanup = runOnboardingTour({
      steps: [
        makeStep({
          id: 'step-1',
          isLast: false,
          duration: 0,
        }),
        makeStep({
          id: 'step-2',
          isLast: true,
        }),
      ],
      router: makeMockRouter(),
      store: makeMockStore(),
      onComplete,
      onSkip: vi.fn(),
    })

    // 等待第二步的完成按钮出现
    await vi.waitFor(
      () => {
        expect(document.querySelector('.xcagi-tour-btn-finish')).not.toBeNull()
      },
      { timeout: 3000 },
    )
    cleanup()
  })

  it('所有步骤完成 → 调用 onComplete', async () => {
    const el = makeVisibleElement()
    mockWaitForSelector.mockResolvedValue(el)

    const onComplete = vi.fn()
    const cleanup = runOnboardingTour({
      steps: [
        makeStep({
          id: 'step-1',
          isLast: false,
          duration: 0,
        }),
      ],
      router: makeMockRouter(),
      store: makeMockStore(),
      onComplete,
      onSkip: vi.fn(),
    })

    // 第一步 duration=0 → waitWithPause 立即返回 → runStep(1) 无 step → onComplete
    await vi.waitFor(() => expect(onComplete).toHaveBeenCalled(), { timeout: 3000 })
    cleanup()
  })
})

describe('runOnboardingTour - skip 与 destroy', () => {
  it('skipRequested 在步骤开始时为 true → 调用 onSkip', async () => {
    const store = makeMockStore({ skipRequested: true })
    const onSkip = vi.fn()
    const cleanup = runOnboardingTour({
      steps: [makeStep({ isLast: false })],
      router: makeMockRouter(),
      store,
      onComplete: vi.fn(),
      onSkip,
    })

    await vi.waitFor(() => expect(onSkip).toHaveBeenCalled(), { timeout: 2000 })
    cleanup()
  })

  it('onDestroyStarted → 触发 cleanup', async () => {
    const el = makeVisibleElement()
    mockWaitForSelector.mockResolvedValue(el)

    const cleanup = runOnboardingTour(makeOptions([makeStep({ isLast: true })]))

    await vi.waitFor(() => expect(mockHighlight).toHaveBeenCalled())

    // 模拟 driver.js 触发 destroyStarted
    capturedDriverConfigRef.value.onDestroyStarted()

    // cleanup 后 tutorial-active class 被移除
    expect(document.body.classList.contains('tutorial-active')).toBe(false)
  })
})

describe('runOnboardingTour - body class', () => {
  it('运行时添加 tutorial-active class', () => {
    const cleanup = runOnboardingTour(makeOptions([makeStep()]))
    expect(document.body.classList.contains('tutorial-active')).toBe(true)
    cleanup()
  })

  it('cleanup 后移除 tutorial-active class', () => {
    const cleanup = runOnboardingTour(makeOptions([makeStep()]))
    cleanup()
    expect(document.body.classList.contains('tutorial-active')).toBe(false)
  })
})

describe('runOnboardingTour - 空步骤', () => {
  it('空步骤 → 立即调用 onSkip', () => {
    const onSkip = vi.fn()
    const onComplete = vi.fn()
    const cleanup = runOnboardingTour({
      steps: [],
      router: makeMockRouter(),
      store: makeMockStore(),
      onComplete,
      onSkip,
    })

    expect(onSkip).toHaveBeenCalled()
    expect(onComplete).not.toHaveBeenCalled()
    cleanup()
  })
})

describe('runOnboardingTour - cleanup 幂等性', () => {
  it('多次调用 cleanup 不抛错', () => {
    const cleanup = runOnboardingTour(makeOptions([makeStep()]))
    cleanup()
    expect(() => cleanup()).not.toThrow()
  })

  it('cleanup 时 driver.destroy() 抛错 → catch 分支不中断', () => {
    // 让 mockDestroy 抛错以覆盖 catch 分支（line 46-48）
    mockDestroy.mockImplementation(() => {
      throw new Error('destroy error')
    })

    const cleanup = runOnboardingTour(makeOptions([makeStep()]))
    // 调用 cleanup 触发 destroy 抛错，但不应中断
    expect(() => cleanup()).not.toThrow()
  })
})

describe('runOnboardingTour - waitWithPause 分支', () => {
  it('paused 状态下等待 → 走 paused 分支并最终 skip', async () => {
    // 控制 Date.now 以使 while 循环可终止
    let currentTime = 0
    const dateSpy = vi.spyOn(Date, 'now').mockImplementation(() => currentTime)

    const store = makeMockStore({ paused: true })
    const onSkip = vi.fn()

    // mockSleep: 推进时间，第 2 次后设置 skipRequested 以退出循环
    let sleepCallCount = 0
    mockSleep.mockImplementation(async (ms: number) => {
      sleepCallCount++
      currentTime += ms
      if (sleepCallCount >= 2) {
        store.skipRequested = true
      }
      return undefined
    })

    const cleanup = runOnboardingTour({
      steps: [makeStep({ isLast: false, duration: 500 })],
      router: makeMockRouter(),
      store,
      onComplete: vi.fn(),
      onSkip,
    })

    // waitWithPause 返回 false → 走 cleanup + onSkip 分支（lines 199-201）
    await vi.waitFor(() => expect(onSkip).toHaveBeenCalled(), { timeout: 3000 })
    dateSpy.mockRestore()
    cleanup()
  })

  it('正常等待完成 → 走 normal sleep 分支并进入下一步', async () => {
    let currentTime = 0
    const dateSpy = vi.spyOn(Date, 'now').mockImplementation(() => currentTime)

    const onComplete = vi.fn()

    // mockSleep: 每次推进时间，模拟真实 sleep 行为
    mockSleep.mockImplementation(async (ms: number) => {
      currentTime += ms
      return undefined
    })

    const cleanup = runOnboardingTour({
      steps: [makeStep({ isLast: false, duration: 500 })],
      router: makeMockRouter(),
      store: makeMockStore(),
      onComplete,
      onSkip: vi.fn(),
    })

    // waitWithPause 正常完成 → 返回 true → runStep(1) → 无 step → onComplete
    await vi.waitFor(() => expect(onComplete).toHaveBeenCalled(), { timeout: 3000 })
    dateSpy.mockRestore()
    cleanup()
  })
})
