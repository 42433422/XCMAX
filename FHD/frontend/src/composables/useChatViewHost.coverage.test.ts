import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, ref, nextTick, KeepAlive } from 'vue'
import { mount } from '@vue/test-utils'
import { useChatViewHost, type UseChatViewHostDeps } from './useChatViewHost'

function makeDeps(overrides: Partial<UseChatViewHostDeps> = {}): UseChatViewHostDeps {
  return {
    modsStore: {
      initialize: vi.fn().mockResolvedValue(undefined),
      isLoaded: true,
    } as any,
    modsFromStore: ref([{ id: 'mod1', name: 'Test Mod' }]),
    autoRefreshStarredWechat: ref(false),
    isTaskPaneResizable: ref(true),
    messageInput: ref(''),
    latestAssistantPush: ref(null),
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

describe('useChatViewHost – coverage ramp', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    const w = window as unknown as Record<string, unknown>
    delete w.__VUE_CHAT_SEND__
    delete w.__VUE_CHAT_FILL__
    w.__VUE_HANDLE_AUTO_ACTION__ = false
  })

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

  it('returning from approval refreshes a cached chat without sending or remounting', async () => {
    const deps = makeDeps()
    const shown = ref(true)
    const Chat = defineComponent({ setup() { useChatViewHost(deps); return () => h('div', 'chat') } })
    const wrapper = mount(defineComponent({ setup() {
      return () => h(KeepAlive, () => shown.value ? h(Chat) : h('div', 'approval'))
    } }))
    await nextTick()
    expect(deps.syncSessionMessages).toHaveBeenCalledTimes(1)
    shown.value = false
    await nextTick()
    shown.value = true
    await nextTick()
    expect(deps.syncSessionMessages).toHaveBeenCalledTimes(2)
    expect(deps.modsStore.initialize).toHaveBeenCalledTimes(1)
    expect(deps.sendMessage).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('syncSessionMessages 抛异常时不影响挂载', async () => {
    const deps = makeDeps({
      syncSessionMessages: vi.fn().mockRejectedValue(new Error('sync fail')),
    })
    expect(() => mountWithHost(deps)).not.toThrow()
  })

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
    expect(deps.chatHandleAutoAction).toHaveBeenCalledWith({ type: 'navigate' }, 'user msg')
    wrapper.unmount()
  })

  it('handleAutoAction 处理非对象 action', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()
    ;(window as any).handleAutoAction(null)
    expect(deps.chatHandleAutoAction).toHaveBeenCalledWith({}, undefined)
    wrapper.unmount()
  })

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

  it('onMounted 不再注册 xcagi:switch-view（统一由 AppShellBridge 处理）', async () => {
    const addSpy = vi.spyOn(window, 'addEventListener')
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()
    expect(addSpy).not.toHaveBeenCalledWith('xcagi:switch-view', expect.any(Function))
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

  it('xcagi:assistant-push 事件更新 latestAssistantPush', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    const push = { title: '推送标题', description: '推送描述' }
    window.dispatchEvent(new CustomEvent('xcagi:assistant-push', { detail: push }))
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

  it('onMounted 时设置 isTaskPaneResizable 基于 matchMedia', async () => {
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    expect(deps.isTaskPaneResizable.value).toBe(true)
    wrapper.unmount()
  })

  it('matchMedia matches=true 时 isTaskPaneResizable=false 并调用 stopTaskPaneResize', async () => {
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
      dispatchEvent: () => false,
    })) as any

    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    expect(addListenerSpy).toHaveBeenCalled()
    window.matchMedia = origMatchMedia
    wrapper.unmount()
  })

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

  it('onBeforeUnmount 移除事件监听', async () => {
    const removeSpy = vi.spyOn(window, 'removeEventListener')
    const deps = makeDeps()
    const { wrapper } = mountWithHost(deps)
    await nextTick()

    wrapper.unmount()

    expect(removeSpy).toHaveBeenCalledWith('xcagi:assistant-push', expect.any(Function))
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
})
