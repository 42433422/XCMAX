import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import AdminEmployeeWorkNotificationBridge from './AdminEmployeeWorkNotificationBridge.vue'

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  push: vi.fn(),
}))

vi.mock('@/api/managementWork', () => ({
  managementWorkApi: { list: mocks.list },
}))

vi.mock('@/utils/adminConsoleUrl', () => ({
  isAdminConsoleSpa: () => true,
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ fullPath: '/employee-inbox', meta: {} }),
  useRouter: () => ({ push: mocks.push }),
}))

describe('AdminEmployeeWorkNotificationBridge', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    localStorage.clear()
    mocks.list.mockReset()
    mocks.list.mockResolvedValue({ items: [] })
    mocks.push.mockReset()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
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
})
