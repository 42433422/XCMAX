import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api/core'
import NotificationInbox from './NotificationInbox.vue'

vi.mock('@/api/core', () => ({ api: { get: vi.fn(), post: vi.fn() } }))
enableAutoUnmount(afterEach)
afterEach(() => {
  vi.resetAllMocks()
  vi.restoreAllMocks()
  vi.useRealTimers()
})

const inbox = '/api/mobile/v1/notifications/inbox'
function notice(id: number, title: string, read = false) {
  return { id, title, body: title + '正文', is_read: read, read_at: read ? '2026-11-26T03:00:00Z' : null }
}
function page(notifications: ReturnType<typeof notice>[], next_before_id: number | null = null) {
  return { success: true, data: { notifications, next_before_id } }
}

describe('NotificationInbox', () => {
  it('shows cursor pages, deduplicates overlapping rows and applies only the confirmed read receipt', async () => {
    const first = notice(4, '审批结果')
    const older = notice(3, '任务回执')
    let release!: (response: ReturnType<typeof page>) => void
    vi.mocked(api.get).mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
      .mockResolvedValueOnce(page([first, older]))
    vi.mocked(api.post).mockResolvedValueOnce({ success: true, data: notice(4, '审批结果', true) })
    const view = mount(NotificationInbox, { props: { scopeKey: 'tenant:1' } })
    await view.vm.$nextTick()
    expect(view.get('[role="status"]').text()).toContain('正在同步')
    release(page([first], 4))
    await flushPromises()
    const button = (label: string) => view.findAll('button').find(item => item.text() === label)!
    await button('更早通知').trigger('click')
    await flushPromises()
    expect(api.get).toHaveBeenLastCalledWith(inbox, { limit: 50, before_id: 4 }, { signal: expect.any(AbortSignal) })
    expect(view.findAll('article').map(item => item.get('strong').text())).toEqual(['审批结果', '任务回执'])
    expect(button('更早通知')).toBeUndefined()
    await view.get('article button').trigger('click')
    await flushPromises()
    expect(api.post).toHaveBeenCalledExactlyOnceWith(
      '/api/mobile/v1/notifications/4/read', {}, { signal: expect.any(AbortSignal) },
    )
    expect(view.get('article').get('span').text()).toBe('已读')
    expect(view.get('article').find('button').exists()).toBe(false)
  })

  it('keeps a notification unread after a mismatched receipt and shows an explicit retry', async () => {
    vi.mocked(api.get)
      .mockResolvedValueOnce(page([notice(4, '审批结果')]))
      .mockResolvedValueOnce({ success: false })
      .mockResolvedValueOnce(page([]))
    vi.mocked(api.post).mockResolvedValueOnce({ success: true, data: notice(8, '其他通知', true) })
    const view = mount(NotificationInbox, { props: { scopeKey: 'tenant:1' } })
    await flushPromises()
    await view.get('article button').trigger('click')
    await flushPromises()
    expect(view.get('article span').text()).toBe('未读')
    expect(view.get('[role="alert"]').text()).toContain('未收到已读回执')
    await view.get('header button').trigger('click')
    await flushPromises()
    expect(view.get('[role="alert"]').text()).toContain('通知同步失败')
    await view.get('header button').trigger('click')
    await flushPromises()
    expect(view.text()).toContain('暂无通知')
  })

  it('retires an old account read, polls only while visible and stops after unmount', async () => {
    vi.useFakeTimers()
    let release!: (response: ReturnType<typeof page>) => void
    vi.mocked(api.get).mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
      .mockResolvedValue(page([notice(7, '当前账号')]))
    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    const view = mount(NotificationInbox, { props: { scopeKey: 'tenant:1' } })
    const oldSignal = vi.mocked(api.get).mock.calls[0][2]?.signal
    await view.setProps({ scopeKey: 'tenant:2' })
    await flushPromises()
    expect(oldSignal?.aborted).toBe(true)
    release(page([notice(4, '上个账号')]))
    await flushPromises()
    expect(view.get('article').text()).toContain('当前账号')
    expect(view.text()).not.toContain('上个账号')

    await vi.advanceTimersByTimeAsync(10_000)
    expect(api.get).toHaveBeenCalledTimes(2)
    visibility.mockReturnValue('visible')
    document.dispatchEvent(new Event('visibilitychange'))
    await flushPromises()
    expect(api.get).toHaveBeenCalledTimes(3)
    view.unmount()
    await vi.advanceTimersByTimeAsync(10_000)
    document.dispatchEvent(new Event('visibilitychange'))
    expect(api.get).toHaveBeenCalledTimes(3)
  })
})
