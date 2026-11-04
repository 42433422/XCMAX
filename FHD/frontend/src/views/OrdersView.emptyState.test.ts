import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import OrdersView from '../../../mods/xcagi-erp-domain-bridge/frontend/views/OrdersView.vue'
import { useOrdersStore } from '@/stores/orders'

const { clearOrders, prompt } = vi.hoisted(() => ({ clearOrders: vi.fn(), prompt: vi.fn() }))
vi.mock('@/api/orders', () => ({ default: { getOrders: vi.fn(async () => ({ success: true, data: [] })), clearAllOrders: clearOrders } }))
vi.mock('@/stores/tutorialV2', () => ({ useTutorialV2Store: () => ({ courses: [], loadCourses: async () => {} }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/utils/appDialog', () => ({ appAlert: vi.fn(), appConfirm: vi.fn(), appPrompt: prompt }))

beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks() })
it('blocks empty, loading, and failed lists and rechecks before clearing', async () => {
  const wrapper = mount(OrdersView, { global: { stubs: { DataTable: true, ConfirmDialog: true } } })
  await flushPromises()
  const store = useOrdersStore()
  const button = wrapper.get('.page-header .btn-danger')
  const actions = (wrapper.vm as any).$?.setupState
  expect(button.attributes('disabled')).toBeDefined()
  await actions.handleClearAll()
  await actions.confirmClearAll()
  expect(prompt).not.toHaveBeenCalled()
  expect(clearOrders).not.toHaveBeenCalled()
  store.orders = [{ id: 'test-order', order_number: 'test-order' }] as any
  await flushPromises()
  expect(button.attributes('disabled')).toBeUndefined()
  store.loading = true
  await actions.handleClearAll()
  store.loading = false
  store.error = '读取失败'
  await actions.confirmClearAll()
  expect(prompt).not.toHaveBeenCalled()
  expect(clearOrders).not.toHaveBeenCalled()
  wrapper.unmount()
})
