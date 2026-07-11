import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import AdminEmployeeWorkNotificationBridge from './AdminEmployeeWorkNotificationBridge.vue'

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  push: vi.fn(),
  isAdminConsole: true,
  route: {
    fullPath: '/employee-inbox',
    meta: {} as Record<string, unknown>,
  },
}))

vi.mock('@/api/managementWork', () => ({
  managementWorkApi: { list: mocks.list },
}))

vi.mock('@/utils/adminConsoleUrl', () => ({
  isAdminConsoleSpa: () => mocks.isAdminConsole,
}))

vi.mock('vue-router', () => ({
  useRoute: () => mocks.route,
  useRouter: () => ({ push: mocks.push }),
}))

function workItem(
  overrides: Partial<{
    task_id: string
    title: string
    description: string
    owner_employee_id: string
    status: string
    priority: string
    risk_level: string
    progress: number
    current_stage: string
    last_update: string
    error: string
    attempt_count: number
    max_attempts: number
    updated_at: string
  }> = {},
) {
  return {
    task_id: 'task-1',
    title: '核对发布候选',
    description: '确认发布证据完整',
    owner_employee_id: 'release-manager',
    status: 'running',
    priority: 'high',
    risk_level: 'medium',
    progress: 50,
    attempt_count: 1,
    max_attempts: 3,
    ...overrides,
  }
}

function installDesktopBridge(overrides: Record<string, unknown> = {}) {
  const bridge = {
    setBadge: vi.fn().mockResolvedValue(undefined),
    showNotification: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  }
  Object.defineProperty(window, 'xcagiDesktop', {
    configurable: true,
    writable: true,
    value: bridge,
  })
  return bridge
}

describe('AdminEmployeeWorkNotificationBridge', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    localStorage.clear()
    mocks.isAdminConsole = true
    mocks.route.fullPath = '/employee-inbox'
    mocks.route.meta = {}
    mocks.list.mockReset()
    mocks.list.mockResolvedValue({ items: [] })
    mocks.push.mockReset()
    Object.defineProperty(window, 'xcagiDesktop', {
      configurable: true,
      writable: true,
      value: undefined,
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    Object.defineProperty(window, 'xcagiDesktop', {
      configurable: true,
      writable: true,
      value: undefined,
    })
    vi.useRealTimers()
  })

  it('polls only the management proxy and never opens the shared IM WebSocket', async () => {
    const webSocket = vi.fn()
    vi.stubGlobal('WebSocket', webSocket)

    const wrapper = mount(AdminEmployeeWorkNotificationBridge)
    await flushPromises()

    expect(mocks.list).toHaveBeenCalledWith({ limit: 500 })
    expect(webSocket).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(5_000)
    await flushPromises()
    expect(mocks.list).toHaveBeenCalledTimes(2)
    expect(webSocket).not.toHaveBeenCalled()

    wrapper.unmount()
  })

  it('persists the first task baseline and publishes the attention badge without noisy alerts', async () => {
    const desktop = installDesktopBridge()
    mocks.list.mockResolvedValue({
      items: [
        workItem({ task_id: 'decision', status: 'waiting_decision' }),
        workItem({ task_id: 'delivery', status: 'delivered' }),
        workItem({ task_id: 'blocked', status: 'blocked' }),
        workItem({ task_id: 'failed', status: 'failed' }),
        workItem({ task_id: 'active', status: 'running' }),
      ],
    })

    const wrapper = mount(AdminEmployeeWorkNotificationBridge)
    await flushPromises()

    expect(desktop.setBadge).toHaveBeenCalledWith(4)
    expect(desktop.showNotification).not.toHaveBeenCalled()
    expect(
      JSON.parse(
        localStorage.getItem('xcagi.admin.employee-work.notification-snapshot.v1') || '{}',
      ),
    ).toEqual({
      decision: 'waiting_decision|release-manager||',
      delivery: 'delivered|release-manager||',
      blocked: 'blocked|release-manager||',
      failed: 'failed|release-manager||',
      active: 'running|release-manager||',
    })

    wrapper.unmount()
  })

  it('notifies every meaningful management transition once and ignores ordinary progress', async () => {
    localStorage.setItem('xcagi.admin.employee-work.notification-snapshot.v1', '{}')
    const desktop = installDesktopBridge()
    mocks.list.mockResolvedValue({
      items: [
        workItem({
          task_id: 'decision',
          status: 'waiting_decision',
          last_update: '请选择是否正式发布',
        }),
        workItem({
          task_id: 'delivery',
          title: '',
          owner_employee_id: '',
          status: 'delivered',
          current_stage: '验收材料已生成',
        }),
        workItem({ task_id: 'blocked', status: 'blocked', error: '缺少签名证书' }),
        workItem({ task_id: 'failed', status: 'failed' }),
        workItem({ task_id: 'stopping', status: 'cancel_requested' }),
        workItem({ task_id: 'cancelled', status: 'cancelled' }),
        workItem({
          task_id: 'reassigned',
          status: 'assigned',
          current_stage: 'reassigned',
          owner_employee_id: 'security-reviewer',
        }),
        workItem({ task_id: 'active', status: 'running' }),
      ],
    })

    const wrapper = mount(AdminEmployeeWorkNotificationBridge)
    await flushPromises()

    expect(desktop.setBadge).toHaveBeenCalledWith(4)
    expect(desktop.showNotification).toHaveBeenCalledTimes(7)
    expect(desktop.showNotification).toHaveBeenNthCalledWith(
      1,
      '员工等待你决策',
      'release-manager：核对发布候选；请选择是否正式发布',
    )
    expect(desktop.showNotification).toHaveBeenNthCalledWith(
      2,
      '员工已交付，等待验收',
      '管理端员工：delivery；验收材料已生成',
    )
    expect(desktop.showNotification).toHaveBeenNthCalledWith(
      3,
      '员工任务被阻塞',
      'release-manager：核对发布候选；缺少签名证书',
    )
    expect(desktop.showNotification).toHaveBeenNthCalledWith(
      4,
      '员工任务执行失败',
      'release-manager：核对发布候选',
    )
    expect(desktop.showNotification).toHaveBeenNthCalledWith(
      5,
      '员工任务正在安全停止',
      'release-manager：核对发布候选',
    )
    expect(desktop.showNotification).toHaveBeenNthCalledWith(
      6,
      '员工任务已停止',
      'release-manager：核对发布候选',
    )
    expect(desktop.showNotification).toHaveBeenNthCalledWith(
      7,
      '管理任务已改派',
      '核对发布候选 → security-reviewer；reassigned',
    )

    await vi.advanceTimersByTimeAsync(5_000)
    await flushPromises()
    expect(desktop.showNotification).toHaveBeenCalledTimes(7)

    wrapper.unmount()
  })

  it('falls back to an actionable browser notification when the desktop bridge rejects', async () => {
    localStorage.setItem('xcagi.admin.employee-work.notification-snapshot.v1', '{}')
    const desktop = installDesktopBridge({
      showNotification: vi.fn().mockRejectedValue(new Error('native notification unavailable')),
    })
    mocks.list.mockResolvedValue({
      items: [workItem({ status: 'waiting_decision' })],
    })

    const notifications: Array<{
      title: string
      options?: NotificationOptions
      onclick: (() => void) | null
      close: ReturnType<typeof vi.fn>
    }> = []
    class FakeNotification {
      static permission: NotificationPermission = 'default'
      static requestPermission = vi.fn().mockResolvedValue('granted')
      title: string
      options?: NotificationOptions
      onclick: (() => void) | null = null
      close = vi.fn()

      constructor(title: string, options?: NotificationOptions) {
        this.title = title
        this.options = options
        notifications.push(this)
      }
    }
    vi.stubGlobal('Notification', FakeNotification)
    const focus = vi.spyOn(window, 'focus').mockImplementation(() => undefined)

    const wrapper = mount(AdminEmployeeWorkNotificationBridge)
    await flushPromises()

    expect(desktop.showNotification).toHaveBeenCalledTimes(1)
    expect(FakeNotification.requestPermission).toHaveBeenCalledTimes(1)
    expect(notifications).toHaveLength(1)
    expect(notifications[0]).toMatchObject({
      title: '员工等待你决策',
      options: {
        body: 'release-manager：核对发布候选',
        tag: 'xcagi-employee-work:task-1:waiting_decision',
      },
    })

    notifications[0]?.onclick?.()
    expect(focus).toHaveBeenCalledTimes(1)
    expect(mocks.push).toHaveBeenCalledWith('/employee-inbox')
    expect(notifications[0]?.close).toHaveBeenCalledTimes(1)

    wrapper.unmount()
  })

  it('suppresses privileged polling on public routes and clears any stale badge', async () => {
    mocks.route.meta = { publicAccess: true }
    const desktop = installDesktopBridge()

    const wrapper = mount(AdminEmployeeWorkNotificationBridge)
    await flushPromises()

    expect(mocks.list).not.toHaveBeenCalled()
    expect(desktop.setBadge).toHaveBeenCalledWith(0)

    wrapper.unmount()
  })

  it('does not install the poller outside the admin console SPA', async () => {
    mocks.isAdminConsole = false
    const desktop = installDesktopBridge()

    const wrapper = mount(AdminEmployeeWorkNotificationBridge)
    await flushPromises()
    await vi.advanceTimersByTimeAsync(10_000)

    expect(mocks.list).not.toHaveBeenCalled()
    expect(desktop.setBadge).not.toHaveBeenCalled()

    wrapper.unmount()
  })

  it('keeps a single request in flight and discards a response after unmount', async () => {
    let resolveList: ((value: { items: ReturnType<typeof workItem>[] }) => void) | undefined
    mocks.list.mockReturnValue(
      new Promise((resolve) => {
        resolveList = resolve
      }),
    )
    const desktop = installDesktopBridge()

    const wrapper = mount(AdminEmployeeWorkNotificationBridge)
    await flushPromises()
    await vi.advanceTimersByTimeAsync(5_000)
    expect(mocks.list).toHaveBeenCalledTimes(1)

    wrapper.unmount()
    resolveList?.({ items: [workItem({ status: 'failed' })] })
    await flushPromises()

    expect(desktop.setBadge).not.toHaveBeenCalled()
    expect(localStorage.getItem('xcagi.admin.employee-work.notification-snapshot.v1')).toBeNull()
  })
})
