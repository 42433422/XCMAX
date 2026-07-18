/**
 * useAdminModHostView 测试
 * 覆盖：useAdminModHostView 主路径、loaderKey、load 成功/失败、无 loader 回退
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { nextTick } from 'vue'

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

  it('loaderKey constructs correct path', async () => {
    // The loaderKey is internal but we can verify its effect by checking
    // that the composable doesn't crash with various modId/viewFile combos
    const { useAdminModHostView } = await import('./useAdminModHostView')
    expect(() => useAdminModHostView('mod-1', 'View1', 'Title1')).not.toThrow()
    expect(() => useAdminModHostView('mod-2', 'View2', 'Title2')).not.toThrow()
    expect(() => useAdminModHostView('', '', '')).not.toThrow()
  })

  it('loads every registered admin Mod physical view', async () => {
    const { modRuntimeViewLoaders, useAdminModHostView } = await import('./useAdminModHostView')
    const registered = Object.entries(modRuntimeViewLoaders)

    expect(registered.length).toBeGreaterThan(0)
    const results = await Promise.allSettled(registered.map(([, load]) => load()))
    expect(results).toHaveLength(registered.length)
    expect(results.some((result) => result.status === 'fulfilled')).toBe(true)

    const fulfilledIndex = results.findIndex((result) => result.status === 'fulfilled')
    const matched = registered[fulfilledIndex][0].match(
      /mods-admin-runtime\/([^/]+)\/frontend\/views\/([^/]+)\.vue$/,
    )
    expect(matched).not.toBeNull()
    const fulfilled = results[fulfilledIndex]
    if (fulfilled.status !== 'fulfilled') throw new Error('expected fulfilled Mod view loader')
    const { View } = useAdminModHostView(matched![1], matched![2], 'Registered view')
    await vi.waitFor(() => expect(View.value).toBe(fulfilled.value.default))
  })

  it('keeps the fallback view when a registered loader rejects', async () => {
    const { modRuntimeViewLoaders, useAdminModHostView } = await import('./useAdminModHostView')
    const key = '../../../mods-admin-runtime/test-rejection/frontend/views/MainView.vue'
    modRuntimeViewLoaders[key] = vi.fn().mockRejectedValue(new Error('load failed'))

    const { View } = useAdminModHostView('test-rejection', 'MainView', 'Rejected view')
    const fallback = View.value
    await nextTick()
    await Promise.resolve()

    expect(View.value).toBe(fallback)
    delete modRuntimeViewLoaders[key]
  })
})
