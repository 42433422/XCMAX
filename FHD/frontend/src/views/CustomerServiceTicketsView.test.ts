import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import CustomerServiceTicketsView from '../../../admin-console/src/views/CustomerServiceTicketsView.vue'
import { ADMIN_HOST_ROUTE_RECORDS } from '../../../admin-console/src/adminHostRoutes'
import { ADMIN_OPERATOR_MENU_ITEMS, ADMIN_OPERATOR_ROUTE_NAMES } from '../../../admin-console/src/constants/adminOperatorNav'

const { list, detail } = vi.hoisted(() => ({ list: vi.fn(), detail: vi.fn() }))
vi.mock('@/api/xcmaxAdmin', () => ({ xcmaxAdminApi: { fetchCustomerTickets: list, fetchCustomerTicket: detail } }))
const ticket = { id: 42, ticket_no: 'CS-20261016-290063', user_id: 7, status: 'processing', summary: 'UPDATELOG-20261016 更新说明不可见', assigned_admin_id: null }
const payload = { ticket, actions: [], decisions: [], audit_logs: [], }

beforeEach(() => { vi.resetAllMocks(); list.mockResolvedValue({ items: [ticket], total: 1 }); detail.mockResolvedValue(payload) })
describe('customer service original tickets', () => {
  it('is discoverable by 客服, 工单 and 客户反馈 and remains an admin route', () => {
    const item = ADMIN_OPERATOR_MENU_ITEMS.find(row => row.key === 'customer-service-tickets')!
    for (const keyword of ['客服', '工单', '客户反馈']) expect(item.name).toContain(keyword)
    expect(ADMIN_OPERATOR_ROUTE_NAMES.has(item.key)).toBe(true)
    expect(ADMIN_HOST_ROUTE_RECORDS.find(row => row.name === item.key)?.meta).toMatchObject({ requiresAdminAccount: true, hostAdmin: true })
  })
  it('loads CS independently of Work Orders and opens real internal id with full original evidence', async () => {
    const wrapper = mount(CustomerServiceTicketsView)
    await flushPromises()
    await wrapper.findAll('button').find(row => row.text().includes(ticket.ticket_no))!.trigger('click')
    await flushPromises()
    expect(detail).toHaveBeenCalledWith(42)
    expect(wrapper.text()).toContain(ticket.ticket_no)
    expect(wrapper.text()).toContain(ticket.summary)
    expect(wrapper.text()).toContain('暂无管理员指派记录')
    expect(wrapper.text()).toContain('暂无记录')
    expect(wrapper.text()).toContain('处理状态本身不代表员工已领取或执行')
    wrapper.unmount()
  })
  it('shows resolution, attachments and followups as escaped evidence without binary support packs', async () => {
    detail.mockResolvedValue({ ...payload, ticket: { ...ticket, evidence: {
      resolution: { employee_id: 'repair-worker', status: 'awaiting_verification', delivery: { verification: 'pending' } },
      attachments: [{ name: '<script>evidence</script>' }], followups: [{ note: 'customer followup' }],
      support_bundle_base64: 'binary-not-for-display',
    } } })
    const wrapper = mount(CustomerServiceTicketsView); await flushPromises()
    await wrapper.findAll('button').find(row => row.text().includes(ticket.ticket_no))!.trigger('click'); await flushPromises()
    for (const text of ['repair-worker', 'awaiting_verification', 'pending', '<script>evidence</script>', 'customer followup']) expect(wrapper.text()).toContain(text)
    expect(wrapper.find('script').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('binary-not-for-display')
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
    await wrapper.find('input').setValue('290063'); await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(list).toHaveBeenLastCalledWith('290063', 0)
    await wrapper.findAll('button').find(row => row.text() === '下一页')!.trigger('click'); await flushPromises()
    expect(list).toHaveBeenLastCalledWith('290063', 50)
    await wrapper.find('input').setValue('UPDATELOG-20261016')
    await wrapper.findAll('button').find(row => row.text() === '上一页')!.trigger('click'); await flushPromises()
    expect(list).toHaveBeenLastCalledWith('290063', 0)
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(list).toHaveBeenLastCalledWith('UPDATELOG-20261016', 0)
    wrapper.unmount()
  })
  it('rejects mismatched identity and ignores an old detail response after refresh', async () => {
    const wrapper = mount(CustomerServiceTicketsView); await flushPromises()
    detail.mockResolvedValueOnce({ ...payload, ticket: { ...ticket, id: 290063 } })
    await wrapper.findAll('button').find(row => row.text().includes(ticket.ticket_no))!.trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('详情响应不完整')
    let resolve!: (value: typeof payload) => void
    detail.mockReturnValueOnce(new Promise(done => { resolve = done }))
    await wrapper.findAll('button').find(row => row.text() === '重试详情')!.trigger('click')
    await wrapper.find('form').trigger('submit'); await flushPromises()
    resolve(payload); await flushPromises()
    expect(wrapper.find('[aria-label="客服原单详情"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
