import { defineComponent, reactive } from 'vue'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { fetchImUnreadTotal } from '@/api/im'
import { useImUnreadBadge } from './useImUnreadBadge'

const Host = defineComponent({
  setup() {
    useImUnreadBadge()
    return {}
  },
  template: '<div />',
})

vi.mock('@/api/im', () => ({
  fetchImUnreadTotal: vi.fn().mockResolvedValue(5),
}))

vi.mock('@/utils/adminConsoleUrl', () => ({
  isAdminConsoleSpa: vi.fn().mockReturnValue(false),
}))

vi.mock('vue-router', () => ({
  useRoute: vi.fn().mockReturnValue({ name: 'chat' }),
}))

describe('useImUnreadBadge', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns imUnreadTotal ref', () => {
    const { imUnreadTotal } = useImUnreadBadge()
    expect(imUnreadTotal).toBeDefined()
    expect(typeof imUnreadTotal.value).toBe('number')
  })

  it('returns refreshImUnreadTotal function', () => {
    const { refreshImUnreadTotal } = useImUnreadBadge()
    expect(typeof refreshImUnreadTotal).toBe('function')
  })

  it('refreshImUnreadTotal fetches and sets total', async () => {
    const { imUnreadTotal, refreshImUnreadTotal } = useImUnreadBadge()
    await refreshImUnreadTotal()
    expect(imUnreadTotal.value).toBe(5)
  })

  it('refreshImUnreadTotal sets 0 on public routes', async () => {
    const { useRoute } = await import('vue-router')
    vi.mocked(useRoute).mockReturnValue({ name: 'login' } as any)
    const { imUnreadTotal, refreshImUnreadTotal } = useImUnreadBadge()
    await refreshImUnreadTotal()
    expect(imUnreadTotal.value).toBe(0)
  })

  it('refreshImUnreadTotal sets 0 on login-prefixed routes', async () => {
    const { useRoute } = await import('vue-router')
    vi.mocked(useRoute).mockReturnValue({ name: 'login-help' } as any)
    const { imUnreadTotal, refreshImUnreadTotal } = useImUnreadBadge()
    await refreshImUnreadTotal()
    expect(imUnreadTotal.value).toBe(0)
  })

  it('refreshImUnreadTotal sets 0 on lan-gate route', async () => {
    const { useRoute } = await import('vue-router')
    vi.mocked(useRoute).mockReturnValue({ name: 'lan-gate' } as any)
    const { imUnreadTotal, refreshImUnreadTotal } = useImUnreadBadge()
    await refreshImUnreadTotal()
    expect(imUnreadTotal.value).toBe(0)
  })

  it('refreshImUnreadTotal sets 0 on product-onboarding route', async () => {
    const { useRoute } = await import('vue-router')
    vi.mocked(useRoute).mockReturnValue({ name: 'product-onboarding' } as any)
    const { imUnreadTotal, refreshImUnreadTotal } = useImUnreadBadge()
    await refreshImUnreadTotal()
    expect(imUnreadTotal.value).toBe(0)
  })

  it('resumes unread polling when the sidebar remounts signed in', async () => {
    const { useRoute } = await import('vue-router')
    vi.mocked(useRoute).mockReturnValue({ name: 'chat' } as any)
    const first = mount(Host)
    await flushPromises()
    window.dispatchEvent(new Event('xcagi:session-unauthorized'))
    first.unmount()

    vi.mocked(fetchImUnreadTotal).mockClear()
    const second = mount(Host)
    await flushPromises()
    expect(fetchImUnreadTotal).toHaveBeenCalled()
    second.unmount()
  })

  it('restarts unread polling when login ends and the route becomes private', async () => {
    const { useRoute } = await import('vue-router')
    const route = reactive({ name: 'login' })
    vi.mocked(useRoute).mockReturnValue(route as never)
    const callbacks: Array<() => void> = []
    const intervalSpy = vi.spyOn(window, 'setInterval').mockImplementation((handler) => {
      callbacks.push(handler as () => void)
      return 1 as unknown as ReturnType<typeof setInterval>
    })
    const clearSpy = vi.spyOn(window, 'clearInterval').mockImplementation(() => undefined)
    const wrapper = mount(Host)
    await flushPromises()
    route.name = 'chat'
    await flushPromises()
    window.dispatchEvent(new Event('xcagi:session-unauthorized'))
    route.name = 'login'
    await flushPromises()
    vi.mocked(fetchImUnreadTotal).mockClear()
    route.name = 'settings'
    await flushPromises()
    expect(fetchImUnreadTotal).toHaveBeenCalled()
    callbacks.at(-1)?.()
    await flushPromises()
    expect(fetchImUnreadTotal.mock.calls.length).toBeGreaterThan(1)
    wrapper.unmount()
    vi.mocked(useRoute).mockReturnValue({ name: 'chat' } as never)
    intervalSpy.mockRestore()
    clearSpy.mockRestore()
  })

  it('refreshImUnreadTotal sets 0 for admin console SPA', async () => {
    const { isAdminConsoleSpa } = await import('@/utils/adminConsoleUrl')
    vi.mocked(isAdminConsoleSpa).mockReturnValue(true)
    const { imUnreadTotal, refreshImUnreadTotal } = useImUnreadBadge()
    await refreshImUnreadTotal()
    expect(imUnreadTotal.value).toBe(0)
    vi.mocked(isAdminConsoleSpa).mockReturnValue(false)
  })
})
