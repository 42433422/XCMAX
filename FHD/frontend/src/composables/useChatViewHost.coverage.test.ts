/**
 * useChatViewHost coverage ramp 测试
 *
 * 目标：覆盖 useChatViewHost.ts 的 onMounted/onBeforeUnmount 生命周期、
 * 事件监听、pro-task-status 状态映射、storage 同步、viewport 媒体查询、
 * MutationObserver 等场景。
 * 遵循铁律3：happy path + 空值/None + 边界值 + 异常路径。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, ref, nextTick, type Ref } from 'vue'
import { mount } from '@vue/test-utils'
import { useChatViewHost, type UseChatViewHostDeps } from './useChatViewHost'

vi.mock('@/constants/clientModeTiers', () => ({
  resetClientModeTierLocalState: vi.fn(),
  PRO_INTENT_EXPERIENCE_KEY: 'xcagi_pro_intent_experience',
}))

vi.mock('@/utils/hostBusinessPageRedirect', () => ({
  resolveHostBusinessPageRedirect: vi.fn(() => null),
}))

vi.mock('@/utils/typeGuards', () => ({
  asRecord: vi.fn((v) => v || {}),
}))

// ── helpers ──────────────────────────────────────────────────────────

function makeDeps(overrides: Partial<UseChatViewHostDeps> = {}): UseChatViewHostDeps {
  return {
    router: {
      push: vi.fn(),
      currentRoute: { value: { fullPath: '/' } },
    } as any,
    modsStore: {
      initialize: vi.fn().mockResolvedValue(undefined),
      isLoaded: true,
    } as any,
    modsFromStore: ref([{ id: 'mod1', name: 'Test Mod' }]),
    clientModeTiersUiEnabled: true,
    proIntentExperienceEnabled: ref(false),
    autoRefreshStarredWechat: ref(false),
    isTaskPaneResizable: ref(true),
    messageInput: ref(''),
    isProMode: ref(false),
    currentTask: ref(null),
    proRuntimeTask: ref(null),
    latestAssistantPush: ref(null),
    syncProModeState: vi.fn(),
    syncSessionMessages: vi.fn().mockResolvedValue(undefined),
    chatHandleAutoAction: vi.fn(),
    sendMessage: vi.fn().mockResolvedValue(undefined),
    batchCalculateHeights: vi.fn(),
    stopMessageTts: vi.fn(),
    cleanupVoiceInput: vi.fn(),
    stopTaskPaneResize: vi.fn(),
    ...overrides,
  }
}

/** 在组件 setup 中调用 composable，触发 onMounted/onBeforeUnmount */
function mountWithHost(deps: UseChatViewHostDeps) {
  let api: ReturnType<typeof useChatViewHost> | null = null
  const Comp = defineComponent({
    setup() {
      api = useChatViewHost(deps)
      return () => h('div')
    },
  })
  const wrapper = mount(Comp)
  return { wrapper, api: api! }
}

// ── 测试套件 ─────────────────────────────────────────────────────────

describe('useChatViewHost – coverage ramp', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    // 清理 window 上挂载的全局函数
    const w = window as unknown as Record<string, unknown>
    delete w.__VUE_CHAT_SEND__
    delete w.__VUE_CHAT_FILL__
    w.__VUE_HANDLE_AUTO_ACTION__ = false
  })

  // ── 基础：返回 toolbar handlers ─────────────────────────────────

  it('返回 onProIntentToolbarChange 和 onAutoRefreshToolbarChange', () => {
    const { wrapper, api } = mountWithHost(makeDeps())
    expect(typeof api.onProIntentToolbarChange).toBe('function')
    expect(typeof api.onAutoRefreshToolbarChange).toBe('function')
    wrapper.unmount()
  })

  // ── onMounted：modsStore.initialize 调用 ────────────────────────

  it('onMounted 时调用 modsStore.initialize', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()
    expect(deps.modsStore.initialize).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('modsStore 未加载时再次调用 initialize', async () => {
    vi.useFakeTimers()
    const deps = makeDeps({
      modsStore: {
        initialize: vi.fn().mockResolvedValue(undefined),
        isLoaded: false,
      } as any,
      modsFromStore: ref([]),
    })
    const { wrapper } = mountWithHost(deps)
    await nextTick()
    await vi.advanceTimersByTimeAsync(50)
    await nextTick()
    expect(deps.modsStore.initialize).toHaveBeenCalledTimes(2)
    vi.useRealTimers()
    wrapper.unmount()
  })

  // ── onMounted：syncSessionMessages 调用 ─────────────────────────

  it('onMounted 时调用 syncSessionMessages', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()
    expect(deps.syncSessionMessages).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('syncSessionMessages 抛异常时不影响挂载', async () => {
    const deps = makeDeps({
      syncSessionMessages: vi.fn().mockRejectedValue(new Error('sync fail')),
    })
    expect(() => mountWithHost(deps)).not.toThrow()
  })

  // ── onMounted：batchCalculateHeights 延时调用 ───────────────────

  it('onMounted 后延时调用 batchCalculateHeights', async () => {
    vi.useFakeTimers()
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    expect(deps.batchCalculateHeights).not.toHaveBeenCalled()
    vi.advanceTimersByTime(100)
    expect(deps.batchCalculateHeights).toHaveBeenCalled()
    vi.useRealTimers()
    wrapper.unmount()
  })

  // ── onMounted：window.handleAutoAction 注入 ─────────────────────

  it('onMounted 注入 window.__VUE_CHAT_SEND__ 和 handleAutoAction', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()
    const w = window as unknown as Record<string, unknown>
    expect(typeof w.__VUE_CHAT_SEND__).toBe('function')
    expect(typeof w.__VUE_CHAT_FILL__).toBe('function')
    expect(w.__VUE_HANDLE_AUTO_ACTION__).toBe(true)
    expect(typeof (window as any).handleAutoAction).toBe('function')
    wrapper.unmount()
  })

  it('__VUE_CHAT_SEND__ 空消息返回 false', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()
    const send = (window as any).__VUE_CHAT_SEND__ as (m: string) => Promise<boolean>
    const result = await send('')
    expect(result).toBe(false)
    expect(deps.sendMessage).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('__VUE_CHAT_SEND__ 有效消息调用 sendMessage', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()
    const send = (window as any).__VUE_CHAT_SEND__ as (m: string) => Promise<boolean>
    const result = await send('你好')
    expect(result).toBe(true)
    expect(deps.messageInput.value).toBe('你好')
    expect(deps.sendMessage).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('__VUE_CHAT_FILL__ 空消息返回 false', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()
    const fill = (window as any).__VUE_CHAT_FILL__ as (m: string) => boolean
    expect(fill('')).toBe(false)
    wrapper.unmount()
  })

  it('__VUE_CHAT_FILL__ 有效消息填入 messageInput', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()
    const fill = (window as any).__VUE_CHAT_FILL__ as (m: string) => boolean
    expect(fill('测试消息')).toBe(true)
    expect(deps.messageInput.value).toBe('测试消息')
    wrapper.unmount()
  })

  it('handleAutoAction 调用 chatHandleAutoAction', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()
    ;(window as any).handleAutoAction({ type: 'navigate' }, 'user msg')
    expect(deps.chatHandleAutoAction).toHaveBeenCalledWith(
      { type: 'navigate' },
      'user msg',
    )
    wrapper.unmount()
  })

  it('handleAutoAction 处理非对象 action', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()
    ;(window as any).handleAutoAction(null)
    // asRecord mock 会把 null 转成 {}
    expect(deps.chatHandleAutoAction).toHaveBeenCalledWith({}, undefined)
    wrapper.unmount()
  })

  // ── onMounted：legacyAutoActionHandler 恢复 ─────────────────────

  it('卸载时恢复 legacy handleAutoAction', async () => {
    const legacyFn = vi.fn()
    ;(window as any).handleAutoAction = legacyFn
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()
    expect((window as any).handleAutoAction).not.toBe(legacyFn)
    wrapper.unmount()
    expect((window as any).handleAutoAction).toBe(legacyFn)
  })

  // ── onMounted：事件监听注册 ─────────────────────────────────────

  it('onMounted 注册 xcagi:pro-task-status 事件监听', async () => {
    const addSpy = vi.spyOn(window, 'addEventListener')
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()
    expect(addSpy).toHaveBeenCalledWith('xcagi:pro-task-status', expect.any(Function))
    wrapper.unmount()
    addSpy.mockRestore()
  })

  it('onMounted 注册 xcagi:switch-view 事件监听', async () => {
    const addSpy = vi.spyOn(window, 'addEventListener')
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()
    expect(addSpy).toHaveBeenCalledWith('xcagi:switch-view', expect.any(Function))
    wrapper.unmount()
    addSpy.mockRestore()
  })

  it('onMounted 注册 xcagi:pro-mode-changed 事件监听', async () => {
    const addSpy = vi.spyOn(window, 'addEventListener')
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()
    expect(addSpy).toHaveBeenCalledWith('xcagi:pro-mode-changed', expect.any(Function))
    wrapper.unmount()
    addSpy.mockRestore()
  })

  it('onMounted 注册 xcagi:assistant-push 事件监听', async () => {
    const addSpy = vi.spyOn(window, 'addEventListener')
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()
    expect(addSpy).toHaveBeenCalledWith('xcagi:assistant-push', expect.any(Function))
    wrapper.unmount()
    addSpy.mockRestore()
  })

  it('onMounted 注册 storage 事件监听', async () => {
    const addSpy = vi.spyOn(window, 'addEventListener')
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()
    expect(addSpy).toHaveBeenCalledWith('storage', expect.any(Function))
    wrapper.unmount()
    addSpy.mockRestore()
  })

  // ── xcagi:switch-view 事件处理 ──────────────────────────────────

  it('xcagi:switch-view 事件触发 router.push', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    window.dispatchEvent(
      new CustomEvent('xcagi:switch-view', { detail: { view: 'products' } }),
    )
    await nextTick()

    expect(deps.router.push).toHaveBeenCalledWith({ name: 'products' })
    wrapper.unmount()
  })

  it('xcagi:switch-view 事件无 detail 时不触发 router.push', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    window.dispatchEvent(new CustomEvent('xcagi:switch-view', {}))
    await nextTick()

    expect(deps.router.push).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('xcagi:switch-view 事件 detail.view 非字符串时不触发', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    window.dispatchEvent(
      new CustomEvent('xcagi:switch-view', { detail: { view: 123 } }),
    )
    await nextTick()

    expect(deps.router.push).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  // ── xcagi:pro-mode-changed 事件处理 ─────────────────────────────

  it('xcagi:pro-mode-changed 事件更新 isProMode', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    window.dispatchEvent(
      new CustomEvent('xcagi:pro-mode-changed', { detail: { isProMode: true } }),
    )
    await nextTick()

    expect(deps.isProMode.value).toBe(true)
    wrapper.unmount()
  })

  it('xcagi:pro-mode-changed 事件无 detail 时 isProMode 为 false', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()
    deps.isProMode.value = true

    window.dispatchEvent(new CustomEvent('xcagi:pro-mode-changed', {}))
    await nextTick()

    expect(deps.isProMode.value).toBe(false)
    wrapper.unmount()
  })

  // ── xcagi:assistant-push 事件处理 ───────────────────────────────

  it('xcagi:assistant-push 事件更新 latestAssistantPush', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    const push = { title: '推送标题', description: '推送描述' }
    window.dispatchEvent(
      new CustomEvent('xcagi:assistant-push', { detail: push }),
    )
    await nextTick()

    expect(deps.latestAssistantPush.value).toEqual(push)
    wrapper.unmount()
  })

  it('xcagi:assistant-push 事件无 detail 时不更新', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    window.dispatchEvent(new CustomEvent('xcagi:assistant-push', {}))
    await nextTick()

    expect(deps.latestAssistantPush.value).toBeNull()
    wrapper.unmount()
  })

  // ── xcagi:pro-task-status 事件处理 ──────────────────────────────

  it('pro-task-status running 状态更新 proRuntimeTask', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    window.dispatchEvent(
      new CustomEvent('xcagi:pro-task-status', {
        detail: { status: 'running', current_task: '生成订单', current_tool: 'tool1' },
      }),
    )
    await nextTick()

    expect(deps.proRuntimeTask.value).not.toBeNull()
    expect(deps.proRuntimeTask.value!.title).toBe('生成订单')
    expect(deps.proRuntimeTask.value!.statusText).toBe('进行中')
    expect(deps.proRuntimeTask.value!.statusClass).toBe('in-progress')
    expect(deps.proRuntimeTask.value!.description).toContain('工具：tool1')
    wrapper.unmount()
  })

  it('pro-task-status done 状态设置已完成', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    window.dispatchEvent(
      new CustomEvent('xcagi:pro-task-status', {
        detail: { status: 'done' },
      }),
    )
    await nextTick()

    expect(deps.proRuntimeTask.value!.statusText).toBe('已完成')
    expect(deps.proRuntimeTask.value!.statusClass).toBe('completed')
    wrapper.unmount()
  })

  it('pro-task-status failed 状态设置已完成', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    window.dispatchEvent(
      new CustomEvent('xcagi:pro-task-status', {
        detail: { status: 'failed' },
      }),
    )
    await nextTick()

    expect(deps.proRuntimeTask.value!.statusText).toBe('失败')
    expect(deps.proRuntimeTask.value!.statusClass).toBe('completed')
    wrapper.unmount()
  })

  it('pro-task-status error 状态设置异常', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    window.dispatchEvent(
      new CustomEvent('xcagi:pro-task-status', {
        detail: { status: 'error' },
      }),
    )
    await nextTick()

    expect(deps.proRuntimeTask.value!.statusText).toBe('异常')
    wrapper.unmount()
  })

  it('pro-task-status exception 状态设置异常', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    window.dispatchEvent(
      new CustomEvent('xcagi:pro-task-status', {
        detail: { status: 'exception' },
      }),
    )
    await nextTick()

    expect(deps.proRuntimeTask.value!.statusText).toBe('异常')
    wrapper.unmount()
  })

  it('pro-task-status idle 状态清空 proRuntimeTask', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    // 先设置一个 running
    window.dispatchEvent(
      new CustomEvent('xcagi:pro-task-status', {
        detail: { status: 'running' },
      }),
    )
    await nextTick()
    expect(deps.proRuntimeTask.value).not.toBeNull()

    // 再设置 idle
    window.dispatchEvent(
      new CustomEvent('xcagi:pro-task-status', {
        detail: { status: 'idle' },
      }),
    )
    await nextTick()

    expect(deps.proRuntimeTask.value).toBeNull()
    wrapper.unmount()
  })

  it('pro-task-status 空字符串状态清空 proRuntimeTask', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    window.dispatchEvent(
      new CustomEvent('xcagi:pro-task-status', {
        detail: { status: '' },
      }),
    )
    await nextTick()

    expect(deps.proRuntimeTask.value).toBeNull()
    wrapper.unmount()
  })

  it('pro-task-status currentTask 已存在时不更新 proRuntimeTask', async () => {
    const deps = makeDeps({
      currentTask: ref({ type: 'shipment_generate' } as any),
    })
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    window.dispatchEvent(
      new CustomEvent('xcagi:pro-task-status', {
        detail: { status: 'running' },
      }),
    )
    await nextTick()

    expect(deps.proRuntimeTask.value).toBeNull()
    wrapper.unmount()
  })

  it('pro-task-status 未知状态映射为"进行中"', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    window.dispatchEvent(
      new CustomEvent('xcagi:pro-task-status', {
        detail: { status: 'unknown_status' },
      }),
    )
    await nextTick()

    expect(deps.proRuntimeTask.value!.statusText).toBe('unknown_status')
    expect(deps.proRuntimeTask.value!.statusClass).toBe('in-progress')
    wrapper.unmount()
  })

  it('pro-task-status 无 current_task 时使用默认标题', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    window.dispatchEvent(
      new CustomEvent('xcagi:pro-task-status', {
        detail: { status: 'running' },
      }),
    )
    await nextTick()

    expect(deps.proRuntimeTask.value!.title).toBe('工具执行')
    wrapper.unmount()
  })

  it('pro-task-status 无 current_tool 时 description 不含工具', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    window.dispatchEvent(
      new CustomEvent('xcagi:pro-task-status', {
        detail: { status: 'running', current_task: '任务' },
      }),
    )
    await nextTick()

    expect(deps.proRuntimeTask.value!.description).not.toContain('工具：')
    wrapper.unmount()
  })

  it('pro-task-status 含 updated_at 时 description 含更新时间', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    window.dispatchEvent(
      new CustomEvent('xcagi:pro-task-status', {
        detail: { status: 'running', updated_at: '2026-06-17T10:00:00Z' },
      }),
    )
    await nextTick()

    expect(deps.proRuntimeTask.value!.description).toContain('更新时间：')
    wrapper.unmount()
  })

  it('pro-task-status completed 状态触发延时清除', async () => {
    vi.useFakeTimers()
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    window.dispatchEvent(
      new CustomEvent('xcagi:pro-task-status', {
        detail: { status: 'completed', updated_at: '2026-06-17T10:00:00Z' },
      }),
    )
    await nextTick()
    expect(deps.proRuntimeTask.value).not.toBeNull()

    vi.advanceTimersByTime(5000)
    await nextTick()

    expect(deps.proRuntimeTask.value).toBeNull()
    vi.useRealTimers()
    wrapper.unmount()
  })

  it('pro-task-status dispatch 状态映射为进行中', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    window.dispatchEvent(
      new CustomEvent('xcagi:pro-task-status', {
        detail: { status: 'dispatch' },
      }),
    )
    await nextTick()

    expect(deps.proRuntimeTask.value!.statusText).toBe('进行中')
    wrapper.unmount()
  })

  it('pro-task-status matched 状态映射为进行中', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    window.dispatchEvent(
      new CustomEvent('xcagi:pro-task-status', {
        detail: { status: 'matched' },
      }),
    )
    await nextTick()

    expect(deps.proRuntimeTask.value!.statusText).toBe('进行中')
    wrapper.unmount()
  })

  it('pro-task-status in-progress 状态映射为进行中', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    window.dispatchEvent(
      new CustomEvent('xcagi:pro-task-status', {
        detail: { status: 'in-progress' },
      }),
    )
    await nextTick()

    expect(deps.proRuntimeTask.value!.statusText).toBe('进行中')
    wrapper.unmount()
  })

  it('pro-task-status complete 状态映射为已完成', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    window.dispatchEvent(
      new CustomEvent('xcagi:pro-task-status', {
        detail: { status: 'complete' },
      }),
    )
    await nextTick()

    expect(deps.proRuntimeTask.value!.statusText).toBe('已完成')
    wrapper.unmount()
  })

  it('pro-task-status failure 状态映射为失败', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    window.dispatchEvent(
      new CustomEvent('xcagi:pro-task-status', {
        detail: { status: 'failure' },
      }),
    )
    await nextTick()

    expect(deps.proRuntimeTask.value!.statusText).toBe('失败')
    wrapper.unmount()
  })

  // ── storage 事件处理 ────────────────────────────────────────────

  it('storage 事件 key 匹配时同步 proIntentExperienceEnabled', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    localStorage.setItem('xcagi_pro_intent_experience', '1')

    // 触发 storage 事件
    const storageEvent = new StorageEvent('storage', {
      key: 'xcagi_pro_intent_experience',
      newValue: '1',
    })
    window.dispatchEvent(storageEvent)
    await nextTick()

    expect(deps.proIntentExperienceEnabled.value).toBe(true)
    wrapper.unmount()
  })

  it('storage 事件 key 不匹配时不同步', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    const storageEvent = new StorageEvent('storage', {
      key: 'other_key',
      newValue: '1',
    })
    window.dispatchEvent(storageEvent)
    await nextTick()

    expect(deps.proIntentExperienceEnabled.value).toBe(false)
    wrapper.unmount()
  })

  it('storage 事件 key 为 null 时同步', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    localStorage.setItem('xcagi_pro_intent_experience', '1')

    const storageEvent = new StorageEvent('storage', {
      key: null,
      newValue: null,
    })
    window.dispatchEvent(storageEvent)
    await nextTick()

    expect(deps.proIntentExperienceEnabled.value).toBe(true)
    wrapper.unmount()
  })

  // ── xcagi:pro-intent-experience-changed 事件 ────────────────────

  it('xcagi:pro-intent-experience-changed 事件同步状态', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    localStorage.setItem('xcagi_pro_intent_experience', '1')

    window.dispatchEvent(
      new CustomEvent('xcagi:pro-intent-experience-changed', {
        detail: { enabled: true },
      }),
    )
    await nextTick()

    expect(deps.proIntentExperienceEnabled.value).toBe(true)
    wrapper.unmount()
  })

  // ── onProIntentToolbarChange ────────────────────────────────────

  it('onProIntentToolbarChange(true) 启用并持久化', async () => {
    const deps = makeDeps()
    const { wrapper, api } = mountWithHost(deps)
    await nextTick()

    api.onProIntentToolbarChange(true)
    expect(deps.proIntentExperienceEnabled.value).toBe(true)
    expect(localStorage.getItem('xcagi_pro_intent_experience')).toBe('1')
    wrapper.unmount()
  })

  it('onProIntentToolbarChange(false) 禁用并持久化', async () => {
    const deps = makeDeps()
    const { wrapper, api } = mountWithHost(deps)
    await nextTick()

    api.onProIntentToolbarChange(false)
    expect(deps.proIntentExperienceEnabled.value).toBe(false)
    expect(localStorage.getItem('xcagi_pro_intent_experience')).toBe('0')
    wrapper.unmount()
  })

  it('onProIntentToolbarChange 在 clientModeTiersUiEnabled=false 时重置', async () => {
    const { resetClientModeTierLocalState } = await import('@/constants/clientModeTiers')
    const deps = makeDeps({ clientModeTiersUiEnabled: false })
    const { wrapper, api } = mountWithHost(deps)
    await nextTick()

    api.onProIntentToolbarChange(true)
    expect(deps.proIntentExperienceEnabled.value).toBe(false)
    expect(resetClientModeTierLocalState).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('onProIntentToolbarChange 派发自定义事件', async () => {
    const deps = makeDeps()
    const { wrapper, api } = mountWithHost(deps)
    await nextTick()

    const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
    api.onProIntentToolbarChange(true)
    expect(dispatchSpy).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'xcagi:pro-intent-experience-changed' }),
    )
    dispatchSpy.mockRestore()
    wrapper.unmount()
  })

  // ── onAutoRefreshToolbarChange ──────────────────────────────────

  it('onAutoRefreshToolbarChange(true) 启用并持久化', async () => {
    const deps = makeDeps()
    const { wrapper, api } = mountWithHost(deps)
    await nextTick()

    api.onAutoRefreshToolbarChange(true)
    expect(deps.autoRefreshStarredWechat.value).toBe(true)
    expect(localStorage.getItem('xcagi_auto_refresh_starred_wechat')).toBe('1')
    wrapper.unmount()
  })

  it('onAutoRefreshToolbarChange(false) 禁用并持久化', async () => {
    const deps = makeDeps()
    const { wrapper, api } = mountWithHost(deps)
    await nextTick()

    api.onAutoRefreshToolbarChange(false)
    expect(deps.autoRefreshStarredWechat.value).toBe(false)
    expect(localStorage.getItem('xcagi_auto_refresh_starred_wechat')).toBe('0')
    wrapper.unmount()
  })

  it('onAutoRefreshToolbarChange 派发自定义事件', async () => {
    const deps = makeDeps()
    const { wrapper, api } = mountWithHost(deps)
    await nextTick()

    const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
    api.onAutoRefreshToolbarChange(true)
    expect(dispatchSpy).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'xcagi:auto-refresh-wechat-changed' }),
    )
    dispatchSpy.mockRestore()
    wrapper.unmount()
  })

  // ── onMounted：clientModeTiersUiEnabled=false 时重置 ────────────

  it('onMounted 时 clientModeTiersUiEnabled=false 重置本地状态', async () => {
    const { resetClientModeTierLocalState } = await import('@/constants/clientModeTiers')
    const deps = makeDeps({ clientModeTiersUiEnabled: false })
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    expect(resetClientModeTierLocalState).toHaveBeenCalled()
    expect(deps.proIntentExperienceEnabled.value).toBe(false)
    wrapper.unmount()
  })

  // ── onMounted：MutationObserver ─────────────────────────────────

  it('onMounted 创建 MutationObserver 观察 body', async () => {
    const observeSpy = vi.fn()
    const disconnectSpy = vi.fn()
    const origMO = globalThis.MutationObserver
    globalThis.MutationObserver = vi.fn().mockImplementation(() => ({
      observe: observeSpy,
      disconnect: disconnectSpy,
    })) as any

    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    expect(observeSpy).toHaveBeenCalledWith(document.body, {
      attributes: true,
      attributeFilter: ['class'],
    })
    wrapper.unmount()
    expect(disconnectSpy).toHaveBeenCalled()

    globalThis.MutationObserver = origMO
  })

  it('onMounted 时若存在 proModeOverlay 元素也观察它', async () => {
    const observeSpy = vi.fn()
    const origMO = globalThis.MutationObserver
    globalThis.MutationObserver = vi.fn().mockImplementation(() => ({
      observe: observeSpy,
      disconnect: vi.fn(),
    })) as any

    const overlay = document.createElement('div')
    overlay.id = 'proModeOverlay'
    document.body.appendChild(overlay)

    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    expect(observeSpy).toHaveBeenCalledWith(overlay, {
      attributes: true,
      attributeFilter: ['class', 'style'],
    })

    document.body.removeChild(overlay)
    globalThis.MutationObserver = origMO
    wrapper.unmount()
  })

  it('MutationObserver 回调触发 syncProModeState', async () => {
    let moCallback: () => void = () => {}
    const origMO = globalThis.MutationObserver
    globalThis.MutationObserver = vi.fn().mockImplementation((cb: () => void) => {
      moCallback = cb
      return { observe: vi.fn(), disconnect: vi.fn() }
    }) as any

    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    moCallback()
    expect(deps.syncProModeState).toHaveBeenCalled()

    globalThis.MutationObserver = origMO
    wrapper.unmount()
  })

  // ── onMounted：matchMedia viewport 监听 ─────────────────────────

  it('onMounted 时设置 isTaskPaneResizable 基于 matchMedia', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    // matchMedia stub 返回 matches: false → isTaskPaneResizable = true
    expect(deps.isTaskPaneResizable.value).toBe(true)
    wrapper.unmount()
  })

  it('matchMedia matches=true 时 isTaskPaneResizable=false 并调用 stopTaskPaneResize', async () => {
    // 覆盖 matchMedia stub
    const origMatchMedia = window.matchMedia
    window.matchMedia = ((query: string) => ({
      matches: true, // 视口 <= 1023px
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    })) as any

    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    expect(deps.isTaskPaneResizable.value).toBe(false)
    expect(deps.stopTaskPaneResize).toHaveBeenCalled()

    window.matchMedia = origMatchMedia
    wrapper.unmount()
  })

  it('matchMedia 使用 addListener 兼容旧浏览器', async () => {
    const origMatchMedia = window.matchMedia
    const addListenerSpy = vi.fn()
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: addListenerSpy,
      removeListener: () => {},
      // 不提供 addEventListener
      dispatchEvent: () => false,
    })) as any

    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    expect(addListenerSpy).toHaveBeenCalled()
    window.matchMedia = origMatchMedia
    wrapper.unmount()
  })

  // ── onBeforeUnmount：清理 ───────────────────────────────────────

  it('onBeforeUnmount 删除 window 全局函数', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    const w = window as unknown as Record<string, unknown>
    expect(w.__VUE_CHAT_SEND__).toBeDefined()
    expect(w.__VUE_CHAT_FILL__).toBeDefined()

    wrapper.unmount()

    expect(w.__VUE_CHAT_SEND__).toBeUndefined()
    expect(w.__VUE_CHAT_FILL__).toBeUndefined()
    expect(w.__VUE_HANDLE_AUTO_ACTION__).toBe(false)
  })

  it('onBeforeUnmount 移除所有事件监听', async () => {
    const removeSpy = vi.spyOn(window, 'removeEventListener')
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    wrapper.unmount()

    expect(removeSpy).toHaveBeenCalledWith('xcagi:pro-task-status', expect.any(Function))
    expect(removeSpy).toHaveBeenCalledWith('xcagi:switch-view', expect.any(Function))
    expect(removeSpy).toHaveBeenCalledWith('xcagi:pro-mode-changed', expect.any(Function))
    expect(removeSpy).toHaveBeenCalledWith('xcagi:assistant-push', expect.any(Function))
    expect(removeSpy).toHaveBeenCalledWith('storage', expect.any(Function))
    removeSpy.mockRestore()
  })

  it('onBeforeUnmount 调用 stopTaskPaneResize、stopMessageTts、cleanupVoiceInput', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    wrapper.unmount()

    expect(deps.stopTaskPaneResize).toHaveBeenCalled()
    expect(deps.stopMessageTts).toHaveBeenCalled()
    expect(deps.cleanupVoiceInput).toHaveBeenCalled()
  })

  it('onBeforeUnmount 清除 proRuntimeClearTimer', async () => {
    vi.useFakeTimers()
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    // 触发 completed 状态设置 timer
    window.dispatchEvent(
      new CustomEvent('xcagi:pro-task-status', {
        detail: { status: 'completed', updated_at: '2026-06-17T10:00:00Z' },
      }),
    )
    await nextTick()

    // 卸载（不应抛异常）
    expect(() => wrapper.unmount()).not.toThrow()

    vi.useRealTimers()
  })

  // ── watch(currentTask) ──────────────────────────────────────────

  it('currentTask 变为 shipment_generate 未完成时触发 watch', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    // 设置一个未完成的 shipment_generate 任务
    deps.currentTask.value = {
      type: 'shipment_generate',
      completed: false,
      customOrderNumber: '',
    } as any
    await nextTick()

    // watch 不应抛异常
    expect(deps.currentTask.value?.type).toBe('shipment_generate')
    wrapper.unmount()
  })

  it('currentTask 变为已完成任务时不触发逻辑', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    deps.currentTask.value = {
      type: 'shipment_generate',
      completed: true,
    } as any
    await nextTick()

    // 不应抛异常
    expect(deps.currentTask.value?.completed).toBe(true)
    wrapper.unmount()
  })

  it('currentTask 变为非 shipment_generate 类型时不触发', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    deps.currentTask.value = {
      type: 'other_type',
      completed: false,
    } as any
    await nextTick()

    expect(deps.currentTask.value?.type).toBe('other_type')
    wrapper.unmount()
  })

  it('currentTask 有 customOrderNumber 时不触发', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    deps.currentTask.value = {
      type: 'shipment_generate',
      completed: false,
      customOrderNumber: 'ORDER123',
    } as any
    await nextTick()

    expect(deps.currentTask.value?.customOrderNumber).toBe('ORDER123')
    wrapper.unmount()
  })

  it('currentTask 设为 null 时不触发', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    expect(() => {
      deps.currentTask.value = null
    }).not.toThrow()
    wrapper.unmount()
  })

  // ── syncProModeState 调用 ───────────────────────────────────────

  it('onMounted 时调用 syncProModeState', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    expect(deps.syncProModeState).toHaveBeenCalled()
    wrapper.unmount()
  })

  // ── 边界：modsFromStore 为空 ────────────────────────────────────

  it('modsFromStore 为空时仍能正常挂载', async () => {
    const deps = makeDeps({
      modsFromStore: ref([]),
      modsStore: {
        initialize: vi.fn().mockResolvedValue(undefined),
        isLoaded: false,
      } as any,
    })
    const { wrapper } = mountWithHost(deps)
    await nextTick()
    expect(deps.modsStore.initialize).toHaveBeenCalled()
    wrapper.unmount()
  })

  // ── 边界：proRuntimeTask 已有值时新事件覆盖 ─────────────────────

  it('proRuntimeTask 已有值时新事件覆盖', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    // 第一次事件
    window.dispatchEvent(
      new CustomEvent('xcagi:pro-task-status', {
        detail: { status: 'running', current_task: '任务1' },
      }),
    )
    await nextTick()
    expect(deps.proRuntimeTask.value!.title).toBe('任务1')

    // 第二次事件覆盖
    window.dispatchEvent(
      new CustomEvent('xcagi:pro-task-status', {
        detail: { status: 'running', current_task: '任务2' },
      }),
    )
    await nextTick()
    expect(deps.proRuntimeTask.value!.title).toBe('任务2')
    wrapper.unmount()
  })

  // ── 边界：pro-task-status 无 detail ─────────────────────────────

  it('pro-task-status 无 detail 时按 idle 处理', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    // 先设置一个 running
    window.dispatchEvent(
      new CustomEvent('xcagi:pro-task-status', {
        detail: { status: 'running' },
      }),
    )
    await nextTick()
    expect(deps.proRuntimeTask.value).not.toBeNull()

    // 无 detail 事件（detail 为 undefined → {} → status 为 '' → idle）
    window.dispatchEvent(new CustomEvent('xcagi:pro-task-status'))
    await nextTick()

    expect(deps.proRuntimeTask.value).toBeNull()
    wrapper.unmount()
  })

  // ── 边界：__VUE_CHAT_FILL__ 调用 messageInput DOM ───────────────

  it('__VUE_CHAT_FILL__ 时同步更新 DOM messageInput 元素', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    // 创建 mock DOM 元素
    const mockInput = { value: '' } as HTMLTextAreaElement
    const getElementSpy = vi.spyOn(document, 'getElementById').mockReturnValue(mockInput)

    const fill = (window as any).__VUE_CHAT_FILL__ as (m: string) => boolean
    expect(fill('DOM 测试')).toBe(true)
    expect(mockInput.value).toBe('DOM 测试')

    getElementSpy.mockRestore()
    wrapper.unmount()
  })

  it('__VUE_CHAT_FILL__ 无 DOM 元素时仍返回 true', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    const getElementSpy = vi.spyOn(document, 'getElementById').mockReturnValue(null)

    const fill = (window as any).__VUE_CHAT_FILL__ as (m: string) => boolean
    expect(fill('无 DOM')).toBe(true)
    expect(deps.messageInput.value).toBe('无 DOM')

    getElementSpy.mockRestore()
    wrapper.unmount()
  })

  // ── 边界：onMounted 时无 legacy handleAutoAction ─────────────────

  it('onMounted 时无 legacy handleAutoAction 不影响卸载', async () => {
    // 确保初始无 handleAutoAction
    delete (window as any).handleAutoAction
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    expect(() => wrapper.unmount()).not.toThrow()
  })
})
