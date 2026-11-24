import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAgentStore } from './agent'
import { useAuthStore } from './auth'
import { getActionLog } from '../composables/agent/useActionExecutor'

// 模拟 localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => {
      store[k] = v
    },
    removeItem: (k: string) => {
      delete store[k]
    },
    clear: () => {
      store = {}
    },
  }
})()

Object.defineProperty(window, 'localStorage', { value: localStorageMock })

describe('useAgentStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorageMock.clear()
    sessionStorage.clear()
  })

  it('初始状态 isOpen=false', () => {
    const store = useAgentStore()
    expect(store.isOpen).toBe(false)
  })

  it('账号切换同步清除原对话、确认与无归属操作日志', () => {
    const auth = useAuthStore()
    auth.user = { id: 11, username: 'A', is_admin: false }
    sessionStorage.setItem('xc_butler_action_log', '[{"label":"unowned legacy"}]')
    const store = useAgentStore()
    const legacyLog = sessionStorage.getItem('xc_butler_action_log')
    const resolve = vi.fn()
    store.addMessage({ id: 'private-A', role: 'user', content: 'private A', timestamp: 1 })
    store.currentConversationId = 10
    store.isLoading = true
    store.orchestrationSession = { sessionId: 'A-session', steps: [], status: 'running' }
    store.setPendingAction({ id: 'A-action', action: 'click', risk: 'medium', label: 'A only', args: {}, resolve })
    sessionStorage.setItem('xc_butler_action_log', '[{"label":"A action"}]')
    auth.user = { id: 22, username: 'B', is_admin: false }
    expect(legacyLog).toBeNull()
    expect(store.messages).toEqual([])
    expect(store.currentConversationId).toBeNull()
    expect(store.orchestrationSession).toBeNull()
    expect(store.pendingAction).toBeNull()
    expect(store.isLoading).toBe(false)
    expect(resolve).toHaveBeenCalledExactlyOnceWith(false)
    expect(sessionStorage.getItem('xc_butler_action_log')).toBeNull()
  })

  it('grantConsent 设置 consentGiven=true 并写 localStorage', () => {
    const store = useAgentStore()
    store.grantConsent()
    expect(store.consentGiven).toBe(true)
    expect(localStorageMock.getItem('xc_butler_consent')).toBe('v1')
    expect(store.isOpen).toBe(true)
  })

  it('openPanel 未同意时不打开面板', () => {
    const store = useAgentStore()
    store.openPanel()
    expect(store.isOpen).toBe(false)
    expect(store.showPermissionDialog).toBe(true)
  })

  it('openPanel 同意后打开面板', () => {
    const store = useAgentStore()
    store.consentGiven = true
    store.openPanel()
    expect(store.isOpen).toBe(true)
  })

  it('closePanel 关闭面板', () => {
    const store = useAgentStore()
    store.consentGiven = true
    store.openPanel()
    store.closePanel()
    expect(store.isOpen).toBe(false)
  })

  it('addMessage 增加消息', () => {
    const store = useAgentStore()
    store.addMessage({ id: '1', role: 'user', content: 'hello', timestamp: Date.now() })
    expect(store.messages).toHaveLength(1)
    expect(store.messages[0].content).toBe('hello')
  })

  it('clearMessages 清空消息', () => {
    const store = useAgentStore()
    store.addMessage({ id: '1', role: 'user', content: 'hello', timestamp: Date.now() })
    store.clearMessages()
    expect(store.messages).toHaveLength(0)
  })

  it('不认领无账号归属的旧操作日志，账号切换清掉当前小 C 的操作历史', () => {
    const auth = useAuthStore()
    auth.user = { id: 11, username: 'A', is_admin: true }
    const entry = { ts: 1, action: 'navigate', label: '账号 A 私有页面', risk: 'low', success: true }
    sessionStorage.setItem('xc_butler_action_log', JSON.stringify([entry]))
    useAgentStore()
    const restored = getActionLog()
    sessionStorage.setItem('xc_butler_action_log', JSON.stringify([entry]))
    const currentAccount = getActionLog()
    auth.user = { id: 22, username: 'B', is_admin: true }

    expect(restored).toEqual([])
    expect(currentAccount).toEqual([entry])
    expect(getActionLog()).toEqual([])
  })

  it('savePosition 持久化位置到 localStorage', () => {
    const store = useAgentStore()
    store.savePosition(100, 200)
    expect(store.position).toEqual({ x: 100, y: 200 })
    const saved = JSON.parse(localStorageMock.getItem('xc_butler_pos') || '{}')
    expect(saved).toEqual({ x: 100, y: 200 })
  })

  it('dismissButler 写 localStorage 并关闭', () => {
    const store = useAgentStore()
    store.dismissButler()
    expect(store.dismissed).toBe(true)
    expect(localStorageMock.getItem('xc_butler_dismissed')).toBe('1')
  })

  it('unreadCount 增加（面板关闭时新消息）', () => {
    const store = useAgentStore()
    store.consentGiven = true
    // 面板关闭
    store.addMessage({ id: '2', role: 'assistant', content: 'reply', timestamp: Date.now() })
    expect(store.unreadCount).toBe(1)
    // 打开后清零
    store.openPanel()
    expect(store.unreadCount).toBe(0)
  })

  it('setPendingAction 切换模式', () => {
    const store = useAgentStore()
    const pending = {
      id: 'a1',
      action: 'click',
      label: '点击',
      risk: 'medium' as const,
      args: {},
      resolve: () => {},
    }
    store.setPendingAction(pending)
    expect(store.mode).toBe('awaiting_confirm')
    store.setPendingAction(null)
    expect(store.mode).toBe('idle')
  })

  it('orchestrationSession 初始为 null', () => {
    const store = useAgentStore()
    expect(store.orchestrationSession).toBeNull()
  })

  it('可写入 orchestrationSession 并通过 clearOrchestration 清除', () => {
    const store = useAgentStore()
    store.orchestrationSession = {
      sessionId: 'abc123',
      steps: [{ id: 'snapshot', label: '备份快照', status: 'done', message: null }],
      status: 'running',
    }
    expect(store.orchestrationSession?.sessionId).toBe('abc123')
    expect(store.orchestrationSession?.steps).toHaveLength(1)

    // Simulate orchestrating mode
    store.setMode('orchestrating')
    expect(store.mode).toBe('orchestrating')

    store.clearOrchestration()
    expect(store.orchestrationSession).toBeNull()
    expect(store.mode).toBe('idle')
  })

  it('clearOrchestration 仅在 orchestrating 模式下重置 mode', () => {
    const store = useAgentStore()
    store.orchestrationSession = { sessionId: 's1', steps: [], status: 'done' }
    store.setMode('thinking') // not orchestrating
    store.clearOrchestration()
    expect(store.mode).toBe('thinking') // unchanged
    expect(store.orchestrationSession).toBeNull()
  })
})
