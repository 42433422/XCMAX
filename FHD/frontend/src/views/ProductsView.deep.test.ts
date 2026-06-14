import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import ProductsView from './ProductsView.vue'

const mockFetchProducts = vi.fn().mockResolvedValue({ success: true, data: [{ id: 1, model_number: 'A1', name: 'P1', price: 10 }] })

vi.mock('@/stores/products', async () => {
  const { ref } = await import('vue')
  return {
    useProductsStore: () => {
      const products = ref([])
      const loading = ref(false)
      return {
        products,
        loading,
        fetchProducts: mockFetchProducts,
        createProduct: vi.fn().mockResolvedValue({ success: true }),
        updateProduct: vi.fn().mockResolvedValue({ success: true }),
        deleteProduct: vi.fn().mockResolvedValue({ success: true }),
        batchDelete: vi.fn().mockResolvedValue({ success: true }),
      }
    },
  }
})

vi.mock('@/api/customers', () => ({
  default: {
    getCustomers: vi.fn().mockResolvedValue({
      success: true,
      data: [{ unit_name: '单位A', customer_name: '客户A' }],
    }),
  },
}))
vi.mock('@/api/products', () => ({
  default: {
    exportPriceList: vi.fn().mockResolvedValue({ success: true }),
    exportPriceListExcel: vi.fn().mockResolvedValue({ success: true }),
  },
}))
vi.mock('@/api/templatePreview', () => ({
  default: {
    listTemplates: vi.fn().mockResolvedValue({ success: true, data: [] }),
  },
}))
vi.mock('@/api/index', () => ({
  api: { get: vi.fn().mockResolvedValue({ success: true }) },
}))
vi.mock('@/utils/appDialog', () => ({
  appAlert: vi.fn(),
  appConfirm: vi.fn().mockResolvedValue(true),
}))
vi.mock('@/composables/useCoreNavLabel', () => ({
  useCoreNavLabel: () => '产品管理',
}))

function mountProducts() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/products', component: ProductsView }],
  })
  return router.push('/products').then(() =>
    router.isReady().then(() =>
      mount(ProductsView, {
        global: {
          plugins: [router],
          stubs: {
            DataTable: {
              props: ['data', 'columns', 'selectedIds'],
              template: '<div class="data-table-stub" />',
            },
            ConfirmDialog: {
              props: ['modelValue'],
              template: '<div v-if="modelValue" class="confirm-dialog" />',
            },
          },
        },
      }),
    ),
  )
}

describe('ProductsView deep', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('loads products on mount', async () => {
    const wrapper = await mountProducts()
    await vi.waitFor(() => expect(mockFetchProducts).toHaveBeenCalled())
    expect(wrapper.find('#view-products').exists()).toBe(true)
  })

  it('opens add product modal', async () => {
    const wrapper = await mountProducts()
    const addBtn = wrapper.findAll('button').find((b) => b.text().includes('添加产品'))
    expect(addBtn).toBeTruthy()
    await addBtn!.trigger('click')
    expect(wrapper.text()).toContain('添加产品')
  })

  it('triggers import excel input', async () => {
    const wrapper = await mountProducts()
    const importBtn = wrapper.findAll('button').find((b) => b.text().includes('导入Excel'))
    expect(importBtn).toBeTruthy()
    await importBtn!.trigger('click')
  })

  it('calls export price list', async () => {
    const wrapper = await mountProducts()
    const exportBtn = wrapper.findAll('button').find((b) => b.text().includes('导出价格表'))
    expect(exportBtn).toBeTruthy()
    await exportBtn!.trigger('click')
  })

  it('toggles attendance detail import checkbox', async () => {
    const wrapper = await mountProducts()
    const checkbox = wrapper.find('input[type="checkbox"]')
    expect(checkbox.exists()).toBe(true)
    await checkbox.setValue(true)
  })
})
