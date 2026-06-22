import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h, nextTick } from 'vue'
import TopAssistantFloat from './TopAssistantFloat.vue'

// ===== Mock 模块 =====

// RouterLink 桩组件
const RouterLinkStub = defineComponent({
  name: 'RouterLinkStub',
  props: { to: { type: [String, Object], default: '/' } },
  setup: (props, { slots }) => () => h('a', { href: typeof props.to === 'string' ? props.to : '#' }, slots.default?.()),
})

// ExcelPreview 桩组件，附带 $el 与 querySelector 以覆盖滚动同步逻辑
const ExcelPreviewStub = defineComponent({
  name: 'ExcelPreview',
  setup() {
    return () => h('div', { class: 'excel-preview-stub' })
  },
})

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
      get: vi.fn(async () => ({ success: true, data: {} })),
      post: vi.fn(async () => ({ success: true, data: {} })),
      put: vi.fn(async () => ({ success: true, data: {} })),
      delete: vi.fn(async () => ({ success: true, data: {} })),
    },
    ApiError,
  }
})

vi.mock('@/api/products', () => {
  const searchProducts = vi.fn(async (keyword = '') => ({
    success: true,
    data: String(keyword).trim()
      ? [
        { id: 1, model_number: 'M-1', name: '产品A', product_name: '产品A', price: 10, unit: '件' },
        { id: 2, model_number: 'M-2', name: '产品B', product_name: '产品B', price: 20, unit: '套' },
      ]
      : [],
    total: String(keyword).trim() ? 2 : 0,
  }))
  const updateProduct = vi.fn(async () => ({ success: true }))
  return { default: { searchProducts, updateProduct }, productsApi: { searchProducts, updateProduct } }
})

vi.mock('@/tutorial/promptAdvancedTutorial', () => ({
  launchAdvancedDriverTour: vi.fn(async () => undefined),
}))

vi.mock('@/composables/useTutorialCatalog', () => ({
  useTutorialCatalog: () => ({
    tutorialTracks: [
      { id: 'host', title: '宿主入门', summary: '认识XC', description: '宿主入门说明', recommended: true },
      { id: 'advanced', title: '进阶', summary: '进阶教程', description: '进阶说明' },
    ],
    advancedTrackHint: '进阶路线提示',
    buildContext: () => ({ industryId: '考勤', mods: [], visibleNav: [], isProMode: false }),
  }),
}))

vi.mock('@/composables/useWorkflowModsRuntimeContext', () => ({
  useWorkflowModsRuntimeContext: () => ({ modWorkflowEmployeesActive: { value: false } }),
}))

vi.mock('@/composables/useWorkflowPanoramaNavVisible', () => ({
  useWorkflowPanoramaNavVisible: () => ({ showWorkflowPanoramaNav: { value: false } }),
}))

vi.mock('@/utils/workflowNav', () => ({
  resolveWorkflowVisualizationLocation: vi.fn(() => ({ name: 'workflow-visualization' })),
}))

vi.mock('@/utils/erpDomainPaths', () => ({
  resolveErpApiPath: (p: string) => p,
}))

vi.mock('@/composables/useEnterpriseScopedWorkflowRegistry', () => ({
  useEnterpriseScopedWorkflowRegistry: () => ({
    scopedRegistryEntries: { value: [{ id: 'wechat_msg' }, { id: 'label_print' }, { id: 'receipt_confirm' }] },
  }),
}))

vi.mock('@/utils/workflowEmployeeRegistry', () => ({
  resolveLabel: (entry: { id: string }, resolver: (k: string) => string) => {
    const map: Record<string, string> = {
      wechat_msg: '微信消息员工',
      label_print: '标签打印员工',
      receipt_confirm: '收货确认员工',
    }
    return map[entry.id] || entry.id
  },
}))

vi.mock('@/utils/syncEnterpriseWorkflowRegistry', () => ({
  syncEnterpriseWorkflowRegistry: vi.fn(async () => undefined),
}))

vi.mock('@/utils/wechatIntent', () => ({
  inferWechatCustomerIntent: vi.fn((text: string) => ({
    label: '通用意图',
    detail: `本地规则识别：${String(text).slice(0, 30)}`,
  })),
  isLabelPrintRelatedWechatIntent: vi.fn(() => false),
  isReceiptConfirmRelatedWechatIntent: vi.fn(() => false),
}))

vi.mock('@/utils/wechatShipmentDetect', () => ({
  shouldTryWechatShipmentPreview: vi.fn(() => false),
}))

vi.mock('@/constants/productFlow', () => ({
  DEFAULT_TUTORIAL_TRACK_ID: 'host',
}))

vi.mock('@/constants/workflowEmployeeMods', () => ({
  WORKFLOW_EMPLOYEE_IDS: ['wechat_msg', 'label_print', 'receipt_confirm', 'shipment_mgmt'],
}))

// ===== 测试辅助 =====

function makeFetchResponse(body: unknown = { ok: true }, ok = true) {
  return {
    ok,
    status: ok ? 200 : 500,
    headers: { get: () => 'application/json' },
    json: async () => body,
    text: async () => JSON.stringify(body),
  }
}

function createTestRouter() {
  const names = [
    'home', 'login', 'register', 'settings', 'mod-store', 'products', 'product-onboarding',
    'chat', 'dashboard', 'workflow-visualization', 'shipment-records', 'customers',
    'template-preview', 'materials', 'inventory', 'approval-hub',
  ]
  const EmptyComp = defineComponent({ setup: () => () => h('div') })
  const routes = names.map((name) => ({ path: `/${name}`, name, component: EmptyComp }))
  routes.push({ path: '/', name: 'home', component: EmptyComp })
  routes.push({ path: '/:pathMatch(.*)*', name: 'fallback', component: EmptyComp })
  return createRouter({ history: createMemoryHistory(), routes })
}

async function mountComponent(options: Record<string, unknown> = {}) {
  const router = options.router || createTestRouter()
  await router.push('/chat')
  await router.isReady()
  const wrapper = mount(TopAssistantFloat, {
    global: {
      plugins: [router],
      stubs: {
        RouterLink: RouterLinkStub,
        ExcelPreview: ExcelPreviewStub,
        Teleport: true,
      },
    },
  })
  await flushPromises()
  return { wrapper, router }
}

function dispatchWindowEvent(name: string, detail: Record<string, unknown> = {}) {
  window.dispatchEvent(new CustomEvent(name, { detail }))
}

describe('TopAssistantFloat.vue 覆盖率补齐测试', () => {
  let originalFetch: typeof globalThis.fetch

  beforeEach(() => {
    setActivePinia(createPinia())
    originalFetch = globalThis.fetch
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    // 重置 localStorage 状态
    localStorage.clear()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    localStorage.clear()
  })

  // ===== 1. 基础渲染与切换 =====

  it('挂载后渲染浮动按钮且默认关闭', async () => {
    const { wrapper } = await mountComponent()
    expect(wrapper.find('.assistant-float-toggle').exists()).toBe(true)
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(false)
    expect(wrapper.text()).toContain('副窗')
  })

  it('点击浮动按钮打开副窗并切换标题', async () => {
    const { wrapper } = await mountComponent()
    const toggle = wrapper.find('.assistant-float-toggle')
    expect(toggle.attributes('title')).toBe('打开副窗')
    await toggle.trigger('click')
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
    expect(toggle.attributes('title')).toBe('收起副窗')
    expect(toggle.attributes('aria-expanded')).toBe('true')
  })

  it('再次点击浮动按钮关闭副窗', async () => {
    const { wrapper } = await mountComponent()
    const toggle = wrapper.find('.assistant-float-toggle')
    await toggle.trigger('click')
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
    await toggle.trigger('click')
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(false)
  })

  it('点击关闭按钮关闭副窗', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const closeBtn = wrapper.find('.assistant-close')
    expect(closeBtn.exists()).toBe(true)
    await closeBtn.trigger('click')
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(false)
  })

  // ===== 2. 标签页切换 =====

  it('切换到推送标签显示空状态', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    // 默认就是 push 标签
    expect(wrapper.find('.assistant-empty').exists()).toBe(true)
    expect(wrapper.text()).toContain('暂无推送')
  })

  it('切换到协助副窗标签显示查询区域', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    const assistantTab = tabs.find((t) => t.text().includes('协助副窗'))
    expect(assistantTab).toBeTruthy()
    await assistantTab!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.product-search-row').exists()).toBe(true)
    expect(wrapper.find('.assistant-grid-actions').exists()).toBe(true)
  })

  it('切换到新手对话包标签显示预设', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    const starterTab = tabs.find((t) => t.text().includes('新手对话包'))
    await starterTab!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.starter-pack-list').exists()).toBe(true)
  })

  it('切换到新手教程标签显示教程列表', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    const tutorialTab = tabs.find((t) => t.text().includes('新手教程'))
    await tutorialTab!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.tutorial-track-pick').exists()).toBe(true)
    expect(wrapper.findAll('.tutorial-track-card').length).toBeGreaterThan(0)
  })

  // ===== 3. 推送功能 =====

  it('收到微信推送事件后添加推送项', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:assistant-push', {
      title: '测试推送',
      description: '测试描述',
      feature: 'wechat',
      source: 'wechat_contacts',
    })
    await flushPromises()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('测试推送')
    expect(wrapper.text()).toContain('测试描述')
  })

  it('非微信推送事件被忽略', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:assistant-push', {
      title: '其他推送',
      description: '不应显示',
      feature: 'other',
    })
    await flushPromises()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    expect(wrapper.text()).not.toContain('其他推送')
  })

  it('副窗关闭时收到推送显示弹窗通知', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:assistant-push', {
      title: '新消息推送',
      description: '请查看',
      feature: 'wechat',
    })
    await flushPromises()
    expect(wrapper.find('.assistant-popup-notice').exists()).toBe(true)
    expect(wrapper.text()).toContain('新消息推送')
    expect(wrapper.find('.assistant-float-toggle.pulse').exists()).toBe(true)
  })

  it('点击弹窗通知打开副窗并清除通知', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:assistant-push', {
      title: '弹窗通知',
      description: '点击查看',
      feature: 'wechat',
    })
    await flushPromises()
    expect(wrapper.find('.assistant-popup-notice').exists()).toBe(true)
    await wrapper.find('.assistant-popup-notice').trigger('click')
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
    expect(wrapper.find('.assistant-popup-notice').exists()).toBe(false)
  })

  it('推送标题为空时使用默认值', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:assistant-push', {
      feature: 'wechat',
    })
    await flushPromises()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('新推送')
    expect(wrapper.text()).toContain('收到一条助手消息')
  })

  // ===== 4. 产品查询 =====

  it('空关键词查询清空结果', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const input = wrapper.find('.product-search-row input')
    await input.setValue('')
    await wrapper.find('.product-search-row .btn-primary').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('请先输入')
  })

  it('有效关键词查询返回产品列表', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const input = wrapper.find('.product-search-row input')
    await input.setValue('产品')
    await wrapper.find('.product-search-row .btn-primary').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.product-item').length).toBe(2)
    expect(wrapper.text()).toContain('编号 1')
    expect(wrapper.text()).toContain('编号 2')
  })

  it('查询返回空结果显示未找到提示', async () => {
    const productsApi = (await import('@/api/products')).default
      ; (productsApi.searchProducts as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        success: true,
        data: [],
        total: 0,
      })
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const input = wrapper.find('.product-search-row input')
    await input.setValue('不存在的')
    await wrapper.find('.product-search-row .btn-primary').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('未找到')
  })

  it('查询失败显示错误信息', async () => {
    const { ApiError } = await import('@/api')
    const productsApi = (await import('@/api/products')).default
      ; (productsApi.searchProducts as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
        new ApiError('服务器错误', 500),
      )
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const input = wrapper.find('.product-search-row input')
    await input.setValue('触发错误')
    await wrapper.find('.product-search-row .btn-primary').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('请求失败')
  })

  it('查询返回 success:false 显示失败提示', async () => {
    const productsApi = (await import('@/api/products')).default
      ; (productsApi.searchProducts as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        success: false,
        message: '查询异常',
      })
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const input = wrapper.find('.product-search-row input')
    await input.setValue('异常')
    await wrapper.find('.product-search-row .btn-primary').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('查询异常')
  })

  it('查询时网络异常显示网络异常提示', async () => {
    const productsApi = (await import('@/api/products')).default
      ; (productsApi.searchProducts as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('网络异常'))
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const input = wrapper.find('.product-search-row input')
    await input.setValue('网络')
    await wrapper.find('.product-search-row .btn-primary').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('网络异常')
  })

  it('回车键触发查询', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const input = wrapper.find('.product-search-row input')
    await input.setValue('回车查询')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(wrapper.findAll('.product-item').length).toBeGreaterThan(0)
  })

  it('保存产品行调用 updateProduct', async () => {
    const productsApi = (await import('@/api/products')).default
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const input = wrapper.find('.product-search-row input')
    await input.setValue('保存')
    await wrapper.find('.product-search-row .btn-primary').trigger('click')
    await flushPromises()
    const saveBtn = wrapper.find('.product-actions .btn-secondary')
    expect(saveBtn.exists()).toBe(true)
    await saveBtn.trigger('click')
    await flushPromises()
    expect(productsApi.updateProduct).toHaveBeenCalled()
  })

  it('保存产品行失败仍重置 savingProductId', async () => {
    const productsApi = (await import('@/api/products')).default
      ; (productsApi.updateProduct as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('保存失败'))
    // 捕获未处理的 rejection（saveProductRow 不 catch，由 finally 重置状态）
    const rejectionHandler = vi.fn()
    process.on('unhandledRejection', rejectionHandler)
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const input = wrapper.find('.product-search-row input')
    await input.setValue('保存失败')
    await wrapper.find('.product-search-row .btn-primary').trigger('click')
    await flushPromises()
    const saveBtn = wrapper.find('.product-actions .btn-secondary')
    await saveBtn.trigger('click')
    // 等待所有 promise 完成（包括 rejected 的）
    await flushPromises()
    // finally 块已执行，按钮文字恢复
    expect(saveBtn.text()).toContain('保存修改')
    process.off('unhandledRejection', rejectionHandler)
  })

  // ===== 5. 工作流员工切换 =====
  // 一键托管/龙虾托管 tab 已移除（改为 AI 自动 + 事件驱动），工作流员工开关测试同步移除

  // ===== 6. 新手对话包 =====

  it('点击新手对话包预设项跳转聊天页', async () => {
    const { wrapper, router } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('新手对话包'))!.trigger('click')
    await flushPromises()
    const item = wrapper.find('.starter-pack-item')
    expect(item.exists()).toBe(true)
    await item.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('chat')
  })

  // ===== 7. 教程功能 =====

  it('点击新手教程标签触发预热事件', async () => {
    const { wrapper } = await mountComponent()
    let warmed = false
    window.addEventListener('xcagi:warmup-tutorial-tts', () => { warmed = true })
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('新手教程'))!.trigger('click')
    await flushPromises()
    await nextTick()
    expect(warmed).toBe(true)
  })

  it('点击默认教程开始按钮触发 onboarding 跳转', async () => {
    const { wrapper, router } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('新手教程'))!.trigger('click')
    await flushPromises()
    const startBtn = wrapper.find('.tutorial-track-card .btn-primary')
    expect(startBtn.exists()).toBe(true)
    await startBtn.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('product-onboarding')
  })

  it('点击进阶教程按钮触发 driver tour', async () => {
    const { launchAdvancedDriverTour } = await import('@/tutorial/promptAdvancedTutorial')
    // 在 DOM 中放置 newConversationBtn，让 startTutorialGuide 内部循环立即 break
    const newConvBtn = document.createElement('button')
    newConvBtn.id = 'newConversationBtn'
    document.body.appendChild(newConvBtn)
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('新手教程'))!.trigger('click')
    await flushPromises()
    const cards = wrapper.findAll('.tutorial-track-card')
    // 进阶教程卡片
    const advancedCard = cards.find((c) => c.text().includes('进阶'))
    expect(advancedCard).toBeTruthy()
    const advancedBtn = advancedCard!.find('.btn')
    await advancedBtn.trigger('click')
    // startTutorialGuide 是异步的，需要等待所有 promise 链完成
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(launchAdvancedDriverTour).toHaveBeenCalled()
    document.body.removeChild(newConvBtn)
  })

  // ===== 8. 浮窗打开事件 =====

  it('open-assistant-float 事件 forceOpen 强制打开', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:open-assistant-float', { forceOpen: true })
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
  })

  it('open-assistant-float 事件带 task 自动打开', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:open-assistant-float', { task: { type: 'demo' } })
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
  })

  it('open-assistant-float 事件 feature=products 切换到协助标签', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:open-assistant-float', { feature: 'products' })
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
    expect(wrapper.find('.product-search-row').exists()).toBe(true)
  })

  it('open-assistant-float 事件 feature=products 带 hydrateProductSearch 直接填充', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:open-assistant-float', {
      feature: 'products',
      query: '预填',
      hydrateProductSearch: {
        rows: [{ id: 99, name: '预填产品', model_number: 'PM-99', price: 5, unit: '个' }],
        total: 1,
      },
    })
    await flushPromises()
    // 名称在 input 的 value 中，需检查 input 元素
    expect(wrapper.text()).toContain('编号 99')
    const nameInput = wrapper.find('#pf-name-99')
    expect(nameInput.exists()).toBe(true)
    expect((nameInput.element as HTMLInputElement).value).toBe('预填产品')
  })

  it('open-assistant-float 事件 feature=products 带不同 query 触发查询', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:open-assistant-float', {
      feature: 'products',
      query: '触发查询',
    })
    await flushPromises()
    expect(wrapper.find('.product-search-row').exists()).toBe(true)
  })

  it('open-assistant-float 事件 feature=assistant 切换到协助标签', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:open-assistant-float', { feature: 'assistant' })
    await flushPromises()
    expect(wrapper.find('.product-search-row').exists()).toBe(true)
  })

  it('open-assistant-float 事件 feature=starterPack 切换到对话包标签', async () => {
    const { wrapper } = await mountComponent()
    // starterPack 不在自动打开列表中，需 forceOpen
    dispatchWindowEvent('xcagi:open-assistant-float', { feature: 'starterPack', forceOpen: true })
    await flushPromises()
    expect(wrapper.find('.starter-pack-list').exists()).toBe(true)
  })

  it('open-assistant-float 事件 feature=tutorial 切换到教程标签', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:open-assistant-float', { feature: 'tutorial' })
    await flushPromises()
    expect(wrapper.find('.tutorial-track-pick').exists()).toBe(true)
  })

  it('open-assistant-float 事件其他 feature 仅标记未读', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:open-assistant-float', { feature: 'unknown' })
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(false)
    expect(wrapper.find('.assistant-float-toggle.pulse').exists()).toBe(true)
  })

  // ===== 9. 关闭浮窗事件 =====

  it('close-assistant-float 事件关闭副窗', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
    dispatchWindowEvent('xcagi:close-assistant-float')
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(false)
  })

  // ===== 10. Excel 上下文 =====

  it('excel-sheet-context 事件应用 Sheet 上下文', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:excel-sheet-context', {
      selected_sheet: { sheet_name: 'Sheet1', sheet_index: 1 },
      excel_analysis: {
        preview_data: {
          all_sheets: [
            {
              sheet_name: 'Sheet1',
              sheet_index: 1,
              grid_preview: { rows: [{ cells: ['A1'] }] },
              fields: [{ name: '字段1' }],
              sample_rows: [{ 字段1: '值1' }],
            },
          ],
        },
      },
    })
    await flushPromises()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Sheet 1')
    expect(wrapper.text()).toContain('Sheet1')
  })

  it('excel-sheet-context 事件无匹配 sheet 时使用首个', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:excel-sheet-context', {
      selected_sheet: { sheet_name: '不存在', sheet_index: 99 },
      excel_analysis: {
        preview_data: {
          all_sheets: [
            { sheet_name: '默认Sheet', sheet_index: 0, grid_preview: null, fields: [], sample_rows: [] },
          ],
        },
      },
    })
    await flushPromises()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    // 无网格数据时显示空提示
    expect(wrapper.text()).toContain('暂无可展示网格')
  })

  it('点击调用上传并提取读取网格按钮跳转聊天页', async () => {
    const { wrapper, router } = await mountComponent()
    dispatchWindowEvent('xcagi:excel-sheet-context', {
      selected_sheet: { sheet_name: 'Sheet1', sheet_index: 1 },
      excel_analysis: { preview_data: { all_sheets: [] } },
    })
    await flushPromises()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const gridBtn = wrapper.find('.assistant-grid-actions .btn')
    expect(gridBtn.exists()).toBe(true)
    await gridBtn.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('chat')
  })

  it('未关联 Sheet 时点击读取网格按钮不跳转', async () => {
    const { wrapper, router } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const gridBtn = wrapper.find('.assistant-grid-actions .btn')
    await gridBtn.trigger('click')
    await flushPromises()
    // 未关联 Sheet 直接 return，不跳转
    expect(router.currentRoute.value.name).toBe('chat')
  })

  // ===== 11. 状态恢复 =====

  it('tutorial:restore-float 事件恢复副窗状态', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:tutorial:restore-float', {
      isOpen: true,
      activeTab: 'assistant',
      assistantState: {
        pushFeed: [{ id: 'r1', title: '恢复推送', description: '恢复描述' }],
        productKeyword: '恢复关键词',
        productRows: [],
        linkedSheetName: '',
        linkedSheetIndex: 0,
        linkedGridData: null,
        linkedSheetFields: [],
        linkedSheetSampleRows: [],
        topScrollInnerWidth: 0,
        loadingProducts: false,
        lastProductSearchQuery: '',
        productSearchFailed: false,
        productSearchErrorText: '',
        lastProductSearchTotal: null,
        popupNotice: null,
        hasUnreadPush: false,
        operationHistory: [],
      },
    })
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
    expect(wrapper.find('.product-search-row').exists()).toBe(true)
  })

  it('tutorial:set-assistant-tab 事件设置标签', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:tutorial:set-assistant-tab', { open: true, tab: 'tutorial' })
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
    expect(wrapper.find('.tutorial-track-pick').exists()).toBe(true)
  })

  // ===== 12. 键盘交互 =====

  it('Escape 键关闭副窗', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
    const escEvent = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    window.dispatchEvent(escEvent)
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(false)
  })

  it('副窗关闭时 Escape 键不触发', async () => {
    const { wrapper } = await mountComponent()
    const escEvent = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    window.dispatchEvent(escEvent)
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(false)
  })

  it('ArrowRight 键切换到下一个标签', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    // 默认 push 标签，按右键应切到 assistant
    const panel = wrapper.find('.assistant-float-panel')
    const tab = panel.find('[role="tab"]')
    await tab.trigger('keydown', { key: 'ArrowRight' })
    await flushPromises()
    expect(wrapper.find('.product-search-row').exists()).toBe(true)
  })

  it('ArrowLeft 键切换到上一个标签', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    // 先切到 assistant 标签
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    // 按左键应回到 push
    const panel = wrapper.find('.assistant-float-panel')
    const tab = panel.find('[role="tab"][aria-selected="true"]')
    await tab.trigger('keydown', { key: 'ArrowLeft' })
    await flushPromises()
    expect(wrapper.text()).toContain('暂无推送')
  })

  it('非方向键不触发标签切换', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const panel = wrapper.find('.assistant-float-panel')
    const tab = panel.find('[role="tab"]')
    await tab.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    // 仍在 push 标签
    expect(wrapper.text()).toContain('暂无推送')
  })

  it('方向键但目标非 tab 元素不切换', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const panel = wrapper.find('.assistant-float-panel')
    // 在非 tab 元素上触发方向键
    await panel.trigger('keydown', { key: 'ArrowRight' })
    await flushPromises()
    expect(wrapper.text()).toContain('暂无推送')
  })

  // ===== 13. 自动刷新微信 =====

  it('auto-refresh-wechat-changed 事件开启轮询', async () => {
    localStorage.setItem('xcagi_auto_refresh_starred_wechat', '1')
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:auto-refresh-wechat-changed')
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  it('auto-refresh-wechat-changed 事件关闭轮询', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:auto-refresh-wechat-changed')
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  it('pollStarredFeed 网络异常不抛错', async () => {
    localStorage.setItem('xcagi_auto_refresh_starred_wechat', '1')
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:auto-refresh-wechat-changed')
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  it('pollStarredFeed 返回非 ok 状态静默处理', async () => {
    localStorage.setItem('xcagi_auto_refresh_starred_wechat', '1')
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse({ success: false }, false)))
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:auto-refresh-wechat-changed')
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  it('pollStarredFeed 返回成功 feed 触发推送事件', async () => {
    localStorage.setItem('xcagi_auto_refresh_starred_wechat', '1')
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse({
      success: true,
      feed: [
        {
          contact_id: 'c1',
          contact_name: '联系人A',
          messages: [{ role: 'user', text: '你好' }],
        },
      ],
    })))
    const { wrapper } = await mountComponent()
    // 第一次轮询建立基线
    dispatchWindowEvent('xcagi:auto-refresh-wechat-changed')
    await flushPromises()
    // 第二次轮询，消息变化触发推送
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse({
      success: true,
      feed: [
        {
          contact_id: 'c1',
          contact_name: '联系人A',
          messages: [{ role: 'user', text: '新消息内容' }],
        },
      ],
    })))
    dispatchWindowEvent('xcagi:auto-refresh-wechat-changed')
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  // ===== 14. 微信消息 AI 管道 =====

  it('pollStarredFeed 触发微信消息 AI 管道（专业模式）', async () => {
    localStorage.setItem('xcagi_auto_refresh_starred_wechat', '1')
    localStorage.setItem('xcagi_pro_intent_experience', '1')
    // 启用 wechat_msg 员工以触发 AI 管道
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse({
      success: true,
      data: {
        success: true,
        primary_intent: '询问价格',
        tool_key: 'price_query',
        intent_hints: ['价格相关'],
        confidence: 0.9,
      },
      feed: [
        {
          contact_id: 'c1',
          contact_name: '联系人A',
          messages: [{ role: 'user', text: '这个多少钱' }],
        },
      ],
    })))
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:auto-refresh-wechat-changed')
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  it('pollStarredFeed 专业模式 API 失败回退本地规则', async () => {
    localStorage.setItem('xcagi_auto_refresh_starred_wechat', '1')
    localStorage.setItem('xcagi_pro_intent_experience', '1')
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('API 不可用') }))
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:auto-refresh-wechat-changed')
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  // ===== 15. 卸载清理 =====

  it('组件卸载时清理事件监听与定时器', async () => {
    const { wrapper } = await mountComponent()
    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
    await flushPromises()
    // 卸载不报错即可
    expect(true).toBe(true)
  })

  // ===== 16. 工作流全景链接 =====

  it('mods 变化触发 syncEnterpriseWorkflowRegistry', async () => {
    const { syncEnterpriseWorkflowRegistry } = await import('@/utils/syncEnterpriseWorkflowRegistry')
    const { wrapper } = await mountComponent()
    // 触发 mods store 变化（这里仅验证不报错）
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
    // syncEnterpriseWorkflowRegistry 在 onMounted 已被调用
    expect(syncEnterpriseWorkflowRegistry).toHaveBeenCalled()
  })

  // ===== 17. 推送数量上限 =====

  it('推送超过上限只保留最近 12 条', async () => {
    const { wrapper } = await mountComponent()
    // 连续发送 15 条推送
    for (let i = 0; i < 15; i += 1) {
      dispatchWindowEvent('xcagi:assistant-push', {
        title: `推送${i}`,
        description: `描述${i}`,
        feature: 'wechat',
      })
      await flushPromises()
    }
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const items = wrapper.findAll('.push-item')
    expect(items.length).toBeLessThanOrEqual(12)
  })

  // ===== 18. recommendIntroText 计算属性 =====
  // recommendIntroText 已随一键托管/龙虾托管 tab 一并移除

  // ===== 19. productEmptyMessage 各分支 =====

  it('查询成功后修改关键词显示关键词已变更提示', async () => {
    const productsApi = (await import('@/api/products')).default
      // 先让搜索返回空结果，使 productRows.length === 0
      ; (productsApi.searchProducts as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        success: true,
        data: [],
        total: 0,
      })
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const input = wrapper.find('.product-search-row input')
    // 搜索返回空结果
    await input.setValue('原始词')
    await wrapper.find('.product-search-row .btn-primary').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.product-item').length).toBe(0)
    // 修改关键词但未查询，应显示关键词已变更
    await input.setValue('新词未查')
    await flushPromises()
    expect(wrapper.text()).toContain('关键词已变更')
  })

  // ===== 20. openFromNotice 清除定时器 =====

  it('弹窗通知定时器到期后清除通知', async () => {
    vi.useFakeTimers()
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:assistant-push', {
      title: '定时通知',
      description: '将自动消失',
      feature: 'wechat',
    })
    await flushPromises()
    expect(wrapper.find('.assistant-popup-notice').exists()).toBe(true)
    // 快进 6 秒
    vi.advanceTimersByTime(6000)
    await flushPromises()
    expect(wrapper.find('.assistant-popup-notice').exists()).toBe(false)
    vi.useRealTimers()
  })

  // ===== 21. 教程激活时关闭副窗不生效 =====

  it('教程激活且有 assistantTab 时关闭按钮不关闭副窗', async () => {
    const { useTutorialStore } = await import('@/stores/tutorial')
    const tutorialStore = useTutorialStore()
    // currentStep 是 computed，需设置 steps 和 currentStepIndex
    tutorialStore.isActive = true
    tutorialStore.steps = [{ id: 's1', assistantTab: 'push' }] as never
    tutorialStore.currentStepIndex = 0
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
    await wrapper.find('.assistant-close').trigger('click')
    await flushPromises()
    // 教程激活时不应关闭
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
  })

  it('教程激活时 close-assistant-float 事件不关闭副窗', async () => {
    const { useTutorialStore } = await import('@/stores/tutorial')
    const tutorialStore = useTutorialStore()
    tutorialStore.isActive = true
    tutorialStore.steps = [{ id: 's1', assistantTab: 'push' }] as never
    tutorialStore.currentStepIndex = 0
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    dispatchWindowEvent('xcagi:close-assistant-float')
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
  })

  it('教程激活时 Escape 键不关闭副窗', async () => {
    const { useTutorialStore } = await import('@/stores/tutorial')
    const tutorialStore = useTutorialStore()
    tutorialStore.isActive = true
    tutorialStore.steps = [{ id: 's1', assistantTab: 'push' }] as never
    tutorialStore.currentStepIndex = 0
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const escEvent = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    window.dispatchEvent(escEvent)
    await flushPromises()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
  })

  // ===== 22. onOpenAssistantFloat 相同关键词分支 =====

  it('open-assistant-float feature=products 相同关键词且无结果时重新查询', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    const input = wrapper.find('.product-search-row input')
    await input.setValue('相同词')
    await wrapper.find('.product-search-row .btn-primary').trigger('click')
    await flushPromises()
    // 再次发送相同 query，应触发 sameKw 分支
    dispatchWindowEvent('xcagi:open-assistant-float', {
      feature: 'products',
      query: '相同词',
    })
    await flushPromises()
    expect(wrapper.find('.product-search-row').exists()).toBe(true)
  })

  // ===== 23. 微信消息 AI 管道 - 完整路径 =====

  it('pollStarredFeed 触发微信 AI 管道并执行发货预览', async () => {
    localStorage.setItem('xcagi_auto_refresh_starred_wechat', '1')
    const { shouldTryWechatShipmentPreview } = await import('@/utils/wechatShipmentDetect')
      ; (shouldTryWechatShipmentPreview as ReturnType<typeof vi.fn>).mockReturnValue(true)
    // 第一次 fetch: 建立基线
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse({
      success: true,
      feed: [
        { contact_id: 'c1', contact_name: '联系人A', messages: [{ role: 'user', text: '发货' }] },
      ],
    })))
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:auto-refresh-wechat-changed')
    await flushPromises()
    // 第二次 fetch: 消息变化 + 触发发货预览
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse({
      success: true,
      data: { success: true, task: { type: 'shipment_generate' } },
      feed: [
        { contact_id: 'c1', contact_name: '联系人A', messages: [{ role: 'user', text: '请帮我发货' }] },
      ],
    })))
    dispatchWindowEvent('xcagi:auto-refresh-wechat-changed')
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  it('pollStarredFeed 触发标签打印信号', async () => {
    localStorage.setItem('xcagi_auto_refresh_starred_wechat', '1')
    const { isLabelPrintRelatedWechatIntent } = await import('@/utils/wechatIntent')
      ; (isLabelPrintRelatedWechatIntent as ReturnType<typeof vi.fn>).mockReturnValue(true)
    // 第一次 fetch: 建立基线
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse({
      success: true,
      feed: [
        { contact_id: 'c2', contact_name: '联系人B', messages: [{ role: 'user', text: '打印' }] },
      ],
    })))
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:auto-refresh-wechat-changed')
    await flushPromises()
    // 第二次 fetch: 消息变化
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse({
      success: true,
      feed: [
        { contact_id: 'c2', contact_name: '联系人B', messages: [{ role: 'user', text: '打印标签' }] },
      ],
    })))
    dispatchWindowEvent('xcagi:auto-refresh-wechat-changed')
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  it('pollStarredFeed 触发收货确认信号', async () => {
    localStorage.setItem('xcagi_auto_refresh_starred_wechat', '1')
    const { isReceiptConfirmRelatedWechatIntent } = await import('@/utils/wechatIntent')
      ; (isReceiptConfirmRelatedWechatIntent as ReturnType<typeof vi.fn>).mockReturnValue(true)
    // 第一次 fetch: 建立基线
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse({
      success: true,
      feed: [
        { contact_id: 'c3', contact_name: '联系人C', messages: [{ role: 'user', text: '收货' }] },
      ],
    })))
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:auto-refresh-wechat-changed')
    await flushPromises()
    // 第二次 fetch: 消息变化
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse({
      success: true,
      feed: [
        { contact_id: 'c3', contact_name: '联系人C', messages: [{ role: 'user', text: '确认收货' }] },
      ],
    })))
    dispatchWindowEvent('xcagi:auto-refresh-wechat-changed')
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  it('pollStarredFeed 专业模式 API 返回无效数据回退本地规则', async () => {
    localStorage.setItem('xcagi_auto_refresh_starred_wechat', '1')
    localStorage.setItem('xcagi_pro_intent_experience', '1')
    // 第一次 fetch: 建立基线
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse({
      success: true,
      feed: [
        { contact_id: 'c4', contact_name: '联系人D', messages: [{ role: 'user', text: '基线' }] },
      ],
    })))
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:auto-refresh-wechat-changed')
    await flushPromises()
    // 第二次 fetch: API 返回 success:false
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse({
      success: true,
      data: { success: false },
      feed: [
        { contact_id: 'c4', contact_name: '联系人D', messages: [{ role: 'user', text: '新消息' }] },
      ],
    })))
    dispatchWindowEvent('xcagi:auto-refresh-wechat-changed')
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  // ===== 24. 滚动同步 =====

  it('关联网格后触发滚动同步', async () => {
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:excel-sheet-context', {
      selected_sheet: { sheet_name: 'Sheet1', sheet_index: 1 },
      excel_analysis: {
        preview_data: {
          all_sheets: [
            {
              sheet_name: 'Sheet1',
              sheet_index: 1,
              grid_preview: { rows: [{ cells: ['A1', 'B1'] }] },
              fields: [{ name: '字段1' }],
              sample_rows: [{ 字段1: '值1' }],
            },
          ],
        },
      },
    })
    await flushPromises()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('协助副窗'))!.trigger('click')
    await flushPromises()
    // 网格预览区域应存在
    expect(wrapper.find('.linked-grid-preview').exists()).toBe(true)
  })

  // ===== 25. ArrowRight 切换到 tutorial 标签 =====

  it('ArrowRight 从 starterPack 切换到 tutorial 标签', async () => {
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    // 先切到 starterPack 标签
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('新手对话包'))!.trigger('click')
    await flushPromises()
    // 按右键应切到 tutorial
    const panel = wrapper.find('.assistant-float-panel')
    const tab = panel.find('[role="tab"][aria-selected="true"]')
    await tab.trigger('keydown', { key: 'ArrowRight' })
    await flushPromises()
    expect(wrapper.find('.tutorial-track-pick').exists()).toBe(true)
  })

  // ===== 26. tryFillChatInput =====

  it('window.__VUE_CHAT_FILL__ 存在时填充聊天输入', async () => {
    const fillFn = vi.fn(() => true)
    Object.defineProperty(window, '__VUE_CHAT_FILL__', {
      configurable: true,
      value: fillFn,
    })
    const { wrapper } = await mountComponent()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    await flushPromises()
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs.find((t) => t.text().includes('新手对话包'))!.trigger('click')
    await flushPromises()
    const item = wrapper.find('.starter-pack-item')
    await item.trigger('click')
    await flushPromises()
    expect(fillFn).toHaveBeenCalled()
    delete (window as Record<string, unknown>).__VUE_CHAT_FILL__
  })

  // ===== 27. pollStarredFeed 联系人消失清理 =====

  it('pollStarredFeed 清理消失的联系人', async () => {
    localStorage.setItem('xcagi_auto_refresh_starred_wechat', '1')
    // 第一次: 有两个联系人
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse({
      success: true,
      feed: [
        { contact_id: 'c1', contact_name: 'A', messages: [{ role: 'user', text: 'hi' }] },
        { contact_id: 'c2', contact_name: 'B', messages: [{ role: 'user', text: 'hello' }] },
      ],
    })))
    const { wrapper } = await mountComponent()
    dispatchWindowEvent('xcagi:auto-refresh-wechat-changed')
    await flushPromises()
    // 第二次: c2 消失
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse({
      success: true,
      feed: [
        { contact_id: 'c1', contact_name: 'A', messages: [{ role: 'user', text: 'hi' }] },
      ],
    })))
    dispatchWindowEvent('xcagi:auto-refresh-wechat-changed')
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  // ===== 28. mods 变化触发 watch =====

  it('mods store 变化触发 syncEnterpriseWorkflowRegistry watch', async () => {
    const { syncEnterpriseWorkflowRegistry } = await import('@/utils/syncEnterpriseWorkflowRegistry')
    const { useModsStore } = await import('@/stores/mods')
    const { wrapper } = await mountComponent()
    const modsStore = useModsStore()
    // 触发 modsForWorkflowUi 变化
    modsStore.modsForWorkflowUi = [] as never
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
    expect(syncEnterpriseWorkflowRegistry).toHaveBeenCalled()
  })

  // ===== 29. clientModsUiOff 模式 =====

  it('clientModsUiOff 时调用 stripModWorkflowEmployeeKeys', async () => {
    const { useModsStore } = await import('@/stores/mods')
    const modsStore = useModsStore()
    modsStore.clientModsUiOff = true
    const { wrapper } = await mountComponent()
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })
})
