import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import ProductsView from './ProductsView.vue'

vi.mock('@/utils/apiBase', () => ({
  getApiBase: () => '',
  apiFetch: vi.fn().mockResolvedValue({ ok: true, json: async () => ({ success: true, data: [], total: 0 }) }),
}))
vi.mock('@/utils/appDialog', () => ({
  appAlert: vi.fn(),
  appConfirm: vi.fn().mockResolvedValue(true),
}))

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/products', name: 'products', component: ProductsView }],
  })
}

describe('ProductsView.vue', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('mounts products page', async () => {
    const router = makeRouter()
    await router.push('/products')
    await router.isReady()
    const wrapper = mount(ProductsView, {
      global: {
        plugins: [router],
        stubs: {
          DataTable: true,
          RouterLink: true,
        },
      },
    })
    expect(wrapper.find('#view-products').exists()).toBe(true)
  })

  it('reads the top-search model and focuses that product row', async () => {
    const router = makeRouter()
    await router.push({ path: '/products', query: { keyword: 'A001', focus: '7' } })
    await router.isReady()
    const wrapper = mount(ProductsView, {
      global: {
        plugins: [router],
        stubs: {
          DataTable: { props: ['highlightId'], template: '<div class="stub-table">{{ highlightId }}</div>' },
          RouterLink: true,
        },
      },
    })
    const search = wrapper.findAll('input').find((node) => (node.attributes('placeholder') || '').includes('型号'))
    expect((search?.element as HTMLInputElement).value).toBe('A001')
    expect(wrapper.find('.stub-table').text()).toBe('7')
  })
})
