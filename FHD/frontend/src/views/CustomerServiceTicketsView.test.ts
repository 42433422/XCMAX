import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import CustomerServiceTicketsView from '../../../admin-console/src/views/CustomerServiceTicketsView.vue'
import CustomerServiceTicketDetailView from '../../../admin-console/src/views/CustomerServiceTicketDetailView.vue'
import { ADMIN_HOST_ROUTE_RECORDS } from '../../../admin-console/src/adminHostRoutes'
import { ADMIN_OPERATOR_MENU_ITEMS, ADMIN_OPERATOR_ROUTE_NAMES } from '../../../admin-console/src/constants/adminOperatorNav'
import { SIDEBAR_ROUTE_NAME_MAP } from '@/constants/sidebarRouteNameMap'

const { list, detail, updateEta, push, route, put, post, get, prompt, confirm } = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), put: vi.fn(), list: vi.fn(), detail: vi.fn(), updateEta: vi.fn(), push: vi.fn(), prompt: vi.fn(), confirm: vi.fn(), route: { params: {} as Record<string, string> },
}))
vi.mock('@/api/xcmaxAdmin', () => ({ xcmaxAdminApi: { fetchCustomerTickets: list, fetchCustomerTicket: detail, updateCustomerTicketExpectedCompletion: updateEta } }))
vi.mock('@/api/core', () => ({ default: { get, put, post } }))
vi.mock('@/utils/appDialog', () => ({ appConfirm: confirm, appPrompt: prompt }))
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
  updateEta.mockResolvedValue(payload)
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
  it('connects category and status filters to the list endpoint and preserves them across pages', async () => {
    list.mockResolvedValue({ items: [ticket], total: 51 })
    const wrapper = mount(CustomerServiceTicketsView); await flushPromises()
    const filters = wrapper.findAll('select')
    await filters[0].setValue('product_issue')
    await filters[1].setValue('resolved')
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(list).toHaveBeenLastCalledWith('', 0, '', 'product_issue', 'resolved')
    expect(wrapper.find('tbody tr').text()).toContain('产品问题')
    await wrapper.findAll('button').find(row => row.text() === '下一页')!.trigger('click'); await flushPromises()
    expect(list).toHaveBeenLastCalledWith('', 50, '', 'product_issue', 'resolved')
    wrapper.unmount()
  })
})

describe('customer service ticket detail', () => {
  it('shows separate product progress, the actual review receipt and next step', async () => {
    detail.mockResolvedValue({ ...payload, execution_overview: {
      work_order: { binding: 'verified', id: 'WO-PUBLIC', status: 'in_dev' }, blocker: 'review_in_progress',
      responsible: { label: 'grok_bot' }, last_progress: { at: '2026-10-21T12:00:00Z', label: '复核任务回执更新' },
      next_step: { label: '跟进已接单的复核任务' },
      verification: { source: 'customer_decision', release_bound: false, customer_confirmed: true },
      receipts: [{ kind: 'escalation', role: 'fix', task_id: 'task-real-12', state: 'accepted', accepted: true, completed: false }],
    } })
    const wrapper = mountDetail(); await flushPromises()
    const overview = wrapper.find('[aria-label="执行总览"]')
    expect(overview.text()).toContain('WO-PUBLIC · 开发中')
    expect(overview.text()).toContain('task-real-12')
    expect(overview.text()).toContain('已真实接单')
    expect(overview.text()).toContain('原客户直接确认')
    expect(overview.text()).toContain('未记录正式版本绑定')
    expect(overview.text()).toContain('2026-10-21 20:00:00')
    wrapper.unmount()
  })
  it('requires an explicit root-cause confirmation and retains the link request on retry', async () => {
    detail.mockResolvedValue({ ...payload, ticket: { ...ticket, status: 'processing' } })
    get.mockResolvedValue({ items: [{ source_ticket_id: 10, source_action_id: 11, ticket_no: 'CS-SOURCE', change_request_id: 12, repair_head_sha: 'a'.repeat(40) }], match_sha256: 'b'.repeat(64) })
    post.mockRejectedValueOnce(new Error('请求超时')).mockResolvedValue({ success: true })
    const wrapper = mountDetail(); await flushPromises()
    const section = wrapper.find('[aria-label="同根因公共修复"]')
    await section.find('button').trigger('click'); await flushPromises()
    expect(get).toHaveBeenCalledWith('/api/xcmax/market-proxy/customer-service/issues/42/shared-repair-candidates')
    await section.find('select').setValue('11')
    await section.find('textarea').setValue('已核对相同源版本和相同问题根因')
    await section.find('form').trigger('submit'); await flushPromises()
    expect(post).not.toHaveBeenCalled()
    await section.find('input[type="checkbox"]').setValue(true)
    await section.find('form').trigger('submit'); await flushPromises()
    const body = post.mock.calls[0][1]
    expect(body).toMatchObject({ source_ticket_id: 10, source_action_id: 11, confirmed_same_root_cause: true, match_sha256: 'b'.repeat(64) })
    expect(body.request_id).toBeTruthy()
    await section.find('form').trigger('submit'); await flushPromises()
    expect(post.mock.calls[1][1]).toEqual(body)
    expect(detail).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
  it.each([{ issue_domain: 'custom' }, { source: 'private_mod_rework' }])('requires customer acceptance for private Mod evidence %o', async evidence => {
    detail.mockResolvedValue({ ...payload, ticket: { ...ticket, status: 'processing', intent: 'general', evidence } }); const wrapper = mountDetail(); await flushPromises()
    expect(wrapper.find('.cs-close-form select').exists()).toBe(false); expect(wrapper.text()).toContain('过期与后续活跃需求核对记录'); wrapper.unmount()
  })
  it.each(['resolved', 'expired'])('keeps %s disposition and retry identity distinct from ETA', async (disposition) => {
    const processing = { ...payload, ticket: { ...ticket, status: 'processing', intent: 'account_support' } }
    detail.mockResolvedValue(processing)
    let decide!: (accepted: boolean) => void; confirm.mockReturnValueOnce(new Promise(resolve => { decide = resolve })).mockResolvedValue(true)
    const wrapper = mountDetail(); await flushPromises()
    await wrapper.find('.cs-close-form select').setValue(disposition); expect(wrapper.find('form.cs-eta-editor').exists()).toBe(true)
    await wrapper.findAll('.cs-close-form textarea')[0].setValue('修复已部署并完成原场景验收')
    await wrapper.findAll('.cs-close-form textarea')[1].setValue('主线 SHA abc123，目标版本已按原步骤运行并核实结果。')
    const closeForm = wrapper.find('.cs-close-form'), cancelled = closeForm.trigger('submit'); await flushPromises(); await closeForm.trigger('submit')
    expect(confirm).toHaveBeenCalledOnce(); expect(post).not.toHaveBeenCalled(); decide(false); await cancelled
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining(disposition === 'expired' ? '确认已核对过期时间及后续需求' : '确认已在目标版本完成实际验收'), { title: '确认管理员处置', confirmText: '记录并关闭', cancelText: '返回检查', danger: true })
    let reject!: (error: Error) => void; post.mockReturnValueOnce(new Promise((_resolve, fail) => { reject = fail }))
    const submitting = closeForm.trigger('submit'); await flushPromises(); await closeForm.trigger('submit'); await closeForm.trigger('submit')
    await wrapper.find('form.cs-eta-editor').trigger('submit')
    expect(confirm).toHaveBeenCalledTimes(2); expect(post).toHaveBeenCalledTimes(1); expect(updateEta).not.toHaveBeenCalled()
    await submitting; const original = post.mock.calls[0]
    reject(new Error('network response unknown')); await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '重试详情')!.trigger('click'); await flushPromises()
    expect((wrapper.findAll('.cs-close-form textarea')[0].element as HTMLTextAreaElement).value).toBe('修复已部署并完成原场景验收')
    detail.mockResolvedValue({ ...payload, ticket: { ...ticket, status: disposition, evidence: { resolution: { state: disposition, verification_mode: disposition === 'expired' ? 'admin_expiry' : 'admin_runtime' } } } })
    post.mockResolvedValueOnce({ success: true })
    await wrapper.find('.cs-close-form').trigger('submit'); await flushPromises()
    expect(post.mock.calls[1]).toEqual(original)
    expect(original[0]).toBe('/api/xcmax/admin/customer-service/tickets/42/close')
    expect(original[1].disposition).toBe(disposition)
    expect(wrapper.text()).toContain(disposition === 'expired' ? '已过期不再处理（未修复）' : '管理员验收已关闭'); expect(wrapper.text()).not.toContain('客户确认已解决')
    expect(wrapper.find('.cs-close-form').exists()).toBe(false)
    wrapper.unmount()
  })
  it('does not apply an old ETA save result after navigating to another ticket', async () => {
    let complete!: (value: unknown) => void
    updateEta.mockReturnValueOnce(new Promise(resolve => { complete = resolve }))
    const wrapper = mountDetail(); await flushPromises()
    await wrapper.find('#customer-ticket-eta').setValue('2026-10-21T11:30')
    await wrapper.find('form.cs-eta-editor').trigger('submit')
    detail.mockResolvedValue({ ...payload, ticket: { ...ticket, id: 43, title: '另一张工单' } })
    route.params.ticketId = '43'; await flushPromises()
    complete(payload); await flushPromises()
    expect(updateEta).toHaveBeenCalledWith(42, '2026-10-21T11:30:00+08:00')
    expect(detail).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('另一张工单'); expect(wrapper.text()).not.toContain('已保存，客户工单页面会显示此时间。')
    wrapper.unmount()
  })
  it.each([false, true])('corrects original-ticket metadata with CAS and refreshed audit (classification=%s)', async classification => {
    const before = { ...ticket, ...(classification ? { status: 'processing', intent: 'account_support' } : {}) }
    const title = classification ? before.title : '员工图谱无法正常显示', reason = '原描述明确是软件功能故障，纠正误分类'
    prompt.mockResolvedValueOnce(classification ? reason : `  ${title}  `)
    detail.mockResolvedValueOnce({ ...payload, ticket: before }).mockResolvedValueOnce({ ...payload, ticket: { ...before, title, intent: 'product_issue' }, audit_logs: [{ event_type: classification ? 'ticket_classification_corrected' : 'ticket_title_corrected', detail: { old_title: before.title, new_title: title, ...(classification ? { old_intent: before.intent, new_intent: 'product_issue', reason } : {}) } }] })
    const wrapper = mountDetail(); await flushPromises()
    await wrapper.findAll('button').find(row => row.text() === (classification ? '纠正为平台功能问题' : '更正标题'))!.trigger('click'); await flushPromises()
    expect(put).toHaveBeenCalledWith('/api/xcmax/market-proxy/customer-service/tickets/42/title', { title, expected_title: before.title, ...(classification ? { intent: 'product_issue', expected_intent: before.intent, reason } : {}) })
    expect(wrapper.find('h2').text()).toBe(title)
    for (const part of classification ? ['纠正工单分类', '分类：账号支持 → 产品问题', reason] : ['更正工单标题', '标题：平台功能问题 → 员工图谱无法正常显示']) expect(wrapper.text()).toContain(part)
    expect(wrapper.findAll('button').some(row => row.text() === '纠正为平台功能问题')).toBe(false)
    expect(prompt).toHaveBeenCalledOnce()
    wrapper.unmount()
  })
  it('lets an admin set the customer-visible expected completion time', async () => {
    const wrapper = mountDetail(); await flushPromises()
    await wrapper.find('#customer-ticket-eta').setValue('2026-10-21T11:30')
    await wrapper.find('form.cs-eta-editor').trigger('submit')
    await flushPromises()
    expect(updateEta).toHaveBeenCalledWith(42, '2026-10-21T11:30:00+08:00')
    expect(wrapper.text()).toContain('已保存，客户工单页面会显示此时间。')
    wrapper.unmount()
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

it('sends a customer-visible reply without closing the original ticket', async () => {
  detail.mockResolvedValue({ ...payload, ticket: { ...ticket, status: 'processing' } })
  post.mockResolvedValue({})
  const wrapper = mountDetail()
  await flushPromises()
  await wrapper.get('.cs-reply-form textarea').setValue('请在信息页展开问题工单处理结果查看进度。')
  const send = wrapper.findAll('button').find(button => button.text() === '发送答复并保留原单')!
  await send.trigger('submit')
  await flushPromises()
  expect(post).toHaveBeenCalledWith('/api/xcmax/admin/customer-service/tickets/42/reply', {
    request_id: expect.any(String), note: '请在信息页展开问题工单处理结果查看进度。',
  })
  expect(post.mock.calls.every(([url]) => !url.endsWith('/close'))).toBe(true)
  expect(confirm).not.toHaveBeenCalled()
})
