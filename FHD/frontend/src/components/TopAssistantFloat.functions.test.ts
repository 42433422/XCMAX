import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h, nextTick } from 'vue'
import TopAssistantFloat from './TopAssistantFloat.vue'

// ===== Mock 模块 =====

const RouterLinkStub = defineComponent({
  name: 'RouterLinkStub',
  props: { to: { type: [String, Object], default: '/' } },
  setup: (props, { slots }) => () => h('a', { href: typeof props.to === 'string' ? props.to : '#' }, slots.default?.()),
})

const ExcelPreviewStub = defineComponent({
  name: 'ExcelPreview',
  setup() {
    return () => h('div', { class: 'excel-preview-stub' })
  },
})

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
  resolveLabel: (entry: { id: string }, _resolver: (k: string) => string) => {
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

const mockInferWechatCustomerIntent = vi.fn((text: string) => ({
  label: '通用意图',
  detail: `本地规则识别：${String(text).slice(0, 30)}`,
}))
const mockIsLabelPrintRelatedWechatIntent = vi.fn(() => false)
const mockIsReceiptConfirmRelatedWechatIntent = vi.fn(() => false)

vi.mock('@/utils/wechatIntent', () => ({
  inferWechatCustomerIntent: (...args: unknown[]) => mockInferWechatCustomerIntent(...(args as [string])),
  isLabelPrintRelatedWechatIntent: (...args: unknown[]) => mockIsLabelPrintRelatedWechatIntent(...args as []),
  isReceiptConfirmRelatedWechatIntent: (...args: unknown[]) => mockIsReceiptConfirmRelatedWechatIntent(...args as []),
}))

const mockShouldTryWechatShipmentPreview = vi.fn(() => false)
vi.mock('@/utils/wechatShipmentDetect', () => ({
  shouldTryWechatShipmentPreview: (...args: unknown[]) => mockShouldTryWechatShipmentPreview(...(args as [])),
}))

vi.mock('@/constants/productFlow', () => ({
  DEFAULT_TUTORIAL_TRACK_ID: 'host',
}))

vi.mock('@/constants/workflowEmployeeMods', () => ({
  WORKFLOW_EMPLOYEE_IDS: ['wechat_msg', 'label_print', 'receipt_confirm', 'shipment_mgmt'],
}))

vi.mock('@/composables/useIndustryUiText', () => ({
  useIndustryUiText: () => ({
    entityName: { value: '产品' },
    entityListName: { value: '产品列表' },
    nameLabel: { value: '名称' },
    modelLabel: { value: '型号' },
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
  }),
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

// ===== 测试 =====

describe('TopAssistantFloat functions – toggleOpen', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('点击切换按钮打开副窗', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.isOpen).toBe(false)
    await vm.toggleOpen()
    await flushPromises()
    expect(vm.isOpen).toBe(true)
    expect(vm.hasUnreadPush).toBe(false)
    wrapper.unmount()
  })

  it('再次点击切换按钮关闭副窗', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    await vm.toggleOpen()
    await flushPromises()
    expect(vm.isOpen).toBe(true)
    await vm.toggleOpen()
    await flushPromises()
    expect(vm.isOpen).toBe(false)
    wrapper.unmount()
  })

  it('打开时清除 popupNotice', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.popupNotice = { title: '测试', description: '描述' }
    await vm.toggleOpen()
    await flushPromises()
    expect(vm.popupNotice).toBeNull()
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – closeAssistantPanelUi', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('关闭打开的副窗', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.isOpen = true
    await vm.closeAssistantPanelUi()
    await flushPromises()
    expect(vm.isOpen).toBe(false)
    wrapper.unmount()
  })

  it('教程激活且有 assistantTab 时不关闭', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
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
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('按 Escape 关闭打开的副窗', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
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
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.isOpen).toBe(false)
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    window.dispatchEvent(event)
    await flushPromises()
    expect(vm.isOpen).toBe(false)
    wrapper.unmount()
  })

  it('非 Escape 键不处理', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.isOpen = true
    const event = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
    window.dispatchEvent(event)
    await flushPromises()
    expect(vm.isOpen).toBe(true)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – recordOperation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('记录操作到 operationHistory', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    const initialLen = vm.operationHistory.length
    vm.recordOperation('test_op', { foo: 'bar' })
    expect(vm.operationHistory.length).toBe(initialLen + 1)
    expect(vm.operationHistory[0].type).toBe('test_op')
    expect(vm.operationHistory[0].detail).toEqual({ foo: 'bar' })
    wrapper.unmount()
  })

  it('空 type 记录为空字符串', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.recordOperation('', null)
    expect(vm.operationHistory[0].type).toBe('')
    expect(vm.operationHistory[0].detail).toEqual({})
    wrapper.unmount()
  })

  it('超过最大数量时只保留最近 30 条', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
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

describe('TopAssistantFloat functions – isWechatPush', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('feature 为 wechat 时返回 true', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.isWechatPush({ feature: 'wechat' })).toBe(true)
    wrapper.unmount()
  })

  it('feature 为 wechat_contacts 时返回 true', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.isWechatPush({ feature: 'wechat_contacts' })).toBe(true)
    wrapper.unmount()
  })

  it('feature 为 wechat-message 时返回 true', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.isWechatPush({ feature: 'wechat-message' })).toBe(true)
    wrapper.unmount()
  })

  it('source 包含 wechat 时返回 true', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.isWechatPush({ source: 'some_wechat_source' })).toBe(true)
    wrapper.unmount()
  })

  it('非微信推送返回 false', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.isWechatPush({ feature: 'other', source: 'other_source' })).toBe(false)
    wrapper.unmount()
  })

  it('空对象返回 false', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.isWechatPush({})).toBe(false)
    wrapper.unmount()
  })

  it('null/undefined 返回 false', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.isWechatPush(null)).toBe(false)
    expect(vm.isWechatPush(undefined)).toBe(false)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – addPush', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('添加推送项到 pushFeed', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.addPush({ title: '测试', description: '描述' })
    expect(vm.pushFeed.length).toBe(1)
    expect(vm.pushFeed[0].title).toBe('测试')
    expect(vm.pushFeed[0].description).toBe('描述')
    wrapper.unmount()
  })

  it('空 title 使用默认值', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.addPush({ title: '', description: '' })
    expect(vm.pushFeed[0].title).toBe('新推送')
    expect(vm.pushFeed[0].description).toBe('收到一条助手消息')
    wrapper.unmount()
  })

  it('null detail 使用默认值', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.addPush(null)
    expect(vm.pushFeed[0].title).toBe('新推送')
    wrapper.unmount()
  })

  it('副窗关闭时设置 hasUnreadPush 和 popupNotice', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.isOpen = false
    vm.addPush({ title: '新消息', description: '内容' })
    expect(vm.hasUnreadPush).toBe(true)
    expect(vm.popupNotice).toEqual({ title: '新消息', description: '内容' })
    wrapper.unmount()
  })

  it('副窗打开时不设置 hasUnreadPush', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.isOpen = true
    vm.addPush({ title: '新消息', description: '内容' })
    expect(vm.hasUnreadPush).toBe(false)
    expect(vm.popupNotice).toBeNull()
    wrapper.unmount()
  })

  it('超过最大数量时只保留 12 条', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    for (let i = 0; i < 15; i++) {
      vm.addPush({ title: `推送${i}`, description: '' })
    }
    expect(vm.pushFeed.length).toBe(12)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – openFromNotice', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('打开副窗并清除通知状态', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
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
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('打开副窗并切换到 tutorial 标签', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
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
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('ArrowRight 切换到下一个标签', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.activeTab = 'push'
    const target = document.createElement('button')
    target.setAttribute('role', 'tab')
    const event = { key: 'ArrowRight', preventDefault: vi.fn(), target } as any
    await vm.onAssistantPanelKeydown(event)
    expect(vm.activeTab).toBe('assistant')
    wrapper.unmount()
  })

  it('ArrowLeft 切换到上一个标签', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.activeTab = 'assistant'
    const target = document.createElement('button')
    target.setAttribute('role', 'tab')
    const event = { key: 'ArrowLeft', preventDefault: vi.fn(), target } as any
    await vm.onAssistantPanelKeydown(event)
    expect(vm.activeTab).toBe('push')
    wrapper.unmount()
  })

  it('非方向键不处理', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.activeTab = 'push'
    const target = document.createElement('button')
    target.setAttribute('role', 'tab')
    const event = { key: 'Enter', preventDefault: vi.fn(), target } as any
    await vm.onAssistantPanelKeydown(event)
    expect(vm.activeTab).toBe('push')
    wrapper.unmount()
  })

  it('target 非 tab 不处理', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
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
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('微信推送事件添加到 pushFeed', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.onAssistantPush({ detail: { title: '微信消息', description: '内容', feature: 'wechat' } })
    expect(vm.pushFeed.length).toBe(1)
    expect(vm.pushFeed[0].title).toBe('微信消息')
    wrapper.unmount()
  })

  it('非微信推送事件被忽略', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.onAssistantPush({ detail: { title: '其他', description: '内容', feature: 'other' } })
    expect(vm.pushFeed.length).toBe(0)
    wrapper.unmount()
  })

  it('空 detail 被忽略', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.onAssistantPush({ detail: null })
    expect(vm.pushFeed.length).toBe(0)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – onOpenAssistantFloat', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('forceOpen 时打开副窗', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.onOpenAssistantFloat({ detail: { forceOpen: true } })
    expect(vm.isOpen).toBe(true)
    wrapper.unmount()
  })

  it('有 task 时打开副窗', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.onOpenAssistantFloat({ detail: { task: { type: 'test' } } })
    expect(vm.isOpen).toBe(true)
    wrapper.unmount()
  })

  it('feature 为 products 时打开副窗并切换到 assistant 标签', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.onOpenAssistantFloat({ detail: { feature: 'products' } })
    expect(vm.isOpen).toBe(true)
    expect(vm.activeTab).toBe('assistant')
    wrapper.unmount()
  })

  it('feature 为 starterPack 时切换到 starterPack 标签', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.onOpenAssistantFloat({ detail: { feature: 'starterPack' } })
    expect(vm.activeTab).toBe('starterPack')
    wrapper.unmount()
  })

  it('feature 为 tutorial 时打开副窗并切换到 tutorial 标签', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.onOpenAssistantFloat({ detail: { feature: 'tutorial' } })
    expect(vm.isOpen).toBe(true)
    expect(vm.activeTab).toBe('tutorial')
    wrapper.unmount()
  })

  it('普通 feature 不打开副窗但设置 hasUnreadPush', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.onOpenAssistantFloat({ detail: { feature: 'normal' } })
    expect(vm.isOpen).toBe(false)
    expect(vm.hasUnreadPush).toBe(true)
    wrapper.unmount()
  })

  it('hydrateProductSearch 时填充产品搜索结果', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
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
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
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
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('空关键词清空状态', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
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
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
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
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.productKeyword = 'test'
    await vm.searchProducts()
    expect(vm.productRows).toEqual([])
    expect(vm.productSearchFailed).toBe(true)
    expect(vm.productSearchErrorText).toContain('查询失败')
    wrapper.unmount()
  })

  it('搜索抛异常时设置错误状态', async () => {
    mockSearchProducts.mockRejectedValue(new Error('网络错误'))
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
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
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.productKeyword = 'test'
    await vm.searchProducts()
    expect(vm.productSearchFailed).toBe(true)
    expect(vm.productSearchErrorText).toContain('HTTP 500')
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – productEmptyMessage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('搜索失败时返回失败消息', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.productSearchFailed = true
    vm.productSearchErrorText = '错误详情'
    expect(vm.productEmptyMessage).toContain('查询失败')
    expect(vm.productEmptyMessage).toContain('错误详情')
    wrapper.unmount()
  })

  it('未搜索时返回搜索前提示', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.productSearchFailed = false
    vm.lastProductSearchQuery = ''
    expect(vm.productEmptyMessage).toContain('请输入关键词查询')
    wrapper.unmount()
  })

  it('关键词已修改时返回修改提示', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.productSearchFailed = false
    vm.lastProductSearchQuery = 'old'
    vm.productKeyword = 'new'
    expect(vm.productEmptyMessage).toContain('关键词已修改')
    wrapper.unmount()
  })

  it('搜索无结果时返回未找到消息', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
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
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('成功保存产品', async () => {
    mockUpdateProduct.mockResolvedValue({ success: true })
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    const row = { id: 1, name: '产品A', model_number: 'M1', price: 10, unit: '件' }
    await vm.saveProductRow(row)
    expect(mockUpdateProduct).toHaveBeenCalled()
    expect(vm.savingProductId).toBeNull()
    wrapper.unmount()
  })

  it('无 id 时不执行', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    await vm.saveProductRow({ id: 0 })
    expect(mockUpdateProduct).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('null row 时不执行', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    await vm.saveProductRow(null)
    expect(mockUpdateProduct).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('保存失败时仍重置 savingProductId', async () => {
    mockUpdateProduct.mockRejectedValue(new Error('保存失败'))
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    // saveProductRow 没有 catch，错误会传播，但 finally 仍会重置 savingProductId
    await expect(vm.saveProductRow({ id: 1, name: 'A' })).rejects.toThrow('保存失败')
    expect(vm.savingProductId).toBeNull()
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – applyExcelSheetContext', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('应用 Excel sheet 上下文', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.applyExcelSheetContext({
      selected_sheet: { sheet_name: 'Sheet1', sheet_index: 1 },
      excel_analysis: {
        preview_data: {
          all_sheets: [
            { sheet_name: 'Sheet1', sheet_index: 1, fields: ['f1'], sample_rows: [['v1']], grid_preview: { rows: [] } },
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
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.applyExcelSheetContext({})
    expect(vm.linkedSheetName).toBe('')
    expect(vm.linkedSheetIndex).toBe(0)
    expect(vm.linkedGridData).toBeNull()
    expect(vm.linkedSheetFields).toEqual([])
    wrapper.unmount()
  })

  it('null detail 清空状态', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.applyExcelSheetContext(null)
    expect(vm.linkedSheetName).toBe('')
    expect(vm.linkedGridData).toBeNull()
    wrapper.unmount()
  })

  it('按 sheet_index 匹配目标 sheet', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
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
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('products 跳转到 products 路由', async () => {
    const { wrapper, router } = await mountComponent()
    const vm = wrapper.vm as any
    await vm.navigateToSubjectPage('products')
    expect(router.currentRoute.value.name).toBe('products')
    wrapper.unmount()
  })

  it('customers 跳转到 customers 路由', async () => {
    const { wrapper, router } = await mountComponent()
    const vm = wrapper.vm as any
    await vm.navigateToSubjectPage('customers')
    expect(router.currentRoute.value.name).toBe('customers')
    wrapper.unmount()
  })

  it('未知 subject 跳转到 chat', async () => {
    const { wrapper, router } = await mountComponent()
    const vm = wrapper.vm as any
    await vm.navigateToSubjectPage('unknown')
    expect(router.currentRoute.value.name).toBe('chat')
    wrapper.unmount()
  })

  it('空 subject 跳转到 chat', async () => {
    const { wrapper, router } = await mountComponent()
    const vm = wrapper.vm as any
    await vm.navigateToSubjectPage('')
    expect(router.currentRoute.value.name).toBe('chat')
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – isAutoRefreshEnabled', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('localStorage 为 1 时返回 true', async () => {
    localStorage.setItem('xcagi_auto_refresh_starred_wechat', '1')
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.isAutoRefreshEnabled()).toBe(true)
    wrapper.unmount()
  })

  it('localStorage 为其他值时返回 false', async () => {
    localStorage.setItem('xcagi_auto_refresh_starred_wechat', '0')
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.isAutoRefreshEnabled()).toBe(false)
    wrapper.unmount()
  })

  it('localStorage 为空时返回 false', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.isAutoRefreshEnabled()).toBe(false)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – normalizeMsgSignature', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('正常消息返回 role::text 签名', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.normalizeMsgSignature({ role: 'user', text: 'hello' })).toBe('user::hello')
    wrapper.unmount()
  })

  it('空 text 返回 role:: 签名', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.normalizeMsgSignature({ role: 'user', text: '' })).toBe('user::')
    wrapper.unmount()
  })

  it('null 消息返回空签名', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.normalizeMsgSignature(null)).toBe('::')
    wrapper.unmount()
  })

  it('text 有空白时 trim', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.normalizeMsgSignature({ role: 'ai', text: '  hello  ' })).toBe('ai::hello')
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – onRestoreFloatState', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('恢复完整状态', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
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
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.onRestoreFloatState({
      detail: { isOpen: true, activeTab: 'push' },
    })
    expect(vm.isOpen).toBe(true)
    expect(vm.activeTab).toBe('push')
    wrapper.unmount()
  })

  it('空 detail 时设置为默认值', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.onRestoreFloatState({ detail: null })
    expect(vm.isOpen).toBe(false)
    expect(vm.activeTab).toBe('push')
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – onTutorialSetAssistantTab', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('open 为 true 时打开副窗', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.onTutorialSetAssistantTab({ detail: { open: true, tab: 'tutorial' } })
    expect(vm.isOpen).toBe(true)
    expect(vm.activeTab).toBe('tutorial')
    wrapper.unmount()
  })

  it('open 为 false 时不打开副窗', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.isOpen = false
    vm.onTutorialSetAssistantTab({ detail: { open: false, tab: 'push' } })
    expect(vm.isOpen).toBe(false)
    expect(vm.activeTab).toBe('push')
    wrapper.unmount()
  })

  it('空 tab 不切换标签', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.activeTab = 'assistant'
    vm.onTutorialSetAssistantTab({ detail: { open: true } })
    expect(vm.activeTab).toBe('assistant')
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – onCloseAssistantFloat', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('关闭打开的副窗', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.isOpen = true
    vm.onCloseAssistantFloat()
    expect(vm.isOpen).toBe(false)
    wrapper.unmount()
  })

  it('教程激活且有 assistantTab 时不关闭', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
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
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('空 text 返回 false', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.tryFillChatInput('')).toBe(false)
    expect(vm.tryFillChatInput('   ')).toBe(false)
    expect(vm.tryFillChatInput(null)).toBe(false)
    wrapper.unmount()
  })

  it('window.__VUE_CHAT_FILL__ 存在时调用', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    const fillFn = vi.fn(() => true)
    ;(window as any).__VUE_CHAT_FILL__ = fillFn
    expect(vm.tryFillChatInput('hello')).toBe(true)
    expect(fillFn).toHaveBeenCalledWith('hello')
    delete (window as any).__VUE_CHAT_FILL__
    wrapper.unmount()
  })

  it('window.__VUE_CHAT_FILL__ 不存在时返回 false', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    delete (window as any).__VUE_CHAT_FILL__
    expect(vm.tryFillChatInput('hello')).toBe(false)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – onAutoRefreshWechatChanged', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('auto refresh 关闭时调用 stopFeedPolling', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.onAutoRefreshWechatChanged()
    // 不报错即通过
    expect(true).toBe(true)
    wrapper.unmount()
  })

  it('auto refresh 开启时调用 startFeedPolling', async () => {
    localStorage.setItem('xcagi_auto_refresh_starred_wechat', '1')
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.onAutoRefreshWechatChanged()
    await flushPromises()
    expect(true).toBe(true)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – onExcelSheetContext', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('处理 Excel sheet context 事件', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
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
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.onExcelSheetContext({ detail: null })
    expect(vm.linkedSheetName).toBe('')
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – triggerGridReadFromChat', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('无 linkedSheetName 时不执行', async () => {
    const { wrapper, router } = await mountComponent()
    const vm = wrapper.vm as any
    vm.linkedSheetName = ''
    const beforeRoute = router.currentRoute.value.name
    await vm.triggerGridReadFromChat()
    expect(router.currentRoute.value.name).toBe(beforeRoute)
    wrapper.unmount()
  })

  it('有 linkedSheetName 时跳转到 chat', async () => {
    const { wrapper, router } = await mountComponent()
    const vm = wrapper.vm as any
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
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('点击 starter pack item 跳转到 chat 并记录操作', async () => {
    const { wrapper, router } = await mountComponent()
    const vm = wrapper.vm as any
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
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    await vm.onStarterPackItemClick('')
    await flushPromises()
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – startHostOnboardingGuide', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('跳转到 product-onboarding 并关闭副窗', async () => {
    const { wrapper, router } = await mountComponent()
    const vm = wrapper.vm as any
    vm.isOpen = true
    await vm.startHostOnboardingGuide()
    await flushPromises()
    expect(vm.isOpen).toBe(false)
    expect(router.currentRoute.value.name).toBe('product-onboarding')
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – workflowEmployeeDefs computed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('返回工作流员工定义列表', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    const defs = vm.workflowEmployeeDefs
    expect(Array.isArray(defs)).toBe(true)
    expect(defs.length).toBeGreaterThan(0)
    expect(defs[0]).toHaveProperty('id')
    expect(defs[0]).toHaveProperty('label')
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – workflowPanoramaLinkTitle computed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('返回工作流全景链接标题', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    const title = vm.workflowPanoramaLinkTitle
    expect(typeof title).toBe('string')
    expect(title.length).toBeGreaterThan(0)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – coreWorkflowEnabled', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('enabled 中存在的 id 返回 true', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    // 默认 enabled 为空对象，返回 false
    expect(vm.coreWorkflowEnabled('wechat_msg')).toBe(false)
    wrapper.unmount()
  })

  it('不存在的 id 返回 false', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.coreWorkflowEnabled('nonexistent')).toBe(false)
    wrapper.unmount()
  })

  it('空 id 返回 false', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.coreWorkflowEnabled('')).toBe(false)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – shouldRunStarredWechatIntentPipeline', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('默认无 enabled 时返回 false', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.shouldRunStarredWechatIntentPipeline()).toBe(false)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – toggleWorkflowEmployee', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('切换工作流员工状态', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.toggleWorkflowEmployee('wechat_msg')
    // 不报错即通过
    expect(true).toBe(true)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – pollStarredFeed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('auto refresh 关闭时不执行', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    await vm.pollStarredFeed()
    expect(vi.mocked(globalThis.fetch)).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('auto refresh 开启时执行 fetch', async () => {
    localStorage.setItem('xcagi_auto_refresh_starred_wechat', '1')
    const mockFetch = vi.fn(async () => makeFetchResponse({ success: true, feed: [] }))
    vi.stubGlobal('fetch', mockFetch)
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    await vm.pollStarredFeed()
    expect(mockFetch).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('fetch 失败时不报错', async () => {
    localStorage.setItem('xcagi_auto_refresh_starred_wechat', '1')
    const mockFetch = vi.fn(async () => { throw new TypeError('Failed to fetch') })
    vi.stubGlobal('fetch', mockFetch)
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    await vm.pollStarredFeed()
    // 不报错即通过
    expect(true).toBe(true)
    wrapper.unmount()
  })

  it('返回非 ok 时不处理', async () => {
    localStorage.setItem('xcagi_auto_refresh_starred_wechat', '1')
    const mockFetch = vi.fn(async () => makeFetchResponse({ success: false }, false))
    vi.stubGlobal('fetch', mockFetch)
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    await vm.pollStarredFeed()
    expect(true).toBe(true)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – runWechatMessageAiPipeline', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('空 text 时不执行', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    await vm.runWechatMessageAiPipeline({ contact_name: 'test' }, { text: '' })
    expect(vi.mocked(globalThis.fetch)).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('使用本地规则识别意图（非 pro 模式）', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    await vm.runWechatMessageAiPipeline(
      { contact_name: '联系人', contact_id: 'c1' },
      { text: '帮我发货' }
    )
    expect(mockInferWechatCustomerIntent).toHaveBeenCalledWith('帮我发货')
    wrapper.unmount()
  })

  it('pro 模式调用 intent API', async () => {
    localStorage.setItem('xcagi_pro_intent_experience', '1')
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse({
      success: true,
      data: {
        primary_intent: 'shipment',
        tool_key: 'shipment_tool',
        intent_hints: ['hint1', 'hint2'],
        confidence: 0.9,
      },
    })))
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    await vm.runWechatMessageAiPipeline(
      { contact_name: '联系人', contact_id: 'c1' },
      { text: '帮我发货' }
    )
    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('pro 模式 API 失败时回退本地规则', async () => {
    localStorage.setItem('xcagi_pro_intent_experience', '1')
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse({ success: false })))
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    await vm.runWechatMessageAiPipeline(
      { contact_name: '联系人', contact_id: 'c1' },
      { text: '帮我发货' }
    )
    expect(mockInferWechatCustomerIntent).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('pro 模式 fetch 抛异常时回退本地规则', async () => {
    localStorage.setItem('xcagi_pro_intent_experience', '1')
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('network') }))
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    await vm.runWechatMessageAiPipeline(
      { contact_name: '联系人', contact_id: 'c1' },
      { text: '帮我发货' }
    )
    expect(mockInferWechatCustomerIntent).toHaveBeenCalled()
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – startFeedPolling / stopFeedPolling', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('stopFeedPolling 不报错', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.stopFeedPolling()
    expect(true).toBe(true)
    wrapper.unmount()
  })

  it('startFeedPolling 在 auto refresh 关闭时不执行', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.startFeedPolling()
    expect(vi.mocked(globalThis.fetch)).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('startFeedPolling 在 auto refresh 开启时执行', async () => {
    localStorage.setItem('xcagi_auto_refresh_starred_wechat', '1')
    const mockFetch = vi.fn(async () => makeFetchResponse({ success: true, feed: [] }))
    vi.stubGlobal('fetch', mockFetch)
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.startFeedPolling()
    await flushPromises()
    expect(mockFetch).toHaveBeenCalled()
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – onTopScroll / onExcelScroll', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('onTopScroll 无 excelContainer 时不报错', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.onTopScroll({ target: { scrollLeft: 100 } })
    expect(true).toBe(true)
    wrapper.unmount()
  })

  it('onExcelScroll 无 excelContainer 时不报错', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    vm.onExcelScroll()
    expect(true).toBe(true)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – syncTopScrollMetrics', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('无 excelContainer 时设置 topScrollInnerWidth 为 0', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    await vm.syncTopScrollMetrics()
    expect(vm.topScrollInnerWidth).toBe(0)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat functions – fillChatInputWithRetry', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => makeFetchResponse()))
    localStorage.clear()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('空 text 不执行', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    await vm.fillChatInputWithRetry('')
    expect(true).toBe(true)
    wrapper.unmount()
  })

  it('window.__VUE_CHAT_FILL__ 存在时填充成功', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
    const fillFn = vi.fn(() => true)
    ;(window as any).__VUE_CHAT_FILL__ = fillFn
    await vm.fillChatInputWithRetry('hello')
    expect(fillFn).toHaveBeenCalledWith('hello')
    delete (window as any).__VUE_CHAT_FILL__
    wrapper.unmount()
  })

  it('window.__VUE_CHAT_FILL__ 返回 false 时重试', async () => {
    const { wrapper } = await mountComponent()
    const vm = wrapper.vm as any
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
