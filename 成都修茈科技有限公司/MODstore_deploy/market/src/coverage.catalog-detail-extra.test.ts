import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  catalogDetail: vi.fn(),
  catalogReviews: vi.fn(),
  catalogQuality: vi.fn(),
  catalogToggleFavorite: vi.fn(),
  catalogSubmitReview: vi.fn(),
  catalogSubmitComplaint: vi.fn(),
  getEmployeeStatus: vi.fn(),
  buyItem: vi.fn(),
  paymentCheckout: vi.fn(),
  downloadItem: vi.fn(),
  adminDeleteCatalog: vi.fn(),
}))

const routeMock = vi.hoisted(() => ({
  params: { id: '10' } as Record<string, unknown>,
}))

const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
}))

const authMock = vi.hoisted(() => ({
  user: { id: 1, is_admin: true },
}))

vi.mock('./api', () => ({ api: apiMock }))
vi.mock('vue-router', () => ({
  useRoute: () => routeMock,
  useRouter: () => routerMock,
}))
vi.mock('./stores/auth', () => ({ useAuthStore: () => authMock }))

import CatalogDetailView from './views/CatalogDetailView.vue'

const globalMount = {
  global: {
    stubs: {
      RouterLink: { props: ['to'], template: '<a><slot /></a>' },
      CatalogCreatorProfile: { template: '<div class="creator-profile" />' },
      EmployeeSixDimPanel: { template: '<div class="six-dim" />' },
      Teleport: true,
      Transition: false,
      TransitionGroup: false,
    },
  },
}

function catalogItem(overrides: Record<string, unknown> = {}) {
  return {
    id: 10,
    pkg_id: 'emp_customer_service',
    name: 'Customer Agent',
    version: '1.0.0',
    industry: 'retail',
    artifact: 'employee_pack',
    material_category: 'ai_employee',
    description: 'desc',
    license_scope: 'enterprise',
    origin_type: 'original',
    ip_risk_level: 'medium',
    compliance_status: 'approved',
    security_level: 'enterprise',
    price: 0,
    favorited: false,
    purchased: true,
    user_has_review: false,
    status: 'active',
    execution_stats: { total_runs: 3, success_rate: 0.8 },
    capabilities: [{ label: 'Chat', description: 'Talks' }],
    examples: [{ title: 'Example', description: 'desc', input: { q: 'x' } }],
    author_id: 2,
    author: { id: 2, name: 'Author' },
    creator_stats: { favorite_count: 2 },
    install_count: 5,
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  document.body.innerHTML = ''
  routeMock.params = { id: '10' }
  authMock.user = { id: 1, is_admin: true }
  localStorage.setItem('modstore_token', 'token')

  apiMock.catalogDetail.mockResolvedValue(catalogItem())
  apiMock.catalogReviews.mockResolvedValue({ reviews: [{ id: 1, rating: 5, content: 'good' }], average_rating: 5, total: 1 })
  apiMock.catalogQuality.mockResolvedValue({
    six_dimension: {
      overall_score: 91.25,
      overall_grade: 'a',
      scoring_source: 'llm',
      llm_summary: 'good quality',
    },
    validate_errors: ['minor'],
    pipeline_label: 'pipeline',
    audited_at: '2026-01-02T03:04:05Z',
    from_cache: true,
  })
  apiMock.catalogToggleFavorite.mockResolvedValue({ favorited: true })
  apiMock.catalogSubmitReview.mockResolvedValue({})
  apiMock.catalogSubmitComplaint.mockResolvedValue({})
  apiMock.getEmployeeStatus.mockResolvedValue({ status: 'online', execution_stats: { total_executions: 7, success_rate: 0.9 } })
  apiMock.buyItem.mockResolvedValue({ message: 'owned' })
  apiMock.paymentCheckout.mockResolvedValue({ ok: true, type: 'precreate', order_id: 'ord_1' })
  apiMock.downloadItem.mockResolvedValue({})
  apiMock.adminDeleteCatalog.mockResolvedValue({})

  vi.stubGlobal('confirm', vi.fn(() => true))
  vi.stubGlobal('alert', vi.fn())
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('catalog detail coverage', () => {
  it('covers mount, labels, author follow, quality and employee status paths', async () => {
    const wrapper = mount(CatalogDetailView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any

    expect(apiMock.catalogDetail).toHaveBeenCalledWith('10')
    expect(vm.itemCapabilities).toHaveLength(1)
    expect(vm.itemExamples).toHaveLength(1)
    expect(vm.securityLevelLabel('team')).toBe('团队级')
    expect(vm.securityLevelLabel(undefined)).toBe('个人级')
    expect(vm.getArtifactLabel('employee_pack')).toBe('AI 员工包')
    expect(vm.materialCategoryLabel('ai_employee')).toBe('AI 员工')
    expect(vm.licenseScopeLabel('enterprise')).toBe('企业级')
    expect(vm.originTypeLabel('derivative')).toBe('二创/改编')
    expect(vm.ipRiskLabel('high')).toBe('高')
    expect(vm.ipRiskLabel('unknown')).toBe('低')
    expect(vm.complianceStatusLabel('under_review')).toBe('投诉处理中')
    expect(vm.employeeTotalExecutions({ execution_stats: { total_runs: 4 } })).toBe(4)
    expect(vm.employeeSuccessRate({ execution_stats: { success_rate: 0.75 } })).toBe(0.75)
    expect(vm.productAvatarLetter).toBe('C')

    localStorage.setItem('catalog_author_follows', 'bad-json')
    expect([...vm.readAuthorFollowSet()]).toEqual([])
    vm.syncAuthorFollowing()
    expect(vm.authorFollowing).toBe(false)

    vm.toggleAuthorFollow()
    expect(vm.authorFollowing).toBe(true)
    vm.toggleAuthorFollow()
    expect(vm.authorFollowing).toBe(false)

    localStorage.removeItem('modstore_token')
    await vm.toggleAuthorFollow()
    expect(routerMock.push).toHaveBeenCalledWith({ name: 'login', query: { redirect: '/catalog/10' } })
    localStorage.setItem('modstore_token', 'token')

    await vm.loadQuality(true)
    expect(apiMock.catalogQuality).toHaveBeenCalledWith('10', { refresh: true })
    expect(vm.qualityScoringLabel).toContain('LLM')
    expect(vm.qualityOverallScore).toBe('91.3')
    expect(vm.qualityOverallGrade).toBe('A')
    expect(vm.qualityFromCache).toBe(true)

    await vm.loadQuality({ llm: true })
    expect(vm.qualityFromCache).toBe(false)

    apiMock.catalogQuality.mockRejectedValueOnce(new Error('quality failed'))
    await vm.loadQuality()
    expect(vm.qualityError).toContain('quality failed')

    await vm.loadEmployeeStatus()
    expect(apiMock.getEmployeeStatus).toHaveBeenCalledWith('emp_customer_service')
    expect(vm.employeeStatus.data.status).toBe('online')

    apiMock.getEmployeeStatus.mockRejectedValueOnce(new Error('status failed'))
    await vm.loadEmployeeStatus()
    expect(vm.employeeStatus.error).toContain('status failed')
  })

  it('covers favorite, reviews and complaint branches', async () => {
    const wrapper = mount(CatalogDetailView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any

    localStorage.removeItem('modstore_token')
    await vm.toggleFavorite()
    expect(routerMock.push).toHaveBeenCalledWith({ name: 'login', query: { redirect: '/catalog/10' } })

    localStorage.setItem('modstore_token', 'token')
    await vm.toggleFavorite()
    expect(apiMock.catalogToggleFavorite).toHaveBeenCalledWith('10')
    expect(vm.item.favorited).toBe(true)
    expect(vm.item.creator_stats.favorite_count).toBe(3)

    apiMock.catalogToggleFavorite.mockRejectedValueOnce(new Error('favorite failed'))
    await vm.toggleFavorite()
    expect(window.alert).toHaveBeenCalledWith('favorite failed')

    vm.reviewRating = 4
    vm.reviewContent = ' useful '
    await vm.submitReview()
    expect(apiMock.catalogSubmitReview).toHaveBeenCalledWith('10', 4, 'useful')
    expect(vm.item.user_has_review).toBe(true)

    apiMock.catalogReviews.mockRejectedValueOnce(new Error('reviews failed'))
    await vm.loadReviews()
    expect(vm.reviewsErr).toContain('reviews failed')

    vm.item.user_has_review = false
    apiMock.catalogSubmitReview.mockRejectedValueOnce(new Error('review failed'))
    await vm.submitReview()
    expect(window.alert).toHaveBeenCalledWith('review failed')

    vm.openComplaintPanel()
    expect(vm.complaintPanelOpen).toBe(true)
    expect(vm.customerServiceLink('refund')).toEqual({
      name: 'customer-service',
      query: expect.objectContaining({ scene: 'refund', catalog_id: '10', pkg_id: 'emp_customer_service' }),
    })

    localStorage.removeItem('modstore_token')
    await vm.submitComplaint()
    expect(routerMock.push).toHaveBeenCalledWith({ name: 'login', query: { redirect: '/catalog/10' } })

    localStorage.setItem('modstore_token', 'token')
    vm.complaintReason = 'abc'
    await vm.submitComplaint()
    expect(window.alert).toHaveBeenCalledWith('请至少填写 4 个字的问题说明')

    vm.complaintReason = 'real issue'
    await vm.submitComplaint()
    expect(apiMock.catalogSubmitComplaint).toHaveBeenCalledWith(
      '10',
      'plagiarism',
      'real issue',
      expect.objectContaining({ pkg_id: 'emp_customer_service' }),
    )

    apiMock.catalogSubmitComplaint.mockRejectedValueOnce(new Error('complaint failed'))
    vm.complaintReason = 'another issue'
    await vm.submitComplaint()
    expect(window.alert).toHaveBeenCalledWith('complaint failed')
  })

  it('covers buy, download, delist, navigate and mount error branches', async () => {
    const wrapper = mount(CatalogDetailView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any

    localStorage.removeItem('modstore_token')
    await vm.doBuy()
    expect(routerMock.push).toHaveBeenCalledWith({ name: 'login', query: { redirect: '/catalog/10' } })

    localStorage.setItem('modstore_token', 'token')
    vm.item.price = 0
    await vm.doBuy()
    expect(apiMock.buyItem).toHaveBeenCalledWith('10')
    expect(window.alert).toHaveBeenCalledWith('owned')

    apiMock.buyItem.mockRejectedValueOnce(new Error('buy failed'))
    vm.item.price = 0
    await vm.doBuy()
    expect(window.alert).toHaveBeenCalledWith('buy failed')

    vm.item.price = 99
    apiMock.paymentCheckout.mockResolvedValueOnce({ ok: false, message: 'pay failed' })
    await vm.doBuy()
    expect(window.alert).toHaveBeenCalledWith('pay failed')

    apiMock.paymentCheckout.mockResolvedValueOnce({ ok: true, type: 'precreate', order_id: 'ord_2' })
    await vm.doBuy()
    expect(routerMock.push).toHaveBeenCalledWith({ name: 'checkout', params: { orderId: 'ord_2' } })

    apiMock.paymentCheckout.mockResolvedValueOnce({ ok: true, type: 'unknown' })
    await vm.doBuy()
    expect(window.alert).toHaveBeenCalledWith('未知的支付类型')

    apiMock.paymentCheckout.mockRejectedValueOnce(new Error('checkout failed'))
    await vm.doBuy()
    expect(window.alert).toHaveBeenCalledWith('checkout failed')

    await vm.doDownload()
    expect(apiMock.downloadItem).toHaveBeenCalledWith('10')
    apiMock.downloadItem.mockRejectedValueOnce(new Error('download failed'))
    await vm.doDownload()
    expect(window.alert).toHaveBeenCalledWith('download failed')

    ;(window.confirm as any).mockReturnValueOnce(false)
    await vm.delistItem()
    expect(apiMock.adminDeleteCatalog).not.toHaveBeenCalled()
    ;(window.confirm as any).mockReturnValueOnce(true)
    await vm.delistItem()
    expect(apiMock.adminDeleteCatalog).toHaveBeenCalledWith(10)
    expect(routerMock.push).toHaveBeenCalledWith({ name: 'ai-store' })

    apiMock.adminDeleteCatalog.mockRejectedValueOnce(new Error('delist failed'))
    await vm.delistItem()
    expect(window.alert).toHaveBeenCalledWith('delist failed')

    vm.navigateToWorkflow()
    expect(routerMock.push).toHaveBeenCalledWith('/workflow')

    apiMock.catalogDetail.mockRejectedValueOnce(new Error('detail failed'))
    const bad = mount(CatalogDetailView, globalMount)
    await flushPromises()
    expect((bad.vm as any).err).toContain('detail failed')
  })

  it('covers array route param and author self computed branch', async () => {
    routeMock.params = { id: ['88'] }
    authMock.user = { id: 2, is_admin: true }
    apiMock.catalogDetail.mockResolvedValueOnce(catalogItem({ id: 88, author_id: 2, author: { id: 2, name: 'Self' } }))
    const wrapper = mount(CatalogDetailView, globalMount)
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.catalogParamId).toBe('88')
    expect(vm.isAuthorSelf).toBe(true)
  })
})
