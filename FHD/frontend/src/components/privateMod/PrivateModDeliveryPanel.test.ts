import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import PrivateModDeliveryPanel from './PrivateModDeliveryPanel.vue'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { apiFetch } from '@/utils/apiBase'

vi.mock('@/utils/apiBase', () => ({ apiFetch: vi.fn() }))
const ticket = {
  id: 7, ticket_no: 'CS-7', title: '客户一的工资核算', summary: '按工时计算',
  custom_delivery: { kind: 'bundle', stage: 'delivering', artifacts: [
    { kind: 'module', id: 'private-payroll', name: '工资模块' },
    { kind: 'module', source_artifact_kind: 'employee', id: 'private-payroll-employee', name: '工资员工' },
  ] },
}
const response = (items = [ticket]) => new Response(JSON.stringify({ success: true, data: { requests: items, projects: [] } }))
async function setup() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const account = useAccountProfileStore()
  account.marketUserId = 1
  const wrapper = mount(PrivateModDeliveryPanel, { global: { plugins: [pinia] } })
  await flushPromises()
  return { wrapper, account }
}
beforeEach(() => { vi.clearAllMocks(); vi.mocked(apiFetch).mockImplementation(async () => response()) })

it('selects each actual artifact when a bundle contains two signed Mods', async () => {
  const { wrapper } = await setup()
  const buttons = wrapper.findAll('.private-mod-request__delivery button')
  expect(buttons.map(button => button.text())).toEqual(['安装私有 Mod · 工资模块', '安装 AI 员工 · 工资员工'])
  await buttons[1].trigger('click')
  await flushPromises()
  expect(apiFetch).toHaveBeenNthCalledWith(2, '/api/mod-store/private-delivery/requests/7/install', expect.objectContaining({
    method: 'POST', body: JSON.stringify({ artifact_kind: 'module', artifact_id: 'private-payroll-employee' }),
  }))
  expect(wrapper.text()).toContain('运行与业务验证通过才算交付')
  expect(wrapper.find('.private-mod-request__delivered').exists()).toBe(false)
  wrapper.unmount()
})

it('discards a previous account response and clears its private request draft', async () => {
  const { wrapper, account } = await setup()
  await wrapper.get('.private-mod-intake__toggle').trigger('click')
  await wrapper.get('input[maxlength="128"]').setValue('客户一的秘密需求')
  let finish: ((value: Response) => void) | undefined
  vi.mocked(apiFetch).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  await wrapper.findAll('.private-mod-request__delivery button')[0].trigger('click')
  vi.mocked(apiFetch).mockResolvedValueOnce(response([]))
  account.marketUserId = 2
  await flushPromises()
  finish?.(new Response(JSON.stringify({ detail: '客户一私包失败' }), { status: 409 }))
  await flushPromises()
  expect(wrapper.text()).not.toContain('客户一')
  expect(wrapper.find('.private-mod-intake__form').exists()).toBe(false)
  await wrapper.get('.private-mod-intake__toggle').trigger('click')
  expect((wrapper.get('input[maxlength="128"]').element as HTMLInputElement).value).toBe('')
  wrapper.unmount()
})

it('does not show a late library response after logout', async () => {
  let finish: ((value: Response) => void) | undefined
  vi.mocked(apiFetch).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const { wrapper, account } = await setup()
  account.marketUserId = null
  await flushPromises()
  finish?.(response())
  await flushPromises()
  expect(wrapper.find('.private-mod-request').exists()).toBe(false)
  wrapper.unmount()
})

function centerResponse(data: Record<string, unknown>) {
  return new Response(JSON.stringify({ success: true, data }))
}
function acceptanceTicket() {
  return { ...ticket, custom_delivery: { ...ticket.custom_delivery, stage: 'acceptance', runs: [{
    steps: [
      { id: 'compile', label: '编译', status: 'done', message: { summary: '签包构建通过' } },
      { id: 'probe', label: '业务测试', status: 'pending' },
    ],
  }] } }
}
async function fillRequest(wrapper: Awaited<ReturnType<typeof setup>>['wrapper']) {
  await wrapper.get('.private-mod-intake__toggle').trigger('click')
  await wrapper.get('input[maxlength="128"]').setValue('  工资核算员工  ')
  await wrapper.get('input[maxlength="64"]').setValue('  payroll-employee  ')
  await wrapper.get('input[value="employee"]').setValue(true)
  await wrapper.get('textarea[maxlength="12000"]').setValue('  按员工工时表计算每月应发工资并定位异常记录  ')
  await wrapper.get('textarea[maxlength="6000"]').setValue('  月工资与已知样例金额一致  ')
}

it('requires usable requirements and acceptance criteria before creating a customer ticket', async () => {
  const { wrapper } = await setup()
  await wrapper.get('.private-mod-intake__toggle').trigger('click')
  await wrapper.get('input[maxlength="128"]').setValue('工资核算')
  await wrapper.get('.private-mod-intake__form').trigger('submit')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('请完整填写需求名称、需求说明和验收标准')
  expect(apiFetch).toHaveBeenCalledTimes(1)
  wrapper.unmount()
})

it('submits the selected employee requirements and displays the newly accepted production ticket', async () => {
  const { wrapper } = await setup()
  await fillRequest(wrapper)
  vi.mocked(apiFetch).mockResolvedValueOnce(centerResponse({}))
    .mockResolvedValueOnce(centerResponse({ requests: [{ ...ticket, title: '工资核算员工' }], projects: [] }))
  await wrapper.get('.private-mod-intake__form').trigger('submit')
  await flushPromises()
  expect(apiFetch).toHaveBeenNthCalledWith(2, '/api/mod-store/private-delivery/requests', expect.objectContaining({
    method: 'POST', body: JSON.stringify({ kind: 'employee', title: '工资核算员工',
      requirements: '按员工工时表计算每月应发工资并定位异常记录', acceptance_criteria: '月工资与已知样例金额一致', suggested_id: 'payroll-employee' }),
  }))
  expect(wrapper.find('.private-mod-intake__form').exists()).toBe(false)
  expect(wrapper.get('.private-mod-request h5').text()).toBe('工资核算员工')
  wrapper.unmount()
})

it.each(['rejected', 'network', 'invalid-json'])('keeps the filled request available after %s failure', async kind => {
  const { wrapper } = await setup()
  await fillRequest(wrapper)
  if (kind === 'network') vi.mocked(apiFetch).mockRejectedValueOnce(new Error('连接暂不可用'))
  else vi.mocked(apiFetch).mockResolvedValueOnce(kind === 'invalid-json'
    ? new Response('gateway down', { status: 503 })
    : new Response(JSON.stringify({ detail: '工单服务繁忙，请稍后重试' }), { status: 503 }))
  await wrapper.get('.private-mod-intake__form').trigger('submit')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain(kind === 'network' ? '连接暂不可用' : kind === 'invalid-json' ? 'HTTP 503' : '工单服务繁忙')
  expect((wrapper.get('input[maxlength="128"]').element as HTMLInputElement).value).toContain('工资核算员工')
  expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeUndefined()
  wrapper.unmount()
})

it('accepts tested delivery and shows installation pending until runtime verification completes', async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(centerResponse({ requests: [acceptanceTicket()] }))
  const { wrapper } = await setup()
  expect(wrapper.text()).toContain('签包构建通过')
  expect(wrapper.text()).toContain('待执行')
  vi.mocked(apiFetch).mockResolvedValueOnce(centerResponse({})).mockResolvedValueOnce(response())
  await wrapper.get('.private-mod-request__actions .private-mod-center__update').trigger('click')
  await flushPromises()
  expect(apiFetch).toHaveBeenNthCalledWith(2, '/api/mod-store/private-delivery/requests/7/decision', expect.objectContaining({
    body: JSON.stringify({ action: 'accept' }),
  }))
  expect(wrapper.get('.private-mod-request__delivery').text()).toContain('自动验证运行与业务结果')
  expect(wrapper.find('.private-mod-request__delivered').exists()).toBe(false)
  wrapper.unmount()
})

it('validates actionable rework notes and sends them on the original acceptance ticket', async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(centerResponse({ requests: [acceptanceTicket()] }))
  const { wrapper } = await setup()
  const toggle = wrapper.get('.private-mod-request__actions .private-mod-node__action--rework')
  await toggle.trigger('click')
  await toggle.trigger('click')
  expect(wrapper.find('.private-mod-request__rework').exists()).toBe(false)
  await toggle.trigger('click')
  await wrapper.get('.private-mod-request__rework button').trigger('click')
  expect(wrapper.get('[role="alert"]').text()).toContain('返工意见至少 4 个字')
  expect(apiFetch).toHaveBeenCalledTimes(1)
  await wrapper.get('.private-mod-request__rework textarea').setValue('加班工资未按两倍时薪计算')
  vi.mocked(apiFetch).mockResolvedValueOnce(centerResponse({})).mockResolvedValueOnce(centerResponse({ requests: [] }))
  await wrapper.get('.private-mod-request__rework button').trigger('click')
  await flushPromises()
  expect(apiFetch).toHaveBeenNthCalledWith(2, '/api/mod-store/private-delivery/requests/7/decision', expect.objectContaining({
    body: JSON.stringify({ action: 'rework', note: '加班工资未按两倍时薪计算' }),
  }))
  expect(wrapper.find('.private-mod-request__rework').exists()).toBe(false)
  wrapper.unmount()
})

it('leaves acceptance available if the remote decision is rejected', async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(centerResponse({ requests: [acceptanceTicket()] }))
  const { wrapper } = await setup()
  vi.mocked(apiFetch).mockResolvedValueOnce(new Response(JSON.stringify({ message: '验收状态已变化' }), { status: 409 }))
  await wrapper.get('.private-mod-request__actions .private-mod-center__update').trigger('click')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toBe('验收状态已变化')
  expect(wrapper.get('.private-mod-request__actions button').attributes('disabled')).toBeUndefined()
  wrapper.unmount()
})

function privateProject() {
  return { mod_id: 'private-payroll', name: '工资核算', current_version: '1.0.0', latest_version: '1.1.0', update_available: true,
    tracks: { modules: { status: 'testing' }, employees: { status: 'delivered' } },
    track_nodes: { modules: [
      { id: 'payroll', label: '工资计算', status: 'testing', next_stages: ['acceptance', 'rework'] },
      { id: 'export', label: '工资导出', status: 'rework', next_stages: ['testing'],
        timeline: [{ status: 'testing' }, { status: 'rework', note: '日期格式与银行要求不符' }] },
    ], employees: [{ id: 'checks', label: '异常核对', status: 'delivered', next_stages: [] }] },
  }
}

it('shows module and employee progress and updates the exact offered private version', async () => {
  const project = privateProject()
  vi.mocked(apiFetch).mockResolvedValueOnce(centerResponse({ projects: [project], requests: [],
    happy_path: ['production', 'testing', 'acceptance', 'delivered'], stage_flow: { testing: { label: '测试中', goal: '用真实工资样例验证' } } }))
  const { wrapper } = await setup()
  expect(wrapper.text()).toContain('用真实工资样例验证')
  expect(wrapper.text()).toContain('日期格式与银行要求不符')
  expect(wrapper.text()).toContain('返工完成，重回测试')
  expect(wrapper.findAll('.private-mod-track--employees .private-mod-flow__step').every(node => node.attributes('data-done') === 'true')).toBe(true)
  vi.mocked(apiFetch).mockResolvedValueOnce(centerResponse({})).mockResolvedValueOnce(centerResponse({ projects: [{ ...project, current_version: '1.1.0', update_available: false }] }))
  await wrapper.get('.private-mod-project__update button').trigger('click')
  await flushPromises()
  expect(apiFetch).toHaveBeenNthCalledWith(2, '/api/mod-store/private-mod/update', expect.objectContaining({
    body: JSON.stringify({ mod_id: 'private-payroll', expected_version: '1.1.0' }),
  }))
  expect(wrapper.get('.private-mod-project__meta').text()).toContain('当前 v1.1.0')
  expect(wrapper.find('.private-mod-project__update').exists()).toBe(false)
  wrapper.unmount()
})

it('advances a tested node and requires an actionable issue before sending it to rework', async () => {
  vi.mocked(apiFetch).mockResolvedValue(centerResponse({ projects: [privateProject()] }))
  const { wrapper } = await setup()
  vi.mocked(apiFetch).mockImplementation(async () => centerResponse({ projects: [privateProject()] }))
  await wrapper.findAll('.private-mod-node__actions button')[0].trigger('click')
  await flushPromises()
  expect(apiFetch).toHaveBeenNthCalledWith(2, '/api/mod-store/private-delivery/status', expect.objectContaining({
    body: JSON.stringify({ mod_id: 'private-payroll', track: 'modules', node_id: 'payroll', status: 'acceptance' }),
  }))
  await wrapper.findAll('.private-mod-node__actions button')[1].trigger('click')
  expect(wrapper.get('[role="dialog"]').text()).toContain('工资计算')
  await wrapper.get('.private-mod-rework__cancel').trigger('click')
  expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  await wrapper.findAll('.private-mod-node__actions button')[1].trigger('click')
  await wrapper.get('.private-mod-rework').trigger('submit')
  expect(wrapper.get('[role="alert"]').text()).toContain('须填写问题说明')
  await wrapper.get('#private-mod-rework-problem').setValue('夜班跨日时工时合计错误')
  await wrapper.get('.private-mod-rework').trigger('submit')
  await flushPromises()
  expect(apiFetch).toHaveBeenNthCalledWith(4, '/api/mod-store/private-delivery/status', expect.objectContaining({
    body: JSON.stringify({ mod_id: 'private-payroll', track: 'modules', node_id: 'payroll', status: 'rework', note: '夜班跨日时工时合计错误' }),
  }))
  expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  wrapper.unmount()
})

it.each(['version', 'stage'])('keeps the previous %s when the server rejects the requested change', async kind => {
  vi.mocked(apiFetch).mockResolvedValueOnce(centerResponse({ projects: [privateProject()] }))
  const { wrapper } = await setup()
  vi.mocked(apiFetch).mockResolvedValueOnce(new Response(JSON.stringify({ detail: '交付版本或流程状态已变化，请刷新' }), { status: 409 }))
  const action = kind === 'version' ? wrapper.get('.private-mod-project__update button') : wrapper.findAll('.private-mod-node__actions button')[0]
  await action.trigger('click')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('请刷新')
  expect(wrapper.get('.private-mod-project__meta').text()).toContain('当前 v1.0.0')
  expect(wrapper.findAll('.private-mod-node')[0].attributes('data-status')).toBe('testing')
  expect(action.attributes('disabled')).toBeUndefined()
  wrapper.unmount()
})
