import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  paymentPlans: vi.fn(),
  paymentMyPlan: vi.fn(),
  paymentCheckout: vi.fn(),
  templatesCategories: vi.fn(),
  templatesList: vi.fn(),
  templateInstall: vi.fn(),
  templateDetail: vi.fn(),
  adminYuangonOnboardStatus: vi.fn(),
  adminYuangonOnboardRun: vi.fn(),
  adminAlignEmployeeLlmToAuto: vi.fn(),
  adminDutyGraphHealth: vi.fn(),
  opsOrchestrateAsync: vi.fn(),
  adminChangeRequestsList: vi.fn(),
  adminChangeRequestApprove: vi.fn(),
  adminChangeRequestReject: vi.fn(),
  me: vi.fn(),
  adminEnterpriseAssignableMods: vi.fn(),
  adminListUserMods: vi.fn(),
  adminBindUserMod: vi.fn(),
  adminUnbindUserMod: vi.fn(),
  adminSetUserEnterprise: vi.fn(),
  refundsAdminPending: vi.fn(),
  adminListUsers: vi.fn(),
  adminListWallets: vi.fn(),
  adminListCatalog: vi.fn(),
  adminListTransactions: vi.fn(),
  refundsAdminReview: vi.fn(),
}))

const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
}))

const routeMock = vi.hoisted(() => ({
  params: { id: '42' },
  query: { employee: 'emp_route', redirect: '/console' },
  fullPath: '/templates/42',
}))

const authMock = vi.hoisted(() => ({
  isAdmin: true,
  hasToken: vi.fn(() => true),
  refreshMembership: vi.fn(),
  loginWithPassword: vi.fn(),
}))

const graphOpenGapMock = vi.hoisted(() => vi.fn())

vi.mock('./api', () => ({ api: apiMock }))
vi.mock('./stores/auth', () => ({ useAuthStore: () => authMock }))
vi.mock('pinia', () => ({
  storeToRefs: (store: Record<string, unknown>) =>
    Object.fromEntries(
      Object.entries(store)
        .filter(([, value]) => typeof value !== 'function')
        .map(([key, value]) => [key, { value }]),
    ),
}))
vi.mock('vue-router', () => ({
  useRouter: () => routerMock,
  useRoute: () => routeMock,
}))
vi.mock('./authPaths', () => ({
  pickRedirectFromRoute: vi.fn(() => '/console'),
}))
vi.mock('./i18n', () => ({
  useI18n: () => ({
    t: (key: string, params?: Record<string, unknown>) => (params ? `${key}:${JSON.stringify(params)}` : key),
  }),
}))
vi.mock('./components/admin/AdminDutyEmployeeGraph.vue', () => ({
  default: {
    name: 'AdminDutyEmployeeGraph',
    methods: { openGapPanel: graphOpenGapMock },
    template: '<section class="graph-stub"><slot name="pageActions" /></section>',
  },
}))

import PaymentPlansView from './views/public/PaymentPlansView.vue'
import LoginView from './views/public/LoginView.vue'
import TemplatesView from './views/templates/TemplatesView.vue'
import TemplateDetailView from './views/templates/TemplateDetailView.vue'
import AdminYuangonOnboardView from './views/AdminYuangonOnboardView.vue'
import AdminDutyEmployeesView from './views/AdminDutyEmployeesView.vue'
import AdminEmployeeChangeRequestsView from './views/AdminEmployeeChangeRequestsView.vue'
import AdminDatabaseView from './views/AdminDatabaseView.vue'

const globalMount = {
  global: {
    stubs: {
      RouterLink: { props: ['to'], template: '<a><slot /></a>' },
      Teleport: true,
      Transition: false,
      TransitionGroup: false,
    },
  },
}

function plan(id: string, price = 10, extra: Record<string, unknown> = {}) {
  return {
    id,
    name: id,
    price,
    description: `${id} plan`,
    features: ['feature'],
    ...extra,
  }
}

function templateItem(overrides: Record<string, unknown> = {}) {
  return {
    id: 42,
    pkg_id: 'tpl_pkg',
    name: 'Template',
    description: 'desc',
    version: '1.0.0',
    price: 0,
    industry: 'retail',
    template_category: 'sales',
    template_difficulty: 'easy',
    difficulty_label: 'Easy',
    install_count: 9,
    created_at: '2026-01-02T03:04:05Z',
    ...overrides,
  }
}

function crRow(overrides: Record<string, unknown> = {}) {
  return {
    id: 3,
    source_employee_id: 'emp_a',
    change_kind: 'patch',
    diff_summary: 'summary',
    diff_blob: 'diff',
    status: 'pending',
    risk_level: 'low',
    created_at: '2026-01-02T03:04:05Z',
    target_paths: ['src/a.ts'],
    ...overrides,
  }
}

function dbUser(overrides: Record<string, unknown> = {}) {
  return {
    id: 8,
    username: 'alice',
    email: 'alice@example.test',
    is_admin: false,
    is_enterprise: true,
    mod_ids: ['mod_old'],
    created_at: '2026-01-02T03:04:05Z',
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
  authMock.hasToken.mockReturnValue(true)
  authMock.refreshMembership.mockResolvedValue(undefined)
  authMock.loginWithPassword.mockResolvedValue(undefined)
  routeMock.params = { id: '42' }
  routeMock.query = { employee: 'emp_route', redirect: '/console' }

  apiMock.paymentPlans.mockResolvedValue({
    plans: [
      plan('plan_basic', 0),
      plan('plan_pro', 49),
      plan('plan_enterprise', 199),
      plan('plan_svip2', 299, { requires_plan: 'plan_enterprise' }),
      plan('unknown_x', 9),
    ],
  })
  apiMock.paymentMyPlan.mockResolvedValue({ plan: plan('plan_enterprise', 199) })
  apiMock.paymentCheckout.mockResolvedValue({ ok: true, type: 'precreate', order_id: 'ord_1' })

  apiMock.templatesCategories.mockResolvedValue({
    categories: [{ name: 'sales', count: 2 }],
    difficulties: { easy: 'Easy', hard: 'Hard' },
  })
  apiMock.templatesList.mockResolvedValue({ items: [templateItem()], total: 1 })
  apiMock.templateInstall.mockResolvedValue({ workflow_id: 777 })
  apiMock.templateDetail.mockResolvedValue({
    ...templateItem(),
    graph: {
      name: 'Graph',
      description: 'graph desc',
      nodes: [{ local_id: 1, node_type: 'employee', name: 'Employee', config: {}, position_x: 0, position_y: 0 }],
      edges: [{ source_local_id: 1, target_local_id: 2, condition: 'ok' }],
      node_count: 1,
      edge_count: 1,
    },
  })

  apiMock.adminYuangonOnboardStatus.mockResolvedValue({
    repo_root: '/repo',
    yuangon_employee_count: 2,
    catalog_employee_pack_count: 1,
    missing_in_catalog: ['emp_missing'],
    parse_errors: ['bad manifest'],
    yuangon_pkg_ids: ['emp_a'],
  })
  apiMock.adminYuangonOnboardRun.mockResolvedValue({ ok: true, exit_code: 0, stdout_tail: 'ok', stderr_tail: '' })

  apiMock.adminAlignEmployeeLlmToAuto.mockResolvedValue({ updated_count: 2, skipped_count: 1, error_count: 0 })
  apiMock.adminDutyGraphHealth.mockResolvedValue({
    staffing: {
      planned_count: 3,
      registered_count: 2,
      missing_employees: ['emp_missing'],
      extra_employees: [],
      areas: [{ key: 'sales', label: 'Sales', missing: ['emp_missing'] }],
    },
    employee_cron_jobs: [{ employee_id: 'emp_a', next_run_time: null }],
    change_requests: { pending: 4, failed: 1 },
    incident_unknown_24h: 2,
    env_flags: { A: '1' },
  })
  apiMock.opsOrchestrateAsync.mockResolvedValue({ ok: true, job_id: 'job_1' })

  apiMock.adminChangeRequestsList.mockResolvedValue({ items: [crRow()] })
  apiMock.adminChangeRequestApprove.mockResolvedValue({
    git_suggestions: ['git diff'],
    post_apply_pytest: { ok: true },
  })
  apiMock.adminChangeRequestReject.mockResolvedValue({})

  apiMock.me.mockResolvedValue({ is_admin: true })
  apiMock.adminEnterpriseAssignableMods.mockResolvedValue({ mods: [{ id: 'mod_new', name: 'New Mod' }, { id: 'mod_old', name: 'Old Mod' }] })
  apiMock.adminListUserMods.mockResolvedValue({ mod_ids: ['mod_old'] })
  apiMock.adminBindUserMod.mockResolvedValue({})
  apiMock.adminUnbindUserMod.mockResolvedValue({})
  apiMock.adminSetUserEnterprise.mockResolvedValue({})
  apiMock.refundsAdminPending.mockResolvedValue({
    refunds: [{ id: 9, user_id: 8, order_no: 'R1', amount: 12, reason: 'reason', created_at: '2026-01-02T03:04:05Z' }],
  })
  apiMock.adminListUsers.mockResolvedValue({ users: [dbUser(), dbUser({ id: 9, username: 'bob', is_enterprise: false, mod_ids: [] })] })
  apiMock.adminListWallets.mockResolvedValue({ items: [{ id: 1, user_id: 8, balance: 12, updated_at: '2026-01-02T03:04:05Z' }] })
  apiMock.adminListCatalog.mockResolvedValue({ items: [{ id: 1, name: 'Pack', pkg_id: 'pkg', version: '1', price: 0, downloads: 3, created_at: '2026-01-02T03:04:05Z' }] })
  apiMock.adminListTransactions.mockResolvedValue({ items: [{ id: 1, user_id: 8, amount: -3, txn_type: 'pay', status: 'completed', description: 'desc', created_at: '2026-01-02T03:04:05Z' }] })
  apiMock.refundsAdminReview.mockResolvedValue({})

  vi.stubGlobal('confirm', vi.fn(() => true))
  vi.stubGlobal('alert', vi.fn())
  vi.stubGlobal('prompt', vi.fn(() => 'note'))
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('low coverage public and template views, round 3', () => {
  it('covers payment plans loading, tier helpers, reveal and checkout branches', async () => {
    vi.useFakeTimers()
    sessionStorage.setItem('modstore_svip_ladder_reveal', '1')
    const wrapper = mount(PaymentPlansView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any

    expect(vm.hasSvipTier).toBe(true)
    expect(vm.visiblePlans.map((p: any) => p.id)).toContain('plan_svip2')
    expect(vm.planTierOrder('plan_svip8')).toBe(9)
    expect(vm.planTierOrder('missing')).toBe(-1)
    expect(vm.tierOf({ id: 'plan_basic' })).toBe('vip')
    expect(vm.tierOf({ id: 'plan_pro' })).toBe('vip_plus')
    expect(vm.tierOf({ id: 'plan_enterprise' })).toBe('svip1')
    expect(vm.tierOf({ id: 'plan_svip7' })).toBe('svip7')
    expect(vm.tierOf({ id: 'custom' })).toBe('free')
    expect(vm.isSvipLadderPlan({ id: 'plan_svip2' })).toBe(true)
    expect(vm.svipLadderStaggerDelay({ id: 'plan_svip4' })).toBe('0.14s')
    expect(vm.isCurrent({ id: 'plan_enterprise' })).toBe(true)
    expect(vm.isBelowMyPlan({ id: 'plan_basic' })).toBe(true)
    await vi.advanceTimersByTimeAsync(2300)
    expect(vm.svipLadderRevealPop).toBe(true)

    authMock.hasToken.mockReturnValue(false)
    vm.myPlan = null
    await vm.handleBuy({ id: 'plan_pro' })
    expect(routerMock.push).toHaveBeenCalledWith({ name: 'login', query: { redirect: '/plans' } })

    authMock.hasToken.mockReturnValue(true)
    apiMock.paymentCheckout.mockResolvedValueOnce({ ok: false, message: 'bad order' })
    await vm.handleBuy({ id: 'plan_pro' })
    expect(vm.errorMsg).toContain('bad order')

    apiMock.paymentCheckout.mockResolvedValueOnce({ ok: true, type: 'precreate', order_id: 'ord_2' })
    await vm.handleBuy({ id: 'plan_pro' })
    expect(routerMock.push).toHaveBeenCalledWith({ name: 'checkout', params: { orderId: 'ord_2' } })

    apiMock.paymentCheckout.mockResolvedValueOnce({ ok: true, type: 'mystery' })
    await vm.handleBuy({ id: 'plan_pro' })
    expect(vm.errorMsg).toContain('未知')

    apiMock.paymentCheckout.mockRejectedValueOnce(new Error('checkout failed'))
    await vm.handleBuy({ id: 'plan_pro' })
    expect(vm.errorMsg).toContain('checkout failed')
    wrapper.unmount()
  })

  it('covers payment plans load failure and no-token my-plan branch', async () => {
    authMock.hasToken.mockReturnValue(false)
    apiMock.paymentPlans.mockRejectedValueOnce(new Error('plans failed'))
    const wrapper = mount(PaymentPlansView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.errorMsg).toContain('plans failed')
    expect(apiMock.paymentMyPlan).not.toHaveBeenCalled()
  })

  it('covers password login success and failure', async () => {
    const wrapper = mount(LoginView, globalMount)
    const vm = wrapper.vm as any
    vm.username = 'alice'
    vm.password = 'secret'
    await vm.doLogin()
    expect(authMock.loginWithPassword).toHaveBeenCalledWith('alice', 'secret')
    expect(routerMock.replace).toHaveBeenCalledWith('/console')

    authMock.loginWithPassword.mockRejectedValueOnce(new Error('login failed'))
    await vm.doLogin()
    expect(vm.err).toContain('login failed')
  })

  it('covers template list filters, debounced search, install, navigation and errors', async () => {
    vi.useFakeTimers()
    const wrapper = mount(TemplatesView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any
    const item = vm.items[0]

    expect(vm.totalCount).toBe(1)
    vm.pickCategory('sales')
    expect(vm.filters.category).toBe('sales')
    vm.pickCategory('sales')
    expect(vm.filters.category).toBe('')
    expect(vm.difficultyLabel('easy')).toBe('Easy')
    expect(vm.difficultyLabel('unknown')).toBe('unknown')

    vm.openDetail(item)
    expect(routerMock.push).toHaveBeenCalledWith({ name: 'template-detail', params: { id: '42' } })

    ;(window.confirm as any).mockReturnValueOnce(false)
    await vm.quickInstall(item)
    expect(apiMock.templateInstall).not.toHaveBeenCalled()

    ;(window.confirm as any).mockReturnValueOnce(true)
    await vm.quickInstall(item)
    expect(routerMock.push).toHaveBeenCalledWith({ name: 'workflow-v2-editor', params: { id: '777' } })

    apiMock.templateInstall.mockResolvedValueOnce({})
    await vm.quickInstall(item)
    expect(window.alert).toHaveBeenCalledWith(expect.stringContaining('workflow_id'))

    apiMock.templateInstall.mockRejectedValueOnce(new Error('install failed'))
    await vm.quickInstall(item)
    expect(window.alert).toHaveBeenCalledWith(expect.stringContaining('install failed'))

    vm.filters.q = 'abc'
    await vi.advanceTimersByTimeAsync(300)
    expect(apiMock.templatesList).toHaveBeenCalled()

    apiMock.templatesCategories.mockRejectedValueOnce(new Error('category failed'))
    await vm.loadCategories()
    expect(vm.categories).toEqual([])

    apiMock.templatesList.mockRejectedValueOnce(new Error('list failed'))
    await vm.loadList()
    expect(vm.errMsg).toContain('list failed')
    wrapper.unmount()
  })

  it('covers template detail load, node labels, install and error paths', async () => {
    const wrapper = mount(TemplateDetailView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any
    expect(apiMock.templateDetail).toHaveBeenCalledWith(42)
    expect(vm.nodeKindLabel('employee')).toBe('AI 员工')
    expect(vm.nodeKindLabel('custom')).toBe('custom')

    ;(window.confirm as any).mockReturnValueOnce(false)
    await vm.install()
    expect(apiMock.templateInstall).not.toHaveBeenCalled()

    ;(window.confirm as any).mockReturnValueOnce(true)
    await vm.install()
    expect(routerMock.push).toHaveBeenCalledWith({ name: 'workflow-v2-editor', params: { id: '777' } })

    apiMock.templateInstall.mockRejectedValueOnce(new Error('install failed'))
    await vm.install()
    expect(vm.errMsg).toContain('install failed')

    apiMock.templateDetail.mockRejectedValueOnce(new Error('detail failed'))
    await vm.load()
    expect(vm.errMsg).toContain('detail failed')
  })

  it('covers template detail empty route id branch', async () => {
    routeMock.params = { id: '0' }
    const wrapper = mount(TemplateDetailView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.templateId).toBe(0)
    expect(apiMock.templateDetail).not.toHaveBeenCalled()
  })
})

describe('low coverage admin views, round 3', () => {
  it('covers Yuangon status and dry-run/run flows', async () => {
    const wrapper = mount(AdminYuangonOnboardView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.status.repo_root).toBe('/repo')

    vm.pkgIds = 'emp_a,emp_b'
    await vm.runScript(true)
    expect(apiMock.adminYuangonOnboardRun).toHaveBeenCalledWith({
      dry_run: true,
      force: false,
      pkg_ids: 'emp_a,emp_b',
    })
    await vm.runScript(false)
    expect(apiMock.adminYuangonOnboardRun).toHaveBeenCalledWith({
      dry_run: false,
      force: true,
      pkg_ids: 'emp_a,emp_b',
    })

    apiMock.adminYuangonOnboardRun.mockRejectedValueOnce(new Error('run failed'))
    await vm.runScript(true)
    expect(vm.error).toContain('run failed')

    apiMock.adminYuangonOnboardStatus.mockRejectedValueOnce(new Error('status failed'))
    await vm.loadStatus()
    expect(vm.error).toContain('status failed')
  })

  it('covers Yuangon non-admin early returns', async () => {
    authMock.isAdmin = false
    const wrapper = mount(AdminYuangonOnboardView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any
    await vm.loadStatus()
    await vm.runScript(true)
    expect(apiMock.adminYuangonOnboardStatus).not.toHaveBeenCalled()
    expect(apiMock.adminYuangonOnboardRun).not.toHaveBeenCalled()
  })

  it('covers duty employee health, align, dispatch, menu and document click flows', async () => {
    const wrapper = mount(AdminDutyEmployeesView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any

    expect(vm.missingCount).toBe(1)
    expect(vm.cronCount).toBe(1)
    expect(vm.pendingCr).toBe(4)
    expect(vm.failedCr).toBe(1)
    expect(vm.unknownEvents).toBe(2)
    expect(vm.desktopDutyUrl).toContain('emp_route')

    await vm.runAlignLlm(true)
    expect(vm.alignMsg).toContain('预览')
    await vm.runAlignLlm(false)
    expect(vm.alignMsg).toContain('已完成')

    await vm.submitDispatch()
    expect(apiMock.opsOrchestrateAsync).not.toHaveBeenCalled()
    vm.dispatchTask = 'ship this task'
    vm.dispatchAllowHighRisk = true
    await vm.submitDispatch()
    expect(apiMock.opsOrchestrateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        task_description: 'ship this task',
        allow_high_risk_real_run: true,
        dispatch_source: 'web',
      }),
    )
    expect(vm.dispatchOpen).toBe(false)

    vm.toggleMore()
    expect(vm.moreOpen).toBe(true)
    document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    expect(vm.moreOpen).toBe(false)

    vm.openMissingGapPanel()
    expect(graphOpenGapMock).toHaveBeenCalled()
  })

  it('covers duty employee error branches and non-admin mount', async () => {
    apiMock.adminDutyGraphHealth.mockRejectedValueOnce(new Error('health failed'))
    const wrapper = mount(AdminDutyEmployeesView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.healthErr).toContain('health failed')

    apiMock.adminAlignEmployeeLlmToAuto.mockRejectedValueOnce(new Error('align failed'))
    await vm.runAlignLlm(true)
    expect(vm.alignMsg).toContain('align failed')

    apiMock.opsOrchestrateAsync.mockResolvedValueOnce({ ok: false })
    vm.dispatchTask = 'bad dispatch'
    await vm.submitDispatch()
    expect(vm.dispatchMsg).toContain('派发失败')

    apiMock.opsOrchestrateAsync.mockRejectedValueOnce(new Error('dispatch failed'))
    vm.dispatchTask = 'bad dispatch'
    await vm.submitDispatch()
    expect(vm.dispatchMsg).toContain('dispatch failed')

    authMock.isAdmin = false
    mount(AdminDutyEmployeesView, globalMount)
    await flushPromises()
  })

  it('covers change request list, detail, approve, reject and errors', async () => {
    const wrapper = mount(AdminEmployeeChangeRequestsView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.items).toHaveLength(1)
    expect(vm.formatBlob('x'.repeat(13000))).toContain('…')

    vm.openDetail(vm.items[0])
    expect(vm.drawerOpen).toBe(true)
    await vm.approve()
    expect(apiMock.adminChangeRequestApprove).toHaveBeenCalledWith(3)
    expect(vm.approveExtras.git_suggestions).toEqual(['git diff'])

    vm.approveExtras = null
    vm.openDetail(crRow({ id: 4 }))
    ;(window.prompt as any).mockReturnValueOnce('not safe')
    await vm.reject()
    expect(apiMock.adminChangeRequestReject).toHaveBeenCalledWith(4, { reason: 'not safe' })

    apiMock.adminChangeRequestsList.mockRejectedValueOnce(new Error('list failed'))
    await vm.load()
    expect(vm.error).toContain('list failed')

    vm.openDetail(crRow({ id: 5 }))
    apiMock.adminChangeRequestApprove.mockRejectedValueOnce(new Error('approve failed'))
    await vm.approve()
    expect(vm.error).toContain('approve failed')

    vm.openDetail(crRow({ id: 6 }))
    apiMock.adminChangeRequestReject.mockRejectedValueOnce(new Error('reject failed'))
    await vm.reject()
    expect(vm.error).toContain('reject failed')

    vm.closeDrawer()
    expect(vm.selected).toBeNull()
  })

  it('covers change request non-admin early returns', async () => {
    authMock.isAdmin = false
    const wrapper = mount(AdminEmployeeChangeRequestsView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any
    await vm.load()
    expect(apiMock.adminChangeRequestsList).not.toHaveBeenCalled()
  })

  it('covers admin database load, filters, mod assignment, enterprise toggles and refund review', async () => {
    const wrapper = mount(AdminDatabaseView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any

    expect(vm.isAdmin).toBe(true)
    expect(vm.dbUsers).toHaveLength(2)
    expect(vm.enterpriseUserCount).toBe(1)
    vm.setUserFilter('enterprise')
    expect(vm.filteredUsers).toHaveLength(1)
    vm.setUserFilter('non-enterprise')
    expect(vm.filteredUsers).toHaveLength(1)
    vm.setUserFilter('all')
    expect(vm.filteredUsers).toHaveLength(2)
    expect(vm.modDisplayName('mod_new')).toBe('New Mod')
    expect(vm.modDisplayName('missing_mod')).toBe('missing_mod')
    expect(vm.formatTime(undefined)).toBe('—')
    expect(vm.formatTime('2026-01-02T03:04:05Z')).toBeTruthy()

    await vm.openModEditor(dbUser({ id: 9, is_enterprise: false }))
    expect(vm.messageOk).toBe(false)

    await vm.openModEditor(dbUser())
    expect(vm.modEditorOpen).toBe(true)
    expect(vm.modEditorSelected).toEqual(['mod_old'])
    vm.modEditorSelected = ['mod_old']
    await vm.saveModEditor()
    expect(apiMock.adminBindUserMod).not.toHaveBeenCalled()

    await vm.openModEditor(dbUser())
    vm.modEditorSelected = ['mod_new']
    await vm.saveModEditor()
    expect(apiMock.adminBindUserMod).toHaveBeenCalledWith(8, 'mod_new')
    expect(apiMock.adminUnbindUserMod).toHaveBeenCalledWith(8, 'mod_old')

    ;(window.confirm as any).mockReturnValueOnce(false)
    await vm.toggleEnterprise(dbUser({ id: 9, username: 'bob', is_enterprise: false }), true)
    expect(apiMock.adminSetUserEnterprise).not.toHaveBeenCalled()
    ;(window.confirm as any).mockReturnValueOnce(true)
    await vm.toggleEnterprise(dbUser({ id: 9, username: 'bob', is_enterprise: false }), true)
    expect(apiMock.adminSetUserEnterprise).toHaveBeenCalledWith(9, true)

    ;(window.prompt as any).mockReturnValueOnce(null)
    await vm.reviewRefund({ id: 9 }, 'approve')
    expect(apiMock.refundsAdminReview).not.toHaveBeenCalled()
    ;(window.prompt as any).mockReturnValueOnce('ok')
    await vm.reviewRefund({ id: 9 }, 'reject')
    expect(apiMock.refundsAdminReview).toHaveBeenCalledWith(9, 'reject', 'ok')
  })

  it('covers admin database partial load and action error branches', async () => {
    const wrapper = mount(AdminDatabaseView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any

    apiMock.adminListWallets.mockRejectedValueOnce(new Error('wallet failed'))
    await vm.loadDatabase()
    expect(vm.message).toContain('wallet failed')
    expect(vm.messageOk).toBe(false)

    apiMock.adminListUserMods.mockRejectedValueOnce(new Error('mods failed'))
    await vm.openModEditor(dbUser())
    expect(vm.message).toContain('mods failed')

    await vm.openModEditor(dbUser())
    apiMock.adminBindUserMod.mockRejectedValueOnce(new Error('bind failed'))
    vm.modEditorSelected = ['mod_new']
    await vm.saveModEditor()
    expect(vm.message).toContain('bind failed')

    apiMock.adminSetUserEnterprise.mockRejectedValueOnce(new Error('enterprise failed'))
    await vm.toggleEnterprise(dbUser({ id: 9, username: 'bob', is_enterprise: false }), true)
    expect(vm.message).toContain('enterprise failed')

    apiMock.refundsAdminReview.mockRejectedValueOnce(new Error('refund failed'))
    await vm.reviewRefund({ id: 9 }, 'approve')
    expect(vm.message).toContain('refund failed')
  })

  it('covers admin database login redirect branch', async () => {
    apiMock.me.mockRejectedValueOnce(new Error('not logged in'))
    mount(AdminDatabaseView, globalMount)
    await flushPromises()
    expect(routerMock.push).toHaveBeenCalledWith('/login')
  })
})
