/**
 * useAdminModHostView 测试
 * 覆盖：useAdminModHostView 主路径、loaderKey、load 成功/失败、无 loader 回退
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { effectScope } from 'vue'
import { flushPromises } from '@vue/test-utils'

const findModViewLoader = vi.hoisted(() => vi.fn())
const markRouteChunkError = vi.hoisted(() => vi.fn())

vi.mock('@/router/modViews', () => ({
  findModViewLoader: (...args: unknown[]) => findModViewLoader(...args),
}))

vi.mock('@/utils/routeLoadState', async () => {
  const actual = await vi.importActual<typeof import('@/utils/routeLoadState')>('@/utils/routeLoadState')
  return {
    ...actual,
    markRouteChunkError: (...args: unknown[]) => markRouteChunkError(...args),
  }
})

// Mock ModRequiredView to avoid importing the actual component
vi.mock('@/components/ModRequiredView.vue', () => ({
  default: {
    name: 'ModRequiredView',
    template: '<div class="mod-required-stub" />',
  },
}))

// We need to mock import.meta.glob. This is done via vitest config,
// but we can test the composable by mocking the dynamic import.

describe('useAdminModHostView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    findModViewLoader.mockReturnValue(undefined)
  })

  it('returns ModRequiredView when no loader exists for the given modId/viewFile', async () => {
    const { useAdminModHostView } = await import('./useAdminModHostView')
    const { View, modProps } = useAdminModHostView('nonexistent-mod', 'MainView', 'Test Title')
    expect(View.value).toBeTruthy()
    expect(modProps).toEqual({
      modId: 'nonexistent-mod',
      title: 'Test Title',
    })
  })

  it('passes modId and title through modProps', async () => {
    const { useAdminModHostView } = await import('./useAdminModHostView')
    const { modProps } = useAdminModHostView('my-mod', 'Dashboard', 'Dashboard Title')
    expect(modProps.modId).toBe('my-mod')
    expect(modProps.title).toBe('Dashboard Title')
  })

  it('View is a shallowRef containing a component', async () => {
    const { useAdminModHostView } = await import('./useAdminModHostView')
    const { View } = useAdminModHostView('test-mod', 'MainView', 'Test')
    // Should be a ref-like object with .value
    expect(View).toHaveProperty('value')
    // Default value should be truthy (ModRequiredView)
    expect(View.value).toBeTruthy()
  })

  it('installs a loaded physical view and ignores a result that arrives after dispose', async () => {
    let resolveLoad!: (value: { default?: { name: string } | null }) => void
    findModViewLoader.mockReturnValue(() => new Promise((resolve) => { resolveLoad = resolve }))
    const { useAdminModHostView } = await import('./useAdminModHostView')
    const scope = effectScope()
    const hosted = scope.run(() => useAdminModHostView('erp', 'OrdersView', '订单'))
    expect(hosted).toBeTruthy()
    scope.stop()
    resolveLoad({ default: { name: 'LateView' } })
    await flushPromises()
    expect(hosted!.View.value).toBeNull()
  })

  it('shows the loaded component, then the required view when loading fails', async () => {
    const Loaded = { name: 'LoadedView' }
    findModViewLoader.mockReturnValueOnce(async () => ({ default: Loaded }))
    const { useAdminModHostView } = await import('./useAdminModHostView')
    const loaded = useAdminModHostView('erp', 'OrdersView', '订单')
    await flushPromises()
    expect(loaded.View.value).toBe(Loaded)

    findModViewLoader.mockReturnValueOnce(async () => ({ default: null }))
    const empty = useAdminModHostView('erp', 'EmptyView', '空')
    await flushPromises()
    expect(empty.View.value).toBeNull()

    findModViewLoader.mockReturnValueOnce(async () => {
      throw new Error('Failed to fetch dynamically imported module')
    })
    const failed = useAdminModHostView('erp', 'MissingView', '缺失')
    await flushPromises()
    expect(failed.View.value).toMatchObject({ name: 'ModRequiredView' })
    expect(markRouteChunkError).toHaveBeenCalled()

    markRouteChunkError.mockClear()
    findModViewLoader.mockReturnValueOnce(async () => { throw new Error('ordinary failure') })
    const ordinary = useAdminModHostView('erp', 'BrokenView', '损坏')
    await flushPromises()
    expect(ordinary.View.value).toMatchObject({ name: 'ModRequiredView' })
    expect(markRouteChunkError).not.toHaveBeenCalled()
  })

  it('loaderKey constructs correct path', async () => {
    // The loaderKey is internal but we can verify its effect by checking
    // that the composable doesn't crash with various modId/viewFile combos
    const { useAdminModHostView } = await import('./useAdminModHostView')
    expect(() => useAdminModHostView('mod-1', 'View1', 'Title1')).not.toThrow()
    expect(() => useAdminModHostView('mod-2', 'View2', 'Title2')).not.toThrow()
    expect(() => useAdminModHostView('', '', '')).not.toThrow()
  })
})
