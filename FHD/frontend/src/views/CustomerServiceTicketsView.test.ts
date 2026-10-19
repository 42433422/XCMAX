import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { ApiError } from '@/api/core'
import CustomerServiceTicketsView from '../../../admin-console/src/views/CustomerServiceTicketsView.vue'
import CustomerServiceTicketDetailView from '../../../admin-console/src/views/CustomerServiceTicketDetailView.vue'
import { ADMIN_HOST_ROUTE_RECORDS } from '../../../admin-console/src/adminHostRoutes'
import { ADMIN_OPERATOR_MENU_ITEMS, ADMIN_OPERATOR_ROUTE_NAMES } from '../../../admin-console/src/constants/adminOperatorNav'
import { SIDEBAR_ROUTE_NAME_MAP } from '@/constants/sidebarRouteNameMap'

const { list, detail, create, push, route, put } = vi.hoisted(() => ({
  put: vi.fn(), list: vi.fn(), detail: vi.fn(), create: vi.fn(), push: vi.fn(), route: { params: {} as Record<string, string> },
}))
vi.mock('@/api/xcmaxAdmin', () => ({ xcmaxAdminApi: { fetchCustomerTickets: list, fetchCustomerTicket: detail, createCustomerTicket: create } }))
vi.mock('@/api/core', async importOriginal => {
  const actual = await importOriginal<typeof import('@/api/core')>()
  return { ...actual, default: { ...actual.default, put } }
})
vi.mock('vue-router', () => ({ useRouter: () => ({ push }), useRoute: () => route }))

const ticket = {
  id: 42, ticket_no: 'CS-20261016-290063', user_id: 7, session_id: 63, status: 'resolved', lifecycle_label: '已完成',
  title: '平台功能问题', intent: 'product_issue', issue_domain_label: '平台', priority: 'normal',
  summary: 'UPDATELOG-20261016 更新说明不可见', assigned_admin_id: null,
  created_at: '2026-10-16T04:41:57.835690', updated_at: '2026-10-17T16:37:23.118331', closed_at: '',
  lifecycle_steps: [{ stage: 1, label: '已收到', state: 'done' }, { stage: 5, label: '已完成', state: 'current' }],
}
const payload = { ticket, actions: [], decisions: [], audit_logs: [] }

function mountDetail(id = '42') {
  Object.assign(route, reactive({ params: { ticketId: id } }))
  return mount(CustomerServiceTicketDetailView)
}

beforeEach(() => {
  vi.resetAllMocks()
  route.params = {}
  list.mockResolvedValue({ items: [ticket], total: 1 }); detail.mockResolvedValue(payload); push.mockResolvedValue(undefined)
  create.mockResolvedValue({ ticket_id: 53, ticket_no: 'CS-53' })
})

describe('customer service ticket list', () => {
  it('is discoverable by 客服, 工单 and 客户反馈 and remains an admin route', () => {
    const item = ADMIN_OPERATOR_MENU_ITEMS.find(row => row.key === 'customer-service-tickets')!
    for (const keyword of ['客服', '工单', '客户反馈']) expect(item.name).toContain(keyword)
    expect(ADMIN_OPERATOR_ROUTE_NAMES.has(item.key)).toBe(true)
    expect(ADMIN_HOST_ROUTE_RECORDS.find(row => row.name === item.key)?.meta).toMatchObject({ requiresAdminAccount: true, hostAdmin: true })
  })
  it('registers a directly reachable admin-only detail route that keeps the sidebar on 客服工单', () => {
    const record = ADMIN_HOST_ROUTE_RECORDS.find(row => row.name === 'customer-service-ticket-detail')!
    expect(record.path).toBe('/customer-service-tickets/:ticketId(\\d+)')
    expect(record.meta).toMatchObject({ requiresAdminAccount: true, hostAdmin: true })
    expect(SIDEBAR_ROUTE_NAME_MAP[record.path]).toBe('customer-service-tickets')
  })
  it('renders a table with Chinese status badges and Beijing time, and opens the detail route', async () => {
    const wrapper = mount(CustomerServiceTicketsView); await flushPromises()
    const row = wrapper.find('tbody tr')
    expect(row.text()).toContain(ticket.ticket_no)
    expect(row.text()).toContain('已完成')
    expect(row.text()).not.toContain('resolved')
    expect(row.text()).toContain('2026-10-18 00:37:23')
    expect(row.find('.cs-badge').classes()).toContain('is-success')
    await row.find('button').trigger('click')
    expect(push).toHaveBeenCalledWith({ name: 'customer-service-ticket-detail', params: { ticketId: '42' } })
    await row.trigger('keydown.enter')
    expect(push).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
  it('distinguishes loading, failed, malformed and truly empty sources', async () => {
    let reject!: (cause: Error) => void
    list.mockReturnValueOnce(new Promise((_resolve, fail) => { reject = fail }))
    const wrapper = mount(CustomerServiceTicketsView)
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('正在读取客服工单')
    expect(wrapper.text()).not.toContain('没有客服工单')
    reject(new Error('403 forbidden')); await flushPromises()
    expect(wrapper.text()).toContain('403 forbidden')
    expect(wrapper.text()).not.toContain('当前授权范围与搜索条件下没有客服工单')
    list.mockResolvedValueOnce({ success: false }); await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(wrapper.text()).toContain('响应不完整')
    list.mockResolvedValueOnce({ items: [], total: 0 }); await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(wrapper.text()).toContain('当前授权范围与搜索条件下没有客服工单')
    wrapper.unmount()
  })
  it('searches suffix and original text server-side and paginates beyond the initial 50', async () => {
    list.mockResolvedValue({ items: [ticket], total: 51 })
    const wrapper = mount(CustomerServiceTicketsView); await flushPromises()
    expect(wrapper.text()).toContain('第 1 / 2 页')
    await wrapper.find('input').setValue('290063'); await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(list).toHaveBeenLastCalledWith('290063', 0, '', '', '')
    await wrapper.findAll('button').find(row => row.text() === '下一页')!.trigger('click'); await flushPromises()
    expect(list).toHaveBeenLastCalledWith('290063', 50, '', '', '')
    await wrapper.find('input').setValue('UPDATELOG-20261016')
    await wrapper.findAll('button').find(row => row.text() === '上一页')!.trigger('click'); await flushPromises()
    expect(list).toHaveBeenLastCalledWith('290063', 0, '', '', '')
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(list).toHaveBeenLastCalledWith('UPDATELOG-20261016', 0, '', '', '')
    wrapper.unmount()
  })
  it('allows correction after a definite rejection and uses a fresh request id', async () => {
    create.mockRejectedValueOnce(new ApiError('问题描述至少 4 个字符', 422, {}))
    const wrapper = mount(CustomerServiceTicketsView); await flushPromises()
    await wrapper.find('button.cs-btn-primary').trigger('click')
    const form = wrapper.find('form.cs-create')
    const title = form.find('input')
    await title.setValue('员工图谱页面无法显示关系线')
    await form.find('textarea').setValue('管理端员工图谱页面未显示关系线。')
    await form.trigger('submit')
    await flushPromises()
    expect((title.element as HTMLInputElement).disabled).toBe(false)
    expect(form.text()).toContain('提交被拒绝')
    await title.setValue('员工图谱页面无法显示关系线')
    expect(form.text()).not.toContain('提交被拒绝')
    await form.trigger('submit')
    await flushPromises()
    expect(create).toHaveBeenCalledTimes(2)
    expect(create.mock.calls[0][0].request_id).not.toBe(create.mock.calls[1][0].request_id)
    expect(push).toHaveBeenCalledWith({ name: 'customer-service-ticket-detail', params: { ticketId: '53' } })
    wrapper.unmount()
  })
  it('keeps the same payload and request id after an uncertain response', async () => {
    create.mockRejectedValueOnce(new ApiError('请求超时', 0, null))
    const wrapper = mount(CustomerServiceTicketsView); await flushPromises()
    await wrapper.find('button.cs-btn-primary').trigger('click')
    const form = wrapper.find('form.cs-create')
    await form.find('input').setValue('员工图谱页面无法显示关系线')
    await form.find('textarea').setValue('管理端员工图谱页面未显示关系线。')
    await form.trigger('submit')
    await flushPromises()
    await form.trigger('submit')
    await flushPromises()
    expect(create).toHaveBeenCalledTimes(2)
    expect(create.mock.calls[0][0]).toEqual(create.mock.calls[1][0])
    expect((form.find('input').element as HTMLInputElement).disabled).toBe(true)
    wrapper.unmount()
  })
})

describe('customer service ticket detail', () => {
  it('corrects the same ticket title with a stale-title guard and refreshes audit evidence', async () => {
    const prompt = vi.spyOn(window, 'prompt').mockReturnValue('  员工图谱无法正常显示  ')
    detail.mockResolvedValueOnce(payload).mockResolvedValueOnce({ ...payload, ticket: { ...ticket, title: '员工图谱无法正常显示' }, audit_logs: [{ event_type: 'ticket_title_corrected', detail: { old_title: ticket.title, new_title: '员工图谱无法正常显示' } }] })
    const wrapper = mountDetail(); await flushPromises()
    await wrapper.findAll('button').find(row => row.text() === '更正标题')!.trigger('click'); await flushPromises()
    expect(put).toHaveBeenCalledWith('/api/xcmax/market-proxy/customer-service/tickets/42/title', { title: '员工图谱无法正常显示', expected_title: ticket.title })
    expect(wrapper.find('h2').text()).toBe('员工图谱无法正常显示')
    for (const part of ['更正工单标题', '标题：平台功能问题 → 员工图谱无法正常显示']) expect(wrapper.text()).toContain(part)
    wrapper.unmount(); prompt.mockRestore()
  })
  it('opens the real internal id with header, original text and empty sections', async () => {
    const wrapper = mountDetail(); await flushPromises()
    expect(detail).toHaveBeenCalledWith(42)
    const text = wrapper.text()
    for (const part of [ticket.ticket_no, ticket.summary, '暂无管理员指派记录', '暂无记录', '处理状态本身不代表员工已领取或执行', '平台', '产品问题', '市场用户 ID 7', '会话 63', '2026-10-16 12:41:57', '未关闭', '北京时间']) {
      expect(text).toContain(part)
    }
    expect(wrapper.find('.cs-hero .cs-badge').text()).toBe('已完成')
    expect(wrapper.find('.cs-steps .is-current').text()).toBe('已完成')
    expect(wrapper.find('details.cs-raw').attributes('open')).toBeUndefined()
    await wrapper.find('.cs-back button').trigger('click')
    expect(push).toHaveBeenCalledWith({ name: 'customer-service-tickets' })
    wrapper.unmount()
  })
  it('structures decisions, actions, team status and audit logs with Chinese labels', async () => {
    detail.mockResolvedValue({
      ...payload,
      ticket: { ...ticket, evidence: {
        resolution: { state: 'repair_failed', route: 'shared_core', repair_verified: false, incident_event_id: 85419, updated_at: '2026-10-16T04:48:46.450914+00:00',
          team: [{ role: 'scout', employee_id: 'change-request-auditor', ok: false, status: 'failed' }] },
        customer_decisions: [{ decision: 'reopen', at: '2026-10-17T03:00:00+00:00' }],
        employee_reports: [{ team_ok: true, progress: '复验通过', at: '2026-10-17T05:00:00+00:00' }],
      } },
      decisions: [{ id: 41, decision: 'accepted', intent: 'product_issue', risk_level: 'low', confidence: 0.7, rationale: '已登记，我们会跟进处理。', created_at: '2026-10-16T04:41:57.850507' }],
      actions: [{ id: 28, action_type: 'employee.dispatch', status: 'completed', target_type: 'incident_team', target_id: '85419', request: { team_ok: false, roles: [{ role: 'fix', employee_id: 'vibe-coding-maintainer', ok: false, status: 'failed' }] }, created_at: '2026-10-16T04:48:46.454807' }],
      audit_logs: [
        { id: 207, actor_type: 'ai', actor_user_id: 29, event_type: 'ticket_created', detail: { intent: 'product_issue' }, created_at: '2026-10-16T04:41:57.842595' },
        { id: 214, actor_type: 'user', actor_user_id: 29, event_type: 'customer_issue_reopen', detail: { note: '还是看不到更新日志' }, created_at: '2026-10-17T03:00:00' },
        { id: 299, actor_type: 'robot', event_type: 'brand_new_event', detail: {}, created_at: 'not-a-time' },
      ],
    })
    const wrapper = mountDetail(); await flushPromises()
    const text = wrapper.text()
    for (const part of ['修复未完成', '修复未验证', '平台公共修复', '事件 #85419', '排查', 'change-request-auditor', '失败']) expect(text).toContain(part)
    const timeline = wrapper.findAll('.cs-timeline > li').map(li => li.text())
    expect(timeline).toHaveLength(4)
    expect(timeline[0]).toContain('已受理'); expect(timeline[0]).toContain('低风险'); expect(timeline[0]).toContain('置信度 70%')
    expect(timeline[1]).toContain('派单给处理小组'); expect(timeline[1]).toContain('小组处理未成功'); expect(timeline[1]).toContain('修复 · 失败')
    expect(timeline[2]).toContain('客户重新打开工单'); expect(timeline[3]).toContain('复验通过')
    const audits = wrapper.find('[aria-label="审计记录"]').findAll('tbody tr').map(tr => tr.text())
    expect(audits[0]).toContain('创建工单'); expect(audits[0]).toContain('AI 客服 · 用户 ID 29'); expect(audits[0]).toContain('意图：产品问题')
    expect(audits[1]).toContain('客户重新打开'); expect(audits[1]).toContain('还是看不到更新日志'); expect(audits[1]).toContain('2026-10-17 11:00:00')
    expect(audits[2]).toContain('brand_new_event'); expect(audits[2]).toContain('robot'); expect(audits[2]).toContain('not-a-time')
    wrapper.unmount()
  })
  it('keeps resolution, attachments and followups only as escaped raw evidence without binary support packs', async () => {
    detail.mockResolvedValue({ ...payload, ticket: { ...ticket, evidence: {
      resolution: { employee_id: 'repair-worker', status: 'awaiting_verification', delivery: { verification: 'pending' } },
      attachments: [{ name: '<script>evidence</script>' }], followups: [{ note: 'customer followup' }],
      support_bundle_base64: 'binary-not-for-display',
    } } })
    const wrapper = mountDetail(); await flushPromises()
    const raw = wrapper.find('details.cs-raw').text()
    for (const text of ['repair-worker', 'awaiting_verification', 'pending', '<script>evidence</script>', 'customer followup']) expect(raw).toContain(text)
    expect(wrapper.find('script').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('binary-not-for-display')
    wrapper.unmount()
  })
  it('rejects invalid ids, mismatched identity and stale responses', async () => {
    let wrapper = mountDetail('abc'); await flushPromises()
    expect(detail).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('工单 ID 无效')
    wrapper.unmount()
    detail.mockResolvedValueOnce({ ...payload, ticket: { ...ticket, id: 290063 } })
    wrapper = mountDetail(); await flushPromises()
    expect(wrapper.text()).toContain('详情响应不完整')
    let resolve!: (value: typeof payload) => void
    detail.mockReturnValueOnce(new Promise(done => { resolve = done }))
    await wrapper.findAll('button').find(row => row.text() === '重试详情')!.trigger('click')
    expect(wrapper.text()).toContain('正在读取原单证据')
    wrapper.unmount()
    resolve(payload); await flushPromises()
    detail.mockRejectedValueOnce(new Error('404 not found'))
    wrapper = mountDetail(); await flushPromises()
    expect(wrapper.text()).toContain('404 not found')
    wrapper.unmount()
  })
})
