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
