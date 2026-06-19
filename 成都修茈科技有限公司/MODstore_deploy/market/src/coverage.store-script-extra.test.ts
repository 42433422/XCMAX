import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './infrastructure/http/client'

const apiMock = vi.hoisted(() => ({
  catalog: vi.fn(),
  catalogFacets: vi.fn(),
  catalogToggleFavorite: vi.fn(),
  downloadItem: vi.fn(),
  buyItem: vi.fn(),
  attachCatalogEmployeeToMod: vi.fn(),
  downloadOfficeEmployeePack: vi.fn(),
  downloadWorkflowEmployeePack: vi.fn(),
  downloadHostFoundationEmployeePack: vi.fn(),
  adminDeleteCatalog: vi.fn(),
  commitScriptWorkflowSession: vi.fn(),
  sandboxRunScriptWorkflow: vi.fn(),
  downloadScriptWorkflowRunFile: vi.fn(),
  activateScriptWorkflow: vi.fn(),
  getScriptWorkflow: vi.fn(),
  listScriptWorkflowRuns: vi.fn(),
}))

const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
}))

const routeMock = vi.hoisted(() => ({
  params: {} as Record<string, unknown>,
  query: {} as Record<string, unknown>,
}))

const authMock = vi.hoisted(() => ({
  isLoggedIn: true,
  user: { id: 1, is_admin: true },
}))

const ensureAdminDigestUnlockedMock = vi.hoisted(() => vi.fn())

vi.mock('./api', () => ({ api: apiMock }))
vi.mock('vue-router', () => ({
  useRoute: () => routeMock,
  useRouter: () => routerMock,
}))
vi.mock('./stores/auth', () => ({ useAuthStore: () => authMock }))
vi.mock('./composables/useAdminDigestUnlock', () => ({
  useAdminDigestUnlock: () => ({
    open: { value: false },
    code: { value: '' },
    err: { value: '' },
    busy: { value: false },
    dialogTitle: { value: 'Unlock' },
    dialogSubmitLabel: { value: 'Verify' },
    dialogHint: { value: 'hint' },
    onInputBlur: vi.fn(),
    close: vi.fn(),
    submitVerify: vi.fn(),
    ensureAdminDigestUnlocked: ensureAdminDigestUnlockedMock,
  }),
}))
vi.mock('./infrastructure/storage/tokenStore', () => ({
  getAccessToken: vi.fn(() => 'token-1'),
}))

import AiStoreView from './views/AiStoreView.vue'
import ScriptWorkflowComposerView from './views/ScriptWorkflowComposerView.vue'

const globalMount = {
  global: {
    stubs: {
      RouterLink: { props: ['to'], template: '<a><slot /></a>' },
      AdminDigestUnlockModal: { template: '<div class="digest-modal" />' },
      EmployeePackTypeIcon: { template: '<span class="pack-icon" />' },
      Teleport: true,
      Transition: false,
      TransitionGroup: false,
    },
  },
}

function storeItem(overrides: Record<string, unknown> = {}) {
  return {
    id: 10,
    pkg_id: 'emp_customer_service',
    name: 'Customer Agent',
    version: '1.0.0',
    industry: 'retail',
    artifact: 'employee_pack',
    material_category: 'ai_employee',
    license_scope: 'enterprise',
    security_level: 'enterprise',
    compliance_status: 'approved',
    purchased: false,
    favorited: false,
    favorite_count: 2,
    description: 'A useful employee package',
    price: 19,
    ...overrides,
  }
}

function makeSseResponse(events: any[]) {
  const enc = new TextEncoder()
  const chunks = events.map((ev) => enc.encode(`data: ${JSON.stringify(ev)}\n\n`))
  let i = 0
  return {
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: vi.fn(async () => (i < chunks.length ? { value: chunks[i++], done: false } : { value: undefined, done: true })),
      }),
    },
    text: vi.fn(async () => ''),
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useRealTimers()
  localStorage.clear()
  sessionStorage.clear()
  document.body.innerHTML = ''
  routeMock.params = {}
  routeMock.query = {}
  authMock.isLoggedIn = true
  authMock.user = { id: 1, is_admin: true }
  ensureAdminDigestUnlockedMock.mockResolvedValue(true)

  apiMock.catalog.mockResolvedValue({ items: [storeItem(), storeItem({ id: 11, pkg_id: 'other_pkg', price: 0 })], total: 2 })
  apiMock.catalogFacets.mockResolvedValue({
    industries: ['retail'],
    artifacts: ['employee_pack', 'mod'],
    material_categories: ['ai_employee'],
    license_scopes: ['enterprise'],
    security_levels: ['enterprise'],
  })
  apiMock.catalogToggleFavorite.mockResolvedValue({ favorited: true })
  apiMock.downloadItem.mockResolvedValue({})
  apiMock.buyItem.mockResolvedValue({})
  apiMock.attachCatalogEmployeeToMod.mockResolvedValue({})
  apiMock.downloadOfficeEmployeePack.mockResolvedValue({})
  apiMock.downloadWorkflowEmployeePack.mockResolvedValue({})
  apiMock.downloadHostFoundationEmployeePack.mockResolvedValue({})
  apiMock.adminDeleteCatalog.mockResolvedValue({})

  apiMock.commitScriptWorkflowSession.mockResolvedValue({ id: 22 })
  apiMock.sandboxRunScriptWorkflow.mockResolvedValue({ id: 33, status: 'success', outputs: [{ filename: 'out.json' }] })
  apiMock.downloadScriptWorkflowRunFile.mockResolvedValue(new Blob(['out']))
  apiMock.activateScriptWorkflow.mockResolvedValue({})
  apiMock.getScriptWorkflow.mockResolvedValue({
    id: 44,
    name: 'Existing Workflow',
    brief: { goal: 'existing goal', outputs: 'out', acceptance: 'ok' },
    script_text: 'print("ok")',
  })
  apiMock.listScriptWorkflowRuns.mockResolvedValue([{ id: 55, status: 'success', payload: { stdout_tail: 'ok' } }])

  vi.stubGlobal('confirm', vi.fn(() => true))
  vi.stubGlobal('alert', vi.fn())
  vi.stubGlobal('fetch', vi.fn(async () => makeSseResponse([
    { type: 'session_started', iteration: 0, payload: { session_id: 'sess_1' } },
    { type: 'code', iteration: 0, payload: { code: 'print(1)' } },
    { type: 'run', iteration: 0, payload: { stdout_tail: 'stdout', stderr_tail: '', outputs: [{ filename: 'a.txt' }] } },
    { type: 'done', iteration: 0, payload: { outcome: { ok: true, final_code: 'print(2)' } } },
  ])))
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:script') })
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('AI store view coverage', () => {
  it('covers labels, filters, nav themes, saved state, like, download and attach flows', async () => {
    vi.useFakeTimers()
    routeMock.query = { attachModId: 'mod_1' }
    const wrapper = mount(AiStoreView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any
    const item = vm.items[0]

    expect(vm.artifactLabel('employee_pack')).toBe('AI 员工包')
    expect(vm.artifactLabel('unknown')).toBe('unknown')
    expect(vm.materialCategoryLabel('ai_employee')).toBe('AI 员工')
    expect(vm.licenseScopeLabel('enterprise')).toBe('企业级')
    expect(vm.complianceStatusLabel('under_review')).toBe('投诉处理中')
    expect(vm.securityLabel('confidential')).toBe('保密')
    expect(vm.securityLevelClass('confidential')).toBe('tag-confidential')
    expect(vm.securityLevelClass('enterprise')).toBe('tag-enterprise')
    expect(vm.truncate('abcdef', 3)).toBe('abc…')
    expect(vm.formatSocialCount(12000)).toBe('1.2万')
    expect(vm.formatSocialCount(1300)).toBe('1.3k')

    expect(vm.isItemSaved(item.id)).toBe(false)
    vm.toggleSaved(item)
    expect(vm.isItemSaved(item.id)).toBe(true)

    await vm.toggleLike(item)
    expect(apiMock.catalogToggleFavorite).toHaveBeenCalledWith(10)
    expect(item.favorited).toBe(true)
    expect(item.favorite_count).toBe(3)

    await vm.downloadCard(item)
    expect(apiMock.downloadItem).toHaveBeenCalledWith(10)

    await vm.attachCardToMod(item)
    expect(apiMock.buyItem).toHaveBeenCalledWith(10)
    expect(apiMock.attachCatalogEmployeeToMod).toHaveBeenCalledWith('mod_1', { pkg_id: 'emp_customer_service', catalog_item_id: 10 })
    expect(routerMock.push).toHaveBeenCalledWith({ name: 'mod-authoring', params: { modId: 'mod_1' } })

    vm.setIndustry('retail')
    vm.setArtifact('employee_pack')
    vm.setMaterialCategory('ai_employee')
    vm.setLicenseScope('enterprise')
    vm.setSecurityLevel('enterprise')
    expect(vm.advancedFilterCount).toBeGreaterThan(0)

    vm.applyFilters()
    expect(apiMock.catalog).toHaveBeenCalled()
    vm.resetFilters()
    expect(vm.storeNav).toBe('all')

    vm.setStoreNav('host_foundation')
    expect(vm.activeTheme).toBe('host_foundation')
    vm.setStoreNav('office')
    expect(vm.activeTheme).toBe('office')
    vm.setStoreNav('office_aux')
    expect(vm.activeTheme).toBe('office_aux')
    vm.setStoreNav('workflow')
    expect(vm.activeTheme).toBe('workflow')
    vm.setStoreNav('ai_employee')
    expect(vm.filters.materialCategory).toBe('ai_employee')
    await vi.advanceTimersByTimeAsync(80)
    expect(apiMock.catalog).toHaveBeenCalled()

    expect(vm.customerServiceLink(item, 'refund')).toEqual({
      name: 'customer-service',
      query: expect.objectContaining({ scene: 'refund', catalog_id: '10', pkg_id: 'emp_customer_service' }),
    })
  })

  it('covers AI store unauthenticated and API failure branches', async () => {
    const wrapper = mount(AiStoreView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any
    const item = vm.items[0]

    authMock.isLoggedIn = false
    await vm.toggleLike(item)
    expect(vm.err).toContain('登录')
    await vm.downloadCard(item)
    expect(vm.err).toContain('登录')
    await vm.attachCardToMod(item)
    expect(vm.err).toContain('登录')
    await vm.downloadOfficeBundle()
    expect(vm.err).toContain('登录')
    await vm.downloadWorkflowBundle()
    expect(vm.err).toContain('登录')
    await vm.downloadHostFoundationPack()
    expect(vm.err).toContain('登录')

    authMock.isLoggedIn = true
    apiMock.catalogToggleFavorite.mockRejectedValueOnce(new Error('like failed'))
    await vm.toggleLike(item)
    expect(vm.err).toContain('like failed')
    apiMock.downloadItem.mockRejectedValueOnce(new Error('download failed'))
    await vm.downloadCard(item)
    expect(vm.err).toContain('download failed')

    routeMock.query = { attachModId: 'mod_1' }
    const attachWrapper = mount(AiStoreView, globalMount)
    await flushPromises()
    const attachVm = attachWrapper.vm as any
    apiMock.attachCatalogEmployeeToMod.mockRejectedValueOnce(new Error('attach failed'))
    await attachVm.attachCardToMod(attachVm.items[0])
    expect(attachVm.err).toContain('attach failed')
    attachWrapper.unmount()

    apiMock.catalogFacets.mockRejectedValueOnce(new Error('facets failed'))
    await vm.loadFacets()
    expect(vm.facets.industries).toEqual([])

    apiMock.catalog.mockRejectedValueOnce(new Error('catalog failed'))
    await vm.loadItems()
    expect(vm.err).toContain('catalog failed')

    apiMock.downloadOfficeEmployeePack.mockRejectedValueOnce(new Error('office failed'))
    await vm.downloadOfficeBundle()
    expect(vm.err).toContain('office failed')
    apiMock.downloadWorkflowEmployeePack.mockRejectedValueOnce(new Error('workflow failed'))
    await vm.downloadWorkflowBundle()
    expect(vm.err).toContain('workflow failed')
    apiMock.downloadHostFoundationEmployeePack.mockRejectedValueOnce(new Error('host failed'))
    await vm.downloadHostFoundationPack()
    expect(vm.err).toContain('host failed')
  })

  it('covers AI store delist guard, cancel, success and failure branches', async () => {
    const wrapper = mount(AiStoreView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any
    const item = vm.items[0]

    ensureAdminDigestUnlockedMock.mockResolvedValueOnce(false)
    await vm.delistItem(item)
    expect(apiMock.adminDeleteCatalog).not.toHaveBeenCalled()

    ensureAdminDigestUnlockedMock.mockResolvedValueOnce(true)
    ;(window.confirm as any).mockReturnValueOnce(false)
    await vm.delistItem(item)
    expect(apiMock.adminDeleteCatalog).not.toHaveBeenCalled()

    ;(window.confirm as any).mockReturnValueOnce(true)
    await vm.delistItem(item)
    expect(apiMock.adminDeleteCatalog).toHaveBeenCalledWith(10)

    apiMock.adminDeleteCatalog.mockRejectedValueOnce(new Error('delist failed'))
    await vm.delistItem(item)
    expect(vm.err).toContain('delist failed')
  })

  it('covers AI store attach guards, pack grouping, filtered loads and throttled errors', async () => {
    routeMock.query = { attachModId: 'mod_1' }
    const wrapper = mount(AiStoreView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any

    authMock.isLoggedIn = false
    await vm.attachCardToMod(vm.items[0])
    expect(vm.err).toContain('登录')

    authMock.isLoggedIn = true
    await vm.attachCardToMod({ ...vm.items[0], artifact: 'workflow' })
    expect(vm.err).toContain('AI 员工包')

    vm.items = [
      storeItem({ id: 101, pkg_id: 'word-full-read-employee', name: 'Word 读取员' }),
      storeItem({ id: 102, pkg_id: 'json-report-employee', name: 'JSON 报告员' }),
      storeItem({ id: 103, pkg_id: 'emp_customer_service', name: '客服员工' }),
    ]
    vm.setStoreNav('office')
    expect(vm.displayGroups.some((g: { items: unknown[] }) => g.items.length)).toBe(true)
    vm.setStoreNav('office_aux')
    expect(vm.displayGroups.some((g: { items: unknown[] }) => g.items.length)).toBe(true)

    apiMock.catalog.mockResolvedValueOnce({
      items: [
        storeItem({ id: 201, pkg_id: 'word-full-read-employee' }),
        storeItem({ id: 202, pkg_id: 'emp_customer_service' }),
      ],
      total: 2,
    })
    vm.setStoreNav('office')
    await vm.loadItems()
    expect(vm.items.map((it: { pkg_id: string }) => it.pkg_id)).toEqual(['word-full-read-employee'])

    apiMock.catalog.mockResolvedValueOnce({
      items: [
        storeItem({ id: 301, pkg_id: 'json-report-employee' }),
        storeItem({ id: 302, pkg_id: 'word-full-read-employee' }),
      ],
      total: 2,
    })
    vm.setStoreNav('office_aux')
    await vm.loadItems()
    expect(vm.items.map((it: { pkg_id: string }) => it.pkg_id)).toEqual(['json-report-employee'])
    expect(vm.officeAuxNavBadge).toBe('1')

    apiMock.catalog.mockRejectedValueOnce(new Error('badge down'))
    await vm.refreshOfficeAuxNavBadge()
    expect(vm.officeAuxNavBadge).toBe('0')

    apiMock.catalog.mockRejectedValueOnce(new ApiError('too many', 429))
    await vm.loadItems()
    expect(vm.err).toContain('请求过于频繁')
  })
})

describe('script workflow composer coverage', () => {
  it('covers brief helpers, file inputs, event handling and SSE loop', async () => {
    const wrapper = mount(ScriptWorkflowComposerView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any

    expect(vm.stageRank).toBe(1)
    expect(vm.headTitle).toBe('新建脚本工作流')
    for (const key of ['sales_summary', 'contract_extract', 'data_clean', 'feishu_post']) {
      vm.applyTemplate(key)
      expect(vm.brief.goal).toBeTruthy()
    }
    expect(vm.briefHints.goal).toBe('')

    const file = new File(['a'], 'a.csv')
    const input = document.createElement('input')
    await vm.onFilesPicked({ target: Object.assign(input, { files: [file] }) })
    expect(vm.uploadedFiles).toHaveLength(1)
    expect(vm.brief.inputs[0].filename).toBe('a.csv')
    vm.removeFile(0)
    expect(vm.uploadedFiles).toHaveLength(0)
    await vm.onSandboxFilesPicked({ target: Object.assign(document.createElement('input'), { files: [file] }) })
    expect(vm.sandboxFiles).toHaveLength(1)

    expect(vm.planMdHasMermaid('```mermaid\na-->b\n```')).toBe(true)
    expect(vm.mermaidExcerpt('```mermaid\na-->b\n```')).toBe('a-->b')
    expect(vm.humanSize(512)).toBe('512B')
    expect(vm.humanSize(2048)).toContain('K')
    expect(vm.humanSize(2 * 1024 * 1024)).toContain('M')
    expect(vm.trimCode('x'.repeat(3100))).toContain('…')
    expect(vm.tail('abcdef', 3)).toBe('def')
    expect(vm.eventLabel({ type: 'code', iteration: 1, payload: {} })).toContain('第 2 轮')

    vm.handleEvent({ type: 'session_started', iteration: 0, payload: { session_id: 'manual_sess' } })
    expect(vm.sessionId).toBe('manual_sess')
    vm.handleEvent({ type: 'run', iteration: 0, payload: { stdout_tail: 'stdout', outputs: [{ filename: 'x' }] } })
    expect(vm.tab).toBe('output')
    vm.handleEvent({ type: 'done', iteration: 0, payload: { outcome: { ok: true }, code: 'final' } })
    expect(vm.loopRunning).toBe(false)
    expect(vm.currentCode).toBe('final')
    expect(vm.lastRun.type).toBe('run')
    expect(vm.runStdout).toBe('stdout')
    expect(vm.runOutputs).toHaveLength(1)

    await vm.startAgentLoop()
    expect(fetch).toHaveBeenCalledWith('/api/script-workflows/sessions', expect.objectContaining({ method: 'POST' }))
    expect(vm.sessionId).toBe('sess_1')
    expect(vm.outcome.ok).toBe(true)
  })

  it('covers script workflow feedback, commit, sandbox, download, activate and navigation', async () => {
    vi.useFakeTimers()
    const wrapper = mount(ScriptWorkflowComposerView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any

    vm.workflowId = 22
    await vm.startEditWithAi('improve')
    expect(fetch).toHaveBeenCalledWith('/api/script-workflows/22/edit-with-ai', expect.objectContaining({ method: 'POST' }))

    vm.feedback = 'feedback text'
    vm.sessionId = ''
    await vm.submitFeedback()
    expect(fetch).toHaveBeenCalledWith('/api/script-workflows/22/edit-with-ai', expect.any(Object))

    vm.sessionId = 'sess_1'
    vm.feedback = 'more'
    await vm.submitFeedback()
    expect(fetch).toHaveBeenCalledWith('/api/script-workflows/sessions/sess_1/feedback', expect.objectContaining({ method: 'POST' }))

    vm.workflowName = 'Committed Workflow'
    await vm.commitToWorkflow()
    expect(apiMock.commitScriptWorkflowSession).toHaveBeenCalledWith('sess_1', { name: 'Committed Workflow', schema_in: {} })
    expect(vm.stage).toBe('sandbox')
    expect(vm.canActivate).toBe(false)

    await vm.runManualSandbox()
    expect(apiMock.sandboxRunScriptWorkflow).toHaveBeenCalledWith(22, vm.sandboxFiles)
    expect(vm.canActivate).toBe(true)

    await vm.downloadSandboxOutput({ filename: 'out.json' })
    expect(apiMock.downloadScriptWorkflowRunFile).toHaveBeenCalledWith(22, 33, 'out.json')
    expect(URL.createObjectURL).toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(4000)
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:script')

    await vm.activate()
    expect(routerMock.push).toHaveBeenCalledWith({ name: 'workbench-script-workflow-detail', params: { id: 22 } })
    vm.goList()
    expect(routerMock.push).toHaveBeenCalledWith({ name: 'workbench-script-workflows' })
  })

  it('covers script workflow API and SSE error branches', async () => {
    const wrapper = mount(ScriptWorkflowComposerView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any

    ;(fetch as any).mockResolvedValueOnce({ ok: false, status: 500, body: null, text: vi.fn(async () => 'bad') })
    await vm.startAgentLoop()
    expect(vm.events.at(-1).payload.reason).toContain('HTTP 500')

    vm.workflowId = 22
    ;(fetch as any).mockRejectedValueOnce(new Error('sse failed'))
    await vm.startEditWithAi('bad')
    expect(vm.events.at(-1).payload.reason).toContain('sse failed')

    vm.sessionId = 'sess_1'
    vm.workflowName = 'Bad'
    apiMock.commitScriptWorkflowSession.mockRejectedValueOnce(new Error('commit failed'))
    await vm.commitToWorkflow()
    expect(window.alert).toHaveBeenCalledWith(expect.stringContaining('commit failed'))

    apiMock.sandboxRunScriptWorkflow.mockRejectedValueOnce(new Error('sandbox failed'))
    await vm.runManualSandbox()
    expect(window.alert).toHaveBeenCalledWith(expect.stringContaining('sandbox failed'))

    vm.lastSandboxRun = { id: 99 }
    apiMock.downloadScriptWorkflowRunFile.mockRejectedValueOnce(new Error('download failed'))
    await vm.downloadSandboxOutput({ filename: 'bad.txt' })
    expect(window.alert).toHaveBeenCalledWith(expect.stringContaining('download failed'))

    apiMock.activateScriptWorkflow.mockRejectedValueOnce(new Error('activate failed'))
    await vm.activate()
    expect(window.alert).toHaveBeenCalledWith(expect.stringContaining('activate failed'))
  })

  it('covers script workflow edit-mode mount', async () => {
    routeMock.params = { id: '44' }
    const wrapper = mount(ScriptWorkflowComposerView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.headTitle).toBe('改进脚本工作流')
    expect(apiMock.getScriptWorkflow).toHaveBeenCalledWith('44')
    expect(vm.workflowId).toBe(44)
    expect(vm.workflowName).toBe('Existing Workflow')
    expect(vm.lastSandboxRun.id).toBe(55)
    expect(vm.currentCode).toBe('print("ok")')

    apiMock.getScriptWorkflow.mockRejectedValueOnce(new Error('load failed'))
    mount(ScriptWorkflowComposerView, globalMount)
    await flushPromises()
    expect(window.alert).toHaveBeenCalledWith(expect.stringContaining('load failed'))
  })
})
