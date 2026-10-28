import { makeFetchResponse, mountComponent } from './__tests__/topAssistantFloatHarness'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { webcrypto } from 'node:crypto'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { useModsStore } from '@/stores/mods'

const mockApiPost = vi.fn(async () => ({ success: true, data: {} }))
const mockApiGet = vi.fn(async () => ({ success: true, data: {} }))
const mockApiDelete = vi.fn(async () => ({ success: true, data: {} }))

vi.mock('@/api', () => {
  class ApiError extends Error {
    status?: number
    constructor(message = 'api error', status = 500) {
      super(message)
      this.status = status
    }
  }
  return {
    default: {
      get: (...args: unknown[]) => mockApiGet(...(args as [])),
      post: (...args: unknown[]) => mockApiPost(...(args as [])),
      put: vi.fn(async () => ({ success: true, data: {} })),
      delete: (...args: unknown[]) => mockApiDelete(...(args as [])),
    },
    ApiError,
  }
})

const mockSearchProducts = vi.fn(async (keyword = '') => ({
  success: true,
  data: String(keyword).trim()
    ? [
        { id: 1, model_number: 'M-1', name: '产品A', product_name: '产品A', price: 10, unit: '件' },
        { id: 2, model_number: 'M-2', name: '产品B', product_name: '产品B', price: 20, unit: '套' },
      ]
    : [],
  total: String(keyword).trim() ? 2 : 0,
}))
const mockUpdateProduct = vi.fn(async () => ({ success: true }))

vi.mock('@/api/products', () => ({
  default: {
    searchProducts: (...args: unknown[]) => mockSearchProducts(...(args as [string?])),
    updateProduct: (...args: unknown[]) => mockUpdateProduct(...(args as [number, Record<string, unknown>][])),
  },
}))

vi.mock('@/utils/erpDomainPaths', () => ({
  resolveErpApiPath: (p: string) => p,
}))

vi.mock('@/composables/useIndustryUiText', () => ({
  useIndustryUiText: () => ({
    entityName: { value: '产品' },
    entityPluralName: { value: '产品' },
    entityListName: { value: '产品列表' },
    nameLabel: { value: '名称' },
    modelLabel: { value: '型号' },
    categoryLabel: { value: '分类' },
    priceLabel: { value: '单价' },
    unitLabel: { value: '单位' },
    primaryUnit: { value: '次' },
    primaryQuantityLabel: { value: '数量' },
    queryTitle: { value: '查询' },
    queryDescription: { value: '输入关键词查询' },
    queryPlaceholder: { value: '请输入关键词' },
    searchFailedMessage: { value: '查询失败' },
    emptyBeforeSearch: { value: '请输入关键词查询' },
    keywordChanged: { value: '关键词已修改' },
    starterPackPresets: [
      { label: '预设1', hint: '提示1', text: '文本1' },
      { label: '预设2', hint: '提示2', text: '文本2' },
    ],
    shipmentOrderName: { value: '发货单' },
    recordsName: { value: '记录' },
    assistantSubtitle: { value: '通用系统' },
  }),
}))

// ===== 测试 =====

beforeEach(() => {
    setActivePinia(createPinia())
    useModsStore().activeModId = 'mod-test'
    setRuntimeTenantStorageScopeInput({ tenantId: 5, localUserId: 7 })
    vi.stubGlobal('crypto', webcrypto)
    Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: async (_key: string, _options: unknown, fn: (lock: object) => Promise<unknown>) => fn({}) } })
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => makeFetchResponse()),
    )
    localStorage.clear()
    vi.clearAllMocks()
})

afterEach(() => {
    vi.unstubAllGlobals()
    setRuntimeTenantStorageScopeInput(null)
    delete (navigator as Navigator & { locks?: unknown }).locks
    localStorage.clear()
})

describe('TopAssistantFloat functions – toggleOpen', () => {

  it('点击切换按钮打开副窗', async () => {
    const { wrapper, vm } = await mountComponent()
    expect(vm.isOpen).toBe(false)
    await vm.toggleOpen()
    await flushPromises()
    expect(vm.isOpen).toBe(true)
    expect(vm.hasUnreadPush).toBe(false)
    wrapper.unmount()
  })

  it('再次点击切换按钮关闭副窗', async () => {
    const { wrapper, vm } = await mountComponent()
    await vm.toggleOpen()
    await flushPromises()
    expect(vm.isOpen).toBe(true)
    await vm.toggleOpen()
    await flushPromises()
    expect(vm.isOpen).toBe(false)
    wrapper.unmount()
  })

  it('打开时清除 popupNotice', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.popupNotice = { title: '测试', description: '描述' }
    await vm.toggleOpen()
    await flushPromises()
    expect(vm.popupNotice).toBeNull()
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – closeAssistantPanelUi', () => {

  it('关闭打开的副窗', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.isOpen = true
    await vm.closeAssistantPanelUi()
    await flushPromises()
    expect(vm.isOpen).toBe(false)
    wrapper.unmount()
  })

  it('教程激活且有 assistantTab 时不关闭', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.isOpen = true
    // 直接修改 tutorialStore 的状态
    const tutorialStore = (await import('@/stores/tutorial')).useTutorialStore()
    tutorialStore.isActive = true
    // currentStep 是 computed，需要通过 steps 和 currentStepIndex 设置
    tutorialStore.$patch({
      steps: [{ id: 's1', assistantTab: 'push' }],
      currentStepIndex: 0,
    })
    await vm.closeAssistantPanelUi()
    await flushPromises()
    // 教程激活时不会关闭
    expect(vm.isOpen).toBe(true)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – onDocumentKeydownCapture', () => {

  it('按 Escape 关闭打开的副窗', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.isOpen = true
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    Object.defineProperty(event, 'preventDefault', { value: vi.fn() })
    Object.defineProperty(event, 'stopPropagation', { value: vi.fn() })
    window.dispatchEvent(event)
    await flushPromises()
    expect(vm.isOpen).toBe(false)
    wrapper.unmount()
  })

  it('副窗未打开时按 Escape 不处理', async () => {
    const { wrapper, vm } = await mountComponent()
    expect(vm.isOpen).toBe(false)
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    window.dispatchEvent(event)
    await flushPromises()
    expect(vm.isOpen).toBe(false)
    wrapper.unmount()
  })

  it('非 Escape 键不处理', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.isOpen = true
    const event = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
    window.dispatchEvent(event)
    await flushPromises()
    expect(vm.isOpen).toBe(true)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – recordOperation', () => {

  it('记录操作到 operationHistory', async () => {
    const { wrapper, vm } = await mountComponent()
    const initialLen = vm.operationHistory.length
    vm.recordOperation('test_op', { foo: 'bar' })
    expect(vm.operationHistory.length).toBe(initialLen + 1)
    expect(vm.operationHistory[0].type).toBe('test_op')
    expect(vm.operationHistory[0].detail).toEqual({ foo: 'bar' })
    wrapper.unmount()
  })

  it('空 type 记录为空字符串', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.recordOperation('', null)
    expect(vm.operationHistory[0].type).toBe('')
    expect(vm.operationHistory[0].detail).toEqual({})
    wrapper.unmount()
  })

  it('超过最大数量时只保留最近 30 条', async () => {
    const { wrapper, vm } = await mountComponent()
    // 写入 35 条
    for (let i = 0; i < 35; i++) {
      vm.recordOperation(`op_${i}`, { idx: i })
    }
    expect(vm.operationHistory.length).toBe(30)
    // 最新的在前面
    expect(vm.operationHistory[0].type).toBe('op_34')
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – addPush', () => {

  it('添加推送项到 pushFeed', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.addPush({ title: '测试', description: '描述' })
    expect(vm.pushFeed.length).toBe(1)
    expect(vm.pushFeed[0].title).toBe('测试')
    expect(vm.pushFeed[0].description).toBe('描述')
    wrapper.unmount()
  })

  it('空 title 使用默认值', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.addPush({ title: '', description: '' })
    expect(vm.pushFeed[0].title).toBe('新推送')
    expect(vm.pushFeed[0].description).toBe('收到一条助手消息')
    wrapper.unmount()
  })

  it('null detail 使用默认值', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.addPush(null)
    expect(vm.pushFeed[0].title).toBe('新推送')
    wrapper.unmount()
  })

  it('副窗关闭时设置 hasUnreadPush 和 popupNotice', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.isOpen = false
    vm.addPush({ title: '新消息', description: '内容' })
    expect(vm.hasUnreadPush).toBe(true)
    expect(vm.popupNotice).toEqual({ title: '新消息', description: '内容' })
    wrapper.unmount()
  })

  it('副窗打开时不设置 hasUnreadPush', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.isOpen = true
    vm.addPush({ title: '新消息', description: '内容' })
    expect(vm.hasUnreadPush).toBe(false)
    expect(vm.popupNotice).toBeNull()
    wrapper.unmount()
  })

  it('超过最大数量时只保留 12 条', async () => {
    const { wrapper, vm } = await mountComponent()
    for (let i = 0; i < 15; i++) {
      vm.addPush({ title: `推送${i}`, description: '' })
    }
    expect(vm.pushFeed.length).toBe(12)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – openFromNotice', () => {

  it('打开副窗并清除通知状态', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.isOpen = false
    vm.hasUnreadPush = true
    vm.popupNotice = { title: 't', description: 'd' }
    await vm.openFromNotice()
    expect(vm.isOpen).toBe(true)
    expect(vm.hasUnreadPush).toBe(false)
    expect(vm.popupNotice).toBeNull()
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – openTutorialTab', () => {

  it('打开副窗并切换到 tutorial 标签', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.isOpen = false
    vm.activeTab = 'push'
    vm.openTutorialTab()
    expect(vm.isOpen).toBe(true)
    expect(vm.activeTab).toBe('tutorial')
    expect(vm.hasUnreadPush).toBe(false)
    expect(vm.popupNotice).toBeNull()
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – onAssistantPanelKeydown', () => {

  it('ArrowRight 切换到下一个标签', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.activeTab = 'push'
    const target = document.createElement('button')
    target.setAttribute('role', 'tab')
    const event = { key: 'ArrowRight', preventDefault: vi.fn(), target } as any
    await vm.onAssistantPanelKeydown(event)
    expect(vm.activeTab).toBe('assistant')
    wrapper.unmount()
  })

  it('ArrowLeft 切换到上一个标签', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.activeTab = 'assistant'
    const target = document.createElement('button')
    target.setAttribute('role', 'tab')
    const event = { key: 'ArrowLeft', preventDefault: vi.fn(), target } as any
    await vm.onAssistantPanelKeydown(event)
    expect(vm.activeTab).toBe('push')
    wrapper.unmount()
  })

  it('非方向键不处理', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.activeTab = 'push'
    const target = document.createElement('button')
    target.setAttribute('role', 'tab')
    const event = { key: 'Enter', preventDefault: vi.fn(), target } as any
    await vm.onAssistantPanelKeydown(event)
    expect(vm.activeTab).toBe('push')
    wrapper.unmount()
  })

  it('target 非 tab 不处理', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.activeTab = 'push'
    const target = document.createElement('button')
    target.setAttribute('role', 'button')
    const event = { key: 'ArrowRight', preventDefault: vi.fn(), target } as any
    await vm.onAssistantPanelKeydown(event)
    expect(vm.activeTab).toBe('push')
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – onAssistantPush', () => {

  it('推送事件添加到 pushFeed', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.onAssistantPush({ detail: { title: '微信消息', description: '内容', feature: 'wechat' } })
    expect(vm.pushFeed.length).toBe(1)
    expect(vm.pushFeed[0].title).toBe('微信消息')
    wrapper.unmount()
  })

  it('无标题推送使用默认标题', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.onAssistantPush({ detail: { feature: 'other' } })
    expect(vm.pushFeed.length).toBe(1)
    expect(vm.pushFeed[0].title).toBe('新推送')
    wrapper.unmount()
  })

  it('空 detail 使用默认标题', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.onAssistantPush({ detail: null })
    expect(vm.pushFeed.length).toBe(1)
    expect(vm.pushFeed[0].title).toBe('新推送')
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – onOpenAssistantFloat', () => {

  it('forceOpen 时打开副窗', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.onOpenAssistantFloat({ detail: { forceOpen: true } })
    expect(vm.isOpen).toBe(true)
    wrapper.unmount()
  })

  it('有 task 时打开副窗', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.onOpenAssistantFloat({ detail: { task: { type: 'test' } } })
    expect(vm.isOpen).toBe(true)
    wrapper.unmount()
  })

  it('feature 为 products 时打开副窗并切换到 assistant 标签', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.onOpenAssistantFloat({ detail: { feature: 'products' } })
    expect(vm.isOpen).toBe(true)
    expect(vm.activeTab).toBe('assistant')
    wrapper.unmount()
  })

  it('feature 为 starterPack 时切换到 starterPack 标签', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.onOpenAssistantFloat({ detail: { feature: 'starterPack' } })
    expect(vm.activeTab).toBe('starterPack')
    wrapper.unmount()
  })

  it('feature 为 tutorial 时打开副窗并切换到 tutorial 标签', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.onOpenAssistantFloat({ detail: { feature: 'tutorial' } })
    expect(vm.isOpen).toBe(true)
    expect(vm.activeTab).toBe('tutorial')
    wrapper.unmount()
  })

  it('普通 feature 不打开副窗但设置 hasUnreadPush', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.onOpenAssistantFloat({ detail: { feature: 'normal' } })
    expect(vm.isOpen).toBe(false)
    expect(vm.hasUnreadPush).toBe(true)
    wrapper.unmount()
  })

  it('hydrateProductSearch 时填充产品搜索结果', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.onOpenAssistantFloat({
      detail: {
        feature: 'products',
        query: 'test',
        hydrateProductSearch: {
          rows: [{ id: 1, name: '产品1', model_number: 'M1', price: 10, unit: '件' }],
          total: 1,
        },
      },
    })
    expect(vm.productKeyword).toBe('test')
    expect(vm.productRows.length).toBe(1)
    expect(vm.productRows[0].id).toBe(1)
    expect(vm.lastProductSearchTotal).toBe(1)
    wrapper.unmount()
  })

  it('有 query 但无 hydrate 时触发搜索', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.onOpenAssistantFloat({
      detail: { feature: 'products', query: 'newquery' },
    })
    await flushPromises()
    expect(vm.productKeyword).toBe('newquery')
    // 搜索是异步的，flushPromises 后应已完成
    expect(vm.lastProductSearchQuery).toBe('newquery')
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – searchProducts', () => {

  it('空关键词清空状态', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.productKeyword = '   '
    await vm.searchProducts()
    expect(vm.productRows).toEqual([])
    expect(vm.lastProductSearchQuery).toBe('')
    expect(vm.loadingProducts).toBe(false)
    wrapper.unmount()
  })

  it('成功搜索返回产品列表', async () => {
    mockSearchProducts.mockResolvedValue({
      success: true,
      data: [{ id: 1, name: '产品A', model_number: 'M1', price: 10, unit: '件' }],
      total: 1,
    })
    const { wrapper, vm } = await mountComponent()
    vm.productKeyword = 'test'
    await vm.searchProducts()
    expect(vm.productRows.length).toBe(1)
    expect(vm.productRows[0].name).toBe('产品A')
    expect(vm.lastProductSearchQuery).toBe('test')
    expect(vm.loadingProducts).toBe(false)
    wrapper.unmount()
  })

  it('success:false 时设置错误状态', async () => {
    mockSearchProducts.mockResolvedValue({
      success: false,
      message: '查询失败',
    })
    const { wrapper, vm } = await mountComponent()
    vm.productKeyword = 'test'
    await vm.searchProducts()
    expect(vm.productRows).toEqual([])
    expect(vm.productSearchFailed).toBe(true)
    expect(vm.productSearchErrorText).toContain('查询失败')
    wrapper.unmount()
  })

  it('搜索抛异常时设置错误状态', async () => {
    mockSearchProducts.mockRejectedValue(new Error('网络错误'))
    const { wrapper, vm } = await mountComponent()
    vm.productKeyword = 'test'
    await vm.searchProducts()
    expect(vm.productRows).toEqual([])
    expect(vm.productSearchFailed).toBe(true)
    expect(vm.productSearchErrorText).toContain('网络错误')
    wrapper.unmount()
  })

  it('ApiError 时包含 HTTP 状态', async () => {
    const { ApiError } = await import('@/api')
    mockSearchProducts.mockRejectedValue(new ApiError('Server error', 500))
    const { wrapper, vm } = await mountComponent()
    vm.productKeyword = 'test'
    await vm.searchProducts()
    expect(vm.productSearchFailed).toBe(true)
    expect(vm.productSearchErrorText).toContain('HTTP 500')
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – productEmptyMessage', () => {

  it('搜索失败时返回失败消息', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.productSearchFailed = true
    vm.productSearchErrorText = '错误详情'
    expect(vm.productEmptyMessage).toContain('查询失败')
    expect(vm.productEmptyMessage).toContain('错误详情')
    wrapper.unmount()
  })

  it('未搜索时返回搜索前提示', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.productSearchFailed = false
    vm.lastProductSearchQuery = ''
    expect(vm.productEmptyMessage).toContain('请输入关键词查询')
    wrapper.unmount()
  })

  it('关键词已修改时返回修改提示', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.productSearchFailed = false
    vm.lastProductSearchQuery = 'old'
    vm.productKeyword = 'new'
    expect(vm.productEmptyMessage).toContain('关键词已修改')
    wrapper.unmount()
  })

  it('搜索无结果时返回未找到消息', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.productSearchFailed = false
    vm.lastProductSearchQuery = 'test'
    vm.productKeyword = 'test'
    vm.lastProductSearchTotal = 0
    expect(vm.productEmptyMessage).toContain('未找到')
    expect(vm.productEmptyMessage).toContain('test')
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – saveProductRow', () => {

  it('数据源审批链未验证时显式拒绝保存且不发出请求', async () => {
    const { wrapper, vm } = await mountComponent()
    await expect(vm.saveProductRow({ id: 1, name: '产品A', model_number: 'M1', price: 10, unit: '件' })).rejects.toThrow('当前数据源不可保存，未提交')
    expect(mockUpdateProduct).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('旧 ERP 即使服务宣称支持保存仍不可走旧更新接口', async () => {
    mockUpdateProduct.mockResolvedValue({ success: true })
    const { wrapper, vm } = await mountComponent()
    const row = { id: 1, name: '产品A', model_number: 'M1', price: 10, unit: '件' }
    await expect(vm.saveProductRow(row)).rejects.toThrow('当前数据源不可保存，未提交')
    expect(mockUpdateProduct).not.toHaveBeenCalled()
    expect(vm.savingProductId).toBeNull()
    wrapper.unmount()
  })

  it('无 id 时不执行', async () => {
    const { wrapper, vm } = await mountComponent()
    await vm.saveProductRow({ id: 0 })
    expect(mockUpdateProduct).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('null row 时不执行', async () => {
    const { wrapper, vm } = await mountComponent()
    await vm.saveProductRow(null)
    expect(mockUpdateProduct).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('旧 ERP 保存拒绝不会占用保存状态', async () => {
    mockUpdateProduct.mockRejectedValue(new Error('保存失败'))
    const { wrapper, vm } = await mountComponent()
    await expect(vm.saveProductRow({ id: 1, name: 'A', model_number: 'M1', price: 10, unit: '件' })).rejects.toThrow('当前数据源不可保存，未提交')
    expect(vm.savingProductId).toBeNull()
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – applyExcelSheetContext', () => {

  it('应用 Excel sheet 上下文', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.applyExcelSheetContext({
      selected_sheet: { sheet_name: 'Sheet1', sheet_index: 1 },
      excel_analysis: {
        preview_data: {
          all_sheets: [
            {
              sheet_name: 'Sheet1',
              sheet_index: 1,
              fields: ['f1'],
              sample_rows: [['v1']],
              grid_preview: { rows: [] },
            },
          ],
        },
      },
    })
    expect(vm.linkedSheetName).toBe('Sheet1')
    expect(vm.linkedSheetIndex).toBe(1)
    expect(vm.linkedSheetFields).toEqual(['f1'])
    expect(vm.linkedSheetSampleRows).toEqual([['v1']])
    wrapper.unmount()
  })

  it('空 detail 清空状态', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.applyExcelSheetContext({})
    expect(vm.linkedSheetName).toBe('')
    expect(vm.linkedSheetIndex).toBe(0)
    expect(vm.linkedGridData).toBeNull()
    expect(vm.linkedSheetFields).toEqual([])
    wrapper.unmount()
  })

  it('null detail 清空状态', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.applyExcelSheetContext(null)
    expect(vm.linkedSheetName).toBe('')
    expect(vm.linkedGridData).toBeNull()
    wrapper.unmount()
  })

  it('按 sheet_index 匹配目标 sheet', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.applyExcelSheetContext({
      selected_sheet: { sheet_name: '', sheet_index: 2 },
      excel_analysis: {
        preview_data: {
          all_sheets: [
            { sheet_name: 'A', sheet_index: 1, fields: ['a'] },
            { sheet_name: 'B', sheet_index: 2, fields: ['b'] },
          ],
        },
      },
    })
    expect(vm.linkedSheetFields).toEqual(['b'])
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – navigateToSubjectPage', () => {

  it('products 跳转到 products 路由', async () => {
    const { wrapper, router, vm } = await mountComponent()
    await vm.navigateToSubjectPage('products')
    expect(router.currentRoute.value.name).toBe('products')
    wrapper.unmount()
  })

  it('customers 跳转到 customers 路由', async () => {
    const { wrapper, router, vm } = await mountComponent()
    await vm.navigateToSubjectPage('customers')
    expect(router.currentRoute.value.name).toBe('customers')
    wrapper.unmount()
  })

  it('未知 subject 跳转到 chat', async () => {
    const { wrapper, router, vm } = await mountComponent()
    await vm.navigateToSubjectPage('unknown')
    expect(router.currentRoute.value.name).toBe('chat')
    wrapper.unmount()
  })

  it('空 subject 跳转到 chat', async () => {
    const { wrapper, router, vm } = await mountComponent()
    await vm.navigateToSubjectPage('')
    expect(router.currentRoute.value.name).toBe('chat')
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – onRestoreFloatState', () => {

  it('恢复完整状态', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.onRestoreFloatState({
      detail: {
        isOpen: true,
        activeTab: 'assistant',
        assistantState: {
          pushFeed: [{ id: 1, title: 't', description: 'd' }],
          productKeyword: 'kw',
          productRows: [{ id: 1 }],
          linkedSheetName: 'Sheet1',
          linkedSheetIndex: 2,
          linkedGridData: { rows: [] },
          linkedSheetFields: ['f1'],
          linkedSheetSampleRows: [['v1']],
          topScrollInnerWidth: 100,
          loadingProducts: true,
          lastProductSearchQuery: 'q',
          productSearchFailed: true,
          productSearchErrorText: 'err',
          lastProductSearchTotal: 5,
          popupNotice: { title: 'n' },
          hasUnreadPush: true,
          operationHistory: [{ type: 'op' }],
        },
      },
    })
    expect(vm.isOpen).toBe(true)
    expect(vm.activeTab).toBe('assistant')
    expect(vm.pushFeed.length).toBe(1)
    expect(vm.productKeyword).toBe('kw')
    expect(vm.productRows.length).toBe(1)
    expect(vm.linkedSheetName).toBe('Sheet1')
    expect(vm.linkedSheetIndex).toBe(2)
    expect(vm.loadingProducts).toBe(true)
    expect(vm.productSearchFailed).toBe(true)
    expect(vm.lastProductSearchTotal).toBe(5)
    expect(vm.hasUnreadPush).toBe(true)
    wrapper.unmount()
  })

  it('无 assistantState 时只设置 isOpen 和 activeTab', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.onRestoreFloatState({
      detail: { isOpen: true, activeTab: 'push' },
    })
    expect(vm.isOpen).toBe(true)
    expect(vm.activeTab).toBe('push')
    wrapper.unmount()
  })

  it('空 detail 时设置为默认值', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.onRestoreFloatState({ detail: null })
    expect(vm.isOpen).toBe(false)
    expect(vm.activeTab).toBe('push')
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – onTutorialSetAssistantTab', () => {

  it('open 为 true 时打开副窗', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.onTutorialSetAssistantTab({ detail: { open: true, tab: 'tutorial' } })
    expect(vm.isOpen).toBe(true)
    expect(vm.activeTab).toBe('tutorial')
    wrapper.unmount()
  })

  it('open 为 false 时不打开副窗', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.isOpen = false
    vm.onTutorialSetAssistantTab({ detail: { open: false, tab: 'push' } })
    expect(vm.isOpen).toBe(false)
    expect(vm.activeTab).toBe('push')
    wrapper.unmount()
  })

  it('空 tab 不切换标签', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.activeTab = 'assistant'
    vm.onTutorialSetAssistantTab({ detail: { open: true } })
    expect(vm.activeTab).toBe('assistant')
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – onCloseAssistantFloat', () => {

  it('关闭打开的副窗', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.isOpen = true
    vm.onCloseAssistantFloat()
    expect(vm.isOpen).toBe(false)
    wrapper.unmount()
  })

  it('教程激活且有 assistantTab 时不关闭', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.isOpen = true
    const tutorialStore = (await import('@/stores/tutorial')).useTutorialStore()
    tutorialStore.isActive = true
    tutorialStore.$patch({
      steps: [{ id: 's1', assistantTab: 'push' }],
      currentStepIndex: 0,
    })
    vm.onCloseAssistantFloat()
    expect(vm.isOpen).toBe(true)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – tryFillChatInput', () => {

  it('空 text 返回 false', async () => {
    const { wrapper, vm } = await mountComponent()
    expect(vm.tryFillChatInput('')).toBe(false)
    expect(vm.tryFillChatInput('   ')).toBe(false)
    expect(vm.tryFillChatInput(null)).toBe(false)
    wrapper.unmount()
  })

  it('window.__VUE_CHAT_FILL__ 存在时调用', async () => {
    const { wrapper, vm } = await mountComponent()
    const fillFn = vi.fn(() => true)
    ;(window as any).__VUE_CHAT_FILL__ = fillFn
    expect(vm.tryFillChatInput('hello')).toBe(true)
    expect(fillFn).toHaveBeenCalledWith('hello')
    delete (window as any).__VUE_CHAT_FILL__
    wrapper.unmount()
  })

  it('window.__VUE_CHAT_FILL__ 不存在时返回 false', async () => {
    const { wrapper, vm } = await mountComponent()
    delete (window as any).__VUE_CHAT_FILL__
    expect(vm.tryFillChatInput('hello')).toBe(false)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – onExcelSheetContext', () => {

  it('处理 Excel sheet context 事件', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.onExcelSheetContext({
      detail: {
        selected_sheet: { sheet_name: 'Sheet1', sheet_index: 1 },
        excel_analysis: { preview_data: { all_sheets: [] } },
      },
    })
    expect(vm.linkedSheetName).toBe('Sheet1')
    wrapper.unmount()
  })

  it('空 detail 不报错', async () => {
    const { wrapper, vm } = await mountComponent()
    vm.onExcelSheetContext({ detail: null })
    expect(vm.linkedSheetName).toBe('')
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – triggerGridReadFromChat', () => {

  it('无 linkedSheetName 时不执行', async () => {
    const { wrapper, router, vm } = await mountComponent()
    vm.linkedSheetName = ''
    const beforeRoute = router.currentRoute.value.name
    await vm.triggerGridReadFromChat()
    expect(router.currentRoute.value.name).toBe(beforeRoute)
    wrapper.unmount()
  })

  it('有 linkedSheetName 时跳转到 chat', async () => {
    const { wrapper, router, vm } = await mountComponent()
    vm.linkedSheetName = 'Sheet1'
    vm.linkedSheetIndex = 1
    await router.push('/products')
    await flushPromises()
    await vm.triggerGridReadFromChat()
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('chat')
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – onStarterPackItemClick', () => {

  it('点击 starter pack item 跳转到 chat 并记录操作', async () => {
    const { wrapper, router, vm } = await mountComponent()
    await router.push('/products')
    await flushPromises()
    await vm.onStarterPackItemClick('测试文本')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('chat')
    expect(vm.operationHistory.length).toBeGreaterThan(0)
    expect(vm.operationHistory[0].type).toBe('starter_pack')
    wrapper.unmount()
  })

  it('空文本不报错', async () => {
    const { wrapper, vm } = await mountComponent()
    await vm.onStarterPackItemClick('')
    await flushPromises()
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – startHostOnboardingGuide', () => {

  it('跳转到 product-onboarding 并关闭副窗', async () => {
    const { wrapper, router, vm } = await mountComponent()
    vm.isOpen = true
    await vm.startHostOnboardingGuide()
    await flushPromises()
    expect(vm.isOpen).toBe(false)
    expect(router.currentRoute.value.name).toBe('product-onboarding')
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – workflowEmployeeDefs computed', () => {

  it('返回工作流员工定义列表', async () => {
    const { wrapper, vm } = await mountComponent()
    const defs = vm.workflowEmployeeDefs
    expect(Array.isArray(defs)).toBe(true)
    expect(defs.length).toBeGreaterThan(0)
    expect(defs[0]).toHaveProperty('id')
    expect(defs[0]).toHaveProperty('label')
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – workflowPanoramaLinkTitle computed', () => {

  it('返回工作流全景链接标题', async () => {
    const { wrapper, vm } = await mountComponent()
    const title = vm.workflowPanoramaLinkTitle
    expect(typeof title).toBe('string')
    expect(title.length).toBeGreaterThan(0)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – coreWorkflowEnabled', () => {

  it('enabled 中存在的 id 返回 true', async () => {
    const { wrapper, vm } = await mountComponent()
    // 默认 enabled 为空对象，返回 false
    expect(vm.coreWorkflowEnabled('wechat_msg')).toBe(false)
    wrapper.unmount()
  })

  it('不存在的 id 返回 false', async () => {
    const { wrapper, vm } = await mountComponent()
    expect(vm.coreWorkflowEnabled('nonexistent')).toBe(false)
    wrapper.unmount()
  })

  it('空 id 返回 false', async () => {
    const { wrapper, vm } = await mountComponent()
    expect(vm.coreWorkflowEnabled('')).toBe(false)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – toggleWorkflowEmployee', () => {

  it('切换工作流员工状态', async () => {
    const { useWorkflowAiEmployeesStore } = await import('@/stores/workflowAiEmployees')
    const empStore = useWorkflowAiEmployeesStore()
    const { wrapper, vm } = await mountComponent()
    vm.toggleWorkflowEmployee('wechat_msg')
    expect(empStore.enabled.wechat_msg).toBe(true)
    vm.toggleWorkflowEmployee('wechat_msg')
    expect(empStore.enabled.wechat_msg).toBe(false)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – onTopScroll / onExcelScroll', () => {

  it('onTopScroll 无 excelContainer 时不报错', async () => {
    const { wrapper, vm } = await mountComponent()
    expect(() => vm.onTopScroll({ target: { scrollLeft: 100 } })).not.toThrow()
    wrapper.unmount()
  })

  it('onExcelScroll 无 excelContainer 时不报错', async () => {
    const { wrapper, vm } = await mountComponent()
    expect(() => vm.onExcelScroll()).not.toThrow()
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – syncTopScrollMetrics', () => {

  it('无 excelContainer 时设置 topScrollInnerWidth 为 0', async () => {
    const { wrapper, vm } = await mountComponent()
    await vm.syncTopScrollMetrics()
    expect(vm.topScrollInnerWidth).toBe(0)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – fillChatInputWithRetry', () => {

  it('空 text 不执行', async () => {
    const { wrapper, vm } = await mountComponent()
    const fillFn = vi.fn(() => true)
    ;(window as any).__VUE_CHAT_FILL__ = fillFn
    await vm.fillChatInputWithRetry('')
    expect(fillFn).not.toHaveBeenCalled()
    delete (window as any).__VUE_CHAT_FILL__
    wrapper.unmount()
  })

  it('window.__VUE_CHAT_FILL__ 存在时填充成功', async () => {
    const { wrapper, vm } = await mountComponent()
    const fillFn = vi.fn(() => true)
    ;(window as any).__VUE_CHAT_FILL__ = fillFn
    await vm.fillChatInputWithRetry('hello')
    expect(fillFn).toHaveBeenCalledWith('hello')
    delete (window as any).__VUE_CHAT_FILL__
    wrapper.unmount()
  })

  it('window.__VUE_CHAT_FILL__ 返回 false 时重试', async () => {
    const { wrapper, vm } = await mountComponent()
    let callCount = 0
    const fillFn = vi.fn(() => {
      callCount++
      return callCount >= 2
    })
    ;(window as any).__VUE_CHAT_FILL__ = fillFn
    await vm.fillChatInputWithRetry('hello')
    expect(fillFn).toHaveBeenCalledTimes(2)
    delete (window as any).__VUE_CHAT_FILL__
    wrapper.unmount()
  })
})


it('starts a business tutorial with a clean assistant, preserves return state and caches visible conversation evidence', async () => {
  const { wrapper, vm, router } = await mountComponent()
  const tutorial = (await import('@/stores/tutorial')).useTutorialStore()
  const start = vi.spyOn(tutorial, 'startTutorial')
  const dom = document.createElement('div')
  const button = Object.assign(document.createElement('button'), { id: 'newConversationBtn', textContent: '新对话' })
  const messages = Object.assign(document.createElement('div'), { id: 'chatMessages' })
  messages.append(...[['message ai', ' AI   reply '], ['message user', 'Question'], ['message', 'Other'], ['message', ' ']].map(([className, textContent]) => Object.assign(document.createElement('div'), { className, textContent })))
  dom.append(button, messages)
  document.body.append(dom)
  const newConversation = vi.fn(); dom.querySelector('button')!.addEventListener('click', newConversation)
  vm.productKeyword = 'old search'; vm.productRows = [{ id: 3, name: '旧产品' }]
  vm.pushFeed = [{ id: 'p', title: '旧通知', description: '内容' }]
  vm.popupNotice = { title: '旧通知' }; vm.hasUnreadPush = true
  const previousRoute = router.currentRoute.value.name
  await vm.startTutorialGuide('business'); await flushPromises()
  expect(newConversation).toHaveBeenCalledOnce()
  expect(start).toHaveBeenCalledWith(expect.objectContaining({ track: 'business', returnContext: expect.objectContaining({
    routeName: previousRoute, assistantState: expect.objectContaining({ productKeyword: 'old search', productRows: [{ id: 3, name: '旧产品' }] }),
  }) }))
  expect(vm.productKeyword).toBe(''); expect(vm.productRows).toEqual([]); expect(vm.pushFeed).toEqual([])
  expect(vm.activeTab).toBe('tutorial'); expect(vm.isOpen).toBe(true)
  expect(vm.popupNotice).toBeNull(); expect(vm.hasUnreadPush).toBe(false)
  const payload = mockApiPost.mock.calls.find(call => call[0] === '/api/preferences' && call[1]?.key === 'tutorial_guide_pack_cache')?.[1]
  expect(JSON.parse(payload.value).context.chatMessages).toEqual([
    { role: 'assistant', content: 'AI reply' }, { role: 'user', content: 'Question' }, { role: 'unknown', content: 'Other' },
  ])
  dom.remove(); wrapper.unmount()
})
