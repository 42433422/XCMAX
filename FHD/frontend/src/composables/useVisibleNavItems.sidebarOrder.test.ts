import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { computed, effectScope, nextTick, ref } from 'vue'
import plannerManifest from '../../../mods/xcagi-planner-bridge/manifest.json'
import { ADMIN_SIDEBAR_PINNED_TOP_KEYS } from '../../../admin-console/src/constants/adminOperatorNav'

vi.mock('@/constants/adminOperatorNav', async () => await import('../../../admin-console/src/constants/adminOperatorNav'))

vi.mock('@/stores/industry', () => ({ useIndustryStore: () => ({ currentIndustryId: '涂料' }) }))
vi.mock('@/stores/accountProfile', () => ({
  useAccountProfileStore: () => ({ accountKind: 'enterprise', marketIsEnterprise: true, marketIsAdmin: false, isAdminAccount: false }),
}))
vi.mock('@/stores/mods', async () => {
  const { defineStore } = await import('pinia')
  const { ref, computed } = await import('vue')
  return {
    useModsStore: defineStore('sidebar-order-fixture-mods', () => {
      const mods = ref<Array<{ id: string; menu_overrides?: unknown[]; menu?: Array<Record<string, string>> }>>([])
      return {
        mods, modsForUi: computed(() => mods.value), activeModId: ref(null), modRoutes: ref([]),
        getModMenu: () => mods.value.flatMap((mod) => (mod.menu || []).map((item) => ({ ...item, modId: mod.id }))),
      }
    }),
  }
})
vi.mock('@/constants/platformShellMode', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/constants/platformShellMode')>(),
  isPlatformShellModeEnabled: () => false,
  shouldExposeIndustrySidebar: () => true,
}))

import { useModsStore } from '@/stores/mods'
import { useSidebarLayoutStore } from '@/stores/sidebarLayout'
import { useModRoutes } from './useModRoutes'
import { useVisibleNavItems } from './useVisibleNavItems'
import { useSidebarMenuReorder } from '@/components/sidebar/useSidebarMenuReorder'
import { pinSidebarMenuItemsTop } from '@/utils/pinSidebarMenuItemsTop'

const plannerChat = plannerManifest.frontend.menu.find((item) => item.id === 'mod-planner-chat')!
const businessKeys = ['products', 'customers', 'orders']
const subset = (items: Array<{ key: string }>) => items.map((item) => item.key).filter((key) => businessKeys.includes(key))

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '')
  vi.stubEnv('VITE_XCAGI_EDITION', 'generic')
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllEnvs()
})

describe('sidebar chat ordering through real menu mapping and persisted layout', () => {
  it('maps the actual planner manifest to the top despite a cached business-first order', () => {
    useModsStore().mods = [{
      id: plannerManifest.id,
      menu_overrides: plannerManifest.frontend.menu_overrides,
      menu: plannerManifest.frontend.menu,
    }] as never
    expect(useModRoutes().modMenuItems.value.find((item) => item.key === plannerChat.id)?.path).toBe('/mod/xcagi-planner-bridge/chat')
    localStorage.setItem('xcagi.sidebar.menuOrder', JSON.stringify([...businessKeys, plannerChat.id]))
    const nav = useVisibleNavItems()
    expect(nav.menuItems.value[0]).toMatchObject({ key: plannerChat.id, path: plannerChat.path })
    expect(subset(nav.menuItems.value)).toEqual(businessKeys)
    expect(nav.menuItems.value.some((item) => item.key.includes('brain'))).toBe(false)
  })

  it('keeps host chat first while repeated stored-order changes update the other entries', async () => {
    const store = useSidebarLayoutStore()
    localStorage.setItem('xcagi.sidebar.menuOrder', JSON.stringify([...businessKeys, 'chat']))
    const nav = useVisibleNavItems()
    expect(nav.menuItems.value[0]?.key).toBe('chat')
    expect(subset(nav.menuItems.value)).toEqual(businessKeys)
    store.resetOrder(['orders', 'products', 'customers', 'chat'])
    await nextTick()
    expect(subset(nav.menuItems.value)).toEqual(['orders', 'products', 'customers'])
    store.resetOrder(['customers', 'orders', 'products', 'chat'])
    await nextTick()
    expect(subset(nav.menuItems.value)).toEqual(['customers', 'orders', 'products'])
    store.menuOrder.splice(0, 3, 'products', 'customers', 'orders')
    await nextTick()
    expect(subset(nav.menuItems.value)).toEqual(businessKeys)
    expect(nav.menuItems.value[0]?.key).toBe('chat')
  })
})

describe('drag preview and committed sidebar order', () => {
  function setup(chatKey: string, extraKeys: string[] = []) {
    vi.useFakeTimers()
    const scope = effectScope()
    const store = useSidebarLayoutStore()
    const raw = [{ key: 'products' }, { key: 'orders' }, { key: chatKey }, ...extraKeys.map((key) => ({ key }))]
    store.resetOrder(raw.map((item) => item.key))
    const menuItems = computed(() => pinSidebarMenuItemsTop(store.applyOrder(raw)))
    const gesture = scope.run(() => useSidebarMenuReorder({ sidebarLayoutStore: store, menuItems, sidebarMenuRef: ref(null) }))!
    return { store, gesture, scope }
  }

  it.each(['chat', plannerChat.id, 'mod-mod-planner-chat'])('pins %s in both preview and pointerup result', async (chatKey) => {
    const { store, gesture, scope } = setup(chatKey)
    try {
      gesture.onReorderPointerDown({ button: 2, pointerId: 9, preventDefault: vi.fn() }, 'orders')
      await vi.advanceTimersByTimeAsync(gesture.LONG_PRESS_MS)
      gesture.dragOverKey.value = chatKey
      expect(gesture.displayMenuItems.value.map((item: { key: string }) => item.key)).toEqual([chatKey, 'orders', 'products'])
      const up = new Event('pointerup')
      Object.defineProperty(up, 'pointerId', { value: 9 })
      window.dispatchEvent(up)
      await nextTick()
      expect(gesture.displayMenuItems.value.map((item: { key: string }) => item.key)).toEqual([chatKey, 'orders', 'products'])
      expect(store.menuOrder).toEqual([chatKey, 'orders', 'products'])
      expect(JSON.parse(localStorage.getItem('xcagi.sidebar.menuOrder') || '[]')).toEqual(store.menuOrder)
    } finally {
      gesture.clearReorderGesture()
      scope.stop()
    }
  })

  it('cannot drag the pinned chat below business entries', async () => {
    const { store, gesture, scope } = setup(plannerChat.id)
    try {
      gesture.onReorderPointerDown({ button: 2, pointerId: 9, preventDefault: vi.fn() }, plannerChat.id)
      await vi.advanceTimersByTimeAsync(gesture.LONG_PRESS_MS)
      gesture.dragOverKey.value = 'orders'
      expect(gesture.displayMenuItems.value[0]?.key).toBe(plannerChat.id)
      const up = new Event('pointerup')
      Object.defineProperty(up, 'pointerId', { value: 9 })
      window.dispatchEvent(up)
      expect(store.menuOrder).toEqual([plannerChat.id, 'products', 'orders'])
    } finally {
      gesture.clearReorderGesture()
      scope.stop()
    }
  })

  it('keeps the actual admin pinned sequence in drag preview and persisted result', async () => {
    vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '1')
    const { store, gesture, scope } = setup('chat', ADMIN_SIDEBAR_PINNED_TOP_KEYS.filter((key) => key !== 'chat'))
    try {
      gesture.onReorderPointerDown({ button: 2, pointerId: 9, preventDefault: vi.fn() }, 'orders')
      await vi.advanceTimersByTimeAsync(gesture.LONG_PRESS_MS)
      gesture.dragOverKey.value = 'chat'
      const expected = [...ADMIN_SIDEBAR_PINNED_TOP_KEYS, 'orders', 'products']
      expect(gesture.displayMenuItems.value.map((item: { key: string }) => item.key)).toEqual(expected)
      const up = new Event('pointerup')
      Object.defineProperty(up, 'pointerId', { value: 9 })
      window.dispatchEvent(up)
      expect(store.menuOrder).toEqual(expected)
    } finally {
      gesture.clearReorderGesture()
      scope.stop()
    }
  })

  it('does not persist a drag when reordering is disabled before pointerup', async () => {
    const { store, gesture, scope } = setup(plannerChat.id)
    try {
      const originalOrder = [...store.menuOrder]
      gesture.onReorderPointerDown({ button: 2, pointerId: 9, preventDefault: vi.fn() }, 'orders')
      await vi.advanceTimersByTimeAsync(gesture.LONG_PRESS_MS)
      gesture.dragOverKey.value = plannerChat.id
      store.setReorderEnabled(false)
      const up = new Event('pointerup')
      Object.defineProperty(up, 'pointerId', { value: 9 })
      window.dispatchEvent(up)
      expect(store.menuOrder).toEqual(originalOrder)
      expect(gesture.draggingKey.value).toBe('')
    } finally {
      gesture.clearReorderGesture()
      scope.stop()
    }
  })
})
