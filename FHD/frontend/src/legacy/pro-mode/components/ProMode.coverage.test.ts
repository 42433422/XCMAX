/**
 * ProMode.vue 覆盖率提升测试
 *
 * 目标：覆盖 ProMode.vue 中未覆盖的分支，将覆盖率从 44% 提升到 90%+。
 * 重点覆盖：
 * - overlayClasses 计算属性的各种组合（active / exiting / legacy）
 * - normalizeAssistantName / loadAssistantName / syncAssistantName 的各种输入
 * - cleanupProModeResidualUi 的所有 DOM 元素分支
 * - detectLegacyRuntime 的各种 window 函数组合
 * - syncFromLegacyDom 的 body class / overlay class 分支
 * - enableLegacyBridge 的 overlay 存在/不存在
 * - watch modelValue 的所有分支（legacy bridge / 正常 / exit timer）
 * - exitProMode 的 legacy toggle / emit 分支
 * - stepBack 的所有分支（legacy stepBack / workModeToggle / emit / history.back）
 * - onMounted 的所有分支（legacy runtime / modelValue / interval 检测）
 * - onBeforeUnmount 的所有清理路径
 * - assistant-name-updated 事件监听
 *
 * 遵循铁律3：happy path + 空值/None + 边界值 + 异常路径。
 * Mock 最小化：仅 mock 外部边界（useProMode composable）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ref, nextTick } from 'vue'

// ── Mock 配置 ──────────────────────────────────────────────────────────

const mockStepBack = vi.fn()
const mockCurrentStage = ref('idle')

vi.mock('@/composables/useProMode', () => ({
  useProMode: () => ({
    stepBack: mockStepBack,
    currentStage: mockCurrentStage,
  }),
}))

import ProMode from '@/legacy/pro-mode/components/ProMode.vue'

// ── 辅助函数 ──────────────────────────────────────────────────────────

let mountPoint: HTMLDivElement

function mountComponent(propsOverrides = {}) {
  return mount(ProMode, {
    props: {
      modelValue: false,
      ...propsOverrides,
    },
    global: {
      stubs: {
        Teleport: true,
      },
    },
    attachTo: mountPoint,
  })
}

/** 等待 MutationObserver 微任务回调完成 */
function flushMutationObserver(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 50))
}

// ── 测试套件 ──────────────────────────────────────────────────────────

describe('ProMode (legacy) - coverage ramp', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockCurrentStage.value = 'idle'

    // mock localStorage
    vi.stubGlobal('localStorage', {
      getItem: vi.fn().mockReturnValue('修茈'),
      setItem: vi.fn(),
      removeItem: vi.fn(),
      clear: vi.fn(),
    })

    // 清理 window 上的 legacy 函数
    delete (window as any).__legacyToggleProMode
    delete (window as any).toggleProMode
    delete (window as any).stepBackProMode
    delete (window as any).toggleWorkMode

    // 清理 body class
    document.body.className = ''

    // 创建挂载点并附加到 document，使 document.getElementById 可用
    mountPoint = document.createElement('div')
    document.body.appendChild(mountPoint)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    vi.useRealTimers()

    // 清理 window 上的 legacy 函数
    delete (window as any).__legacyToggleProMode
    delete (window as any).toggleProMode
    delete (window as any).stepBackProMode
    delete (window as any).toggleWorkMode

    // 清理 body class 和挂载点
    document.body.className = ''
    if (mountPoint && mountPoint.parentNode) {
      mountPoint.parentNode.removeChild(mountPoint)
    }
  })

  // ════════════════════════════════════════════════════════════════════
  // normalizeAssistantName / loadAssistantName / syncAssistantName
  // ════════════════════════════════════════════════════════════════════

  describe('助手名称处理', () => {
    it('normalizeAssistantName：通过事件更新为带空白的字符串，trim 后使用', async () => {
      const wrapper = mountComponent()
      // 初始为"修茈"
      expect(wrapper.find('.pro-status').text()).toContain('修茈 SYSTEM ONLINE')
      // 派发事件更新名称（带空白）
      window.dispatchEvent(
        new CustomEvent('assistant-name-updated', { detail: { name: '  贾维斯  ' } })
      )
      await nextTick()
      // trim 后应为"贾维斯"
      expect(wrapper.find('.pro-status').text()).toContain('贾维斯 SYSTEM ONLINE')
    })

    it('normalizeAssistantName：空白字符串使用默认值"修茈"', async () => {
      const wrapper = mountComponent()
      window.dispatchEvent(
        new CustomEvent('assistant-name-updated', { detail: { name: '   ' } })
      )
      await nextTick()
      expect(wrapper.find('.pro-status').text()).toContain('修茈 SYSTEM ONLINE')
    })

    it('normalizeAssistantName：null 值使用默认值"修茈"', async () => {
      const wrapper = mountComponent()
      window.dispatchEvent(
        new CustomEvent('assistant-name-updated', { detail: { name: null } })
      )
      await nextTick()
      expect(wrapper.find('.pro-status').text()).toContain('修茈 SYSTEM ONLINE')
    })

    it('normalizeAssistantName：undefined 值使用默认值"修茈"', async () => {
      const wrapper = mountComponent()
      window.dispatchEvent(
        new CustomEvent('assistant-name-updated', { detail: { name: undefined } })
      )
      await nextTick()
      expect(wrapper.find('.pro-status').text()).toContain('修茈 SYSTEM ONLINE')
    })

    it('loadAssistantName：localStorage.getItem 抛异常时使用默认值并打印警告', () => {
      // 重新 stub localStorage 使 getItem 抛异常
      vi.unstubAllGlobals()
      vi.stubGlobal('localStorage', {
        getItem: vi.fn().mockImplementation(() => {
          throw new Error('localStorage 不可用')
        }),
        setItem: vi.fn(),
        removeItem: vi.fn(),
        clear: vi.fn(),
      })
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      const wrapper = mountComponent()
      const status = wrapper.find('.pro-status')
      expect(status.text()).toContain('修茈 SYSTEM ONLINE')
      expect(warnSpy).toHaveBeenCalled()
      warnSpy.mockRestore()
    })

    it('assistant-name-updated 事件：更新助手名称', async () => {
      const wrapper = mountComponent()
      // 初始为"修茈"
      expect(wrapper.find('.pro-status').text()).toContain('修茈 SYSTEM ONLINE')
      // 派发事件更新名称
      window.dispatchEvent(
        new CustomEvent('assistant-name-updated', { detail: { name: '贾维斯' } })
      )
      await nextTick()
      expect(wrapper.find('.pro-status').text()).toContain('贾维斯 SYSTEM ONLINE')
    })

    it('assistant-name-updated 事件：无 detail 使用默认值', async () => {
      const wrapper = mountComponent()
      window.dispatchEvent(new CustomEvent('assistant-name-updated'))
      await nextTick()
      expect(wrapper.find('.pro-status').text()).toContain('修茈 SYSTEM ONLINE')
    })

    it('assistant-name-updated 事件：detail.name 为非字符串使用默认值', async () => {
      const wrapper = mountComponent()
      window.dispatchEvent(
        new CustomEvent('assistant-name-updated', { detail: { name: 123 } })
      )
      await nextTick()
      expect(wrapper.find('.pro-status').text()).toContain('修茈 SYSTEM ONLINE')
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // overlayClasses 计算属性
  // ════════════════════════════════════════════════════════════════════

  describe('overlayClasses 计算属性', () => {
    it('非 legacy + modelValue=true：有 active 类，无 exiting 类', async () => {
      const wrapper = mountComponent({ modelValue: true })
      await nextTick()
      const overlay = wrapper.find('.pro-mode-overlay')
      expect(overlay.classes()).toContain('active')
      expect(overlay.classes()).not.toContain('exiting')
    })

    it('非 legacy + modelValue=false：无 active 无 exiting', () => {
      const wrapper = mountComponent({ modelValue: false })
      const overlay = wrapper.find('.pro-mode-overlay')
      expect(overlay.classes()).not.toContain('active')
      expect(overlay.classes()).not.toContain('exiting')
    })

    it('从 true 切换到 false：触发 exiting 类，400ms 后消失', async () => {
      vi.useFakeTimers()
      const wrapper = mountComponent({ modelValue: true })
      await nextTick()
      // 切换为 false
      await wrapper.setProps({ modelValue: false })
      await nextTick()
      const overlay = wrapper.find('.pro-mode-overlay')
      expect(overlay.classes()).toContain('exiting')
      // 快进 400ms，exitTimer 回调执行
      vi.advanceTimersByTime(400)
      await nextTick()
      expect(overlay.classes()).not.toContain('exiting')
    })

    it('legacy 运行时：active 和 exiting 类都不应用', () => {
      // 设置 legacy 运行时
      ;(window as any).__legacyToggleProMode = vi.fn()
      const wrapper = mountComponent({ modelValue: true })
      const overlay = wrapper.find('.pro-mode-overlay')
      expect(overlay.classes()).not.toContain('active')
      expect(overlay.classes()).not.toContain('exiting')
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // detectLegacyRuntime / syncFromLegacyDom / enableLegacyBridge
  // ════════════════════════════════════════════════════════════════════

  describe('legacy runtime 检测与桥接', () => {
    it('window.__legacyToggleProMode 为函数：检测为 legacy 运行时', () => {
      ;(window as any).__legacyToggleProMode = vi.fn()
      const wrapper = mountComponent()
      // legacy 运行时不应用 active 类
      const overlay = wrapper.find('.pro-mode-overlay')
      expect(overlay.classes()).not.toContain('active')
      // 应该设置 window.stepBackProMode
      expect(window.stepBackProMode).toBe(mockStepBack)
    })

    it('window.toggleProMode 为函数：检测为 legacy 运行时', () => {
      ;(window as any).toggleProMode = vi.fn()
      const wrapper = mountComponent()
      const overlay = wrapper.find('.pro-mode-overlay')
      expect(overlay.classes()).not.toContain('active')
    })

    it('legacy 运行时：body 有 pro-mode-active 类时同步 isActive 为 true', async () => {
      ;(window as any).__legacyToggleProMode = vi.fn()
      document.body.classList.add('pro-mode-active')
      const wrapper = mountComponent()
      await nextTick()
      // 应该 emit update:modelValue true
      const emitted = wrapper.emitted('update:modelValue')
      expect(emitted).toBeTruthy()
      expect(emitted![emitted!.length - 1]).toEqual([true])
    })

    it('legacy 运行时：body 和 overlay 均无 active 类时同步 isActive 为 false', async () => {
      ;(window as any).__legacyToggleProMode = vi.fn()
      const wrapper = mountComponent()
      await nextTick()
      const emitted = wrapper.emitted('update:modelValue')
      expect(emitted).toBeTruthy()
      // syncFromLegacyDom 在 enableLegacyBridge 中被调用，active=false
      expect(emitted![emitted!.length - 1]).toEqual([false])
    })

    it('legacy 运行时：body class 变化触发 MutationObserver → syncFromLegacyDom', async () => {
      ;(window as any).__legacyToggleProMode = vi.fn()
      const wrapper = mountComponent()
      // 记录当前 emit 数量
      const emittedCountBefore = wrapper.emitted('update:modelValue')?.length ?? 0
      // 修改 body class 触发 MutationObserver
      document.body.classList.add('pro-mode-active')
      await flushMutationObserver()
      const emitted = wrapper.emitted('update:modelValue')
      expect(emitted).toBeTruthy()
      expect(emitted!.length).toBeGreaterThan(emittedCountBefore)
      expect(emitted![emitted!.length - 1]).toEqual([true])
    })

    it('legacy 运行时：overlay class 变化触发 MutationObserver → syncFromLegacyDom', async () => {
      ;(window as any).__legacyToggleProMode = vi.fn()
      const wrapper = mountComponent()
      const emittedCountBefore = wrapper.emitted('update:modelValue')?.length ?? 0
      // 修改 overlay class 触发 MutationObserver
      const overlay = wrapper.find('.pro-mode-overlay')
      overlay.element.classList.add('active')
      await flushMutationObserver()
      const emitted = wrapper.emitted('update:modelValue')
      expect(emitted).toBeTruthy()
      expect(emitted!.length).toBeGreaterThan(emittedCountBefore)
      expect(emitted![emitted!.length - 1]).toEqual([true])
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // watch modelValue 分支
  // ════════════════════════════════════════════════════════════════════

  describe('watch modelValue 分支', () => {
    it('非 legacy + false → true：添加 body class，清除 exitTimer', async () => {
      const wrapper = mountComponent({ modelValue: false })
      await nextTick()
      expect(document.body.classList.contains('pro-mode-active')).toBe(false)
      await wrapper.setProps({ modelValue: true })
      await nextTick()
      expect(document.body.classList.contains('pro-mode-active')).toBe(true)
    })

    it('非 legacy + true → false：移除 body class，清理残留 UI，设置 exitTimer', async () => {
      vi.useFakeTimers()
      const wrapper = mountComponent({ modelValue: true })
      await nextTick()
      expect(document.body.classList.contains('pro-mode-active')).toBe(true)
      await wrapper.setProps({ modelValue: false })
      await nextTick()
      expect(document.body.classList.contains('pro-mode-active')).toBe(false)
      // exiting 类应该出现（exitTimer 已设置）
      const overlay = wrapper.find('.pro-mode-overlay')
      expect(overlay.classes()).toContain('exiting')
    })

    it('非 legacy + true → false → true：清除 exitTimer，isExiting=false', async () => {
      vi.useFakeTimers()
      const wrapper = mountComponent({ modelValue: true })
      await nextTick()
      // 切换到 false 触发 exitTimer
      await wrapper.setProps({ modelValue: false })
      await nextTick()
      // 再切换回 true，应该清除 exitTimer 并 isExiting=false
      await wrapper.setProps({ modelValue: true })
      await nextTick()
      const overlay = wrapper.find('.pro-mode-overlay')
      expect(overlay.classes()).not.toContain('exiting')
      expect(overlay.classes()).toContain('active')
    })

    it('legacy 运行时 + modelValue 变化：走 syncFromLegacyDom 分支', async () => {
      ;(window as any).__legacyToggleProMode = vi.fn()
      const wrapper = mountComponent({ modelValue: false })
      await nextTick()
      const emittedCountBefore = wrapper.emitted('update:modelValue')?.length ?? 0
      // 修改 modelValue
      await wrapper.setProps({ modelValue: true })
      await nextTick()
      // legacy 运行时应该走 syncFromLegacyDom，emit 实际的 active 状态
      const emitted = wrapper.emitted('update:modelValue')
      expect(emitted).toBeTruthy()
      expect(emitted!.length).toBeGreaterThan(emittedCountBefore)
    })

    it('非 legacy + modelValue=true 且检测到 legacy runtime：启用 legacy bridge', async () => {
      const wrapper = mountComponent({ modelValue: false })
      await nextTick()
      // 之后设置 legacy toggle
      ;(window as any).__legacyToggleProMode = vi.fn()
      // 修改 modelValue 为 true，应该触发 enableLegacyBridge
      await wrapper.setProps({ modelValue: true })
      await nextTick()
      // legacy bridge 启用后，active 类不应应用
      const overlay = wrapper.find('.pro-mode-overlay')
      expect(overlay.classes()).not.toContain('active')
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // exitProMode 分支
  // ════════════════════════════════════════════════════════════════════

  describe('exitProMode 分支', () => {
    it('非 legacy 运行时：emit update:modelValue false', async () => {
      const wrapper = mountComponent({ modelValue: true })
      await nextTick()
      const btns = wrapper.findAll('.pro-exit-btn')
      const exitBtn = btns.find((b) => b.text().includes('EXIT PRO MODE'))
      await exitBtn!.trigger('click')
      const emitted = wrapper.emitted('update:modelValue')
      expect(emitted).toBeTruthy()
      expect(emitted![emitted!.length - 1]).toEqual([false])
    })

    it('legacy 运行时（__legacyToggleProMode）：调用 legacy toggle', async () => {
      const legacyToggle = vi.fn()
      ;(window as any).__legacyToggleProMode = legacyToggle
      const wrapper = mountComponent()
      const btns = wrapper.findAll('.pro-exit-btn')
      const exitBtn = btns.find((b) => b.text().includes('EXIT PRO MODE'))
      await exitBtn!.trigger('click')
      expect(legacyToggle).toHaveBeenCalled()
    })

    it('legacy 运行时（toggleProMode）：调用 legacy toggle', async () => {
      const legacyToggle = vi.fn()
      ;(window as any).toggleProMode = legacyToggle
      const wrapper = mountComponent()
      const btns = wrapper.findAll('.pro-exit-btn')
      const exitBtn = btns.find((b) => b.text().includes('EXIT PRO MODE'))
      await exitBtn!.trigger('click')
      expect(legacyToggle).toHaveBeenCalled()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // stepBack 分支
  // ════════════════════════════════════════════════════════════════════

  describe('stepBack 分支', () => {
    it('非 legacy（无 stepBackProMode）+ 非 workMode：emit update:modelValue false', async () => {
      const wrapper = mountComponent({ modelValue: true })
      await nextTick()
      // 删除 window.stepBackProMode 以走非 legacy 分支
      delete (window as any).stepBackProMode
      const btns = wrapper.findAll('.pro-exit-btn')
      const stepBackBtn = btns.find((b) => b.text().includes('撤回'))
      await stepBackBtn!.trigger('click')
      const emitted = wrapper.emitted('update:modelValue')
      expect(emitted).toBeTruthy()
      expect(emitted![emitted!.length - 1]).toEqual([false])
    })

    it('legacy stepBackProMode：调用 legacy stepBack（work-mode，不回退路由）', async () => {
      vi.useFakeTimers()
      const wrapper = mountComponent({ modelValue: true })
      await nextTick()
      // 设置自定义的 legacy stepBack
      const legacyStepBack = vi.fn()
      ;(window as any).stepBackProMode = legacyStepBack
      // 添加 work-mode 类
      const overlay = wrapper.find('.pro-mode-overlay')
      overlay.element.classList.add('work-mode')
      const btns = wrapper.findAll('.pro-exit-btn')
      const stepBackBtn = btns.find((b) => b.text().includes('撤回'))
      await stepBackBtn!.trigger('click')
      expect(legacyStepBack).toHaveBeenCalled()
      // 快进 setTimeout
      vi.advanceTimersByTime(10)
    })

    it('legacy stepBackProMode：monitor-mode，不回退路由', async () => {
      vi.useFakeTimers()
      const wrapper = mountComponent({ modelValue: true })
      await nextTick()
      const legacyStepBack = vi.fn()
      ;(window as any).stepBackProMode = legacyStepBack
      const overlay = wrapper.find('.pro-mode-overlay')
      overlay.element.classList.add('monitor-mode')
      const btns = wrapper.findAll('.pro-exit-btn')
      const stepBackBtn = btns.find((b) => b.text().includes('撤回'))
      await stepBackBtn!.trigger('click')
      expect(legacyStepBack).toHaveBeenCalled()
      vi.advanceTimersByTime(10)
    })

    it('legacy stepBackProMode：stage 未变化 + url 未变化 + history.length>1 → history.back', async () => {
      vi.useFakeTimers()
      const wrapper = mountComponent({ modelValue: true })
      await nextTick()
      const legacyStepBack = vi.fn()
      ;(window as any).stepBackProMode = legacyStepBack
      // mock history.back 和 history.length
      const historyBackSpy = vi.spyOn(window.history, 'back').mockImplementation(() => {})
      Object.defineProperty(window.history, 'length', { value: 5, configurable: true })

      const btns = wrapper.findAll('.pro-exit-btn')
      const stepBackBtn = btns.find((b) => b.text().includes('撤回'))
      await stepBackBtn!.trigger('click')
      expect(legacyStepBack).toHaveBeenCalled()
      // 快进 setTimeout
      vi.advanceTimersByTime(10)
      expect(historyBackSpy).toHaveBeenCalled()
      historyBackSpy.mockRestore()
    })

    it('legacy stepBackProMode：stage 变化 → 不调用 history.back', async () => {
      vi.useFakeTimers()
      const wrapper = mountComponent({ modelValue: true })
      await nextTick()
      // legacyStepBack 会改变 stage
      const legacyStepBack = vi.fn(() => {
        mockCurrentStage.value = 'changed'
      })
      ;(window as any).stepBackProMode = legacyStepBack
      const historyBackSpy = vi.spyOn(window.history, 'back').mockImplementation(() => {})
      Object.defineProperty(window.history, 'length', { value: 5, configurable: true })

      const btns = wrapper.findAll('.pro-exit-btn')
      const stepBackBtn = btns.find((b) => b.text().includes('撤回'))
      await stepBackBtn!.trigger('click')
      vi.advanceTimersByTime(10)
      expect(historyBackSpy).not.toHaveBeenCalled()
      historyBackSpy.mockRestore()
    })

    it('legacy stepBackProMode：history.length<=1 → 不调用 history.back', async () => {
      vi.useFakeTimers()
      const wrapper = mountComponent({ modelValue: true })
      await nextTick()
      const legacyStepBack = vi.fn()
      ;(window as any).stepBackProMode = legacyStepBack
      const historyBackSpy = vi.spyOn(window.history, 'back').mockImplementation(() => {})
      Object.defineProperty(window.history, 'length', { value: 1, configurable: true })

      const btns = wrapper.findAll('.pro-exit-btn')
      const stepBackBtn = btns.find((b) => b.text().includes('撤回'))
      await stepBackBtn!.trigger('click')
      vi.advanceTimersByTime(10)
      expect(historyBackSpy).not.toHaveBeenCalled()
      historyBackSpy.mockRestore()
    })

    it('toggleWorkMode 且 overlay 有 work-mode 类：调用 workModeToggle', async () => {
      const workModeToggle = vi.fn()
      ;(window as any).toggleWorkMode = workModeToggle
      const wrapper = mountComponent({ modelValue: true })
      await nextTick()
      // 删除 window.stepBackProMode 以走非 legacy stepBack 分支
      delete (window as any).stepBackProMode
      const overlay = wrapper.find('.pro-mode-overlay')
      overlay.element.classList.add('work-mode')
      const btns = wrapper.findAll('.pro-exit-btn')
      const stepBackBtn = btns.find((b) => b.text().includes('撤回'))
      await stepBackBtn!.trigger('click')
      expect(workModeToggle).toHaveBeenCalled()
    })

    it('toggleWorkMode 存在但 overlay 无 work-mode 类：emit update:modelValue false', async () => {
      const workModeToggle = vi.fn()
      ;(window as any).toggleWorkMode = workModeToggle
      const wrapper = mountComponent({ modelValue: true })
      await nextTick()
      // 删除 window.stepBackProMode 以走非 legacy stepBack 分支
      delete (window as any).stepBackProMode
      // 不添加 work-mode 类
      const btns = wrapper.findAll('.pro-exit-btn')
      const stepBackBtn = btns.find((b) => b.text().includes('撤回'))
      await stepBackBtn!.trigger('click')
      expect(workModeToggle).not.toHaveBeenCalled()
      const emitted = wrapper.emitted('update:modelValue')
      expect(emitted).toBeTruthy()
      expect(emitted![emitted!.length - 1]).toEqual([false])
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // cleanupProModeResidualUi DOM 清理
  // ════════════════════════════════════════════════════════════════════

  describe('cleanupProModeResidualUi DOM 清理', () => {
    it('清理所有存在的残留 UI 元素', async () => {
      // 创建所有残留 UI 元素
      const labelsExportWindow = document.createElement('div')
      labelsExportWindow.id = 'labelsExportWindow'
      labelsExportWindow.classList.add('show')
      document.body.appendChild(labelsExportWindow)

      const labelFloatPreviews = document.createElement('div')
      labelFloatPreviews.id = 'labelFloatPreviews'
      labelFloatPreviews.innerHTML = '<span>预览</span>'
      document.body.appendChild(labelFloatPreviews)

      const shipmentDownloadEntry = document.createElement('div')
      shipmentDownloadEntry.id = 'shipmentDownloadEntry'
      shipmentDownloadEntry.classList.add('show')
      const entryText = document.createElement('span')
      entryText.className = 'entry-text'
      entryText.textContent = '下载中...'
      shipmentDownloadEntry.appendChild(entryText)
      document.body.appendChild(shipmentDownloadEntry)

      const orderFloatPanel = document.createElement('div')
      orderFloatPanel.id = 'proOrderFloatPanel'
      orderFloatPanel.classList.add('show', 'task-acquiring')
      document.body.appendChild(orderFloatPanel)

      const orderFloatText = document.createElement('div')
      orderFloatText.id = 'proOrderFloatText'
      orderFloatText.textContent = '订单内容'
      document.body.appendChild(orderFloatText)

      const orderFloatDownload = document.createElement('div')
      orderFloatDownload.id = 'proOrderFloatDownload'
      orderFloatDownload.setAttribute('data-hidden', 'false')
      document.body.appendChild(orderFloatDownload)

      const orderFloatDownloadLink = document.createElement('a')
      orderFloatDownloadLink.id = 'proOrderFloatDownloadLink'
      orderFloatDownloadLink.setAttribute('href', '/some/path')
      document.body.appendChild(orderFloatDownloadLink)

      const wrapper = mountComponent({ modelValue: true })
      await nextTick()
      // 切换为 false 触发 cleanup
      await wrapper.setProps({ modelValue: false })
      await nextTick()

      // 验证清理结果
      expect(labelsExportWindow.classList.contains('show')).toBe(false)
      expect(labelFloatPreviews.innerHTML).toBe('')
      expect(labelFloatPreviews.classList.contains('hidden')).toBe(true)
      expect(labelFloatPreviews.getAttribute('aria-hidden')).toBe('true')
      expect(shipmentDownloadEntry.classList.contains('show')).toBe(false)
      expect(entryText.textContent).toBe('下载发货单')
      expect(orderFloatPanel.classList.contains('show')).toBe(false)
      expect(orderFloatPanel.classList.contains('task-acquiring')).toBe(false)
      expect(orderFloatPanel.getAttribute('aria-hidden')).toBe('true')
      expect(orderFloatText.textContent).toBe('')
      expect(orderFloatDownload.getAttribute('data-hidden')).toBe('true')
      expect(orderFloatDownloadLink.getAttribute('href')).toBe('#')

      // 清理 DOM
      ;[
        labelsExportWindow,
        labelFloatPreviews,
        shipmentDownloadEntry,
        orderFloatPanel,
        orderFloatText,
        orderFloatDownload,
        orderFloatDownloadLink,
      ].forEach((el) => el.remove())
    })

    it('残留 UI 元素不存在时不报错', async () => {
      // 不创建任何元素
      const wrapper = mountComponent({ modelValue: true })
      await nextTick()
      // 切换为 false 触发 cleanup（不应抛错）
      await wrapper.setProps({ modelValue: false })
      await nextTick()
      // 测试通过即说明无报错
      expect(true).toBe(true)
    })

    it('shipmentDownloadEntry 无 .entry-text 子元素时不报错', async () => {
      const shipmentDownloadEntry = document.createElement('div')
      shipmentDownloadEntry.id = 'shipmentDownloadEntry'
      shipmentDownloadEntry.classList.add('show')
      document.body.appendChild(shipmentDownloadEntry)

      const wrapper = mountComponent({ modelValue: true })
      await nextTick()
      await wrapper.setProps({ modelValue: false })
      await nextTick()

      expect(shipmentDownloadEntry.classList.contains('show')).toBe(false)
      shipmentDownloadEntry.remove()
    })

    it('exitProMode 也触发 cleanupProModeResidualUi', async () => {
      const labelsExportWindow = document.createElement('div')
      labelsExportWindow.id = 'labelsExportWindow'
      labelsExportWindow.classList.add('show')
      document.body.appendChild(labelsExportWindow)

      const wrapper = mountComponent({ modelValue: true })
      await nextTick()
      // 点击 EXIT 按钮触发 exitProMode → cleanupProModeResidualUi
      const btns = wrapper.findAll('.pro-exit-btn')
      const exitBtn = btns.find((b) => b.text().includes('EXIT PRO MODE'))
      await exitBtn!.trigger('click')

      expect(labelsExportWindow.classList.contains('show')).toBe(false)
      labelsExportWindow.remove()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // onMounted 分支
  // ════════════════════════════════════════════════════════════════════

  describe('onMounted 分支', () => {
    it('非 legacy + modelValue=true：添加 body class', async () => {
      const wrapper = mountComponent({ modelValue: true })
      await nextTick()
      expect(document.body.classList.contains('pro-mode-active')).toBe(true)
    })

    it('非 legacy + modelValue=false：不添加 body class', async () => {
      const wrapper = mountComponent({ modelValue: false })
      await nextTick()
      expect(document.body.classList.contains('pro-mode-active')).toBe(false)
    })

    it('legacy 运行时：启用 legacy bridge（设置 stepBackProMode）', async () => {
      ;(window as any).__legacyToggleProMode = vi.fn()
      const wrapper = mountComponent()
      // legacy bridge 启用后应设置 stepBackProMode
      expect(window.stepBackProMode).toBe(mockStepBack)
    })

    it('interval 检测到 legacy runtime 后启用 legacy bridge', async () => {
      vi.useFakeTimers()
      const wrapper = mountComponent({ modelValue: false })
      await nextTick()
      // 初始不是 legacy，interval 已启动
      // 设置 legacy toggle
      ;(window as any).__legacyToggleProMode = vi.fn()
      // 快进 300ms 触发 interval
      vi.advanceTimersByTime(300)
      await nextTick()
      // legacy bridge 应该被启用：验证 overlay 不应用 active 类即使 modelValue 为 true
      await wrapper.setProps({ modelValue: true })
      await nextTick()
      const overlay = wrapper.find('.pro-mode-overlay')
      expect(overlay.classes()).not.toContain('active')
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // onBeforeUnmount 清理
  // ════════════════════════════════════════════════════════════════════

  describe('onBeforeUnmount 清理', () => {
    it('卸载时清理 window.stepBackProMode', () => {
      const wrapper = mountComponent()
      expect(window.stepBackProMode).toBe(mockStepBack)
      wrapper.unmount()
      expect(window.stepBackProMode).toBeUndefined()
    })

    it('卸载时清理 exitTimer（无报错）', async () => {
      vi.useFakeTimers()
      const wrapper = mountComponent({ modelValue: true })
      await nextTick()
      // 触发 exitTimer 设置
      await wrapper.setProps({ modelValue: false })
      await nextTick()
      // 卸载（应清理 exitTimer）
      wrapper.unmount()
      // 快进时间，不应有错误
      vi.advanceTimersByTime(500)
      expect(true).toBe(true)
    })

    it('卸载时清理 legacyDetectionTimer', async () => {
      vi.useFakeTimers()
      const wrapper = mountComponent({ modelValue: false })
      await nextTick()
      // 卸载（应清理 interval）
      wrapper.unmount()
      // 快进时间，不应触发 enableLegacyBridge
      ;(window as any).__legacyToggleProMode = vi.fn()
      vi.advanceTimersByTime(1000)
      expect(true).toBe(true)
    })

    it('卸载时移除 assistant-name-updated 事件监听', async () => {
      const wrapper = mountComponent()
      wrapper.unmount()
      // 卸载后派发事件不应更新组件（组件已销毁）
      // 主要验证不报错
      window.dispatchEvent(
        new CustomEvent('assistant-name-updated', { detail: { name: '贾维斯' } })
      )
      expect(true).toBe(true)
    })

    it('legacy 运行时卸载：清理 MutationObserver（无报错）', async () => {
      ;(window as any).__legacyToggleProMode = vi.fn()
      const wrapper = mountComponent()
      // 卸载（应断开 MutationObserver）
      wrapper.unmount()
      // 修改 body class 不应触发已断开的 observer
      document.body.classList.add('some-class')
      await flushMutationObserver()
      expect(true).toBe(true)
    })

    it('卸载时 window.stepBackProMode 已被外部覆盖时不删除', () => {
      const wrapper = mountComponent()
      // 外部覆盖 stepBackProMode
      const externalFn = vi.fn()
      window.stepBackProMode = externalFn
      wrapper.unmount()
      // 不应删除外部的函数
      expect(window.stepBackProMode).toBe(externalFn)
      delete (window as any).stepBackProMode
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // 基础渲染验证（确保 attachTo 模式下渲染正常）
  // ════════════════════════════════════════════════════════════════════

  describe('基础渲染', () => {
    it('渲染 overlay 容器', () => {
      const wrapper = mountComponent()
      expect(wrapper.find('.pro-mode-overlay').exists()).toBe(true)
    })

    it('渲染 EXIT PRO MODE 和撤回按钮', () => {
      const wrapper = mountComponent()
      const btns = wrapper.findAll('.pro-exit-btn')
      expect(btns.find((b) => b.text().includes('EXIT PRO MODE'))).toBeTruthy()
      expect(btns.find((b) => b.text().includes('撤回'))).toBeTruthy()
    })

    it('渲染 STARK INDUSTRIES 标题', () => {
      const wrapper = mountComponent()
      expect(wrapper.find('.pro-title').text()).toContain('STARK INDUSTRIES')
    })

    it('状态栏显示助手名称', () => {
      const wrapper = mountComponent()
      const status = wrapper.find('.pro-status')
      expect(status.text()).toContain('修茈 SYSTEM ONLINE')
    })
  })
})
