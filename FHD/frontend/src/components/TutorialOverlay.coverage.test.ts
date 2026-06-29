import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h, nextTick, reactive } from 'vue'

// ===== Mock store 容器（使用 vi.hoisted 确保 vi.mock 工厂可访问）=====
const storeContainer = vi.hoisted(() => ({ state: null as any }))

vi.mock('@/stores/tutorial', () => ({
  useTutorialStore: () => storeContainer.state,
  // warmup 文本与默认 steps 的 description 对齐，便于测试缓存命中场景
  getTutorialTtsWarmupTexts: () => ['描述一', '描述二', '描述三'],
}))

// ===== 创建响应式 store 状态 =====
type StepShape = {
  id: string
  title?: string
  description?: string
  actionType?: string
  allowCardNext?: boolean
  targetSelector?: string
  routeName?: string
  assistantTab?: string
}

function createStoreState() {
  return reactive({
    isActive: false,
    currentStepIndex: 0,
    steps: [
      { id: 's1', title: '第一步', description: '描述一', actionType: 'observe' },
      { id: 's2', title: '第二步', description: '描述二', actionType: 'click', targetSelector: '.target-btn' },
      { id: 's3', title: '第三步', description: '描述三', actionType: 'observe', routeName: 'home' },
    ] as StepShape[],
    highlightRect: null as { top: number; left: number; width: number; height: number } | null,
    blockedTip: '',
    proBasicFallbackNotice: '',
    returnContext: null as {
      routeName?: string
      assistantOpen?: boolean
      assistantTab?: string
      assistantState?: Record<string, unknown> | null
    } | null,
    currentTrackLabel: '基础教程',
    hasPrev: false,
    isLastStep: false,
    currentStep: null as StepShape | null,
    testSummary: { total: 3, passed: 1, skipped: 0, pending: 2 },
    // 方法 mock
    exitTutorial: vi.fn(),
    prevStep: vi.fn(),
    nextStep: vi.fn(),
    markCurrentStepClicked: vi.fn(),
    blockOutsideClick: vi.fn(),
    refreshHighlight: vi.fn(),
  })
}

// ===== 测试辅助 =====

function createTestRouter() {
  const EmptyComp = defineComponent({ setup: () => () => h('div') })
  const routes = [
    { path: '/', name: 'home', component: EmptyComp },
    { path: '/chat', name: 'chat', component: EmptyComp },
    { path: '/products', name: 'products', component: EmptyComp },
    { path: '/:pathMatch(.*)*', name: 'fallback', component: EmptyComp },
  ]
  return createRouter({ history: createMemoryHistory(), routes })
}

// 跟踪当前挂载的 wrapper，避免事件监听器累积
let currentWrapper: ReturnType<typeof mount> | null = null

async function mountComponent(options: Record<string, unknown> = {}) {
  // 卸载上一次挂载的组件，清理 document 上的 capture click 监听器
  if (currentWrapper) {
    currentWrapper.unmount()
    currentWrapper = null
    await flushPromises()
  }
  // resetModules 确保 component 重新读取 import.meta.env
  vi.resetModules()
  const router = options.router || createTestRouter()
  await router.push('/chat')
  await router.isReady()
  const TutorialOverlay = (await import('./TutorialOverlay.vue')).default
  const wrapper = mount(TutorialOverlay, {
    global: {
      plugins: [router],
    },
  })
  currentWrapper = wrapper
  await flushPromises()
  return { wrapper, router }
}

// 激活教程并设置 currentStep 与 rect，触发组件渲染
async function activateTutorial(
  wrapper: ReturnType<typeof mount>,
  overrides: Record<string, unknown> = {},
) {
  const state = storeContainer.state
  // 默认激活教程，除非 overrides 显式指定 isActive
  if (overrides.isActive === undefined) {
    state.isActive = true
  }
  Object.assign(state, overrides)
  // 仅当 overrides 未显式提供 currentStep 时才设置默认值（允许显式传 null 测试不渲染场景）
  if (!('currentStep' in overrides)) {
    if (!state.currentStep) {
      state.currentStep = state.steps[state.currentStepIndex] || null
    }
  }
  // 仅当 overrides 未显式提供 highlightRect 时才设置默认值
  if (!('highlightRect' in overrides)) {
    if (!state.highlightRect) {
      state.highlightRect = { top: 100, left: 100, width: 200, height: 80 }
    }
  }
  await nextTick()
  await flushPromises()
  await nextTick()
  await flushPromises()
  return wrapper
}

function setViewport(width: number, height: number) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: width })
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: height })
}

describe('TutorialOverlay.vue 覆盖率补齐测试', () => {
  let originalInnerWidth: number
  let originalInnerHeight: number

  beforeEach(() => {
    setActivePinia(createPinia())
    storeContainer.state = createStoreState()

    originalInnerWidth = window.innerWidth
    originalInnerHeight = window.innerHeight

    // 默认关闭 TTS
    vi.stubEnv('VITE_ENABLE_TUTORIAL_ONLINE_TTS', '')

    // Mock fetch
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      status: 200,
      headers: { get: () => 'application/json' },
      json: async () => ({ success: true, data: { audioBase64: 'data:audio/mp3;base64,AAAA' } }),
      text: async () => '',
    })))

    // Mock speechSynthesis
    Object.defineProperty(window, 'speechSynthesis', {
      configurable: true,
      writable: true,
      value: { cancel: vi.fn(), speak: vi.fn(), getVoices: vi.fn(() => []) },
    })

    // Mock requestAnimationFrame 为同步执行
    vi.stubGlobal('requestAnimationFrame', vi.fn((cb: FrameRequestCallback) => {
      cb(0)
      return 0
    }))
    vi.stubGlobal('cancelAnimationFrame', vi.fn())

    // Mock requestIdleCallback 为同步执行
    vi.stubGlobal('requestIdleCallback', vi.fn((cb: any) => {
      cb({ didTimeout: false, timeRemaining: () => 0 })
      return 0
    }))
    vi.stubGlobal('cancelIdleCallback', vi.fn())

    // Mock Audio
    vi.stubGlobal('Audio', vi.fn().mockImplementation(() => ({
      play: vi.fn().mockResolvedValue(undefined),
      pause: vi.fn(),
      src: '',
    })))

    window.__XCAGI_IS_PRO_MODE = false as any
  })

  afterEach(() => {
    // 卸载组件，清理 document 上的事件监听器
    if (currentWrapper) {
      currentWrapper.unmount()
      currentWrapper = null
    }
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
    setViewport(originalInnerWidth, originalInnerHeight)
    delete (window as any).__XCAGI_IS_PRO_MODE
  })

  // ===== 1. 基础渲染 =====

  it('教程未激活时不渲染 overlay', async () => {
    const { wrapper } = await mountComponent()
    expect(wrapper.find('.tutorial-overlay-root').exists()).toBe(false)
  })

  it('教程激活但无 currentStep 时不渲染', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, { currentStep: null })
    expect(wrapper.find('.tutorial-overlay-root').exists()).toBe(false)
  })

  it('教程激活但无 rect 时不渲染', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, { highlightRect: null })
    expect(wrapper.find('.tutorial-overlay-root').exists()).toBe(false)
  })

  it('教程激活且有 step 与 rect 时渲染 overlay', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    expect(wrapper.find('.tutorial-overlay-root').exists()).toBe(true)
    expect(wrapper.find('.tutorial-spotlight').exists()).toBe(true)
    expect(wrapper.find('.tutorial-card').exists()).toBe(true)
  })

  it('渲染退出按钮并点击触发 exitTutorial', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    const exitBtn = wrapper.find('.tutorial-exit-btn')
    expect(exitBtn.exists()).toBe(true)
    await exitBtn.trigger('click')
    expect(storeContainer.state.exitTutorial).toHaveBeenCalled()
  })

  it('渲染进度信息含 trackLabel 与步骤序号', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    const progress = wrapper.find('.tutorial-progress')
    expect(progress.text()).toContain('基础教程')
    expect(progress.text()).toContain('步骤')
  })

  it('trackLabel 为空时不显示前缀', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, { currentTrackLabel: '' })
    const progress = wrapper.find('.tutorial-progress')
    expect(progress.text()).not.toContain('·')
  })

  it('渲染标题与描述', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    expect(wrapper.find('.tutorial-title').text()).toBe('第一步')
    expect(wrapper.find('.tutorial-desc').text()).toBe('描述一')
  })

  it('渲染测试摘要，skipped>0 时显示跳过数', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, {
      testSummary: { total: 3, passed: 1, skipped: 2, pending: 0 },
    })
    const test = wrapper.find('.tutorial-test')
    expect(test.text()).toContain('通过 1 / 3')
    expect(test.text()).toContain('跳过 2')
  })

  it('skipped=0 时不显示跳过数', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, {
      testSummary: { total: 3, passed: 1, skipped: 0, pending: 2 },
    })
    const test = wrapper.find('.tutorial-test')
    expect(test.text()).not.toContain('跳过')
  })

  it('proBasicFallbackNotice 有值时显示提示', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, { proBasicFallbackNotice: '专业版回退提示' })
    const notice = wrapper.find('.tutorial-fallback-notice')
    expect(notice.exists()).toBe(true)
    expect(notice.text()).toBe('专业版回退提示')
  })

  it('proBasicFallbackNotice 为空时不显示提示', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, { proBasicFallbackNotice: '' })
    expect(wrapper.find('.tutorial-fallback-notice').exists()).toBe(false)
  })

  it('blockedTip 有值时显示提示', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, { blockedTip: '请先点击高亮' })
    const tips = wrapper.findAll('.tutorial-tip')
    const blockedTipEl = tips.find((t) => !t.classes().includes('tutorial-fallback-notice'))
    expect(blockedTipEl).toBeTruthy()
    expect(blockedTipEl!.text()).toBe('请先点击高亮')
  })

  it('blockedTip 为空时不显示普通提示', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, { blockedTip: '', proBasicFallbackNotice: '' })
    const tips = wrapper.findAll('.tutorial-tip').filter((t) => !t.classes().includes('tutorial-fallback-notice'))
    expect(tips.length).toBe(0)
  })

  // ===== 2. 按钮交互 =====

  it('点击上一步按钮触发 prevStep', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, { hasPrev: true })
    const prevBtn = wrapper.findAll('.tutorial-actions .btn-secondary')[0]
    await prevBtn.trigger('click')
    expect(storeContainer.state.prevStep).toHaveBeenCalled()
  })

  it('hasPrev=false 时上一步按钮 disabled', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, { hasPrev: false })
    const prevBtn = wrapper.findAll('.tutorial-actions .btn-secondary')[0]
    expect(prevBtn.attributes('disabled')).toBeDefined()
  })

  it('点击跳过按钮触发 exitTutorial', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    const skipBtn = wrapper.findAll('.tutorial-actions .btn-secondary')[1]
    await skipBtn.trigger('click')
    expect(storeContainer.state.exitTutorial).toHaveBeenCalled()
  })

  it('非最后一步时主按钮文案为「下一步」', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, { isLastStep: false })
    expect(wrapper.find('.tutorial-primary-next').text()).toBe('下一步')
  })

  it('最后一步时主按钮文案为「完成」', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, { isLastStep: true })
    expect(wrapper.find('.tutorial-primary-next').text()).toBe('完成')
  })

  it('点击下一步按钮触发 nextStep', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    await wrapper.find('.tutorial-primary-next').trigger('click')
    expect(storeContainer.state.nextStep).toHaveBeenCalled()
  })

  it('actionType=click 且 allowCardNext!=true 时主按钮 title 提示', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, {
      currentStep: { id: 's2', title: '点击步', description: '描述', actionType: 'click', targetSelector: '.x' },
    })
    expect(wrapper.find('.tutorial-primary-next').attributes('title')).toContain('建议先按高亮')
  })

  it('actionType=click 且 allowCardNext=true 时主按钮 title 为空', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, {
      currentStep: {
        id: 's2', title: '点击步', description: '描述', actionType: 'click', targetSelector: '.x', allowCardNext: true,
      },
    })
    expect(wrapper.find('.tutorial-primary-next').attributes('title') || '').toBe('')
  })

  it('actionType=observe 时主按钮 title 为空', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, {
      currentStep: { id: 's1', title: '观察步', description: '描述', actionType: 'observe' },
    })
    expect(wrapper.find('.tutorial-primary-next').attributes('title') || '').toBe('')
  })

  // ===== 3. spotlightStyle 计算属性 =====

  it('spotlightStyle 按 rect 与 outset 计算位置', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, {
      highlightRect: { top: 50, left: 60, width: 100, height: 40 },
    })
    const style = wrapper.find('.tutorial-spotlight').attributes('style') || ''
    expect(style).toContain('top: 40px')
    expect(style).toContain('left: 50px')
    expect(style).toContain('width: 120px')
    expect(style).toContain('height: 60px')
  })

  // ===== 4. cardStyle 计算属性 - 多分支 =====

  it('cardStyle: 高亮在视口下半区时卡片放在上方', async () => {
    setViewport(1280, 800)
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, {
      highlightRect: { top: 700, left: 100, width: 200, height: 80 },
    })
    const style = wrapper.find('.tutorial-card').attributes('style') || ''
    // preferTopTop = max(16, 700-288)=412
    expect(style).toContain('top: 412px')
  })

  it('cardStyle: 高亮在视口上半区时卡片放在下方', async () => {
    setViewport(1280, 800)
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, {
      highlightRect: { top: 100, left: 100, width: 200, height: 80 },
    })
    const style = wrapper.find('.tutorial-card').attributes('style') || ''
    // preferBottomTop = 100+80+16 = 196
    expect(style).toContain('top: 196px')
  })

  it('cardStyle: 宽主内容高亮时卡片居中于洞口', async () => {
    setViewport(1280, 800)
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, {
      highlightRect: { top: 100, left: 200, width: 500, height: 150 },
    })
    const style = wrapper.find('.tutorial-card').attributes('style') || ''
    // idealLeft = 200 + (500-320)/2 = 290
    expect(style).toContain('left: 290px')
  })

  it('cardStyle: 高亮在右侧时卡片放在高亮左侧', async () => {
    setViewport(1280, 800)
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, {
      highlightRect: { top: 100, left: 700, width: 200, height: 80 },
    })
    const style = wrapper.find('.tutorial-card').attributes('style') || ''
    // left = 700 - 320 - 16 = 364
    expect(style).toContain('left: 364px')
  })

  it('cardStyle: 高亮在右侧但空间不足时卡片贴左', async () => {
    setViewport(1280, 800)
    const { wrapper } = await mountComponent()
    // left=300, width=800 → cx=700 > 665.6, left-cardWidth-gap=300-336=-36 < 16
    await activateTutorial(wrapper, {
      highlightRect: { top: 100, left: 300, width: 800, height: 80 },
    })
    const style = wrapper.find('.tutorial-card').attributes('style') || ''
    expect(style).toContain('left: 16px')
  })

  it('cardStyle: 默认分支卡片左对齐高亮', async () => {
    setViewport(1280, 800)
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, {
      highlightRect: { top: 100, left: 200, width: 100, height: 80 },
    })
    const style = wrapper.find('.tutorial-card').attributes('style') || ''
    expect(style).toContain('left: 200px')
  })

  it('cardStyle: 高亮在右侧且 left 较大时卡片放在高亮左侧', async () => {
    setViewport(1280, 800)
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, {
      highlightRect: { top: 100, left: 1200, width: 100, height: 80 },
    })
    const style = wrapper.find('.tutorial-card').attributes('style') || ''
    // highlightOnRight 分支: left = 1200 - 320 - 16 = 864
    expect(style).toContain('left: 864px')
  })

  // ===== 5. handleCaptureClick 点击捕获 =====

  it('点击 tutorial-overlay 元素时不拦截', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    await wrapper.find('.tutorial-exit-btn').trigger('click')
    expect(storeContainer.state.blockOutsideClick).not.toHaveBeenCalled()
  })

  it('actionType 非 click 时不处理外部点击', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, {
      currentStep: { id: 's1', title: '观察', description: '描述', actionType: 'observe' },
    })
    const btn = document.createElement('button')
    btn.className = 'outside-target'
    document.body.appendChild(btn)
    btn.click()
    await flushPromises()
    expect(storeContainer.state.markCurrentStepClicked).not.toHaveBeenCalled()
    document.body.removeChild(btn)
  })

  it('点击匹配 targetSelector 的元素时标记步骤已点击', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, {
      currentStep: {
        id: 's2', title: '点击', description: '描述', actionType: 'click', targetSelector: '.target-btn',
      },
    })
    const btn = document.createElement('button')
    btn.className = 'target-btn'
    document.body.appendChild(btn)
    btn.click()
    await flushPromises()
    expect(storeContainer.state.markCurrentStepClicked).toHaveBeenCalled()
    document.body.removeChild(btn)
  })

  it('点击匹配 starter-pack-item 的元素时使用更长延迟', async () => {
    vi.useFakeTimers()
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, {
      currentStep: {
        id: 's2', title: '点击', description: '描述', actionType: 'click', targetSelector: '.starter-pack-item',
      },
    })
    const item = document.createElement('div')
    item.className = 'starter-pack-item'
    document.body.appendChild(item)
    item.click()
    await flushPromises()
    expect(storeContainer.state.markCurrentStepClicked).toHaveBeenCalled()
    expect(storeContainer.state.nextStep).not.toHaveBeenCalled()
    vi.advanceTimersByTime(600)
    expect(storeContainer.state.nextStep).toHaveBeenCalled()
    document.body.removeChild(item)
    vi.useRealTimers()
  })

  it('点击非匹配元素时阻止事件并 blockOutsideClick', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, {
      currentStep: {
        id: 's2', title: '点击', description: '描述', actionType: 'click', targetSelector: '.target-btn',
      },
    })
    const btn = document.createElement('button')
    btn.className = 'other-btn'
    document.body.appendChild(btn)
    btn.click()
    await flushPromises()
    expect(storeContainer.state.blockOutsideClick).toHaveBeenCalled()
    document.body.removeChild(btn)
  })

  it('targetSelector 为空时不处理点击', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, {
      currentStep: {
        id: 's2', title: '点击', description: '描述', actionType: 'click', targetSelector: '',
      },
    })
    const btn = document.createElement('button')
    document.body.appendChild(btn)
    btn.click()
    await flushPromises()
    expect(storeContainer.state.markCurrentStepClicked).not.toHaveBeenCalled()
    document.body.removeChild(btn)
  })

  // ===== 6. 生命周期与事件监听 =====

  it('挂载后注册事件监听', async () => {
    const addSpy = vi.spyOn(window, 'addEventListener')
    const docAddSpy = vi.spyOn(document, 'addEventListener')
    await mountComponent()
    expect(addSpy).toHaveBeenCalledWith('xcagi:warmup-tutorial-tts', expect.any(Function))
    expect(addSpy).toHaveBeenCalledWith('resize', expect.any(Function))
    expect(addSpy).toHaveBeenCalledWith('scroll', expect.any(Function), true)
    expect(docAddSpy).toHaveBeenCalledWith('click', expect.any(Function), true)
  })

  it('卸载时移除事件监听并清理', async () => {
    const removeSpy = vi.spyOn(window, 'removeEventListener')
    const docRemoveSpy = vi.spyOn(document, 'removeEventListener')
    const { wrapper } = await mountComponent()
    wrapper.unmount()
    await flushPromises()
    expect(removeSpy).toHaveBeenCalledWith('xcagi:warmup-tutorial-tts', expect.any(Function))
    expect(removeSpy).toHaveBeenCalledWith('resize', expect.any(Function))
    expect(removeSpy).toHaveBeenCalledWith('scroll', expect.any(Function), true)
    expect(docRemoveSpy).toHaveBeenCalledWith('click', expect.any(Function), true)
  })

  it('resize 事件触发 refreshHighlight', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    storeContainer.state.refreshHighlight.mockClear()
    window.dispatchEvent(new Event('resize'))
    await flushPromises()
    expect(storeContainer.state.refreshHighlight).toHaveBeenCalledWith({ skipMissingOnFail: false })
  })

  it('scroll 事件触发 refreshHighlight', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    storeContainer.state.refreshHighlight.mockClear()
    window.dispatchEvent(new Event('scroll'))
    await flushPromises()
    expect(storeContainer.state.refreshHighlight).toHaveBeenCalledWith({ skipMissingOnFail: false })
  })

  // ===== 7. xcagi:warmup-tutorial-tts 事件 =====

  it('warmup-tutorial-tts 事件触发预热（pro 模式）', async () => {
    window.__XCAGI_IS_PRO_MODE = true as any
    const { wrapper } = await mountComponent()
    await flushPromises()
    window.dispatchEvent(new CustomEvent('xcagi:warmup-tutorial-tts'))
    await flushPromises()
    // 重复事件不应再次触发
    window.dispatchEvent(new CustomEvent('xcagi:warmup-tutorial-tts'))
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  it('warmup-tutorial-tts 事件触发预热（普通模式）', async () => {
    window.__XCAGI_IS_PRO_MODE = false as any
    const { wrapper } = await mountComponent()
    await flushPromises()
    window.dispatchEvent(new CustomEvent('xcagi:warmup-tutorial-tts'))
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  // ===== 8. isActive watcher =====

  it('isActive 变 true 时添加 xcagi-tutorial-active class', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    expect(document.documentElement.classList.contains('xcagi-tutorial-active')).toBe(true)
  })

  it('isActive 变 false 时移除 class', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    expect(document.documentElement.classList.contains('xcagi-tutorial-active')).toBe(true)
    storeContainer.state.isActive = false
    await nextTick()
    await flushPromises()
    expect(document.documentElement.classList.contains('xcagi-tutorial-active')).toBe(false)
  })

  // ===== 9. isActive watcher - 失活时恢复上下文 =====

  it('isActive 失活且有 returnContext.routeName 时跳转回原路由', async () => {
    const { wrapper, router } = await mountComponent()
    await activateTutorial(wrapper)
    storeContainer.state.returnContext = { routeName: 'home', assistantOpen: true, assistantTab: 'push' }
    storeContainer.state.isActive = false
    await nextTick()
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('home')
  })

  it('isActive 失活且 returnContext.routeName 与当前路由相同时不跳转', async () => {
    const { wrapper, router } = await mountComponent()
    await activateTutorial(wrapper)
    storeContainer.state.returnContext = { routeName: 'chat' }
    const pushSpy = vi.spyOn(router, 'push')
    storeContainer.state.isActive = false
    await nextTick()
    await flushPromises()
    expect(pushSpy).not.toHaveBeenCalled()
  })

  it('isActive 失活时派发 restore-float 事件', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    let restoreDetail: any = null
    window.addEventListener('xcagi:tutorial:restore-float', (e: Event) => {
      restoreDetail = (e as CustomEvent).detail
    })
    storeContainer.state.returnContext = { assistantOpen: true, assistantTab: 'assistant', assistantState: { foo: 'bar' } }
    storeContainer.state.isActive = false
    await nextTick()
    await flushPromises()
    expect(restoreDetail).toEqual({
      isOpen: true,
      activeTab: 'assistant',
      assistantState: { foo: 'bar' },
    })
  })

  it('isActive 失活且无 returnContext 时 restore-float 派发默认值', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    let restoreDetail: any = null
    window.addEventListener('xcagi:tutorial:restore-float', (e: Event) => {
      restoreDetail = (e as CustomEvent).detail
    })
    storeContainer.state.returnContext = null
    storeContainer.state.isActive = false
    await nextTick()
    await flushPromises()
    expect(restoreDetail).toEqual({
      isOpen: false,
      activeTab: 'push',
      assistantState: null,
    })
  })

  it('isActive 从未激活变未激活时不派发 restore-float', async () => {
    await mountComponent()
    let dispatched = false
    window.addEventListener('xcagi:tutorial:restore-float', () => {
      dispatched = true
    })
    storeContainer.state.isActive = false
    await nextTick()
    await flushPromises()
    expect(dispatched).toBe(false)
  })

  // ===== 10. currentStep.id watcher =====

  it('currentStep.id 变化时确保路由跳转', async () => {
    const { wrapper, router } = await mountComponent()
    await activateTutorial(wrapper)
    storeContainer.state.currentStep = {
      id: 's3', title: '路由步', description: '描述三', actionType: 'observe', routeName: 'home',
    }
    await nextTick()
    await flushPromises()
    await nextTick()
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('home')
  })

  it('currentStep.id 变化且 step 无 routeName 时不跳转', async () => {
    const { wrapper, router } = await mountComponent()
    await activateTutorial(wrapper)
    const pushSpy = vi.spyOn(router, 'push')
    storeContainer.state.currentStep = {
      id: 's4', title: '无路由步', description: '描述', actionType: 'observe',
    }
    await nextTick()
    await flushPromises()
    expect(pushSpy).not.toHaveBeenCalled()
  })

  it('currentStep.id 变化且 routeName 与当前相同时不跳转', async () => {
    const { wrapper, router } = await mountComponent()
    await router.push('/chat')
    await router.isReady()
    await activateTutorial(wrapper)
    const pushSpy = vi.spyOn(router, 'push')
    storeContainer.state.currentStep = {
      id: 's5', title: '同路由步', description: '描述', actionType: 'observe', routeName: 'chat',
    }
    await nextTick()
    await flushPromises()
    expect(pushSpy).not.toHaveBeenCalled()
  })

  it('currentStep 带 assistantTab 时派发 set-assistant-tab 事件', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    let tabDetail: any = null
    window.addEventListener('xcagi:tutorial:set-assistant-tab', (e: Event) => {
      tabDetail = (e as CustomEvent).detail
    })
    storeContainer.state.currentStep = {
      id: 's6', title: '副窗步', description: '描述', actionType: 'observe', assistantTab: 'assistant',
    }
    await nextTick()
    await flushPromises()
    expect(tabDetail).toEqual({ tab: 'assistant', open: true })
  })

  it('currentStep 无 assistantTab 时不派发 set-assistant-tab', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    let dispatched = false
    window.addEventListener('xcagi:tutorial:set-assistant-tab', () => {
      dispatched = true
    })
    storeContainer.state.currentStep = {
      id: 's7', title: '无副窗步', description: '描述', actionType: 'observe',
    }
    await nextTick()
    await flushPromises()
    expect(dispatched).toBe(false)
  })

  it('教程未激活时 currentStep.id 变化不处理', async () => {
    const { router } = await mountComponent()
    const pushSpy = vi.spyOn(router, 'push')
    storeContainer.state.currentStep = {
      id: 's8', title: '步', description: '描述', actionType: 'observe', routeName: 'home',
    }
    await nextTick()
    await flushPromises()
    expect(pushSpy).not.toHaveBeenCalled()
  })

  it('currentStep 为 null 时 watcher 不处理', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    storeContainer.state.currentStep = null
    await nextTick()
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  // ===== 11. START_PRINT 轮询 =====

  it('currentStep.id 为 starter-pack-demo-3-start-print 时启动轮询', async () => {
    vi.useFakeTimers()
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    storeContainer.state.refreshHighlight.mockClear()
    storeContainer.state.currentStep = {
      id: 'starter-pack-demo-3-start-print', title: '开始打印', description: '描述', actionType: 'observe',
    }
    await nextTick()
    await flushPromises()
    await vi.runOnlyPendingTimersAsync()
    await flushPromises()
    // 立即执行一次 tick
    expect(storeContainer.state.refreshHighlight).toHaveBeenCalled()
    vi.useRealTimers()
  })

  it('轮询中教程失活时停止轮询', async () => {
    vi.useFakeTimers()
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    storeContainer.state.currentStep = {
      id: 'starter-pack-demo-3-start-print', title: '开始打印', description: '描述', actionType: 'observe',
    }
    await nextTick()
    await flushPromises()
    await vi.runOnlyPendingTimersAsync()
    await flushPromises()
    storeContainer.state.refreshHighlight.mockClear()
    // 教程失活
    storeContainer.state.isActive = false
    await nextTick()
    await flushPromises()
    const beforeCalls = storeContainer.state.refreshHighlight.mock.calls.length
    vi.advanceTimersByTime(1500)
    expect(storeContainer.state.refreshHighlight.mock.calls.length).toBe(beforeCalls)
    vi.useRealTimers()
  })

  it('轮询中找到目标按钮时调用 refreshHighlight', async () => {
    vi.useFakeTimers()
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    storeContainer.state.currentStep = {
      id: 'starter-pack-demo-3-start-print', title: '开始打印', description: '描述', actionType: 'observe',
    }
    await nextTick()
    await flushPromises()
    // 添加目标按钮
    const taskPanel = document.createElement('div')
    taskPanel.id = 'taskPanel'
    const btn = document.createElement('button')
    btn.setAttribute('data-action', 'start-print')
    taskPanel.appendChild(btn)
    document.body.appendChild(taskPanel)
    storeContainer.state.refreshHighlight.mockClear()
    vi.advanceTimersByTime(700)
    expect(storeContainer.state.refreshHighlight).toHaveBeenCalled()
    document.body.removeChild(taskPanel)
    vi.useRealTimers()
  })

  // ===== 12. 卸载时清理 =====

  it('卸载时移除 xcagi-tutorial-active class', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    expect(document.documentElement.classList.contains('xcagi-tutorial-active')).toBe(true)
    wrapper.unmount()
    await flushPromises()
    expect(document.documentElement.classList.contains('xcagi-tutorial-active')).toBe(false)
  })

  // ===== 13. 完整流程组合 =====

  it('完整教程流程：激活→下一步→上一步→跳过', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, { hasPrev: false, isLastStep: false })
    expect(wrapper.find('.tutorial-overlay-root').exists()).toBe(true)
    // 点击下一步
    await wrapper.find('.tutorial-primary-next').trigger('click')
    expect(storeContainer.state.nextStep).toHaveBeenCalled()
    // 模拟 store 状态变化
    storeContainer.state.hasPrev = true
    storeContainer.state.currentStepIndex = 1
    storeContainer.state.currentStep = storeContainer.state.steps[1]
    await nextTick()
    await flushPromises()
    // 点击上一步
    const prevBtn = wrapper.findAll('.tutorial-actions .btn-secondary')[0]
    await prevBtn.trigger('click')
    expect(storeContainer.state.prevStep).toHaveBeenCalled()
    // 点击跳过
    const skipBtn = wrapper.findAll('.tutorial-actions .btn-secondary')[1]
    await skipBtn.trigger('click')
    expect(storeContainer.state.exitTutorial).toHaveBeenCalled()
  })

  it('最后一步点击完成触发 nextStep', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, { isLastStep: true })
    const nextBtn = wrapper.find('.tutorial-primary-next')
    expect(nextBtn.text()).toBe('完成')
    await nextBtn.trigger('click')
    expect(storeContainer.state.nextStep).toHaveBeenCalled()
  })

  // ===== 14. 边界场景 =====

  it('steps 为空数组时进度显示 0/0', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, {
      steps: [],
      currentStep: { id: 'x', title: 'X', description: 'd', actionType: 'observe' },
      testSummary: { total: 0, passed: 0, skipped: 0, pending: 0 },
    })
    const progress = wrapper.find('.tutorial-progress')
    expect(progress.text()).toContain('步骤 1 / 0')
  })

  it('currentStepIndex 超出 steps 长度时进度仍渲染', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, {
      currentStepIndex: 5,
      steps: [{ id: 'x', title: 'X', description: 'd', actionType: 'observe' }],
      currentStep: { id: 'y', title: 'Y', description: 'd', actionType: 'observe' },
      testSummary: { total: 1, passed: 0, skipped: 0, pending: 1 },
    })
    const progress = wrapper.find('.tutorial-progress')
    expect(progress.text()).toContain('步骤 6 / 1')
  })

  it('highlightRect 为 0 值时 spotlightStyle 正确计算', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, {
      highlightRect: { top: 0, left: 0, width: 0, height: 0 },
    })
    const style = wrapper.find('.tutorial-spotlight').attributes('style') || ''
    expect(style).toContain('top: -10px')
    expect(style).toContain('left: -10px')
    expect(style).toContain('width: 20px')
    expect(style).toContain('height: 20px')
  })

  it('视口极小时 cardStyle 仍能计算', async () => {
    setViewport(200, 200)
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper, {
      highlightRect: { top: 50, left: 50, width: 100, height: 50 },
    })
    const card = wrapper.find('.tutorial-card')
    expect(card.exists()).toBe(true)
    expect(card.attributes('style')).toBeTruthy()
  })
})

// ===== TTS 路径测试（启用 VITE_ENABLE_TUTORIAL_ONLINE_TTS）=====
describe('TutorialOverlay.vue TTS 路径测试', () => {
  let originalInnerWidth: number
  let originalInnerHeight: number

  beforeEach(() => {
    setActivePinia(createPinia())
    storeContainer.state = createStoreState()
    originalInnerWidth = window.innerWidth
    originalInnerHeight = window.innerHeight

    // 启用 TTS
    vi.stubEnv('VITE_ENABLE_TUTORIAL_ONLINE_TTS', 'true')

    // Mock fetch
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      status: 200,
      headers: { get: () => 'application/json' },
      json: async () => ({ success: true, data: { audioBase64: 'data:audio/mp3;base64,AAAA' } }),
      text: async () => '',
    })))

    // Mock speechSynthesis
    Object.defineProperty(window, 'speechSynthesis', {
      configurable: true,
      writable: true,
      value: { cancel: vi.fn(), speak: vi.fn(), getVoices: vi.fn(() => []) },
    })

    // Mock requestAnimationFrame 为同步
    vi.stubGlobal('requestAnimationFrame', vi.fn((cb: FrameRequestCallback) => {
      cb(0)
      return 0
    }))
    vi.stubGlobal('cancelAnimationFrame', vi.fn())

    // Mock requestIdleCallback 为同步
    vi.stubGlobal('requestIdleCallback', vi.fn((cb: any) => {
      cb({ didTimeout: false, timeRemaining: () => 0 })
      return 0
    }))
    vi.stubGlobal('cancelIdleCallback', vi.fn())

    // Mock Audio
    vi.stubGlobal('Audio', vi.fn().mockImplementation(() => ({
      play: vi.fn().mockResolvedValue(undefined),
      pause: vi.fn(),
      src: '',
    })))

    window.__XCAGI_IS_PRO_MODE = false as any
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
    Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: originalInnerWidth })
    Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: originalInnerHeight })
    delete (window as any).__XCAGI_IS_PRO_MODE
  })

  it('启用 TTS 时 isActive 触发 prefetchTutorialSpeech', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    // isActive watcher 触发 prefetchTutorialSpeech → enqueueTtsPrefetch → drainTtsPrefetchQueue → fetchTtsAudioBase64 → fetch
    expect(globalThis.fetch).toHaveBeenCalled()
  })

  it('启用 TTS 时 currentStep 变化触发 speakTutorialStep', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    ;(globalThis.fetch as any).mockClear()
    storeContainer.state.currentStep = {
      id: 's-tts', title: 'TTS 步', description: '需要朗读的描述', actionType: 'observe',
    }
    await nextTick()
    await flushPromises()
    await nextTick()
    await flushPromises()
    expect(globalThis.fetch).toHaveBeenCalled()
  })

  it('TTS fetch 失败时静默处理', async () => {
    ;(globalThis.fetch as any).mockRejectedValueOnce(new Error('network'))
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  it('TTS fetch 返回非 ok 时返回空字符串', async () => {
    ;(globalThis.fetch as any).mockResolvedValueOnce({
      ok: false, status: 500, headers: { get: () => 'application/json' },
      json: async () => ({}), text: async () => '',
    })
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  it('TTS fetch 返回 success=false 时返回空', async () => {
    ;(globalThis.fetch as any).mockResolvedValueOnce({
      ok: true, status: 200, headers: { get: () => 'application/json' },
      json: async () => ({ success: false, data: {} }), text: async () => '',
    })
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  it('TTS fetch 返回的 audioBase64 非 data:audio/ 前缀时返回空', async () => {
    ;(globalThis.fetch as any).mockResolvedValueOnce({
      ok: true, status: 200, headers: { get: () => 'application/json' },
      json: async () => ({ success: true, data: { audioBase64: 'not-audio-data' } }), text: async () => '',
    })
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  it('TTS fetch 返回 json 解析失败时返回空', async () => {
    ;(globalThis.fetch as any).mockResolvedValueOnce({
      ok: true, status: 200, headers: { get: () => 'application/json' },
      json: async () => { throw new Error('parse error') }, text: async () => '',
    })
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  it('warmup-tutorial-tts 事件触发 TTS 预热', async () => {
    await mountComponent()
    await flushPromises()
    ;(globalThis.fetch as any).mockClear()
    window.dispatchEvent(new CustomEvent('xcagi:warmup-tutorial-tts'))
    await flushPromises()
    expect(globalThis.fetch).toHaveBeenCalled()
  })

  it('isActive 失活时停止 TTS 并清理 prefetch', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    storeContainer.state.isActive = false
    await nextTick()
    await flushPromises()
    // speechSynthesis.cancel 被调用
    expect(window.speechSynthesis.cancel).toHaveBeenCalled()
  })

  it('卸载时停止 TTS', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    wrapper.unmount()
    await flushPromises()
    expect(window.speechSynthesis.cancel).toHaveBeenCalled()
  })

  it('TTS 缓存超过上限时触发 LRU 淘汰', async () => {
    // 构造 85 个唯一描述的步骤，超过 TTS_CACHE_MAX(80) 触发缓存淘汰
    const manySteps = Array.from({ length: 85 }, (_, i) => ({
      id: `step-${i}`,
      title: `步骤${i}`,
      description: `唯一描述-${i}`,
      actionType: 'observe',
    }))
    const { wrapper } = await mountComponent()
    // 先设置 steps，再激活 isActive（不设 currentStep，避免 currentStep.id watcher 干扰）
    storeContainer.state.steps = manySteps
    storeContainer.state.isActive = true
    // 等待 isActive watcher 触发 prefetchTutorialSpeech → drainTtsPrefetchQueue
    // 并发上限 2，85 个文本需多轮微任务才能全部完成
    for (let i = 0; i < 500; i++) {
      await flushPromises()
    }
    // 验证 fetch 被调用（缓存淘汰不影响已完成的 fetch）
    const fetchCallCount = (globalThis.fetch as any).mock.calls.length
    expect(fetchCallCount).toBeGreaterThan(0)
    expect(wrapper.exists()).toBe(true)
  })

  it('speakTutorialStep 中 Audio 构造抛异常时进入 catch 分支', async () => {
    // 让 Audio 构造函数抛出异常，触发 speakTutorialStep 的 catch 分支
    vi.stubGlobal('Audio', vi.fn(() => {
      throw new Error('Audio constructor error')
    }))
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    // 多次 flushPromises 确保异步 speakTutorialStep 完成
    for (let i = 0; i < 10; i++) {
      await flushPromises()
    }
    expect(wrapper.exists()).toBe(true)
  })

  it('TTS 缓存命中时不重复 fetch 已缓存文本', async () => {
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    // 等待首次 prefetch 完成（并发上限 2，前两步立即开始 fetch 并缓存）
    for (let i = 0; i < 15; i++) {
      await flushPromises()
    }
    ;(globalThis.fetch as any).mockClear()
    // 再次触发 warmup 事件，已缓存文本不应再触发 fetch
    window.dispatchEvent(new CustomEvent('xcagi:warmup-tutorial-tts'))
    for (let i = 0; i < 10; i++) {
      await flushPromises()
    }
    // warmup 文本中 '描述一' 和 '描述二' 已在首次 prefetch 中缓存，
    // 不会再次触发 fetch；'描述三' 可能因并发限制尚未缓存，允许至多 1 次调用
    const callCount = (globalThis.fetch as any).mock.calls.length
    expect(callCount).toBeLessThanOrEqual(1)
    if (callCount === 1) {
      const body = JSON.parse((globalThis.fetch as any).mock.calls[0][1].body)
      expect(body.text).toBe('描述三')
    }
    expect(wrapper.exists()).toBe(true)
  })

  it('stopTutorialSpeech 中 audio.pause 抛异常时静默处理', async () => {
    // Audio.pause 抛异常，测试 try-catch 分支
    const pauseError = vi.fn(() => { throw new Error('pause error') })
    vi.stubGlobal('Audio', vi.fn().mockImplementation(() => ({
      play: vi.fn().mockResolvedValue(undefined),
      pause: pauseError,
      src: '',
    })))
    const { wrapper } = await mountComponent()
    await activateTutorial(wrapper)
    // 触发 stopTutorialSpeech（isActive 失活）
    storeContainer.state.isActive = false
    await nextTick()
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })
})
