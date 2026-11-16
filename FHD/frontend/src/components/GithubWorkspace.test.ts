import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { ElCheckbox, ElInput } from 'element-plus'
import Workspace from '../../../admin-console/src/components/workflow/GithubEmployeeWorkspace.vue'
import Ticket from '../../../admin-console/src/components/workflow/TicketGithubPanel.vue'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/api/core', () => ({ default: api, ApiError: class extends Error {} }))
vi.mock('@host/components/employeeWorkspace/EmployeeWorkspaceLoopConsole.vue', () => ({ default: { template: '<div>原执行记录</div>' } }))
let wrapper: ReturnType<typeof mount>
const blank = { repository: '42433422/XCMAX', configured: true, para_configured: true, pulls: [] }
beforeEach(() => {
  vi.clearAllMocks()
  api.get.mockResolvedValue(blank)
  api.post.mockResolvedValue({})
})
afterEach(() => {
  wrapper?.unmount()
  document.body.innerHTML = ''
})
const button = (text: string) => wrapper.findAll('button').find((b) => b.text().includes(text))!

describe('GitHub repair console', () => {
  it('requires preview and explicit public confirmation; never copies customer evidence', async () => {
    wrapper = mount(Ticket, { props: { ticketId: 1, ticketStatus: 'open' }, attachTo: document.body })
    await flushPromises()
    expect(wrapper.find('input').element.value).toBe('')
    expect(button('创建 GitHub Issue').attributes('disabled')).toBeDefined()
    const inputs = wrapper.findAllComponents(ElInput)
    await inputs[0].vm.$emit('update:modelValue', '员工图谱不能显示')
    await inputs[1].vm.$emit('update:modelValue', '复现步骤：打开员工图谱。预期：正常显示节点。实际：没有节点。验收：节点正常。')
    await button('预览提交内容').trigger('click')
    await wrapper.findComponent(ElCheckbox).vm.$emit('update:modelValue', true)
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(api.post).toHaveBeenCalledTimes(1)
    expect(api.post.mock.calls[0][1]).toEqual(expect.objectContaining({ confirm_public: true, title: '员工图谱不能显示' }))
    expect(Object.keys(api.post.mock.calls[0][1]).sort()).toEqual(['body', 'confirm_public', 'title'])
  })

  it('changing preview content revokes prior public confirmation', async () => {
    wrapper = mount(Ticket, { props: { ticketId: 1 } })
    await flushPromises()
    await wrapper.findComponent(ElCheckbox).vm.$emit('update:modelValue', true)
    await wrapper.findAllComponents(ElInput)[0].vm.$emit('update:modelValue', '改变了标题')
    await flushPromises()
    expect(button('创建 GitHub Issue').attributes('disabled')).toBeDefined()
  })

  it('shows uncertain execution and offers reconciliation without dispatching twice', async () => {
    api.get.mockResolvedValue({
      ...blank,
      issue: { number: 123, url: 'https://github.com/42433422/XCMAX/issues/123', status: 'completed' },
      run: { status: 'unknown' },
    })
    wrapper = mount(Ticket, { props: { ticketId: 1 } })
    await flushPromises()
    expect(wrapper.text()).toContain('派工结果待核对')
    expect(button('交给 AI 员工').attributes('disabled')).toBeDefined()
    await button('查询回执').trigger('click')
    await flushPromises()
    expect(api.post).toHaveBeenCalledWith('/api/xcmax/admin/customer-service/tickets/1/github/reconcile', {})
    expect(wrapper.text()).toContain('原客户确认')
  })

  it('drops responses for a previously selected customer ticket', async () => {
    let resolveFirst!: (value: unknown) => void
    api.get.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveFirst = resolve
        }),
    )
    wrapper = mount(Ticket, { props: { ticketId: 1 } })
    await wrapper.setProps({ ticketId: 2 })
    await flushPromises()
    resolveFirst({ ...blank, issue: { number: 999, status: 'completed', url: 'https://github.com/42433422/XCMAX/issues/999' } })
    await flushPromises()
    expect(wrapper.text()).not.toContain('#999')
  })

  it('keeps the workspace empty until real issues are linked', async () => {
    api.get.mockResolvedValue({ ...blank, configured: false, items: [] })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: '<div />' } },
        { path: '/tickets', name: 'customer-service-tickets', component: { template: '<div />' } },
      ],
    })
    await router.push('/')
    wrapper = mount(Workspace, { global: { plugins: [router] } })
    await flushPromises()
    expect(wrapper.text()).toContain('云端连接尚未配置')
    expect(wrapper.text()).toContain('暂无关联的 Issue')
    await button('从工单发起').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('customer-service-tickets')
  })
})
