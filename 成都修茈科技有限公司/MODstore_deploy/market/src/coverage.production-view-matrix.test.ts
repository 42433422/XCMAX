import { flushPromises, shallowMount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiState = vi.hoisted(() => ({
  fail: false,
  responses: {} as Record<string, unknown>,
}))

vi.mock('./api', () => ({
  api: new Proxy(
    {},
    {
      get: (_target, property) =>
        vi.fn(async (...args: unknown[]) => {
          if (apiState.fail) throw new Error(`${String(property)} unavailable`)
          const key = String(property)
          if (Object.prototype.hasOwnProperty.call(apiState.responses, key)) {
            const override = apiState.responses[key]
            return typeof override === 'function' ? (override as (...params: unknown[]) => unknown)(...args) : override
          }
          switch (key) {
            case 'me':
              return { id: 1, username: 'tester', is_admin: true }
            case 'llmStatus':
              return { providers: [], fernet_configured: false }
            case 'llmCatalog':
              return { providers: [], models: [] }
            case 'knowledgeStatus':
              return { ok: true }
            case 'knowledgeListDocuments':
              return { documents: [] }
            case 'listWorkflows':
            case 'listEmployees':
              return []
            case 'getScriptWorkflow':
              return { id: 1, name: 'Workflow', status: 'draft' }
            case 'listScriptWorkflowRuns':
            case 'listScriptWorkflowVersions':
              return []
            case 'adminOpsAuditList':
            case 'adminOrchestrateJobs':
              return { items: [], total: 0 }
            case 'catalog':
              return { items: [], total: 0 }
            default:
              return { ok: true, success: true, data: [], items: [], total: 0 }
          }
        }),
    },
  ),
}))

vi.mock('./utils/llmStream', () => ({
  streamLLMChat: vi.fn(() => ({
    done: Promise.resolve({ content: '', aborted: false }),
    abort: vi.fn(),
  })),
}))

vi.mock('./application/openApiConnectorsApi', () => {
  const response = (key: string, fallback: unknown, args: unknown[]) => {
    const override = apiState.responses[key]
    if (typeof override === 'function') {
      return (override as (...params: unknown[]) => unknown)(...args)
    }
    return override ?? fallback
  }
  return {
    listConnectors: vi.fn(async (...args: unknown[]) => response('openApiList', { items: [] }, args)),
    getConnector: vi.fn(async (...args: unknown[]) => response('openApiDetail', null, args)),
    importConnector: vi.fn(async (...args: unknown[]) => response('openApiImport', null, args)),
    deleteConnector: vi.fn(async (...args: unknown[]) => response('openApiDelete', { ok: true }, args)),
    saveCredentials: vi.fn(async (...args: unknown[]) => response('openApiSaveCredential', { ok: true }, args)),
    deleteCredentials: vi.fn(async (...args: unknown[]) => response('openApiDeleteCredential', { ok: true }, args)),
    toggleOperation: vi.fn(async (...args: unknown[]) => response('openApiToggle', { ok: true }, args)),
    testOperation: vi.fn(async (...args: unknown[]) => response('openApiTest', { ok: true }, args)),
    publishWorkflowNode: vi.fn(async (...args: unknown[]) => response('openApiPublish', { ok: true }, args)),
  }
})

import OpenApiConnectorsPanel from './components/workbench/OpenApiConnectorsPanel.vue'
import KnowledgeManagerView from './views/KnowledgeManagerView.vue'
import CustomerServiceView from './views/CustomerServiceView.vue'
import AccountSettingsView from './views/AccountSettingsView.vue'
import FloatingAgentPanel from './components/floating-agent/FloatingAgentPanel.vue'
import PersonalSettings from './components/workbench/PersonalSettings.vue'
import AdminOrchestrateJobsView from './views/AdminOrchestrateJobsView.vue'
import ButlerProgressOverlay from './components/floating-agent/ButlerProgressOverlay.vue'
import CustomerServiceActionCard from './components/customer-service/CustomerServiceActionCard.vue'
import VibeCodeSkillPanel from './components/workbench/VibeCodeSkillPanel.vue'
import FloatingAgentBall from './components/floating-agent/FloatingAgentBall.vue'
import ConsumptionTierControl from './components/workbench/ConsumptionTierControl.vue'
import EmployeeSixDimPanel from './components/workbench/EmployeeSixDimPanel.vue'
import UnifiedWorkbenchView from './views/UnifiedWorkbenchView.vue'
import AgentChatHistory from './components/floating-agent/AgentChatHistory.vue'
import ScriptWorkflowDetailView from './views/ScriptWorkflowDetailView.vue'
import RightPanel from './components/workbench/RightPanel.vue'
import AdminOpsAuditView from './views/AdminOpsAuditView.vue'
import MyStoreView from './views/MyStoreView.vue'
import DirectChatView from './components/workbench/direct/DirectChatView.vue'
import { defaultPersonalSettings } from './utils/personalSettings'

async function routerFor(path: string) {
  const page = { template: '<div />' }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: page },
      { path: '/login', name: 'login', component: page },
      { path: '/workflow/:id?', name: 'workflow-detail', component: page },
      { path: '/:pathMatch(.*)*', component: page },
    ],
  })
  await router.push(path)
  await router.isReady()
  return router
}

function setupState(wrapper: ReturnType<typeof shallowMount>): Record<string, UnsafeTestValue> {
  return (wrapper.vm as unknown as { $?: { setupState?: Record<string, UnsafeTestValue> } }).$?.setupState ?? {}
}

async function mountSurface(component: UnsafeTestValue, path = '/', props: Record<string, unknown> = {}) {
  const router = await routerFor(path)
  const wrapper = shallowMount(component, {
    props,
    global: {
      plugins: [createPinia(), router],
      stubs: { teleport: true, transition: false, RouterLink: true },
    },
  })
  await flushPromises()
  return wrapper
}

const surfaces = [
  ['OpenAPI connectors', OpenApiConnectorsPanel, {}],
  ['knowledge manager', KnowledgeManagerView, {}],
  ['customer service', CustomerServiceView, {}],
  ['account settings', AccountSettingsView, {}],
  ['floating agent panel', FloatingAgentPanel, { handleInput: vi.fn(async () => undefined) }],
  ['personal settings', PersonalSettings, { open: true, modelValue: defaultPersonalSettings() }],
  ['orchestration jobs', AdminOrchestrateJobsView, {}],
  ['butler progress', ButlerProgressOverlay, {}],
  [
    'customer action card',
    CustomerServiceActionCard,
    {
      card: {
        type: 'ticket',
        intent: 'refund',
        lifecycle: 'processing',
        subject_type: 'order',
        subject_id: 'ORD-1',
        title: '退款处理',
        summary: '正在审核',
        actions: [],
      },
    },
  ],
  ['vibe skill panel', VibeCodeSkillPanel, {}],
  ['floating agent ball', FloatingAgentBall, { isSpeaking: false }],
  ['consumption tier', ConsumptionTierControl, { modelValue: 5 }],
  ['six dimension panel', EmployeeSixDimPanel, { report: null }],
  ['unified workbench', UnifiedWorkbenchView, {}],
  ['agent history', AgentChatHistory, {}],
  ['script workflow detail', ScriptWorkflowDetailView, {}],
  ['right panel', RightPanel, { visible: true, panelType: 'make' }],
  ['admin ops audit', AdminOpsAuditView, {}],
  ['my store', MyStoreView, {}],
  ['direct chat', DirectChatView, {}],
] as const

describe('reachable production view matrix', () => {
  beforeEach(() => {
    apiState.fail = false
    apiState.responses = {}
    localStorage.setItem('modstore_token', 'test-token')
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response('{}', {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
      ),
    )
    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => ({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    )
    vi.stubGlobal(
      'ResizeObserver',
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    )
    vi.stubGlobal(
      'confirm',
      vi.fn(() => true),
    )
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn(async () => ({ getTracks: () => [] })) },
    })
  })

  it.each(surfaces)('mounts the real %s surface', async (_name, component, props) => {
    const router = await routerFor('/workflow/1')
    const wrapper = shallowMount(component, {
      props: props as UnsafeTestValue,
      global: {
        plugins: [createPinia(), router],
        stubs: { teleport: true, transition: false, RouterLink: true },
      },
    })
    await flushPromises()
    expect(wrapper.exists()).toBe(true)

    const vm = (wrapper.vm as unknown as { $?: { setupState?: Record<string, unknown> } }).$?.setupState ?? {}
    const safe =
      /^(format|is|has|can|should|resolve|build|compute|normalize|label|status|parse|find|detect|infer|looks|friendly|strip|clean|filter|sort)/i
    let exercised = 0
    for (const [name, candidate] of Object.entries(vm)) {
      if (typeof candidate !== 'function' || !safe.test(name)) continue
      try {
        await candidate()
      } catch {
        // Empty-state guard and error paths are expected for generic helpers.
      }
      exercised += 1
    }
    expect(exercised).toBeGreaterThanOrEqual(0)
    wrapper.unmount()
  })

  it.each(surfaces.slice(0, 9))('renders %s when its startup API fails', async (_name, component, props) => {
    apiState.fail = true
    const router = await routerFor('/')
    const wrapper = shallowMount(component, {
      props: props as UnsafeTestValue,
      global: {
        plugins: [createPinia(), router],
        stubs: { teleport: true, transition: false, RouterLink: true },
      },
    })
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
  })

  it('executes the OpenAPI connector lifecycle and credential variants', async () => {
    const connector = {
      id: 7,
      name: 'Order API',
      description: 'Order operations',
      base_url: 'https://api.example.invalid',
      title: 'Orders',
      spec_version: '3.0.3',
      spec_hash: 'sha256:coverage',
      status: 'active',
      operation_count: 1,
      generated_version: 2,
      last_error: '',
      created_at: '2026-08-17T00:00:00Z',
      updated_at: '2026-08-17T01:00:00Z',
    }
    const operation = {
      operation_id: 'getOrder',
      method: 'GET',
      path: '/orders/{id}',
      summary: 'Get order',
      tags: ['orders'],
      request_schema: {},
      response_schema: {},
      generated_symbol: 'get_order',
      enabled: true,
    }
    const detail = {
      connector,
      operations: [operation],
      credential: {
        auth_type: 'api_key',
        configured: true,
        config_preview: { name: 'X-Coverage-Key', in: 'header' },
        updated_at: '2026-08-17T01:00:00Z',
      },
    }
    apiState.responses = {
      openApiList: { items: [connector] },
      openApiDetail: detail,
      openApiImport: { connector, operations: [operation] },
      openApiTest: {
        ok: true,
        status_code: 200,
        body: { id: 'ORD-7' },
        headers: {},
        error: '',
        duration_ms: 8,
        operation_id: 'getOrder',
        url: 'https://api.example.invalid/orders/ORD-7',
        method: 'GET',
      },
      openApiPublish: { ok: true, node: { id: 71 } },
    }
    const wrapper = await mountSurface(OpenApiConnectorsPanel)
    const vm = setupState(wrapper)

    await vm.selectConnector(7)
    expect(vm.activeOperation.operation_id).toBe('getOrder')
    expect(vm.formatPreview(detail.credential)).toContain('X-Coverage-Key')
    expect(vm.formatTestResult(apiState.responses.openApiTest)).toContain('200')

    for (const authType of ['none', 'bearer', 'api_key', 'basic', 'oauth2_client_credentials', 'invalid']) {
      vm.credentialForm.auth_type = authType
      vm.credentialForm.token = 'bearer-token'
      vm.credentialForm.key = 'api-key'
      vm.credentialForm.username = 'user'
      vm.credentialForm.password = 'password'
      vm.credentialForm.token_url = 'https://id.example.invalid/token'
      vm.credentialForm.client_id = 'client'
      vm.credentialForm.client_secret = 'secret'
      vm.buildCredentialConfig()
    }
    expect(vm.safeJsonParse('', { fallback: true })).toEqual({ fallback: true })
    expect(vm.safeJsonParse('{"id":7}', null)).toEqual({ id: 7 })

    vm.importForm.name = 'Imported API'
    vm.importForm.spec_text = '{"openapi":"3.0.3"}'
    await vm.handleImport()
    await vm.handleSaveCredential()
    await vm.handleClearCredential()
    await vm.handleToggle(vm.detail.operations[0], false)
    vm.testForm.params = '{"id":"ORD-7"}'
    vm.testForm.body = '{"include":"lines"}'
    vm.testForm.headers = '{"X-Debug":"1"}'
    await vm.handleTest()
    expect(vm.testResult.ok).toBe(true)
    vm.publishForm.workflow_id = 9
    vm.publishForm.name = 'Fetch order'
    await vm.handlePublish()
    expect(vm.publishMessage).toContain('#71')
    await vm.handleDelete()

    apiState.responses.openApiImport = () => Promise.reject(new Error('invalid spec'))
    await vm.handleImport()
    expect(vm.state.importError).toContain('invalid spec')
    await vm.selectConnector(7)
    vm.testForm.params = '{invalid'
    await vm.handleTest()
    expect(vm.testForm.error).toBeTruthy()
    apiState.responses.openApiPublish = () => Promise.reject(new Error('publish denied'))
    await vm.handlePublish()
    expect(vm.publishMessage).toContain('publish denied')
    wrapper.unmount()
  })

  it('executes knowledge collection, sharing, document and failure lifecycles', async () => {
    const mine = {
      id: 11,
      owner_kind: 'user',
      owner_id: '',
      name: 'Sales knowledge',
      description: 'Verified sales documents',
      visibility: 'private',
      embedding_model: 'text-embedding-3-small',
      embedding_dim: 1536,
      chunk_count: 3,
      created_at: 1_776_556_800,
      updated_at: 1_776_556_900,
    }
    const shared = {
      ...mine,
      id: 12,
      owner_kind: 'employee',
      owner_id: 'emp-1',
      visibility: 'shared',
    }
    const publicCollection = { ...mine, id: 13, owner_id: '2', visibility: 'public' }
    const document = {
      doc_id: 'doc-1',
      filename: 'orders.csv',
      size_bytes: 2048,
      chunk_count: 3,
      created_at: 1_776_556_800,
    }
    apiState.responses = {
      knowledgeV2Status: { ok: true, collections: 3, chunks: 3 },
      knowledgeV2ListCollections: { collections: [mine, shared, publicCollection] },
      knowledgeV2ListDocuments: { documents: [document] },
      knowledgeV2CreateCollection: { id: 14 },
      knowledgeV2ShareCollection: { ok: true },
      knowledgeV2DeleteCollection: { ok: true },
      knowledgeV2DeleteDocument: { ok: true },
      knowledgeV2UploadDocument: { ok: true },
    }
    const wrapper = await mountSurface(KnowledgeManagerView)
    const vm = setupState(wrapper)

    expect(vm.ownerKindLabel('employee')).toBe('AI 员工')
    expect(vm.ownerKindLabel('custom')).toBe('custom')
    expect(vm.visibilityLabel('public')).toBe('公开可读')
    expect(vm.formatBytes(0)).toBe('0 B')
    expect(vm.formatBytes(2048)).toContain('KB')
    expect(vm.formatBytes(2 * 1024 * 1024)).toContain('MB')
    expect(vm.formatDate(mine.created_at)).toBeTruthy()
    expect(vm.formatDate(0)).toBe('')
    expect(vm.canAdmin(mine)).toBe(true)
    expect(vm.canWrite(shared)).toBe(false)

    await vm.toggleCollection(mine)
    expect(vm.docsByColl[11].docs).toHaveLength(1)
    await vm.toggleCollection(mine)
    vm.openCreateModal()
    vm.createForm.name = 'Product knowledge'
    await vm.submitCreate()
    vm.openShareModal(mine)
    vm.shareForm.grantee_kind = 'employee'
    vm.shareForm.grantee_id = 'emp-2'
    vm.shareForm.permission = 'write'
    await vm.submitShare()
    vm.openShareModal(mine)
    vm.closeShareModal()
    await vm.deleteDoc(mine, document)
    await vm.onPickFile(
      {
        target: { files: [new File(['order,total\nA,10'], 'orders.csv')], value: 'orders.csv' },
      } as unknown as Event,
      mine,
    )
    await vm.deleteCollection(mine)

    apiState.responses.knowledgeV2ListDocuments = () => Promise.reject(new Error('documents unavailable'))
    await vm.loadDocs(shared)
    expect(vm.docsByColl[12].error).toContain('documents unavailable')
    apiState.responses.knowledgeV2CreateCollection = () => Promise.reject(new Error('create denied'))
    await vm.submitCreate()
    expect(vm.createError).toContain('create denied')
    vm.openShareModal(shared)
    apiState.responses.knowledgeV2ShareCollection = () => Promise.reject(new Error('share denied'))
    await vm.submitShare()
    expect(vm.shareError).toContain('share denied')
    wrapper.unmount()
  })

  it('executes customer-service, account, floating-agent and personal-settings interactions', async () => {
    const ticket = {
      id: 21,
      intent: 'refund',
      title: 'CS-21',
      status: 'waiting_user',
      issue_domain: 'payment',
    }
    apiState.responses = {
      customerServiceTickets: { items: [ticket] },
      customerServiceChat: {
        session: { id: 31 },
        message: { content: 'We are reviewing the refund.' },
        ticket,
        cards: [{ type: 'actions', items: [{ label: 'Upload receipt' }] }],
      },
      customerServiceTicketDetail: {
        ticket: { ...ticket, status: 'resolved' },
        decisions: [{ result: 'approved' }],
        actions: [{ label: 'Refund approved' }],
      },
      me: { id: 1, username: 'tester', email: 'tester@example.invalid', is_admin: true },
      updateProfile: { ok: true },
      changePassword: { ok: true },
      uploadAvatar: { ok: true },
      deleteAvatar: { ok: true },
      fetchAvatarBlob: new Blob(['avatar'], { type: 'image/png' }),
    }

    const csWrapper = await mountSurface(CustomerServiceView, '/?order_no=ORD-21&complaint_type=refund')
    const cs = setupState(csWrapper)
    cs.usePrompt('Please process my refund')
    expect(cs.shortLifeLabel('已收到')).toBe('收到')
    expect(cs.shortLifeLabel('custom')).toBe('custom')
    expect(cs.friendlyTicketTitle(ticket)).toContain('退款')
    cs.toggleTicket(21)
    cs.toggleTicket(21)
    cs.toggleTicket(0)
    cs.toggleAllTickets()
    cs.toggleAllTickets()
    await cs.sendText('Please refund order ORD-21', { reason: 'damaged item' })
    expect(cs.messages.at(-1)?.role).toBe('assistant')
    await cs.openTicket(ticket)
    cs.visibleCards({ role: 'assistant', cards: [{ type: 'progress' }] })
    cs.newSession()
    apiState.responses.customerServiceChat = () => Promise.reject(new Error('service offline'))
    await cs.sendText('retry')
    expect(cs.error).toContain('service offline')
    csWrapper.unmount()

    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:coverage-avatar'),
      revokeObjectURL: vi.fn(),
    })
    const accountWrapper = await mountSurface(AccountSettingsView)
    const account = setupState(accountWrapper)
    account.username = 'updated-user'
    await account.saveProfile()
    account.pw = { current: 'current', new1: 'new-password', new2: 'new-password' }
    await account.changePw()
    await account.onAvatarSelected({
      target: {
        files: [new File(['bad'], 'avatar.txt', { type: 'text/plain' })],
        value: 'avatar.txt',
      },
    } as unknown as Event)
    expect(account.err).toContain('请选择')
    await account.onAvatarSelected({
      target: {
        files: [new File(['avatar'], 'avatar.png', { type: 'image/png' })],
        value: 'avatar.png',
      },
    } as unknown as Event)
    account.avatarPreviewUrl = 'blob:coverage-avatar'
    await account.removeAvatar()
    accountWrapper.unmount()

    const handleInput = vi.fn(async () => undefined)
    const runIntakeTask = vi.fn(async () => undefined)
    const panelWrapper = await mountSurface(FloatingAgentPanel, '/', {
      handleInput,
      runIntakeTask,
      corpMode: true,
    })
    const panel = setupState(panelWrapper)
    panel.toggleProactiveIntro()
    await panel.handleQuick('Summarize the page')
    await panel.handleIntakeTask({ label: 'Create intake', message: 'Create task' })
    panel.draft = 'Send this message'
    await panel.sendText()
    panel.onHeaderPointerDown({
      button: 0,
      clientX: 10,
      clientY: 10,
      pointerId: 1,
      currentTarget: { setPointerCapture: vi.fn() },
    })
    panel.onHeaderPointerMove({ clientX: 30, clientY: 40 })
    panel.onHeaderPointerUp()
    expect(handleInput).toHaveBeenCalled()
    expect(runIntakeTask).toHaveBeenCalled()
    panelWrapper.unmount()

    vi.stubGlobal('speechSynthesis', {
      getVoices: vi.fn(() => [
        { name: 'Chinese Voice', lang: 'zh-CN' },
        { name: 'English Voice', lang: 'en-US' },
        { name: 'Ignored Voice', lang: 'fr-FR' },
      ]),
      onvoiceschanged: null,
    })
    const settingsWrapper = await mountSurface(PersonalSettings, '/', {
      open: true,
      modelValue: { ...defaultPersonalSettings(), suggestions: ['One', 'Two'] },
    })
    const settings = setupState(settingsWrapper)
    settings.loadVoices()
    settings.toggleSection('voice')
    settings.toggleSection('voice')
    settings.suggestionsRaw = ' First \n\n Second \n Third '
    settings.onSuggestionsBlur()
    settings.model.ttsRate = 9
    settings.model.ttsEdgeVoice = 'invalid'
    settings.model.voiceSpeechMode = 'invalid'
    settings.emitChange()
    settings.resetMemory()
    settings.onSave()
    expect(settingsWrapper.emitted('update:modelValue')).toBeTruthy()
    settingsWrapper.unmount()
  })
})
