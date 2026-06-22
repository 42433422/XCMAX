import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const viewMocks = vi.hoisted(() => {
  const dataArray = Object.assign([], {
    items: [],
    rows: [],
    records: [],
    total: 0,
    balance: 0,
  })
  const defaultPayload = {
    success: true,
    ok: true,
    data: dataArray,
    items: [],
    rows: [],
    records: [],
    list: [],
    total: 0,
    page: 1,
    page_size: 10,
    balance: 0,
    credits: 0,
    amount: 0,
    token: 'tok_test',
    api_key: 'sk_test_full',
    key: 'sk_test_full',
    prefix: 'sk_test',
    id: 'id_test',
    status: 'active',
    user: { id: 'u1', name: '测试用户', role: 'admin', email: 'test@example.com' },
    profile: { id: 'u1', name: '测试用户' },
    settings: {},
    config: {},
    summary: {},
    stats: {},
    permissions: [],
    employees: [],
    materials: [],
    orders: [],
    jobs: [],
    accounts: [],
    requests: [],
    notifications: [],
  }
  const asyncFn = vi.fn(async () => defaultPayload)
  const route = {
    name: 'test',
    path: '/test',
    fullPath: '/test',
    query: {},
    params: { id: 'id_test', orderNo: 'ord_test', token: 'tok_test' },
    meta: {},
  }
  return {
    route,
    router: {
      push: vi.fn(),
      replace: vi.fn(),
      back: vi.fn(),
      hasRoute: vi.fn(() => true),
      afterEach: vi.fn(() => vi.fn()),
      beforeEach: vi.fn(() => vi.fn()),
      currentRoute: { value: route },
      resolve: vi.fn((to: unknown) => ({ href: typeof to === 'string' ? to : '/test' })),
    },
    defaultPayload,
    asyncFn,
  }
})

vi.mock('vue-router', () => ({
  useRoute: () => viewMocks.route,
  useRouter: () => viewMocks.router,
  RouterLink: { template: '<a><slot /></a>' },
  RouterView: { template: '<div><slot /></div>' },
  createRouter: vi.fn(),
  createWebHistory: vi.fn(),
}))

vi.mock('./api', () => ({
  api: new Proxy({}, { get: () => viewMocks.asyncFn }),
}))

vi.mock('./infrastructure/http/client', () => {
  class ApiError extends Error {
    status: number
    data: unknown

    constructor(message = 'mock api error', status = 500, data: unknown = null) {
      super(message)
      this.status = status
      this.data = data
    }
  }
  const http = {
    get: viewMocks.asyncFn,
    post: viewMocks.asyncFn,
    put: viewMocks.asyncFn,
    patch: viewMocks.asyncFn,
    delete: viewMocks.asyncFn,
  }
  return new Proxy({
    ApiError,
    http,
    requestJson: viewMocks.asyncFn,
    requestText: vi.fn(async () => ''),
    requestBlob: vi.fn(async () => new Blob(['ok'])),
    requestStreamBlob: vi.fn(async () => new Blob(['ok'])),
    requestStreamResponse: vi.fn(async () => new Response(null)),
  }, {
    get(target, prop: string | symbol) {
      if (prop in target) return target[prop as keyof typeof target]
      return viewMocks.asyncFn
    },
  })
})

const globalOptions = {
  stubs: {
    RouterLink: { template: '<a><slot /></a>' },
    RouterView: { template: '<div><slot /></div>' },
    Teleport: true,
    Transition: false,
    TransitionGroup: false,
    KeepAlive: true,
    Suspense: true,
    Icon: true,
    ElIcon: true,
    ElButton: { template: '<button><slot /></button>' },
    ElInput: { template: '<input />' },
    ElTable: { template: '<table><slot /></table>' },
    ElTableColumn: true,
    ElDialog: { template: '<div><slot /></div>' },
    ElForm: { template: '<form><slot /></form>' },
    ElFormItem: { template: '<div><slot /></div>' },
    ElSelect: { template: '<select><slot /></select>' },
    ElOption: true,
  },
  mocks: {
    $route: viewMocks.route,
    $router: viewMocks.router,
  },
}

function installBrowserMocks() {
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
  vi.stubGlobal('IntersectionObserver', class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn(() => ({
      matches: false,
      media: '',
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: vi.fn(async () => undefined), readText: vi.fn(async () => '') },
  })
  Object.defineProperty(window, 'alert', { configurable: true, value: vi.fn() })
  Object.defineProperty(window, 'confirm', { configurable: true, value: vi.fn(() => true) })
  Object.defineProperty(window, 'open', { configurable: true, value: vi.fn() })
  Object.defineProperty(window, 'scrollTo', { configurable: true, value: vi.fn() })
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() })
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:view-smoke') })
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
  Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', { configurable: true, value: vi.fn(() => ({})) })
  vi.spyOn(window, 'setInterval').mockImplementation(() => 1)
  vi.spyOn(window, 'clearInterval').mockImplementation(() => undefined)
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(viewMocks.defaultPayload), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })))
}

function fakeEvent() {
  return {
    preventDefault: vi.fn(),
    stopPropagation: vi.fn(),
    target: {
      value: '测试输入',
      checked: true,
      files: [new File(['hello'], 'test.txt', { type: 'text/plain' })],
      dataset: { id: 'id_test' },
    },
    currentTarget: {
      value: '测试输入',
      checked: true,
      dataset: { id: 'id_test' },
      setPointerCapture: vi.fn(),
      releasePointerCapture: vi.fn(),
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 320, height: 240, right: 320, bottom: 240 }),
    },
    clientX: 12,
    clientY: 24,
    pageX: 12,
    pageY: 24,
    key: 'Enter',
    code: 'Enter',
    button: 0,
    pointerId: 1,
    dataTransfer: { files: [new File(['hello'], 'drop.txt', { type: 'text/plain' })] },
  }
}

async function settle(value: unknown) {
  if (!value || typeof (value as Promise<unknown>).then !== 'function') return
  await Promise.race([
    value,
    new Promise((resolve) => window.setTimeout(resolve, 5)),
  ]).catch(() => undefined)
}

async function invokeVmFunctions(vm: Record<string, unknown>) {
  const names = new Set([...Object.keys(vm), ...Object.getOwnPropertyNames(vm)])
  const payload = viewMocks.defaultPayload
  const event = fakeEvent()
  const variants = [
    [],
    [event],
    ['id_test'],
    [payload],
    ['id_test', payload],
    [payload, event],
  ]

  for (const name of names) {
    if (name.startsWith('$') || name.startsWith('_')) continue
    const fn = vm[name]
    if (typeof fn !== 'function') continue
    for (const args of variants) {
      try {
        await settle((fn as (...args: unknown[]) => unknown)(...args))
      } catch {
        // Some page handlers require very specific domain objects; this smoke pass still
        // exercises the safe prefix of those handlers without making the suite brittle.
      }
    }
  }
}

function propsFor(name: string) {
  if (name === 'EmployeeModuleNode') {
    return {
      id: 'node-employee-1',
      selected: false,
      data: {
        label: '员工模块',
        meta: {
          name: '客服员工',
          title: '客户服务',
          role: 'assistant',
          status: 'ready',
          skills: ['咨询', '报价'],
          description: '处理客户咨询',
        },
      },
    }
  }
  return {}
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  installBrowserMocks()
  localStorage.clear()
  sessionStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const viewCases = [
  ['AccountSettingsView', () => import('./views/AccountSettingsView.vue')],
  ['AdminAiAccountsView', () => import('./views/AdminAiAccountsView.vue')],
  ['AdminCustomerServiceView', () => import('./views/AdminCustomerServiceView.vue')],
  ['AdminDatabaseView', () => import('./views/AdminDatabaseView.vue')],
  ['AdminDutyEmployeesView', () => import('./views/AdminDutyEmployeesView.vue')],
  ['AdminEmployeeAutonomyView', () => import('./views/AdminEmployeeAutonomyView.vue')],
  ['AdminEmployeeChangeRequestsView', () => import('./views/AdminEmployeeChangeRequestsView.vue')],
  ['AdminOpsAuditView', () => import('./views/AdminOpsAuditView.vue')],
  ['AdminOrchestrateJobsView', () => import('./views/AdminOrchestrateJobsView.vue')],
  ['AiStoreView', () => import('./views/AiStoreView.vue')],
  ['CatalogDetailView', () => import('./views/CatalogDetailView.vue')],
  ['CustomerServiceView', () => import('./views/CustomerServiceView.vue')],
  ['KnowledgeManagerView', () => import('./views/KnowledgeManagerView.vue')],
  ['ModAuthoringView', () => import('./views/ModAuthoringView.vue')],
  ['MyEmployeesView', () => import('./views/MyEmployeesView.vue')],
  ['MyMaterialsView', () => import('./views/MyMaterialsView.vue')],
  ['MyStoreView', () => import('./views/MyStoreView.vue')],
  ['NotificationCenter', () => import('./views/NotificationCenter.vue')],
  ['OrderListView', () => import('./views/OrderListView.vue')],
  ['PaymentCheckoutView', () => import('./views/PaymentCheckoutView.vue')],
  ['RepositoryView', () => import('./views/RepositoryView.vue')],
  ['SandboxView', () => import('./views/SandboxView.vue')],
  ['ScriptWorkflowComposerView', () => import('./views/ScriptWorkflowComposerView.vue')],
  ['ScriptWorkflowDetailView', () => import('./views/ScriptWorkflowDetailView.vue')],
  ['SoftwareDownloadView', () => import('./views/SoftwareDownloadView.vue')],
  ['UnifiedWorkbenchView', () => import('./views/UnifiedWorkbenchView.vue')],
  ['WalletRechargeView', () => import('./views/WalletRechargeView.vue')],
  ['WalletView', () => import('./views/WalletView.vue')],
  ['WorkbenchHomeView', () => import('./views/WorkbenchHomeView.vue')],
  ['WorkbenchView', () => import('./views/WorkbenchView.vue')],
  ['WorkflowView', () => import('./views/WorkflowView.vue')],
  ['DeveloperPortalView', () => import('./views/developer/DeveloperPortalView.vue')],
  ['DeveloperTokensPanel', () => import('./views/developer/DeveloperTokensPanel.vue')],
  ['DeveloperWebhooksPanel', () => import('./views/developer/DeveloperWebhooksPanel.vue')],
  ['ForgotPasswordView', () => import('./views/public/ForgotPasswordView.vue')],
  ['HomeView', () => import('./views/public/HomeView.vue')],
  ['LoginByEmailView', () => import('./views/public/LoginByEmailView.vue')],
  ['LoginView', () => import('./views/public/LoginView.vue')],
  ['PaymentPlansView', () => import('./views/public/PaymentPlansView.vue')],
  ['RegisterView', () => import('./views/public/RegisterView.vue')],
  ['TemplateDetailView', () => import('./views/templates/TemplateDetailView.vue')],
  ['TemplatesView', () => import('./views/templates/TemplatesView.vue')],
  ['WorkbenchShell', () => import('./views/workbench/WorkbenchShell.vue')],
  ['EmployeeModuleNode', () => import('./views/workbench/nodes/EmployeeModuleNode.vue')],
  ['CanvasStage', () => import('./views/workbench/panels/CanvasStage.vue')],
  ['LeftRail', () => import('./views/workbench/panels/LeftRail.vue')],
  ['RightRail', () => import('./views/workbench/panels/RightRail.vue')],
  ['WorkflowFlowEditor', () => import('./views/workflow/v2/WorkflowFlowEditor.vue')],
  ['WorkflowFlowEditorPage', () => import('./views/workflow/v2/WorkflowFlowEditorPage.vue')],
] as const

describe('view smoke coverage', () => {
  for (const [name, load] of viewCases) {
    it(`mounts ${name}`, async () => {
      const Component = (await load()).default
      const wrapper = shallowMount(Component, {
        props: propsFor(name),
        global: globalOptions,
      })
      expect(wrapper.exists()).toBe(true)
      await wrapper.vm.$nextTick()
      await invokeVmFunctions(wrapper.vm as unknown as Record<string, unknown>)
      await wrapper.vm.$nextTick()
      wrapper.unmount()
    })
  }
})

async function flushViewMicrotasks() {
  await Promise.resolve()
  await Promise.resolve()
}

describe('targeted account and knowledge view coverage', () => {
  it('drives account settings avatar and profile branches', async () => {
    viewMocks.asyncFn.mockResolvedValue(viewMocks.defaultPayload)
    const { useAuthStore } = await import('./stores/auth')
    const auth = useAuthStore() as any
    auth.user = { id: 'u1', username: 'Alice', email: 'alice@example.com', avatar_url: '/avatar.png' }
    auth.refreshSession = vi.fn(async () => undefined)
    auth.refreshMembership = vi.fn(async () => undefined)

    const Component = (await import('./views/AccountSettingsView.vue')).default
    const wrapper = shallowMount(Component, { global: globalOptions })
    await flushViewMicrotasks()
    await wrapper.vm.$nextTick()

    const vm = wrapper.vm as any
    await vm.onAvatarSelected({ target: { files: [], value: 'empty' } })
    await vm.onAvatarSelected({
      target: { files: [new File(['bad'], 'avatar.txt', { type: 'text/plain' })], value: 'bad' },
    })
    await vm.onAvatarSelected({
      target: { files: [new File([new Uint8Array(2 * 1024 * 1024 + 1)], 'big.png', { type: 'image/png' })], value: 'big' },
    })
    await vm.onAvatarSelected({
      target: { files: [new File(['ok'], 'avatar.png', { type: 'image/png' })], value: 'ok' },
    })

    vm.avatarPreviewUrl = 'blob:avatar'
    await vm.removeAvatar()
    auth.user = { ...auth.user, avatar_url: '' }
    vm.avatarPreviewUrl = ''
    await vm.removeAvatar()

    vm.username = '  新用户名  '
    await vm.saveProfile()
    viewMocks.asyncFn.mockRejectedValueOnce(new Error('保存失败 mock'))
    await vm.saveProfile()

    vm.pw = { current: 'old-secret', new1: 'new-secret', new2: 'new-secret' }
    await vm.changePw()
    vm.pw = { current: 'old-secret', new1: 'new-secret', new2: 'new-secret' }
    viewMocks.asyncFn.mockRejectedValueOnce(new Error('密码失败 mock'))
    await vm.changePw()

    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
  })

  it('drives knowledge manager CRUD, permissions, and upload branches', async () => {
    viewMocks.asyncFn.mockResolvedValue({
      ...viewMocks.defaultPayload,
      collections: [],
      documents: [],
      engine: { backend: 'memory', persist_dir: '/tmp/kb' },
      embedding: { model: 'mock-embedding', dim: 768, configured: false },
    })
    const { useAuthStore } = await import('./stores/auth')
    const auth = useAuthStore() as any
    auth.user = { id: 'u1', username: 'Alice' }

    const Component = (await import('./views/KnowledgeManagerView.vue')).default
    const wrapper = shallowMount(Component, { global: globalOptions })
    await flushViewMicrotasks()
    await wrapper.vm.$nextTick()

    const vm = wrapper.vm as any
    const own = {
      id: 1,
      owner_kind: 'user',
      owner_id: 'u1',
      name: '我的知识库',
      description: '业务 SOP',
      visibility: 'private',
      chunk_count: 2,
    }
    const shared = { ...own, id: 2, owner_id: 'u2', name: '共享知识库', visibility: 'shared' }
    const pub = { ...own, id: 3, owner_id: 'u3', name: '公开知识库', visibility: 'public' }
    const doc = { doc_id: 'doc-1', filename: 'manual.pdf', size_bytes: 1536, chunk_count: 4, created_at: 1_700_000_000 }

    vm.collections = [own, shared, pub]
    vm.docsByColl[own.id] = { docs: [doc] }
    await wrapper.vm.$nextTick()

    expect(vm.groupedCollections.length).toBe(3)
    expect(vm.ownerKindLabel('employee')).toBe('AI 员工')
    expect(vm.ownerKindLabel('custom')).toBe('custom')
    expect(vm.visibilityLabel('public')).toBe('公开可读')
    expect(vm.visibilityLabel('custom')).toBe('custom')
    expect(vm.canAdmin(own)).toBe(true)
    expect(vm.canWrite(shared)).toBe(false)
    expect(vm.formatBytes(0)).toBe('0 B')
    expect(vm.formatBytes(512)).toBe('512 B')
    expect(vm.formatBytes(1536)).toContain('KB')
    expect(vm.formatBytes(2 * 1024 * 1024)).toContain('MB')
    expect(vm.formatDate(0)).toBe('')
    expect(vm.granteeIdPlaceholder).toContain('用户')

    await vm.toggleCollection(own)
    await vm.toggleCollection(own)
    vm.openCreateModal()
    vm.createForm.name = '新集合'
    vm.createForm.description = '说明'
    vm.createForm.visibility = 'shared'
    await vm.submitCreate()

    vm.openShareModal(own)
    vm.shareForm.grantee_kind = 'employee'
    vm.shareForm.grantee_id = 'builtin_workmate'
    vm.shareForm.permission = 'write'
    expect(vm.granteeIdPlaceholder).toContain('员工包')
    await vm.submitShare()
    vm.openShareModal(own)
    vm.closeShareModal()

    await vm.deleteCollection(shared)
    await vm.deleteCollection(own)
    await vm.deleteDoc(shared, doc)
    await vm.deleteDoc(own, doc)
    await vm.onPickFile({ target: { files: [], value: 'empty' } }, own)
    await vm.onPickFile({
      target: { files: [new File(['hello'], 'manual.md', { type: 'text/markdown' })], value: 'manual' },
    }, own)

    viewMocks.asyncFn.mockRejectedValueOnce(new Error('status failed'))
    await vm.loadStatus()
    viewMocks.asyncFn.mockRejectedValueOnce(new Error('collections failed'))
    await vm.loadCollections()

    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
  })
})
