import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  adminListAiAccounts: vi.fn(),
  butlerQqStatus: vi.fn(),
  adminCreateAiAccount: vi.fn(),
  adminUpdateAiAccount: vi.fn(),
  adminRotateAiAccountSecret: vi.fn(),
  adminDeleteAiAccount: vi.fn(),
  customerServiceStandards: vi.fn(),
  customerServiceIntegrations: vi.fn(),
  customerServiceCreateStandard: vi.fn(),
  customerServiceUpdateStandard: vi.fn(),
  customerServiceCreateIntegration: vi.fn(),
  customerServiceUpdateIntegration: vi.fn(),
  listStudioAssets: vi.fn(),
  uploadStudioAsset: vi.fn(),
  downloadStudioAssetBlob: vi.fn(),
  patchStudioAssetMetadata: vi.fn(),
  deleteStudioAsset: vi.fn(),
  listEmployees: vi.fn(),
  adminDeleteEmployeePack: vi.fn(),
  adminPurgeAllEmployeePacks: vi.fn(),
  developerListWebhooks: vi.fn(),
  developerWebhookEventCatalog: vi.fn(),
  developerCreateWebhook: vi.fn(),
  developerUpdateWebhook: vi.fn(),
  developerDeleteWebhook: vi.fn(),
  developerTestWebhook: vi.fn(),
  developerListWebhookDeliveries: vi.fn(),
  developerRetryWebhookDelivery: vi.fn(),
  sendRegisterVerificationCode: vi.fn(),
  register: vi.fn(),
  sendVerificationCode: vi.fn(),
  sendResetPasswordCode: vi.fn(),
  resetPassword: vi.fn(),
}))

const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
}))

const routeMock = vi.hoisted(() => ({
  query: { redirect: '/console' },
  fullPath: '/login/email?redirect=/console',
}))

const authMock = vi.hoisted(() => ({
  isAdmin: true,
  loginWithCode: vi.fn(),
}))

const streamingSpeakMock = vi.hoisted(() => vi.fn())

vi.mock('./api', () => ({ api: apiMock }))
vi.mock('./stores/auth', () => ({ useAuthStore: () => authMock }))
vi.mock('pinia', () => ({
  storeToRefs: (store: Record<string, unknown>) =>
    Object.fromEntries(
      Object.entries(store)
        .filter(([, value]) => typeof value !== 'function')
        .map(([key]) => [
          key,
          {
            __v_isRef: true,
            get value() {
              return store[key]
            },
            set value(next: unknown) {
              store[key] = next
            },
          },
        ]),
    ),
}))
vi.mock('vue-router', () => ({
  useRouter: () => routerMock,
  useRoute: () => routeMock,
}))
vi.mock('./authPaths', () => ({
  pickRedirectFromRoute: vi.fn(() => '/console'),
}))
vi.mock('./composables/useStreamingTts', () => ({
  useStreamingTts: vi.fn(() => ({ speak: streamingSpeakMock })),
}))

import AdminAiAccountsView from './views/AdminAiAccountsView.vue'
import AdminCustomerServiceView from './views/AdminCustomerServiceView.vue'
import MyMaterialsView from './views/MyMaterialsView.vue'
import MyEmployeesView from './views/MyEmployeesView.vue'
import DeveloperWebhooksPanel from './views/developer/DeveloperWebhooksPanel.vue'
import RegisterView from './views/public/RegisterView.vue'
import LoginByEmailView from './views/public/LoginByEmailView.vue'
import ForgotPasswordView from './views/public/ForgotPasswordView.vue'

const globalMount = {
  global: {
    stubs: {
      RouterLink: { template: '<a><slot /></a>' },
      Teleport: true,
      Transition: false,
      TransitionGroup: false,
    },
  },
}

function aiAccount(overrides: Record<string, unknown> = {}) {
  return {
    id: 7,
    platform: 'qq',
    external_id: 'qq-open-id',
    employee_id: 'emp_support',
    display_name: 'Support bot',
    status: 'active',
    sandbox: false,
    notes: 'ready',
    has_secret: true,
    secrets_path: '/secrets/qq',
    channel: { platform: 'qq', paths: [{ label: 'webhook', path: '/api/qq/hook' }] },
    ...overrides,
  }
}

function webhookSub(overrides: Record<string, unknown> = {}) {
  return {
    id: 11,
    name: 'Orders',
    description: 'order callbacks',
    target_url: 'https://example.test/hook',
    has_secret: true,
    secret_storage: 'fernet',
    enabled_events: ['order.created'],
    is_active: true,
    success_count: 3,
    failure_count: 1,
    last_delivery_at: '2026-01-02T03:04:05Z',
    last_delivery_status: 'success',
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useRealTimers()
  localStorage.clear()
  sessionStorage.clear()
  document.body.innerHTML = ''
  authMock.isAdmin = true

  apiMock.adminListAiAccounts.mockResolvedValue({ items: [aiAccount()], total: 1, limit: 200, offset: 0 })
  apiMock.butlerQqStatus.mockResolvedValue({
    configured: true,
    credential_source: 'env',
    app_id: 'app-id',
    butler_employee_id: 'butler',
    first_class_employees: [],
    sandbox: false,
    api_base: 'https://qq.example',
  })
  apiMock.adminCreateAiAccount.mockResolvedValue({})
  apiMock.adminUpdateAiAccount.mockResolvedValue({})
  apiMock.adminRotateAiAccountSecret.mockResolvedValue({})
  apiMock.adminDeleteAiAccount.mockResolvedValue({})

  apiMock.customerServiceStandards.mockResolvedValue({
    items: [
      {
        id: 1,
        name: 'Refund',
        scenario: 'refund',
        description: 'desc',
        risk_level: 'high',
        priority: 5,
        auto_enabled: true,
        rules: { amount: 'large' },
        action_policy: { action: 'ticket' },
      },
    ],
  })
  apiMock.customerServiceIntegrations.mockResolvedValue({
    items: [
      {
        id: 2,
        name: 'Ticket API',
        integration_type: 'openapi',
        connector_id: 9,
        workflow_id: 0,
        scenario: 'refund',
        enabled: true,
        config: { operation_id: 'createTicket' },
      },
    ],
  })
  apiMock.customerServiceCreateStandard.mockResolvedValue({})
  apiMock.customerServiceUpdateStandard.mockResolvedValue({})
  apiMock.customerServiceCreateIntegration.mockResolvedValue({})
  apiMock.customerServiceUpdateIntegration.mockResolvedValue({})

  apiMock.listStudioAssets.mockResolvedValue({
    items: [
      {
        id: 5,
        kind: 'audio',
        filename: 'intro.wav',
        mime_type: 'audio/wav',
        size_bytes: 2048,
        metadata: { note: 'old', linked_employee_ids: ['emp_a', 'emp_b'] },
        created_at: '2026-01-02T03:04:05Z',
      },
    ],
  })
  apiMock.uploadStudioAsset.mockResolvedValue({})
  apiMock.downloadStudioAssetBlob.mockResolvedValue(new Blob(['asset']))
  apiMock.patchStudioAssetMetadata.mockResolvedValue({})
  apiMock.deleteStudioAsset.mockResolvedValue({})
  streamingSpeakMock.mockResolvedValue(undefined)

  apiMock.listEmployees.mockResolvedValue([
    { id: 'emp_alpha', name: 'Alpha', source: 'catalog' },
    { id: 'emp_legacy', name: 'Legacy', source: 'v1_catalog' },
  ])
  apiMock.adminDeleteEmployeePack.mockResolvedValue({})
  apiMock.adminPurgeAllEmployeePacks.mockResolvedValue({
    removed_packages_json: 1,
    removed_db_rows: 2,
    removed_files: 3,
  })

  apiMock.developerListWebhooks.mockResolvedValue([webhookSub()])
  apiMock.developerWebhookEventCatalog.mockResolvedValue([
    { name: 'order.created', version: 1, aggregate: 'order', description: 'Order created' },
    { name: 'payment.succeeded', version: 1, aggregate: 'payment', description: 'Payment succeeded' },
  ])
  apiMock.developerCreateWebhook.mockResolvedValue({})
  apiMock.developerUpdateWebhook.mockResolvedValue({})
  apiMock.developerDeleteWebhook.mockResolvedValue({})
  apiMock.developerTestWebhook.mockResolvedValue({})
  apiMock.developerListWebhookDeliveries.mockResolvedValue([
    {
      id: 99,
      event_id: 'evt_1',
      event_type: 'order.created',
      status: 'failed',
      status_code: 500,
      attempts: 2,
      duration_ms: 80,
      request_body: '{}',
      response_body: 'boom',
      error_message: 'failed',
      started_at: '2026-01-02T03:04:05Z',
    },
  ])
  apiMock.developerRetryWebhookDelivery.mockResolvedValue({})

  apiMock.sendRegisterVerificationCode.mockResolvedValue({})
  apiMock.register.mockResolvedValue({})
  apiMock.sendVerificationCode.mockResolvedValue({})
  apiMock.sendResetPasswordCode.mockResolvedValue({ message: 'sent' })
  apiMock.resetPassword.mockResolvedValue({})
  authMock.loginWithCode.mockResolvedValue({})

  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
  })
  vi.stubGlobal('confirm', vi.fn(() => true))
  vi.stubGlobal('alert', vi.fn())
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    value: vi.fn(() => 'blob:asset'),
  })
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    value: vi.fn(),
  })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('low coverage admin and developer views, round 2', () => {
  it('covers AI account CRUD, validation, rotation and delete flows', async () => {
    const wrapper = mount(AdminAiAccountsView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any
    expect(apiMock.adminListAiAccounts).toHaveBeenCalledWith({ limit: 200 })
    expect(vm.fullWebhookList[0].paths[0].url).toContain('/api/qq/hook')

    vm.openCreate()
    await vm.submitCreate()
    expect(vm.error).toContain('不能为空')
    vm.createForm.platform = 'qq'
    vm.createForm.external_id = 'open-id'
    vm.createForm.employee_id = 'emp_new'
    await vm.submitCreate()
    expect(vm.error).toContain('QQ')
    vm.createForm.app_id = 'app'
    vm.createForm.app_secret = 'secret'
    vm.createForm.bot_token = 'token'
    await vm.submitCreate()
    expect(apiMock.adminCreateAiAccount).toHaveBeenCalledWith(
      expect.objectContaining({
        platform: 'qq',
        external_id: 'open-id',
        employee_id: 'emp_new',
        secret: { app_id: 'app', app_secret: 'secret', bot_token: 'token' },
      }),
    )

    const row = aiAccount()
    vm.openEdit(row)
    vm.editForm.display_name = 'Updated'
    await vm.submitEdit()
    expect(apiMock.adminUpdateAiAccount).toHaveBeenCalledWith(7, expect.objectContaining({ display_name: 'Updated' }))

    vm.openRotate(row)
    await vm.submitRotate()
    expect(vm.error).toContain('轮换')
    vm.rotateForm.app_id = 'app2'
    vm.rotateForm.app_secret = 'secret2'
    vm.rotateForm.bot_token = 'token2'
    await vm.submitRotate()
    expect(apiMock.adminRotateAiAccountSecret).toHaveBeenCalledWith(7, {
      app_id: 'app2',
      app_secret: 'secret2',
      bot_token: 'token2',
    })

    ;(window.confirm as any).mockReturnValueOnce(false).mockReturnValueOnce(true)
    await vm.removeAccount(row)
    expect(apiMock.adminDeleteAiAccount).not.toHaveBeenCalled()
    await vm.removeAccount(row)
    expect(apiMock.adminDeleteAiAccount).toHaveBeenCalledWith(7)
  })

  it('covers AI account template interactions, filters and clipboard fallback', async () => {
    apiMock.butlerQqStatus.mockResolvedValueOnce({
      configured: true,
      credential_source: 'env',
      app_id: 'app-id',
      butler_employee_id: 'butler',
      first_class_employees: [
        {
          employee_id: 'emp_fc',
          app_id: 'fc-app',
          app_secret_present: true,
          by_employee_path: '/api/qq/first-class/emp_fc/hook',
        },
      ],
      sandbox: false,
      api_base: 'https://qq.example',
    })
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: undefined,
    })
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: vi.fn(() => true),
    })

    const wrapper = mount(AdminAiAccountsView, { ...globalMount, attachTo: document.body })
    await flushPromises()

    await wrapper.get('.aa-fc-list .btn.link').trigger('click')
    await wrapper.get('tbody .aa-url-list .btn.link').trigger('click')
    expect(document.execCommand).toHaveBeenCalledTimes(2)

    const filters = wrapper.findAll('.aa-filters .aa-input')
    await filters[0].setValue('qq')
    await filters[0].trigger('change')
    await filters[1].setValue('emp_support')
    await filters[1].trigger('change')
    await filters[2].setValue('active')
    await filters[2].trigger('change')
    expect(apiMock.adminListAiAccounts).toHaveBeenLastCalledWith({
      platform: 'qq',
      employee_id: 'emp_support',
      status: 'active',
      limit: 200,
    })

    await wrapper.get('header .btn.primary').trigger('click')
    await flushPromises()
    let inputs = wrapper.findAll('.aa-modal input:not([type="checkbox"])')
    await wrapper.get('.aa-modal select').setValue('qq')
    await inputs[0].setValue('emp_modal')
    await inputs[1].setValue('modal-open-id')
    await inputs[2].setValue('Modal bot')
    await wrapper.get('.aa-modal textarea').setValue('modal notes')
    await wrapper.get('.aa-modal input[type="checkbox"]').setValue(true)
    await inputs[3].setValue('modal-app')
    await inputs[4].setValue('modal-secret')
    await inputs[5].setValue('modal-token')
    ;(wrapper.vm as any).closeCreate()
    await flushPromises()

    await wrapper.findAll('.aa-row-actions .btn')[0].trigger('click')
    await flushPromises()
    inputs = wrapper.findAll('.aa-modal input:not([type="checkbox"])')
    await inputs[0].setValue('emp_edit')
    await inputs[1].setValue('Edited bot')
    await wrapper.get('.aa-modal select').setValue('disabled')
    await wrapper.get('.aa-modal input[type="checkbox"]').setValue(true)
    await wrapper.get('.aa-modal textarea').setValue('edited notes')
    ;(wrapper.vm as any).closeEdit()
    await flushPromises()

    await wrapper.findAll('.aa-row-actions .btn')[1].trigger('click')
    await flushPromises()
    inputs = wrapper.findAll('.aa-modal input:not([type="checkbox"])')
    await inputs[0].setValue('rotate-app')
    await inputs[1].setValue('rotate-secret')
    await inputs[2].setValue('rotate-token')
    ;(wrapper.vm as any).closeRotate()
    await flushPromises()

    await wrapper.findAll('.aa-row-actions .btn')[2].trigger('click')
    await flushPromises()
    expect(apiMock.adminDeleteAiAccount).toHaveBeenCalledWith(7)
  })

  it('covers AI account denied and API error branches', async () => {
    authMock.isAdmin = false
    const denied = mount(AdminAiAccountsView, globalMount)
    await flushPromises()
    await denied.get('.aa-denied .btn').trigger('click')
    expect(routerMock.push).toHaveBeenCalledWith('/')
    denied.unmount()
    authMock.isAdmin = true

    apiMock.butlerQqStatus.mockRejectedValueOnce(new Error('qq status down'))
    const qqStatusFailure = mount(AdminAiAccountsView, globalMount)
    await flushPromises()
    expect((qqStatusFailure.vm as any).qqStatus).toBe(null)
    qqStatusFailure.unmount()

    apiMock.adminListAiAccounts.mockRejectedValueOnce(new Error('list down'))
    const listFailure = mount(AdminAiAccountsView, globalMount)
    await flushPromises()
    expect((listFailure.vm as any).error).toBe('list down')
    listFailure.unmount()

    const wrapper = mount(AdminAiAccountsView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any

    apiMock.adminCreateAiAccount.mockRejectedValueOnce(new Error('create down'))
    vm.openCreate()
    vm.createForm.platform = 'qq'
    vm.createForm.external_id = 'open-id'
    vm.createForm.employee_id = 'emp_new'
    vm.createForm.app_id = 'app'
    vm.createForm.app_secret = 'secret'
    vm.createForm.bot_token = 'token'
    await vm.submitCreate()
    expect(vm.error).toBe('create down')

    apiMock.adminUpdateAiAccount.mockRejectedValueOnce(new Error('edit down'))
    vm.openEdit(aiAccount())
    await vm.submitEdit()
    expect(vm.error).toBe('edit down')

    apiMock.adminRotateAiAccountSecret.mockRejectedValueOnce(new Error('rotate down'))
    vm.openRotate(aiAccount())
    vm.rotateForm.app_id = 'app2'
    vm.rotateForm.app_secret = 'secret2'
    vm.rotateForm.bot_token = 'token2'
    await vm.submitRotate()
    expect(vm.error).toBe('rotate down')

    apiMock.adminDeleteAiAccount.mockRejectedValueOnce(new Error('delete down'))
    await vm.removeAccount(aiAccount())
    expect(vm.error).toBe('delete down')
  })

  it('covers customer service standards and integration save branches', async () => {
    const wrapper = mount(AdminCustomerServiceView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.standards).toHaveLength(1)
    expect(vm.integrations).toHaveLength(1)

    vm.editStandard(vm.standards[0])
    vm.standardRulesText = '{"required":true}'
    vm.standardPolicyText = '{"auto":false}'
    await vm.saveStandard()
    expect(apiMock.customerServiceUpdateStandard).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ rules: { required: true }, action_policy: { auto: false } }),
    )

    vm.standardRulesText = '{bad json'
    await vm.saveStandard()
    expect(vm.message).toBeTruthy()

    vm.resetStandard()
    vm.standardForm.name = 'New'
    vm.standardRulesText = '{}'
    vm.standardPolicyText = '{}'
    await vm.saveStandard()
    expect(apiMock.customerServiceCreateStandard).toHaveBeenCalled()

    vm.editIntegration(vm.integrations[0])
    vm.integrationConfigText = '{"operation_id":"sync"}'
    await vm.saveIntegration()
    expect(apiMock.customerServiceUpdateIntegration).toHaveBeenCalledWith(
      2,
      expect.objectContaining({ config: { operation_id: 'sync' } }),
    )

    vm.integrationConfigText = '{bad json'
    await vm.saveIntegration()
    expect(vm.message).toBeTruthy()

    vm.resetIntegration()
    vm.integrationForm.name = 'Created integration'
    vm.integrationConfigText = '{}'
    await vm.saveIntegration()
    expect(apiMock.customerServiceCreateIntegration).toHaveBeenCalled()
  })

  it('covers material library list, upload, clipboard, download, edit, delete and TTS paths', async () => {
    const wrapper = mount(MyMaterialsView, { ...globalMount, attachTo: document.body })
    await flushPromises()
    const vm = wrapper.vm as any
    const item = vm.items[0]

    expect(vm.kindLabel('audio')).toBe('音频')
    expect(vm.kindLabel('custom')).toBe('custom')
    expect(vm.formatSize(0)).toBe('0 B')
    expect(vm.formatSize(2048)).toContain('KB')
    expect(vm.formatSize(2 * 1024 * 1024)).toContain('MB')
    expect(vm.formatTime('bad-date')).toBeTruthy()
    expect(vm.employeeSummary(item)).toContain('emp_a')

    vm.copyDownloadPath(5)
    await flushPromises()
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('/api/workbench/studio-assets/5/file')

    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
    })
    vm.copyDownloadPath(5)
    await flushPromises()
    expect(vm.listError).toContain('复制失败')

    await vm.downloadBlob(item)
    expect(URL.createObjectURL).toHaveBeenCalled()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:asset')

    vm.openEdit(item)
    vm.editNote = 'new note'
    vm.editEmployees = 'emp_x, emp_y, '
    await vm.saveEdit()
    expect(apiMock.patchStudioAssetMetadata).toHaveBeenCalledWith(5, {
      note: 'new note',
      linked_employee_ids: ['emp_x', 'emp_y'],
    })

    const input = document.createElement('input')
    await vm.onPickUpload({ target: Object.assign(input, { files: [new File(['x'], 'clip.txt')] }) })
    expect(apiMock.uploadStudioAsset).toHaveBeenCalled()

    vm.confirmDelete(item)
    await flushPromises()
    expect(apiMock.deleteStudioAsset).toHaveBeenCalledWith(5)

    await vm.playTts()
    expect(streamingSpeakMock).toHaveBeenCalled()
  })

  it('covers material library error branches', async () => {
    apiMock.listStudioAssets.mockRejectedValueOnce(new Error('list failed'))
    const wrapper = mount(MyMaterialsView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.listError).toContain('list failed')

    apiMock.downloadStudioAssetBlob.mockRejectedValueOnce(new Error('download failed'))
    await vm.downloadBlob({ id: 88, filename: 'x.bin' })
    expect(vm.listError).toContain('download failed')

    apiMock.patchStudioAssetMetadata.mockRejectedValueOnce(new Error('patch failed'))
    vm.editId = 88
    await vm.saveEdit()
    expect(vm.listError).toContain('patch failed')

    apiMock.uploadStudioAsset.mockRejectedValueOnce(new Error('upload failed'))
    const input = document.createElement('input')
    await vm.onPickUpload({ target: Object.assign(input, { files: [new File(['x'], 'bad.txt')] }) })
    expect(vm.listError).toContain('upload failed')

    apiMock.deleteStudioAsset.mockRejectedValueOnce(new Error('delete failed'))
    vm.confirmDelete({ id: 88, filename: 'bad.txt' })
    await flushPromises()
    expect(vm.listError).toContain('delete failed')

    streamingSpeakMock.mockRejectedValueOnce(new Error('speak failed'))
    await vm.playTts()
    expect(vm.listError).toContain('speak failed')
  })

  it('covers employee list visibility, routing, delete and purge flows', async () => {
    localStorage.setItem('modstore_emp_chat_hidden_pkg_ids', JSON.stringify(['emp_hidden', 42]))
    const wrapper = mount(MyEmployeesView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any

    expect(vm.visibleEmployees.map((e: any) => e.id)).toContain('emp_alpha')
    vm.openEmployee('emp_alpha')
    expect(routerMock.push).toHaveBeenCalledWith({
      name: 'workbench-shell',
      params: { target: 'employee', id: 'emp_alpha' },
    })

    ;(window.confirm as any).mockReturnValueOnce(false)
    vm.hideLocally('emp_alpha')
    expect([...vm.hiddenPkgIds]).not.toContain('emp_alpha')
    ;(window.confirm as any).mockReturnValueOnce(true)
    vm.hideLocally('emp_alpha')
    expect([...vm.hiddenPkgIds]).toContain('emp_alpha')
    vm.clearHiddenPkgIds()
    expect([...vm.hiddenPkgIds]).toHaveLength(0)

    ;(window.confirm as any).mockReturnValueOnce(false)
    await vm.confirmDeleteEmployee({ id: 'emp_alpha', name: 'Alpha' })
    expect(apiMock.adminDeleteEmployeePack).not.toHaveBeenCalled()
    ;(window.confirm as any).mockReturnValueOnce(true)
    await vm.confirmDeleteEmployee({ id: 'emp_alpha', name: 'Alpha' })
    expect(apiMock.adminDeleteEmployeePack).toHaveBeenCalledWith('emp_alpha')

    ;(window.confirm as any).mockReturnValueOnce(true)
    await vm.purgeAllEmployees()
    expect(apiMock.adminPurgeAllEmployeePacks).toHaveBeenCalled()
    expect(vm.listError).toContain('packages.json')
  })

  it('covers employee list non-admin and load error branches', async () => {
    authMock.isAdmin = false
    apiMock.listEmployees.mockRejectedValueOnce(new Error('employees failed'))
    const wrapper = mount(MyEmployeesView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.listError).toContain('employees failed')

    await vm.confirmDeleteEmployee({ id: 'emp_alpha', name: 'Alpha' })
    await vm.purgeAllEmployees()
    expect(apiMock.adminDeleteEmployeePack).not.toHaveBeenCalled()
    expect(apiMock.adminPurgeAllEmployeePacks).not.toHaveBeenCalled()
  })

  it('covers developer webhook create, edit, toggle, deliveries, retry and delete paths', async () => {
    const wrapper = mount(DeveloperWebhooksPanel, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any

    expect(vm.subs).toHaveLength(1)
    expect(vm.statusChipClass('failed')).toBe('dw__chip dw__chip--failed')
    expect(vm.formatTime(null)).toBe('—')
    expect(vm.formatTime('not-date')).toBeTruthy()

    vm.openCreate()
    await vm.submitDialog()
    expect(vm.errMsg).toContain('名称')

    vm.dialog.name = 'Created'
    vm.dialog.url = ''
    await vm.submitDialog()
    expect(vm.errMsg).toContain('URL')

    vm.dialog.url = 'https://example.test/created'
    vm.toggleEvent('*')
    vm.toggleEvent('payment.succeeded')
    expect(vm.selectedEventsList).toEqual(['payment.succeeded'])
    await vm.submitDialog()
    expect(apiMock.developerCreateWebhook).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'Created',
        target_url: 'https://example.test/created',
        enabled_events: ['payment.succeeded'],
      }),
    )

    const sub = webhookSub()
    vm.openEdit(sub)
    vm.dialog.secret = 'new-secret'
    vm.toggleEvent('payment.succeeded')
    await vm.submitDialog()
    expect(apiMock.developerUpdateWebhook).toHaveBeenCalledWith(
      11,
      expect.objectContaining({ secret: 'new-secret' }),
    )

    await vm.toggleActive(sub)
    expect(apiMock.developerUpdateWebhook).toHaveBeenCalledWith(11, { is_active: false })

    await vm.openDeliveries(sub)
    expect(apiMock.developerListWebhookDeliveries).toHaveBeenCalledWith(11, { limit: 100, status: undefined })
    await vm.retryDelivery(vm.deliveriesPanel.rows[0])
    expect(apiMock.developerRetryWebhookDelivery).toHaveBeenCalledWith(99)

    await vm.sendTest(sub)
    expect(apiMock.developerTestWebhook).toHaveBeenCalledWith(11)

    ;(window.confirm as any).mockReturnValueOnce(false)
    await vm.deleteSub(sub)
    expect(apiMock.developerDeleteWebhook).not.toHaveBeenCalled()
    ;(window.confirm as any).mockReturnValueOnce(true)
    await vm.deleteSub(sub)
    expect(apiMock.developerDeleteWebhook).toHaveBeenCalledWith(11)
  })

  it('covers developer webhook refresh and action error branches', async () => {
    apiMock.developerListWebhooks.mockRejectedValueOnce(new Error('refresh failed'))
    const wrapper = mount(DeveloperWebhooksPanel, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.errMsg).toContain('refresh failed')

    apiMock.developerCreateWebhook.mockRejectedValueOnce(new Error('create failed'))
    vm.openCreate()
    vm.dialog.name = 'Broken'
    vm.dialog.url = 'https://example.test/broken'
    await vm.submitDialog()
    expect(vm.errMsg).toContain('create failed')

    apiMock.developerUpdateWebhook.mockRejectedValueOnce(new Error('toggle failed'))
    await vm.toggleActive(webhookSub())
    expect(vm.errMsg).toContain('toggle failed')

    apiMock.developerDeleteWebhook.mockRejectedValueOnce(new Error('delete failed'))
    await vm.deleteSub(webhookSub())
    expect(vm.errMsg).toContain('delete failed')

    apiMock.developerTestWebhook.mockRejectedValueOnce(new Error('test failed'))
    await vm.sendTest(webhookSub())
    expect(vm.errMsg).toContain('test failed')

    apiMock.developerListWebhookDeliveries.mockRejectedValueOnce(new Error('delivery failed'))
    vm.deliveriesPanel.subId = 11
    await vm.loadDeliveries()
    expect(vm.deliveriesPanel.rows).toEqual([])

    apiMock.developerRetryWebhookDelivery.mockRejectedValueOnce(new Error('retry failed'))
    await vm.retryDelivery({ id: 123 })
    expect(vm.errMsg).toContain('retry failed')
  })
})

describe('low coverage public auth views, round 2', () => {
  it('covers register verification and submit branches', async () => {
    vi.useFakeTimers()
    const wrapper = mount(RegisterView, globalMount)
    const vm = wrapper.vm as any

    await vm.sendCode()
    expect(vm.err).toContain('邮箱')

    vm.email = ' new@example.test '
    await vm.sendCode()
    expect(apiMock.sendRegisterVerificationCode).toHaveBeenCalledWith('new@example.test')
    expect(vm.cooldown).toBe(60)
    vi.advanceTimersByTime(1000)
    expect(vm.cooldown).toBe(59)

    vm.email = ''
    await vm.doRegister()
    expect(vm.err).toContain('邮箱')

    vm.email = 'new@example.test'
    vm.verificationCode = ''
    await vm.doRegister()
    expect(vm.err).toContain('验证码')

    vm.username = 'tester'
    vm.password = 'secret123'
    vm.verificationCode = '123456'
    await vm.doRegister()
    expect(apiMock.register).toHaveBeenCalledWith('tester', 'secret123', 'new@example.test', '123456')
    expect(routerMock.replace).toHaveBeenCalledWith('/workbench')

    apiMock.sendRegisterVerificationCode.mockRejectedValueOnce(new Error('send failed'))
    vm.cooldown = 0
    await vm.sendCode()
    expect(vm.err).toContain('send failed')
    wrapper.unmount()
  })

  it('covers email login send, resend, stored email, countdown and login branches', async () => {
    vi.useFakeTimers()
    sessionStorage.setItem('login_email', 'stored@example.test')
    const wrapper = mount(LoginByEmailView, globalMount)
    const vm = wrapper.vm as any
    expect(vm.email).toBe('stored@example.test')

    await vm.sendCode()
    expect(apiMock.sendVerificationCode).toHaveBeenCalledWith('stored@example.test')
    expect(vm.codeSent).toBe(true)
    expect(sessionStorage.getItem('login_email')).toBe('stored@example.test')
    vi.advanceTimersByTime(1000)
    expect(vm.countdown).toBe(59)

    await vm.resendCode()
    expect(apiMock.sendVerificationCode).toHaveBeenCalledTimes(2)

    vm.code = '654321'
    await vm.doLogin()
    expect(authMock.loginWithCode).toHaveBeenCalledWith('stored@example.test', '654321')
    expect(routerMock.replace).toHaveBeenCalledWith('/console')

    apiMock.sendVerificationCode.mockRejectedValueOnce(new Error('send code failed'))
    await vm.sendCode()
    expect(vm.err).toContain('send code failed')

    authMock.loginWithCode.mockRejectedValueOnce(new Error('login failed'))
    await vm.doLogin()
    expect(vm.err).toContain('login failed')
    wrapper.unmount()
  })

  it('covers forgot password validation, cooldown, reset and API error branches', async () => {
    vi.useFakeTimers()
    const wrapper = mount(ForgotPasswordView, globalMount)
    const vm = wrapper.vm as any

    await vm.sendCode()
    expect(vm.err).toContain('有效邮箱')

    vm.email = 'Reset@Example.Test'
    await vm.sendCode()
    expect(apiMock.sendResetPasswordCode).toHaveBeenCalledWith('reset@example.test')
    expect(vm.step).toBe(2)
    expect(vm.msg).toBe('sent')
    vi.advanceTimersByTime(1000)
    expect(vm.countdown).toBe(59)

    await vm.resetPw()
    expect(apiMock.resetPassword).not.toHaveBeenCalled()

    vm.code = '1234'
    vm.newPassword = 'secret123'
    vm.confirmPassword = 'secret321'
    expect(vm.canReset).toBe(false)
    vm.confirmPassword = 'secret123'
    expect(vm.canReset).toBe(true)
    await vm.resetPw()
    expect(apiMock.resetPassword).toHaveBeenCalledWith('reset@example.test', '1234', 'secret123')
    vi.advanceTimersByTime(1200)
    expect(routerMock.replace).toHaveBeenCalledWith('/login')

    apiMock.sendResetPasswordCode.mockRejectedValueOnce(new Error('reset code failed'))
    vm.email = 'again@example.test'
    await vm.sendCode()
    expect(vm.err).toContain('reset code failed')

    apiMock.resetPassword.mockRejectedValueOnce(new Error('reset failed'))
    await vm.resetPw()
    expect(vm.err).toContain('reset failed')
    wrapper.unmount()
  })
})
