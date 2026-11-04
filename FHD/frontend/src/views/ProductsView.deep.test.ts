import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import ProductsView from './ProductsView.vue'
import { api } from '@/api/index'
import { appAlert } from '@/utils/appDialog'

const mockFetchProducts = vi.fn().mockResolvedValue({
  success: true,
  data: [{ id: 1, model_number: 'A1', name: 'P1', price: 10 }],
})

vi.mock('@/stores/products', async () => {
  const { ref } = await import('vue')
  return {
    useProductsStore: () => {
      const products = ref([])
      const loading = ref(false)
      return {
        products,
        loading,
        error: ref(null), fresh: ref(true), canEditProducts: ref(true), scopeEpoch: ref(0), invalidationVersion: ref(0), mutating: false,
      syncReadScope: vi.fn(), captureProductsScope: () => ({ key: 'test', epoch: 0 }), isProductsScopeCurrent: () => true,
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
  api: { get: vi.fn().mockResolvedValue({ success: true }), post: vi.fn() },
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

  it('imports selected Excel rows as products without attendance options', async () => {
    const rows = [{ model_number: 'A1', name: 'P1', price: 10 }]
    vi.mocked(api.post)
      .mockResolvedValueOnce({ success: true, rows, headers: [{ value: 'name' }] })
      .mockResolvedValueOnce({ success: true, imported: 1, skipped: 0 })
    const wrapper = await mountProducts()
    await flushPromises()
    const initialFetches = mockFetchProducts.mock.calls.length
    expect(wrapper.find('.page-header input[type="checkbox"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('导入人员')

    const input = wrapper.get<HTMLInputElement>('input[type="file"]')
    const file = new File(['product data'], 'products.xlsx')
    Object.defineProperty(input.element, 'files', { value: [file] })
    await input.trigger('change')
    await flushPromises()

    expect(api.post).toHaveBeenCalledTimes(2)
    const [extractUrl, form] = vi.mocked(api.post).mock.calls[0]
    expect(extractUrl).toBe('/api/excel/data/extract/upload')
    expect(form).toBeInstanceOf(FormData)
    expect((form as FormData).get('excel_file')).toBe(file)
    expect((form as FormData).has('parse_mode')).toBe(false)
    expect(api.post).toHaveBeenNthCalledWith(2, '/api/excel/data/import/products', {
      file_name: 'products.xlsx',
      data: rows,
      field_mapping: { name: 'name' },
      options: { skip_duplicates: true, validate_before_import: true, clean_data: true },
    })
    expect(appAlert).toHaveBeenCalledWith('导入成功！共导入 1 条产品')
    expect(mockFetchProducts.mock.calls.length).toBeGreaterThan(initialFetches)
    expect(input.element.value).toBe('')
    wrapper.unmount()
  })
})
