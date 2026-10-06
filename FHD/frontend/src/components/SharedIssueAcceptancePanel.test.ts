import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import SharedIssueAcceptancePanel from './SharedIssueAcceptancePanel.vue'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { apiFetch } from '@/utils/apiBase'

vi.mock('@/utils/apiBase', () => ({ apiFetch: vi.fn() }))
const repair = { id: 12, ticket_no: 'CS-12', summary: '保存订单失败', ready: true }
const response = (items = [repair]) => new Response(JSON.stringify({ success: true, data: { items } }))
async function setup() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const account = useAccountProfileStore()
  account.marketUserId = 1
  const wrapper = mount(SharedIssueAcceptancePanel, { global: { plugins: [pinia] } })
  await flushPromises()
  return { wrapper, account }
}
beforeEach(() => { vi.clearAllMocks(); vi.mocked(apiFetch).mockImplementation(async () => response()) })

it('never confirms automatically; accepts only an explicit customer result', async () => {
  const { wrapper } = await setup()
  expect(apiFetch).toHaveBeenCalledTimes(1)
  expect(wrapper.get('button').attributes('disabled')).toBeDefined()
  await wrapper.get('input').setValue('保存成功了')
  vi.mocked(apiFetch).mockResolvedValueOnce(response([])).mockResolvedValueOnce(response([]))
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(apiFetch).toHaveBeenNthCalledWith(2, '/api/mod-store/issue-runtime/12', expect.objectContaining({ method: 'POST', body: JSON.stringify({ confirmed: true, note: '保存成功了' }) }))
  expect(wrapper.find('article').exists()).toBe(false)
  wrapper.unmount()
})

it('keeps the ticket visible when confirmation is not saved', async () => {
  const { wrapper } = await setup()
  await wrapper.get('input').setValue('保存成功了')
  vi.mocked(apiFetch).mockResolvedValueOnce(new Response(JSON.stringify({ detail: '客户端需先更新' }), { status: 409 }))
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('客户端需先更新')
  expect(wrapper.find('article').exists()).toBe(true)
  wrapper.unmount()
})

it('discards late responses and customer notes when the account changes', async () => {
  let finish: ((value: Response) => void) | undefined
  vi.mocked(apiFetch).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
  const { wrapper, account } = await setup()
  vi.mocked(apiFetch).mockResolvedValueOnce(response([{ ...repair, id: 13, summary: '账号二的问题' }]))
  account.marketUserId = 2
  await flushPromises()
  finish?.(response())
  await flushPromises()
  expect(wrapper.text()).toContain('账号二的问题')
  expect(wrapper.text()).not.toContain('保存订单失败')
  account.marketUserId = null
  await flushPromises()
  expect(wrapper.find('article').exists()).toBe(false)
  wrapper.unmount()
})

it('has no acceptance control until the repair reaches the current client', async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(response([{ ...repair, ready: false }]))
  const { wrapper } = await setup()
  expect(wrapper.find('input').exists()).toBe(false)
  expect(wrapper.find('button').exists()).toBe(false)
  expect(wrapper.text()).toContain('尚未到达当前客户端')
  wrapper.unmount()
})

it('lets the owner reopen any product issue and retries with the same idempotency key', async () => {
  const issue = { id: 21, ticket_no: 'CI-21', summary: '导出报错', ready: false, state: 'awaiting_delivery', can_resolve: true, can_reopen: true, latest_result: { team_ok: true, progress: '修复（fix）已完成' } }
  vi.mocked(apiFetch).mockResolvedValueOnce(response([issue]))
  const { wrapper } = await setup()
  expect(wrapper.text()).toContain('AI 已提交处理结果')
  expect(wrapper.text()).toContain('修复（fix）已完成')
  expect(wrapper.findAll('button').map((button) => button.text())).toEqual(['已解决', '仍未解决，重新打开'])
  expect(wrapper.findAll('button').at(-1)?.attributes('disabled')).toBeDefined()
  await wrapper.get('input').setValue('导出还是报错')
  vi.mocked(apiFetch).mockResolvedValueOnce(new Response(JSON.stringify({ detail: '网络中断' }), { status: 502 }))
  await wrapper.findAll('button').at(-1)?.trigger('click')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('网络中断')
  vi.mocked(apiFetch).mockResolvedValueOnce(new Response(JSON.stringify({ success: true, data: {} }))).mockResolvedValueOnce(response([]))
  await wrapper.findAll('button').at(-1)?.trigger('click')
  await flushPromises()
  const posts = vi.mocked(apiFetch).mock.calls.filter(([url]) => url === '/api/mod-store/issue-runtime/21/decision')
  const [first, retry] = posts.map(([, init]) => JSON.parse(String(init?.body)))
  expect(posts).toHaveLength(2)
  expect(retry).toEqual(first)
  expect(first).toMatchObject({ decision: 'reopen', note: '导出还是报错' })
  expect(wrapper.find('article').exists()).toBe(false)
  wrapper.unmount()
})

it('offers only reopen on a closed ticket', async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(response([{ id: 22, ticket_no: 'CI-22', summary: '打印乱码', ready: false, state: 'resolved', can_resolve: false, can_reopen: true }]))
  const { wrapper } = await setup()
  expect(wrapper.text()).toContain('工单已关闭')
  expect(wrapper.findAll('button').map((button) => button.text())).toEqual(['仍未解决，重新打开'])
  wrapper.unmount()
})
