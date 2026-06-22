import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import { isRef, isReadonly } from 'vue'
import ProductsView from './ProductsView.vue'

// ===== Mock 数据准备（使用 vi.hoisted 确保 vi.mock 工厂可用） =====
const {
  mockFetchProducts,
  mockCreateProduct,
  mockUpdateProduct,
  mockDeleteProduct,
  mockBatchDelete,
  mockGetCustomers,
  mockExportUnitProductsDocx,
  mockExportUnitProductsXlsx,
  mockListTemplates,
  mockApiPost,
  mockAppAlert,
} = vi.hoisted(() => ({
  mockFetchProducts: vi.fn(),
  mockCreateProduct: vi.fn(),
  mockUpdateProduct: vi.fn(),
  mockDeleteProduct: vi.fn(),
  mockBatchDelete: vi.fn(),
  mockGetCustomers: vi.fn(),
  mockExportUnitProductsDocx: vi.fn(),
  mockExportUnitProductsXlsx: vi.fn(),
  mockListTemplates: vi.fn(),
  mockApiPost: vi.fn(),
  mockAppAlert: vi.fn(),
}))

// ===== Mock 模块 =====
vi.mock('@/stores/products', async () => {
  const { ref } = await import('vue')
  return {
    useProductsStore: () => ({
      products: ref([]),
      loading: ref(false),
      fetchProducts: mockFetchProducts,
      createProduct: mockCreateProduct,
      updateProduct: mockUpdateProduct,
      deleteProduct: mockDeleteProduct,
      batchDelete: mockBatchDelete,
    }),
  }
})

// mock storeToRefs 以兼容 mock store（直接返回 store 上的 ref 属性）
vi.mock('pinia', async () => {
  const actual = await vi.importActual<typeof import('pinia')>('pinia')
  return {
    ...actual,
    storeToRefs: (store: any) => {
      const result: Record<string, any> = {}
      for (const key of Object.keys(store)) {
        const v = store[key]
        if (v && typeof v === 'object' && 'value' in v) {
          result[key] = v
        }
      }
      return result
    },
  }
})

vi.mock('@/api/customers', () => ({
  default: {
    getCustomers: mockGetCustomers,
  },
}))

vi.mock('@/api/products', () => ({
  default: {
    exportUnitProductsDocx: mockExportUnitProductsDocx,
    exportUnitProductsXlsx: mockExportUnitProductsXlsx,
  },
}))

vi.mock('@/api/templatePreview', () => ({
  default: {
    listTemplates: mockListTemplates,
  },
}))

vi.mock('@/api/index', () => ({
  api: { post: mockApiPost },
}))

vi.mock('@/utils/appDialog', () => ({
  appAlert: mockAppAlert,
}))

vi.mock('@/composables/useCoreNavLabel', () => ({
  useCoreNavLabel: () => ({ value: '产品管理' }),
}))

// ===== 辅助函数 =====
function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/products', name: 'products', component: ProductsView }],
  })
}

/** 创建模拟 Response 对象（含 blob/headers） */
function makeResponse(options: {
  blob?: Blob
  disposition?: string
} = {}) {
  const blob = options.blob || new Blob(['fake-content'])
  const disposition = options.disposition || ''
  return {
    blob: async () => blob,
    headers: {
      get: (name: string) => (name.toLowerCase() === 'content-disposition' ? disposition : null),
    },
  }
}

/** 挂载组件 */
async function mountProducts() {
  const router = makeRouter()
  await router.push('/products')
  await router.isReady()
  const wrapper = mount(ProductsView, {
    global: {
      plugins: [router],
      stubs: {
        DataTable: {
          name: 'DataTable',
          props: ['data', 'columns', 'selectedIds', 'selectable', 'loading', 'hasMore', 'height', 'rowKey', 'emptyText'],
          emits: ['update:selectedIds', 'loadMore'],
          template: `<div class="data-table-stub" />`,
        },
        ConfirmDialog: {
          name: 'ConfirmDialog',
          props: ['modelValue', 'title', 'message', 'confirmText', 'confirmClass'],
          emits: ['confirm', 'update:modelValue'],
          template: `<div v-if="modelValue" class="confirm-dialog-stub" @click="$emit('confirm')" />`,
        },
      },
    },
  })
  await flushPromises()
  return wrapper
}

/** 获取 setup 中的 raw ref 状态（可读写） */
function getRawState(wrapper: any): Record<string, any> {
  return wrapper.vm.$.devtoolsRawSetupState || {}
}

/** 获取 setup 中的公开状态（只读代理） */
function getSetupState(wrapper: any): Record<string, any> {
  return wrapper.vm.$.setupState || wrapper.vm || {}
}

/** 设置 setup 状态值（自动判断 ref 还是普通属性） */
function setSetupValue(wrapper: any, key: string, value: any) {
  const raw = getRawState(wrapper)
  const setupState = getSetupState(wrapper)
  try {
    if (isRef(raw[key]) && !isReadonly(raw[key])) {
      raw[key].value = value
      return
    }
  } catch {
    // readonly ref
  }
  try {
    setupState[key] = value
  } catch {
    // public proxy may be readonly
  }
}

/** 获取 setup 中 ref 的值 */
function getSetupRefValue(wrapper: any, key: string): any {
  const raw = getRawState(wrapper)
  if (isRef(raw[key])) return raw[key].value
  return getSetupState(wrapper)[key]
}

describe('ProductsView.coverage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    // mock URL.createObjectURL / revokeObjectURL（jsdom 不提供）
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:mock-url'),
      revokeObjectURL: vi.fn(),
    })
    mockFetchProducts.mockResolvedValue({ success: true, data: [], total: 0 })
    mockGetCustomers.mockResolvedValue({
      success: true,
      data: [{ unit_name: '单位A' }, { customer_name: '客户B' }],
    })
    mockListTemplates.mockResolvedValue({ success: true, templates: [] })
    mockApiPost.mockResolvedValue({ success: true })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  // ===== onMounted 生命周期 =====
  describe('onMounted 生命周期', () => {
    it('挂载时加载单位、产品和 Word 模板', async () => {
      await mountProducts()
      expect(mockGetCustomers).toHaveBeenCalledWith({ page: 1, per_page: 1000 })
      expect(mockFetchProducts).toHaveBeenCalled()
      expect(mockListTemplates).toHaveBeenCalled()
    })
  })

  // ===== loadUnits 单位加载 =====
  describe('loadUnits 加载产品单位', () => {
    it('成功加载单位列表（unit_name + customer_name）', async () => {
      const wrapper = await mountProducts()
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'units')).toEqual(['单位A', '客户B'])
    })

    it('返回 success=false 时抛错并清空单位', async () => {
      mockGetCustomers.mockResolvedValue({ success: false, message: '权限不足' })
      const wrapper = await mountProducts()
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'units')).toEqual([])
    })

    it('返回非数组 data 时清空单位', async () => {
      mockGetCustomers.mockResolvedValue({ success: true, data: null })
      const wrapper = await mountProducts()
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'units')).toEqual([])
    })

    it('请求异常时清空单位', async () => {
      mockGetCustomers.mockRejectedValue(new Error('网络错误'))
      const wrapper = await mountProducts()
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'units')).toEqual([])
    })
  })

  // ===== loadProducts 产品加载 =====
  describe('loadProducts 加载产品列表', () => {
    it('reset=true 时重置分页并替换列表', async () => {
      mockFetchProducts.mockResolvedValue({
        success: true,
        data: [{ id: 1, name: 'P1' }],
        total: 1,
      })
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      await state.loadProducts(true)
      await flushPromises()
      expect(mockFetchProducts).toHaveBeenCalledWith(
        expect.objectContaining({ page: 1, per_page: 1000 }),
      )
    })

    it('reset=false 时追加列表（loadMore 场景）', async () => {
      mockFetchProducts.mockResolvedValue({
        success: true,
        data: [{ id: 2, name: 'P2' }],
        total: 1,
      })
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      setSetupValue(wrapper, 'products', [{ id: 1, name: 'P1' }])
      await state.loadProducts(false)
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'products')).toHaveLength(2)
    })

    it('带搜索关键字和单位时传递参数', async () => {
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      setSetupValue(wrapper, 'searchQuery', 'A001')
      setSetupValue(wrapper, 'selectedUnit', '单位A')
      await state.loadProducts(true)
      await flushPromises()
      expect(mockFetchProducts).toHaveBeenCalledWith(
        expect.objectContaining({ keyword: 'A001', unit: '单位A' }),
      )
    })

    it('result 为 null 时不更新列表', async () => {
      mockFetchProducts.mockResolvedValue(null)
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      setSetupValue(wrapper, 'products', [{ id: 1, name: 'existing' }])
      await state.loadProducts(true)
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'products')).toEqual([{ id: 1, name: 'existing' }])
    })

    it('result 无 data 字段时不更新列表', async () => {
      mockFetchProducts.mockResolvedValue({ success: true })
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      setSetupValue(wrapper, 'products', [{ id: 1, name: 'existing' }])
      await state.loadProducts(true)
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'products')).toEqual([{ id: 1, name: 'existing' }])
    })
  })

  // ===== loadMoreProducts 加载更多 =====
  describe('loadMoreProducts 加载更多', () => {
    it('hasMore=false 时不加载', async () => {
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      setSetupValue(wrapper, 'hasMore', false)
      setSetupValue(wrapper, 'loading', false)
      const callCountBefore = mockFetchProducts.mock.calls.length
      await state.loadMoreProducts()
      await flushPromises()
      expect(mockFetchProducts.mock.calls.length).toBe(callCountBefore)
    })

    it('loading=true 时不加载', async () => {
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      setSetupValue(wrapper, 'hasMore', true)
      setSetupValue(wrapper, 'loading', true)
      const callCountBefore = mockFetchProducts.mock.calls.length
      await state.loadMoreProducts()
      await flushPromises()
      expect(mockFetchProducts.mock.calls.length).toBe(callCountBefore)
    })

    it('hasMore=true 且非 loading 时触发加载', async () => {
      mockFetchProducts.mockResolvedValue({
        success: true,
        data: [{ id: 99, name: 'more' }],
        total: 1,
      })
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      setSetupValue(wrapper, 'hasMore', true)
      setSetupValue(wrapper, 'loading', false)
      await state.loadMoreProducts()
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'products').some((p: any) => p.id === 99)).toBe(true)
    })
  })

  // ===== showAddModal / editProduct =====
  describe('showAddModal / editProduct 模态框', () => {
    it('showAddModal 打开添加模态框并重置表单', async () => {
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      state.showAddModal()
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'showModal')).toBe(true)
      expect(getSetupRefValue(wrapper, 'isEdit')).toBe(false)
      expect(getSetupRefValue(wrapper, 'formData')).toEqual({
        id: null,
        model_number: '',
        name: '',
        specification: '',
        price: 0,
      })
    })

    it('editProduct 打开编辑模态框并填充表单', async () => {
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      const product = { id: 5, model_number: 'M5', name: 'P5', specification: 'spec', price: 99 }
      state.editProduct(product)
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'showModal')).toBe(true)
      expect(getSetupRefValue(wrapper, 'isEdit')).toBe(true)
      expect(getSetupRefValue(wrapper, 'formData')).toEqual(product)
    })
  })

  // ===== saveProduct 保存产品 =====
  describe('saveProduct 保存产品', () => {
    it('新建产品成功时关闭模态框并刷新列表', async () => {
      mockCreateProduct.mockResolvedValue({ success: true })
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      setSetupValue(wrapper, 'isEdit', false)
      setSetupValue(wrapper, 'formData', { id: null, model_number: 'A1', name: 'N1', specification: '', price: 10 })
      setSetupValue(wrapper, 'showModal', true)
      await state.saveProduct()
      await flushPromises()
      expect(mockCreateProduct).toHaveBeenCalled()
      expect(getSetupRefValue(wrapper, 'showModal')).toBe(false)
    })

    it('新建产品失败时弹出告警', async () => {
      mockCreateProduct.mockResolvedValue({ success: false, message: '型号已存在' })
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      setSetupValue(wrapper, 'isEdit', false)
      setSetupValue(wrapper, 'formData', { id: null, model_number: 'A1', name: 'N1', specification: '', price: 10 })
      setSetupValue(wrapper, 'showModal', true)
      await state.saveProduct()
      await flushPromises()
      expect(mockAppAlert).toHaveBeenCalledWith('保存失败: 型号已存在')
      expect(getSetupRefValue(wrapper, 'showModal')).toBe(true)
    })

    it('编辑产品成功时关闭模态框', async () => {
      mockUpdateProduct.mockResolvedValue({ success: true })
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      setSetupValue(wrapper, 'isEdit', true)
      setSetupValue(wrapper, 'formData', { id: 7, model_number: 'A7', name: 'N7', specification: '', price: 10 })
      setSetupValue(wrapper, 'showModal', true)
      await state.saveProduct()
      await flushPromises()
      expect(mockUpdateProduct).toHaveBeenCalledWith(7, getSetupRefValue(wrapper, 'formData'))
      expect(getSetupRefValue(wrapper, 'showModal')).toBe(false)
    })

    it('编辑产品失败时弹出告警', async () => {
      mockUpdateProduct.mockResolvedValue({ success: false, message: '更新失败' })
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      setSetupValue(wrapper, 'isEdit', true)
      setSetupValue(wrapper, 'formData', { id: 7, model_number: 'A7', name: 'N7', specification: '', price: 10 })
      await state.saveProduct()
      await flushPromises()
      expect(mockAppAlert).toHaveBeenCalledWith('保存失败: 更新失败')
    })
  })

  // ===== handleDelete / confirmDelete =====
  describe('handleDelete / confirmDelete 删除', () => {
    it('handleDelete 设置待删除项并显示确认框', async () => {
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      const product = { id: 10, name: 'del' }
      state.handleDelete(product)
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'itemToDelete')).toEqual(product)
      expect(getSetupRefValue(wrapper, 'showDeleteConfirm')).toBe(true)
    })

    it('confirmDelete 删除成功时不弹告警', async () => {
      mockDeleteProduct.mockResolvedValue({ success: true })
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      setSetupValue(wrapper, 'itemToDelete', { id: 10, name: 'del' })
      setSetupValue(wrapper, 'showDeleteConfirm', true)
      await state.confirmDelete()
      await flushPromises()
      expect(mockDeleteProduct).toHaveBeenCalledWith(10)
      expect(getSetupRefValue(wrapper, 'itemToDelete')).toBeNull()
      expect(mockAppAlert).not.toHaveBeenCalled()
    })

    it('confirmDelete 删除失败时弹告警', async () => {
      mockDeleteProduct.mockResolvedValue({ success: false, message: '权限不足' })
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      setSetupValue(wrapper, 'itemToDelete', { id: 10, name: 'del' })
      await state.confirmDelete()
      await flushPromises()
      expect(mockAppAlert).toHaveBeenCalledWith('删除失败: 权限不足')
    })

    it('confirmDelete 无待删除项时直接返回', async () => {
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      setSetupValue(wrapper, 'itemToDelete', null)
      await state.confirmDelete()
      await flushPromises()
      expect(mockDeleteProduct).not.toHaveBeenCalled()
    })
  })

  // ===== batchDelete / confirmBatchDelete =====
  describe('batchDelete / confirmBatchDelete 批量删除', () => {
    it('batchDelete 显示批量删除确认框', async () => {
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      state.batchDelete()
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'showBatchDeleteConfirm')).toBe(true)
    })

    it('confirmBatchDelete 成功时清空选中并刷新', async () => {
      mockBatchDelete.mockResolvedValue({ success: true })
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      setSetupValue(wrapper, 'selectedIds', [1, 2, 3])
      setSetupValue(wrapper, 'selectAll', true)
      await state.confirmBatchDelete()
      await flushPromises()
      expect(mockBatchDelete).toHaveBeenCalledWith([1, 2, 3])
      expect(getSetupRefValue(wrapper, 'selectedIds')).toEqual([])
      expect(getSetupRefValue(wrapper, 'selectAll')).toBe(false)
    })

    it('confirmBatchDelete 失败时弹告警', async () => {
      mockBatchDelete.mockResolvedValue({ success: false, message: '部分失败' })
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      setSetupValue(wrapper, 'selectedIds', [1, 2])
      await state.confirmBatchDelete()
      await flushPromises()
      expect(mockAppAlert).toHaveBeenCalledWith('批量删除失败: 部分失败')
    })
  })

  // ===== docxSlugFromListTemplate / loadWordTemplateOptions =====
  describe('loadWordTemplateOptions 加载 Word 模板选项', () => {
    it('filename 以 .docx 结尾时去掉后缀作为 slug', async () => {
      mockListTemplates.mockResolvedValue({
        success: true,
        templates: [
          { id: 't1', name: '价目表A', filename: 'price_list_a.docx', category: 'word' },
        ],
      })
      const wrapper = await mountProducts()
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'wordTemplateOptions')).toEqual([
        { id: 'price_list_a', name: '价目表A（Word）' },
      ])
    })

    it('id 以 fs: 前缀且 .docx 结尾时去掉前缀和后缀', async () => {
      mockListTemplates.mockResolvedValue({
        success: true,
        templates: [
          { id: 'fs:price_list_b.docx', name: '价目表B', filename: '', category: 'word' },
        ],
      })
      const wrapper = await mountProducts()
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'wordTemplateOptions')).toEqual([
        { id: 'price_list_b', name: '价目表B（Word）' },
      ])
    })

    it('filename 非 .docx 且 id 非 .docx 时回退到 slug', async () => {
      mockListTemplates.mockResolvedValue({
        success: true,
        templates: [
          { id: 't3', name: '价格表C', filename: 'template.xlsx', slug: 'price_c', category: 'word' },
        ],
      })
      const wrapper = await mountProducts()
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'wordTemplateOptions')).toEqual([
        { id: 'price_c', name: '价格表C（Word）' },
      ])
    })

    it('过滤掉 virtual 模板', async () => {
      mockListTemplates.mockResolvedValue({
        success: true,
        templates: [
          { id: 't1', name: '价目A', filename: 'price_list_a.docx', category: 'word', virtual: true },
          { id: 't2', name: '价目B', filename: 'price_list_b.docx', category: 'word' },
        ],
      })
      const wrapper = await mountProducts()
      await flushPromises()
      const opts = getSetupRefValue(wrapper, 'wordTemplateOptions')
      expect(opts).toHaveLength(1)
      expect(opts[0].id).toBe('price_list_b')
    })

    it('过滤掉非 word 类别模板', async () => {
      mockListTemplates.mockResolvedValue({
        success: true,
        templates: [
          { id: 't1', name: '价目A', filename: 'price_list_a.docx', category: 'excel' },
        ],
      })
      const wrapper = await mountProducts()
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'wordTemplateOptions')).toEqual([
        { id: 'price_list_default', name: '产品价格表（Word 价目，默认）' },
      ])
    })

    it('过滤掉非价目相关模板（name/filename/id 不含价目关键词）', async () => {
      mockListTemplates.mockResolvedValue({
        success: true,
        templates: [
          { id: 't1', name: '普通模板', filename: 'normal.docx', category: 'word' },
        ],
      })
      const wrapper = await mountProducts()
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'wordTemplateOptions')).toEqual([
        { id: 'price_list_default', name: '产品价格表（Word 价目，默认）' },
      ])
    })

    it('name 含"价目"时匹配', async () => {
      mockListTemplates.mockResolvedValue({
        success: true,
        templates: [
          { id: 't1', name: '客户价目表', filename: 'cust.docx', category: 'word' },
        ],
      })
      const wrapper = await mountProducts()
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'wordTemplateOptions')).toHaveLength(1)
    })

    it('id 含 price_list 时匹配', async () => {
      mockListTemplates.mockResolvedValue({
        success: true,
        templates: [
          { id: 'price_list_special', name: '特殊', filename: 'special.docx', category: 'word' },
        ],
      })
      const wrapper = await mountProducts()
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'wordTemplateOptions')).toHaveLength(1)
    })

    it('slug 重复时去重', async () => {
      mockListTemplates.mockResolvedValue({
        success: true,
        templates: [
          { id: 't1', name: '价目A', filename: 'price_list.docx', category: 'word' },
          { id: 't2', name: '价目B', filename: 'price_list.docx', category: 'word' },
        ],
      })
      const wrapper = await mountProducts()
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'wordTemplateOptions')).toHaveLength(1)
    })

    it('slug 为空时跳过', async () => {
      mockListTemplates.mockResolvedValue({
        success: true,
        templates: [
          { id: '', name: '价目A', filename: '', slug: '', category: 'word' },
        ],
      })
      const wrapper = await mountProducts()
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'wordTemplateOptions')).toEqual([
        { id: 'price_list_default', name: '产品价格表（Word 价目，默认）' },
      ])
    })

    it('当前选中 slug 不在新列表中时清空', async () => {
      mockListTemplates.mockResolvedValue({
        success: true,
        templates: [
          { id: 't1', name: '价目A', filename: 'price_list_a.docx', category: 'word' },
        ],
      })
      const wrapper = await mountProducts()
      await flushPromises()
      setSetupValue(wrapper, 'selectedWordTemplateSlug', 'old_slug')
      const state = getSetupState(wrapper)
      await state.loadWordTemplateOptions()
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'selectedWordTemplateSlug')).toBe('')
    })

    it('listTemplates 返回 success=false 时不更新', async () => {
      mockListTemplates.mockResolvedValue({ success: false })
      const wrapper = await mountProducts()
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'wordTemplateOptions')).toEqual([])
    })

    it('listTemplates 异常时不抛错', async () => {
      mockListTemplates.mockRejectedValue(new Error('网络错误'))
      const wrapper = await mountProducts()
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'wordTemplateOptions')).toEqual([])
    })

    it('templates 非数组时使用默认模板', async () => {
      mockListTemplates.mockResolvedValue({ success: true, templates: null })
      const wrapper = await mountProducts()
      await flushPromises()
      // templates 为 null 时被当作空数组，无匹配 → 使用默认模板
      expect(getSetupRefValue(wrapper, 'wordTemplateOptions')).toEqual([
        { id: 'price_list_default', name: '产品价格表（Word 价目，默认）' },
      ])
    })
  })

  // ===== exportPriceList 导出 Word 价格表 =====
  describe('exportPriceList 导出 Word 价格表', () => {
    it('成功导出并解析 UTF-8 文件名', async () => {
      const utf8Name = encodeURIComponent('自定义价目表.docx')
      mockExportUnitProductsDocx.mockResolvedValue(
        makeResponse({ disposition: `attachment; filename*=UTF-8''${utf8Name}` }),
      )
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      setSetupValue(wrapper, 'selectedUnit', '单位A')
      setSetupValue(wrapper, 'searchQuery', 'kw')
      setSetupValue(wrapper, 'selectedWordTemplateSlug', 'tpl1')
      await state.exportPriceList()
      await flushPromises()
      expect(mockExportUnitProductsDocx).toHaveBeenCalledWith({
        unit: '单位A',
        keyword: 'kw',
        template_id: 'tpl1',
      })
    })

    it('UTF-8 文件名解码失败时使用原始值', async () => {
      mockExportUnitProductsDocx.mockResolvedValue(
        makeResponse({ disposition: `attachment; filename*=UTF-8''%E9%94%99%E8%AF%AF%` }),
      )
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      await state.exportPriceList()
      await flushPromises()
      expect(mockExportUnitProductsDocx).toHaveBeenCalled()
    })

    it('使用普通 filename 头', async () => {
      mockExportUnitProductsDocx.mockResolvedValue(
        makeResponse({ disposition: 'attachment; filename="plain_name.docx"' }),
      )
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      await state.exportPriceList()
      await flushPromises()
      expect(mockExportUnitProductsDocx).toHaveBeenCalled()
    })

    it('无 content-disposition 时使用默认文件名', async () => {
      mockExportUnitProductsDocx.mockResolvedValue(makeResponse({ disposition: '' }))
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      await state.exportPriceList()
      await flushPromises()
      expect(mockExportUnitProductsDocx).toHaveBeenCalled()
    })

    it('导出异常时弹告警', async () => {
      mockExportUnitProductsDocx.mockRejectedValue(new Error('导出超时'))
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      await state.exportPriceList()
      await flushPromises()
      expect(mockAppAlert).toHaveBeenCalledWith('导出失败: 导出超时')
    })
  })

  // ===== exportPriceListExcel 导出 Excel 价格表 =====
  describe('exportPriceListExcel 导出 Excel 价格表', () => {
    it('成功导出并解析 UTF-8 文件名', async () => {
      const utf8Name = encodeURIComponent('Excel价目.xlsx')
      mockExportUnitProductsXlsx.mockResolvedValue(
        makeResponse({ disposition: `attachment; filename*=UTF-8''${utf8Name}` }),
      )
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      setSetupValue(wrapper, 'selectedUnit', '单位B')
      setSetupValue(wrapper, 'searchQuery', 'q1')
      await state.exportPriceListExcel()
      await flushPromises()
      expect(mockExportUnitProductsXlsx).toHaveBeenCalledWith({
        unit: '单位B',
        keyword: 'q1',
      })
    })

    it('UTF-8 文件名解码失败时使用原始值', async () => {
      mockExportUnitProductsXlsx.mockResolvedValue(
        makeResponse({ disposition: `attachment; filename*=UTF-8''%invalid%` }),
      )
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      await state.exportPriceListExcel()
      await flushPromises()
      expect(mockExportUnitProductsXlsx).toHaveBeenCalled()
    })

    it('使用普通 filename 头', async () => {
      mockExportUnitProductsXlsx.mockResolvedValue(
        makeResponse({ disposition: 'attachment; filename=plain.xlsx' }),
      )
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      await state.exportPriceListExcel()
      await flushPromises()
      expect(mockExportUnitProductsXlsx).toHaveBeenCalled()
    })

    it('无 content-disposition 时使用默认文件名', async () => {
      mockExportUnitProductsXlsx.mockResolvedValue(makeResponse({ disposition: '' }))
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      await state.exportPriceListExcel()
      await flushPromises()
      expect(mockExportUnitProductsXlsx).toHaveBeenCalled()
    })

    it('导出异常时弹告警', async () => {
      mockExportUnitProductsXlsx.mockRejectedValue(new Error('Excel 导出失败'))
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      await state.exportPriceListExcel()
      await flushPromises()
      expect(mockAppAlert).toHaveBeenCalledWith('Excel 导出失败: Excel 导出失败')
    })
  })

  // ===== triggerImportExcel =====
  describe('triggerImportExcel 触发导入', () => {
    it('调用 importExcelInput 的 click 方法', async () => {
      const wrapper = await mountProducts()
      await flushPromises()
      const raw = getRawState(wrapper)
      const clickSpy = vi.fn()
      raw.importExcelInput.value = { click: clickSpy }
      raw.triggerImportExcel()
      expect(clickSpy).toHaveBeenCalled()
    })

    it('importExcelInput 为 null 时不报错', async () => {
      const wrapper = await mountProducts()
      await flushPromises()
      const raw = getRawState(wrapper)
      raw.importExcelInput.value = null
      expect(() => raw.triggerImportExcel()).not.toThrow()
    })
  })

  // ===== handleImport 导入 Excel =====
  describe('handleImport 处理 Excel 导入', () => {
    it('无文件时直接返回', async () => {
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      const event = { target: { files: [], value: '' } }
      await state.handleImport(event)
      await flushPromises()
      expect(mockApiPost).not.toHaveBeenCalled()
    })

    it('解析失败时弹告警', async () => {
      mockApiPost.mockResolvedValueOnce({ success: false, message: '格式错误' })
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      const file = new File(['content'], 'test.xlsx', { type: 'application/vnd.ms-excel' })
      const event = { target: { files: [file], value: 'test.xlsx' } }
      await state.handleImport(event)
      await flushPromises()
      expect(mockAppAlert).toHaveBeenCalledWith('文件解析失败: 格式错误')
    })

    it('解析成功但无数据行时弹告警（普通模式）', async () => {
      mockApiPost.mockResolvedValueOnce({ success: true, rows: [], headers: [] })
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      const file = new File(['content'], 'test.xlsx')
      const event = { target: { files: [file], value: 'test.xlsx' } }
      await state.handleImport(event)
      await flushPromises()
      expect(mockAppAlert).toHaveBeenCalledWith(
        '未解析到任何数据行，请检查表头或换用「考勤统计表·明细导入人员」。',
      )
    })

    it('解析成功但无数据行时弹告警（考勤明细模式）', async () => {
      mockApiPost.mockResolvedValueOnce({ success: true, rows: [], headers: [] })
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      setSetupValue(wrapper, 'useAttendanceDetailImport', true)
      const file = new File(['content'], 'test.xlsx')
      const event = { target: { files: [file], value: 'test.xlsx' } }
      await state.handleImport(event)
      await flushPromises()
      expect(mockAppAlert).toHaveBeenCalledWith(
        expect.stringContaining('未从「明细」表解析到任何人员行'),
      )
    })

    it('导入成功时弹告警并刷新列表', async () => {
      mockApiPost.mockResolvedValueOnce({
        success: true,
        rows: [{ name: 'P1' }],
        headers: [{ value: 'name' }],
      })
      mockApiPost.mockResolvedValueOnce({
        success: true,
        imported: 5,
        skipped: 2,
      })
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      const file = new File(['content'], 'test.xlsx')
      const event = { target: { files: [file], value: 'test.xlsx' } }
      await state.handleImport(event)
      await flushPromises()
      expect(mockAppAlert).toHaveBeenCalledWith('导入成功！共导入 5 条产品，跳过 2 条重复产品')
    })

    it('导入成功但无跳过时只显示导入数', async () => {
      mockApiPost.mockResolvedValueOnce({
        success: true,
        rows: [{ name: 'P1' }],
        headers: [{ value: 'name' }],
      })
      mockApiPost.mockResolvedValueOnce({
        success: true,
        imported: 3,
        skipped: 0,
      })
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      const file = new File(['content'], 'test.xlsx')
      const event = { target: { files: [file], value: 'test.xlsx' } }
      await state.handleImport(event)
      await flushPromises()
      expect(mockAppAlert).toHaveBeenCalledWith('导入成功！共导入 3 条产品')
    })

    it('导入接口返回失败时弹告警', async () => {
      mockApiPost.mockResolvedValueOnce({
        success: true,
        rows: [{ name: 'P1' }],
        headers: [{ value: 'name' }],
      })
      mockApiPost.mockResolvedValueOnce({
        success: false,
        message: '字段映射错误',
      })
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      const file = new File(['content'], 'test.xlsx')
      const event = { target: { files: [file], value: 'test.xlsx' } }
      await state.handleImport(event)
      await flushPromises()
      expect(mockAppAlert).toHaveBeenCalledWith('导入失败: 字段映射错误')
    })

    it('导入过程抛异常时弹告警', async () => {
      mockApiPost.mockRejectedValue(new Error('网络中断'))
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      const file = new File(['content'], 'test.xlsx')
      const event = { target: { files: [file], value: 'test.xlsx' } }
      await state.handleImport(event)
      await flushPromises()
      expect(mockAppAlert).toHaveBeenCalledWith('导入失败: 网络中断')
    })

    it('考勤明细模式时传递 parse_mode 并启用 replace', async () => {
      mockApiPost.mockResolvedValueOnce({
        success: true,
        rows: [{ name: 'P1' }],
        headers: [{ value: 'name' }],
      })
      mockApiPost.mockResolvedValueOnce({
        success: true,
        imported: 1,
        skipped: 0,
      })
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      setSetupValue(wrapper, 'useAttendanceDetailImport', true)
      setSetupValue(wrapper, 'replaceTaggedAttendancePersonnel', true)
      const file = new File(['content'], 'test.xlsx')
      const event = { target: { files: [file], value: 'test.xlsx' } }
      await state.handleImport(event)
      await flushPromises()
      const firstCall = mockApiPost.mock.calls[0]
      expect(firstCall[0]).toBe('/api/excel/data/extract/upload')
      expect(firstCall[2].headers).toEqual({ 'Content-Type': 'multipart/form-data' })
      const secondCall = mockApiPost.mock.calls[1]
      expect(secondCall[0]).toBe('/api/excel/data/import/products')
      expect(secondCall[1].options.replace_attendance_detail_tagged).toBe(true)
    })

    it('导入完成后清空 input value', async () => {
      mockApiPost.mockResolvedValueOnce({
        success: true,
        rows: [{ name: 'P1' }],
        headers: [{ value: 'name' }],
      })
      mockApiPost.mockResolvedValueOnce({ success: true, imported: 1, skipped: 0 })
      const wrapper = await mountProducts()
      await flushPromises()
      const state = getSetupState(wrapper)
      const file = new File(['content'], 'test.xlsx')
      const event = { target: { files: [file], value: 'test.xlsx' } }
      await state.handleImport(event)
      await flushPromises()
      expect(event.target.value).toBe('')
    })
  })

  // ===== UI 交互测试 =====
  describe('UI 交互', () => {
    it('点击导出价格表 按钮触发 exportPriceList', async () => {
      mockExportUnitProductsDocx.mockResolvedValue(makeResponse({ disposition: '' }))
      const wrapper = await mountProducts()
      await flushPromises()
      const btn = wrapper.findAll('button').find((b) => b.text().includes('导出价格表'))
      expect(btn).toBeTruthy()
      await btn!.trigger('click')
      await flushPromises()
      expect(mockExportUnitProductsDocx).toHaveBeenCalled()
    })

    it('点击导出Excel 按钮触发 exportPriceListExcel', async () => {
      mockExportUnitProductsXlsx.mockResolvedValue(makeResponse({ disposition: '' }))
      const wrapper = await mountProducts()
      await flushPromises()
      const btn = wrapper.findAll('button').find((b) => b.text().includes('导出Excel'))
      expect(btn).toBeTruthy()
      await btn!.trigger('click')
      await flushPromises()
      expect(mockExportUnitProductsXlsx).toHaveBeenCalled()
    })

    it('点击添加产品 按钮打开模态框', async () => {
      const wrapper = await mountProducts()
      await flushPromises()
      const btn = wrapper.findAll('button').find((b) => b.text().includes('添加产品'))
      expect(btn).toBeTruthy()
      await btn!.trigger('click')
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'showModal')).toBe(true)
    })

    it('搜索框输入时触发 loadProducts', async () => {
      const wrapper = await mountProducts()
      await flushPromises()
      const input = wrapper.find('input[type="text"]')
      expect(input.exists()).toBe(true)
      await input.setValue('A001')
      await flushPromises()
      expect(mockFetchProducts).toHaveBeenCalled()
    })

    it('单位选择变更时触发 loadProducts', async () => {
      const wrapper = await mountProducts()
      await flushPromises()
      const selects = wrapper.findAll('select')
      expect(selects.length).toBeGreaterThanOrEqual(1)
      await selects[0].setValue('单位A')
      await flushPromises()
      expect(mockFetchProducts).toHaveBeenCalled()
    })

    it('模态框取消按钮关闭模态框', async () => {
      const wrapper = await mountProducts()
      await flushPromises()
      setSetupValue(wrapper, 'showModal', true)
      await flushPromises()
      const cancelBtn = wrapper.findAll('button').find((b) => b.text().includes('取消'))
      expect(cancelBtn).toBeTruthy()
      await cancelBtn!.trigger('click')
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'showModal')).toBe(false)
    })

    it('模态框保存按钮触发 saveProduct', async () => {
      mockCreateProduct.mockResolvedValue({ success: true })
      const wrapper = await mountProducts()
      await flushPromises()
      setSetupValue(wrapper, 'showModal', true)
      setSetupValue(wrapper, 'isEdit', false)
      setSetupValue(wrapper, 'formData', { id: null, model_number: 'A1', name: 'N1', specification: '', price: 10 })
      await flushPromises()
      const saveBtn = wrapper.findAll('button').find((b) => b.text().includes('保存'))
      expect(saveBtn).toBeTruthy()
      await saveBtn!.trigger('click')
      await flushPromises()
      expect(mockCreateProduct).toHaveBeenCalled()
    })
  })

  // ===== ConfirmDialog 事件 =====
  describe('ConfirmDialog 确认框事件', () => {
    it('删除确认框 confirm 事件触发 confirmDelete', async () => {
      mockDeleteProduct.mockResolvedValue({ success: true })
      const wrapper = await mountProducts()
      await flushPromises()
      setSetupValue(wrapper, 'itemToDelete', { id: 10, name: 'del' })
      setSetupValue(wrapper, 'showDeleteConfirm', true)
      await flushPromises()
      const dialogs = wrapper.findAll('.confirm-dialog-stub')
      expect(dialogs.length).toBeGreaterThan(0)
      await dialogs[0].trigger('click')
      await flushPromises()
      expect(mockDeleteProduct).toHaveBeenCalledWith(10)
    })
  })

  // ===== DataTable 事件 =====
  describe('DataTable 事件', () => {
    it('update:selectedIds 事件更新 selectedIds', async () => {
      const wrapper = await mountProducts()
      await flushPromises()
      const dt = wrapper.findComponent({ name: 'DataTable' })
      dt.vm.$emit('update:selectedIds', [1, 2, 3])
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'selectedIds')).toEqual([1, 2, 3])
    })

    it('loadMore 事件触发 loadMoreProducts', async () => {
      mockFetchProducts.mockResolvedValue({
        success: true,
        data: [{ id: 99, name: 'more' }],
        total: 1,
      })
      const wrapper = await mountProducts()
      await flushPromises()
      setSetupValue(wrapper, 'hasMore', true)
      setSetupValue(wrapper, 'loading', false)
      await flushPromises()
      const dt = wrapper.findComponent({ name: 'DataTable' })
      dt.vm.$emit('loadMore')
      await flushPromises()
      expect(getSetupRefValue(wrapper, 'products').some((p: any) => p.id === 99)).toBe(true)
    })
  })
})
