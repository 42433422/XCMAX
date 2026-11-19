import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import CustomerServiceTicketsView from '../../../admin-console/src/views/CustomerServiceTicketsView.vue'
import CustomerServiceTicketDetailView from '../../../admin-console/src/views/CustomerServiceTicketDetailView.vue'
import { ADMIN_HOST_ROUTE_RECORDS } from '../../../admin-console/src/adminHostRoutes'
import { ADMIN_OPERATOR_MENU_ITEMS, ADMIN_OPERATOR_ROUTE_NAMES } from '../../../admin-console/src/constants/adminOperatorNav'
import { SIDEBAR_ROUTE_NAME_MAP } from '@/constants/sidebarRouteNameMap'

const { list, detail, updateEta, decideDelivery, push, route, put, post, get, prompt, confirm } = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), put: vi.fn(), list: vi.fn(), detail: vi.fn(), updateEta: vi.fn(), decideDelivery: vi.fn(), push: vi.fn(), prompt: vi.fn(), confirm: vi.fn(), route: { params: {} as Record<string, string> },
}))
vi.mock('@/api/xcmaxAdmin', () => ({ xcmaxAdminApi: { fetchCustomerTickets: list, fetchCustomerTicket: detail, updateCustomerTicketExpectedCompletion: updateEta, decideCustomDelivery: decideDelivery } }))
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
  updateEta.mockResolvedValue(payload); decideDelivery.mockResolvedValue({ success: true })
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
    expect(row.find('.el-tag').classes()).toContain('el-tag--success')
    await row.find('button').trigger('click')
    expect(push).toHaveBeenCalledWith({ name: 'customer-service-ticket-detail', params: { ticketId: '42' } })
    await row.trigger('click')
    expect(push).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
  it('distinguishes loading, failed, malformed and truly empty sources', async () => {
    let reject!: (cause: Error) => void
    list.mockReturnValueOnce(new Promise((_resolve, fail) => { reject = fail }))
    const wrapper = mount(CustomerServiceTicketsView)
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('正在读取')
    expect(wrapper.text()).not.toContain('暂无工单')
    reject(new Error('403 forbidden')); await flushPromises()
    expect(wrapper.text()).toContain('403 forbidden')
    expect(wrapper.text()).not.toContain('暂无工单')
    list.mockResolvedValueOnce({ success: false }); await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(wrapper.text()).toContain('响应不完整')
    list.mockResolvedValueOnce({ items: [], total: 0 }); await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(wrapper.text()).toContain('暂无工单')
    wrapper.unmount()
  })
  it('searches suffix and original text server-side and paginates beyond the initial 50', async () => {
    list.mockResolvedValue({ items: [ticket], total: 51 })
    const wrapper = mount(CustomerServiceTicketsView); await flushPromises()
    expect(wrapper.text()).toContain('共 51 单')
    await wrapper.find('input').setValue('290063'); await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(list).toHaveBeenLastCalledWith('290063', 0, '', '', '', '', '', '', '')
    await wrapper.find('.btn-next').trigger('click'); await flushPromises()
    expect(list).toHaveBeenLastCalledWith('290063', 50, '', '', '', '', '', '', '')
    await wrapper.find('input').setValue('UPDATELOG-20261016')
    await wrapper.find('.btn-prev').trigger('click'); await flushPromises()
    expect(list).toHaveBeenLastCalledWith('290063', 0, '', '', '', '', '', '', '')
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(list).toHaveBeenLastCalledWith('UPDATELOG-20261016', 0, '', '', '', '', '', '', '')
    wrapper.unmount()
  })
  it('combines ticket type, domain, source and status across pages', async () => {
    list.mockResolvedValue({ items: [{ ...ticket, intent: 'product_issue', submitter_type: 'customer' }], total: 51 })
    const wrapper = mount(CustomerServiceTicketsView); await flushPromises()
    const selects = wrapper.findAllComponents({ name: 'ElSelect' })
    for (const [index, value] of [['0', 'defect'], ['1', 'platform'], ['2', 'customer_chat'], ['3', 'resolved']] as const) {
      selects[Number(index)].vm.$emit('update:modelValue', value)
    }
    await flushPromises()
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(list).toHaveBeenLastCalledWith('', 0, '', '', 'resolved', 'defect', 'platform', 'customer_chat', '')
    for (const label of ['缺陷', '平台', '客户对话']) expect(wrapper.find('tbody tr').text()).toContain(label)
    await wrapper.find('.btn-next').trigger('click'); await flushPromises()
    expect(list).toHaveBeenLastCalledWith('', 50, '', '', 'resolved', 'defect', 'platform', 'customer_chat', '')
    wrapper.unmount()
  })
})

describe('customer service ticket detail', () => {
  it.each(['admin', 'customer'])('keeps %s submitter identity distinct from the customer and assigned administrator', async submitter_type => {
    detail.mockResolvedValue({ ...payload, ticket: { ...ticket, user_id: 29, submitter_type, assigned_admin_id: 9 } })
    const wrapper = mountDetail(); await flushPromises()
    const facts = wrapper.findAll('.cs-hero .cs-facts > div')
    const value = (label: string) => facts.find(row => row.find('dt').text() === label)!.find('dd').text()
    expect(value('客户')).toContain('市场用户 ID 29')
    expect(value('提交人身份')).toBe(submitter_type === 'admin' ? '管理员提交' : '客户提交')
    expect(value('指派管理员')).toBe('9')
    wrapper.unmount()
  })
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
    expect(overview.text()).toContain('派发已受理')
    expect(overview.text()).toContain('未提供独立领取凭证')
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
  it.each(['invalid', 'out_of_scope'])('submits %s on the original ticket and reads its stop evidence', async kind => {
    const note = '核对原问题后形成客户可见处置结论'
    const verification = '按工单原文和给出的页面步骤核对当前产品功能与受理范围。'
    detail.mockResolvedValueOnce({ ...payload, ticket: { ...ticket, status: 'processing', assigned_admin_id: 1 } })
    detail.mockResolvedValueOnce({
      ...payload,
      ticket: { ...ticket, status: 'rejected', closed_at: '2026-11-20', disposition: {
        kind, note, verification, execution_stop: { state: 'stop_unconfirmed' },
      } },
      audit_logs: [{ event_type: 'admin_ticket_disposed', detail: { reason: note } }],
    })
    confirm.mockResolvedValue(true)
    post.mockResolvedValue({})
    const wrapper = mountDetail(); await flushPromises()
    const form = wrapper.find('.cs-close-form')
    expect(form.findAll('option').map(option => option.attributes('value'))).toEqual(['expired', 'invalid', 'out_of_scope'])
    await form.find('select').setValue(kind)
    await form.findAll('textarea')[0].setValue(note)
    await form.findAll('textarea')[1].setValue(verification)
    await form.trigger('submit'); await flushPromises()
    expect(post).toHaveBeenCalledWith('/api/xcmax/admin/customer-service/tickets/42/disposition', {
      disposition: kind, note, verification, request_id: expect.any(String),
    })
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining(ticket.ticket_no), expect.any(Object))
    expect(wrapper.text()).toContain('已拒绝')
    expect(wrapper.text()).toContain('已派发任务停止状态待核实')
    expect(wrapper.text()).toContain('管理员驳回原工单')
    expect(wrapper.text()).toContain(note)
    expect(wrapper.find('.cs-close-form').exists()).toBe(false)
    wrapper.unmount()
  })
  it('revokes only dispatch, reconciles the original on uncertainty, and shows precise downstream receipts', async () => {
    const note = '自动分类错误，改为当前管理员继续人工复核'
    const processing = { ...ticket, status: 'processing', lifecycle_label: '处理中', assigned_admin_id: 17 }
    detail.mockResolvedValue({ ...payload, ticket: processing })
    get.mockResolvedValue({ viewer_id: 17 })
    confirm.mockResolvedValue(true)
    post.mockRejectedValueOnce(new Error('撤销回执暂不可确认'))
    const wrapper = mountDetail(); await flushPromises()
    const revoke = () => wrapper.findAll('button').find(button => button.text() === '撤销派发')!
    await wrapper.get('[aria-label="人工处理"]').get('input[minlength="4"]').setValue(note)
    await revoke().trigger('click'); await flushPromises()
    const original = post.mock.calls[0]
    expect(original).toEqual(['/api/xcmax/admin/customer-service/tickets/42/dispatch-revoke', {
      request_id: expect.any(String), note,
    }])
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining(ticket.ticket_no), expect.any(Object))
    expect(wrapper.text()).toContain('撤销回执暂不可确认')
    expect(wrapper.findAll('button').find(button => button.text() === '撤销派发')).toBeUndefined()
    await wrapper.findAll('button').find(button => button.text() === '重试详情')!.trigger('click'); await flushPromises()
    detail.mockResolvedValue({
      ...payload, ticket: { ...processing, dispatch_revocation: { note, at: '2026-11-20T07:00:00Z', execution_stop: {
        state: 'stop_unconfirmed', new_dispatch_blocked: true,
        unsettled_incidents: [{ incident_event_id: 77, task_ids: ['para-pending'] }],
        unsettled_action_ids: [83],
        mac_control_tasks: [{ id: 'queued-local', state: 'cancelled' }, { id: 'running-local', state: 'cancel_requested' }],
      } } },
      audit_logs: [{ event_type: 'admin_ticket_dispatch_revoked', detail: { note } }],
      execution_overview: { revocation_task_receipts: [{ id: 'running-local', state: 'cancelled' }] },
    })
    post.mockResolvedValue({})
    await revoke().trigger('click'); await flushPromises()
    expect(post.mock.calls[1]).toEqual(original)
    expect(wrapper.text()).toContain('处理中')
    expect(wrapper.text()).toContain('管理员撤销派发')
    const receipt = wrapper.get('[aria-label="撤销派发回执"]')
    expect(receipt.text()).toContain('已派发任务停止状态待核实')
    expect(receipt.text()).toContain('queued-local · 已取消')
    expect(receipt.text()).toContain('running-local · 已申请取消，等待执行端确认')
    expect(receipt.text()).toContain('最新回执 已取消')
    expect(receipt.text()).toContain('para-pending')
    expect(receipt.text()).toContain('动作 #83 · 停止状态待核实')
    expect(wrapper.findAll('button').find(button => button.text() === '撤销派发')).toBeUndefined()
    expect(wrapper.find('.cs-close-form').exists()).toBe(true)
    wrapper.unmount()
  })
  it('does not revoke from a different administrator account', async () => {
    detail.mockResolvedValue({ ...payload, ticket: { ...ticket, status: 'open', assigned_admin_id: 17 } })
    get.mockResolvedValue({ viewer_id: 21 })
    const wrapper = mountDetail(); await flushPromises()
    const handle = wrapper.get('[aria-label="人工处理"]')
    await handle.get('input[minlength="4"]').setValue('自动派发需要转由管理员核对')
    await handle.findAll('button').find(button => button.text() === '撤销派发')!.trigger('click'); await flushPromises()
    expect(handle.get('[role="alert"]').text()).toContain('仅当前工单处理人')
    expect(confirm).not.toHaveBeenCalled()
    expect(post).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('assigns the selected original to the verified logged-in admin', async () => {
    detail.mockResolvedValue({ ...payload, ticket: { ...ticket, status: 'processing' } })
    get.mockResolvedValue({ viewer_id: 17, items: [{ id: 21 }, { id: 17 }] })
    post.mockResolvedValue({})
    const wrapper = mountDetail(); await flushPromises()
    const handle = wrapper.find('[aria-label="人工处理"]')
    await handle.findAll('input')[1].setValue('核对这张原单后处理')
    await handle.findAll('button').find(button => button.text() === '指派给我')!.trigger('click'); await flushPromises()
    expect(get).toHaveBeenCalledWith('/api/xcmax/admin/customer-service/staff')
    expect(post).toHaveBeenCalledWith('/api/xcmax/admin/customer-service/tickets/42/assign', {
      assignee_id: 17, reason: '核对这张原单后处理',
    })
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
    expect(wrapper.text()).toContain('另一张工单'); expect(wrapper.text()).not.toContain('已保存')
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
    expect(wrapper.text()).toContain('已保存')
    wrapper.unmount()
  })
  it('opens the real internal id with header, original text and empty sections', async () => {
    const wrapper = mountDetail(); await flushPromises()
    expect(detail).toHaveBeenCalledWith(42)
    const text = wrapper.text()
    for (const part of [ticket.ticket_no, ticket.summary, '暂无管理员指派记录', '暂无记录', '平台', '缺陷', '市场用户 ID 7', '会话 63', '2026-10-16 12:41:57', '未关闭', '北京时间']) {
      expect(text).toContain(part)
    }
    expect(wrapper.find('.cs-hero .cs-badge').text()).toBe('已完成')
    expect(wrapper.find('.cs-steps .is-current').text()).toBe('已完成')
    expect(wrapper.find('details.cs-raw').attributes('style')).toContain('display: none')
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

it('shows delivery progress on the ticket detail and records acceptance or rework', async () => {
  confirm.mockResolvedValue(true)
  detail.mockResolvedValue({
    ...payload,
    ticket: { ...ticket, status: 'processing', intent: 'custom_delivery', evidence: { issue_domain: 'custom' } },
    custom_delivery: {
      stage: 'acceptance', stage_label: '质量门通过，待客户验收', gate_ok: true, acceptance_status: 'pending',
      requirements: '读取质检单', acceptance_criteria: '用例全部通过', pricing_mode: 'initial_included',
      runs: [{ attempt: 2, status: 'done', steps: [{ id: 'verify' }] }],
      artifacts: [{ kind: 'module', id: 'coating-quality-private' }], install_receipts: [],
    },
  })
  const wrapper = mountDetail(); await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === '交付进度')!.trigger('click')
  await flushPromises()
  const panel = wrapper.find('[aria-label="交付进度"]')
  expect(panel.text()).toContain('质量门通过，待客户验收')
  expect(panel.text()).toContain('coating-quality-private')
  expect(panel.text()).toContain('待安装回执')
  await panel.findAll('button').find(button => button.text() === '内部质量确认')!.trigger('click')
  await flushPromises()
  expect(confirm).toHaveBeenCalled()
  expect(decideDelivery).toHaveBeenCalledWith(42, 'accept', '管理员仅完成内部质量确认，等待客户本人验收')
  const refreshed = wrapper.find('[aria-label="交付进度"]')
  await refreshed.find('input[type="text"]').setValue('不合格')
  await refreshed.findAll('button').find(button => button.text() === '发起返工')!.trigger('click')
  await flushPromises()
  expect(wrapper.find('[aria-label="交付进度"]').text()).toContain('返工原因至少 4 个字')
  const retry = wrapper.find('[aria-label="交付进度"]')
  await retry.find('input[type="text"]').setValue('颜色比对用例缺失')
  await retry.findAll('button').find(button => button.text() === '发起返工')!.trigger('click')
  await flushPromises()
  expect(decideDelivery).toHaveBeenCalledWith(42, 'rework', '颜色比对用例缺失')
  wrapper.unmount()
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

it.each(['内部质量确认', '发起返工'])('does not apply %s after route changes during confirmation', async (action) => {
  let resolve!: (value: boolean) => void
  confirm.mockReturnValue(new Promise<boolean>(done => { resolve = done }))
  detail.mockResolvedValue({ ...payload, custom_delivery: { stage: 'acceptance', gate_ok: true, acceptance_status: 'pending', pricing_mode: 'initial_included' } })
  const wrapper = mountDetail(); await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === '交付进度')!.trigger('click')
  const panel = wrapper.find('[aria-label="交付进度"]')
  await panel.find('input[type="text"]').setValue('需要重新验证')
  await panel.findAll('button').find(button => button.text() === action)!.trigger('click')
  route.params.ticketId = '43'
  await flushPromises()
  resolve(true); await flushPromises()
  expect(decideDelivery).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('keeps the commerce editor reachable in migrated ticket delivery details', async () => {
  detail.mockResolvedValue({ ...payload, custom_delivery: { pricing_mode: 'legacy' } })
  const wrapper = mountDetail(); await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === '交付进度')!.trigger('click')
  const panel = wrapper.find('[aria-label="商务交付信息"]')
  expect(panel.exists()).toBe(true)
  for (const label of ['保存指派', '保存报价', '保存合同', '保存收款']) expect(panel.text()).toContain(label)
  wrapper.unmount()
})


it('preserves optional mainline rework on the original ticket and resets it on navigation', async () => {
  confirm.mockResolvedValue(true)
  detail.mockResolvedValue({ ...payload, custom_delivery: { kind: 'module', suggested_id: 'sunbird-attendance-custom', stage: 'rework' } })
  const wrapper = mountDetail(); await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === '交付进度')!.trigger('click')
  const panel = wrapper.find('[aria-label="交付进度"]')
  const checkbox = panel.get('input[type="checkbox"]')
  expect((checkbox.element as HTMLInputElement).checked).toBe(false)
  await checkbox.setValue(true)
  await panel.get('input[type="text"]').setValue('使用维护主线重新构建')
  await panel.findAll('button').find(button => button.text() === '发起返工')!.trigger('click')
  await flushPromises()
  expect(decideDelivery).toHaveBeenCalledWith(42, 'rework', '使用维护主线重新构建', 'versioned_main')
  detail.mockResolvedValue({ ...payload, ticket: { ...ticket, id: 43 }, custom_delivery: { kind: 'module', suggested_id: 'sunbird-attendance-custom', stage: 'rework' } })
  route.params.ticketId = '43'; await flushPromises()
  expect((wrapper.get('[aria-label="交付进度"] input[type="checkbox"]').element as HTMLInputElement).checked).toBe(false)
  wrapper.unmount()
})
