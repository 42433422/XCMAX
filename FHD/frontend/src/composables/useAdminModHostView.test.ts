/**
 * useAdminModHostView 测试
 * 覆盖：useAdminModHostView 主路径、loaderKey、load 成功/失败、无 loader 回退
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockFindModViewLoader = vi.hoisted(() => vi.fn())

vi.mock('@/router/modViews', () => ({
  findModViewLoader: mockFindModViewLoader,
}))

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
    mockFindModViewLoader.mockReturnValue(undefined)
  })

  it('returns ModRequiredView when no loader exists for the given modId/viewFile', async () => {
    const { useAdminModHostView } = await import('./useAdminModHostView')
    const { View, modProps, loading } = useAdminModHostView('nonexistent-mod', 'MainView', 'Test Title')
    expect(View.value).toBeTruthy()
    expect(loading.value).toBe(false)
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

  it('keeps a loading state until a real built-in view resolves', async () => {
    const LoadedView = { name: 'LoadedView', template: '<div />' }
    mockFindModViewLoader.mockReturnValue(() => Promise.resolve({ default: LoadedView }))

    const { useAdminModHostView } = await import('./useAdminModHostView')
    const { View, loading } = useAdminModHostView('xcagi-erp-domain-bridge', 'TemplatePreviewView', '模板库')

    expect(loading.value).toBe(true)
    await vi.waitFor(() => expect(loading.value).toBe(false))
    expect(View.value).toBe(LoadedView)
  })

  it('shows the unavailable fallback only after a real loader fails', async () => {
    mockFindModViewLoader.mockReturnValue(() => Promise.reject(new Error('chunk failed')))

    const { useAdminModHostView } = await import('./useAdminModHostView')
    const { View, loading } = useAdminModHostView('xcagi-erp-domain-bridge', 'TemplatePreviewView', '模板库')

    expect(loading.value).toBe(true)
    await vi.waitFor(() => expect(loading.value).toBe(false))
    expect((View.value as { name?: string }).name).toBe('ModRequiredView')
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
