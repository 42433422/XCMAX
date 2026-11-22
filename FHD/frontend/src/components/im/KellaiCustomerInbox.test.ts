import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import KellaiCustomerInbox from './KellaiCustomerInbox.vue'
import KellaiMessageComposer from './kellaiInbox/KellaiMessageComposer.vue'
import { deliveryTargetKey, useKellaiStore } from '@/stores/kellai'

const kellaiMocks = vi.hoisted(() => ({
  status: vi.fn(), start: vi.fn(), contacts: vi.fn(), messages: vi.fn(), channels: vi.fn(),
  disconnect: vi.fn(), sendReceipt: vi.fn(), sendMessage: vi.fn(),
}))
vi.mock('@/api/kellaiBinding', () => ({ default: kellaiMocks, kellaiBindingApi: kellaiMocks }))
const contact = { customer_id: 7, connection_id: 'account-a', channel_type: 'chatwoot', contact_id: 'conversation-9', contact_name: '王女士' }
const connectedStatus = {
  state: 'connected' as const,
  connection: { connection_id: 'pairing-a', authorized_scopes: ['messages.read'], authorized_by: { display_name: '企业负责人' } },
  available_scopes: [],
}

describe('Kellai unified inbox', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    Object.values(kellaiMocks).forEach(mock => mock.mockReset())
    kellaiMocks.status.mockResolvedValue(connectedStatus)
    kellaiMocks.contacts.mockResolvedValue([{ ...contact }])
    kellaiMocks.channels.mockResolvedValue([])
    kellaiMocks.messages.mockResolvedValue([
      { id: 'm2', customer_id: 7, connection_id: 'account-a', direction: 'outbound', content: '我来确认交付时间。', created_at: '2026-07-15T10:02:00Z', channel_type: 'chatwoot' },
      { id: 'm1', customer_id: 7, connection_id: 'account-a', direction: 'inbound', content: '请问什么时候可以交付？', created_at: '2026-07-15T10:01:00Z', channel_type: 'chatwoot' },
    ])
    kellaiMocks.start.mockResolvedValue({ request_id: 'req-1', expires_at: '2026-07-15T10:15:00Z' })
    kellaiMocks.disconnect.mockResolvedValue(undefined)
    ;(window as Window & { xcagiDesktop?: unknown }).xcagiDesktop = undefined
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    ;(window as Window & { xcagiDesktop?: unknown }).xcagiDesktop = undefined
  })

  it('requires selecting an account contact before reading its messages and keeps read-only grants read-only', async () => {
    const wrapper = mount(KellaiCustomerInbox)
    await flushPromises()
    expect(wrapper.text()).toContain('统一聊天 · 客来来')
    expect(wrapper.text()).toContain('王女士')
    expect(wrapper.text()).toContain('account-a')
    expect(kellaiMocks.messages).not.toHaveBeenCalled()
    await wrapper.get('.kellai-inbox__customer').trigger('click')
    await flushPromises()
    expect(kellaiMocks.messages).toHaveBeenCalledExactlyOnceWith(7, 'account-a', 100)
    const text = wrapper.get('.kellai-inbox__messages').text()
    expect(text.indexOf('请问什么时候可以交付？')).toBeLessThan(text.indexOf('我来确认交付时间。'))
    expect(wrapper.find('textarea').exists()).toBe(false)
    expect(kellaiMocks.sendMessage).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('requires an explicit recipient selection even when one account is available', async () => {
    const store = useKellaiStore()
    store.contacts = [{ ...contact }]
    store.activeContactId = 7
    store.activeConnectionId = 'account-a'
    store.channels = [{ connection_id: 'account-a', channel_type: 'chatwoot', name: '支持账号', enabled: true, connected: true, capabilities: { send: true, receive: true } }]
    const submit = vi.spyOn(store, 'submitMessage').mockResolvedValue(undefined)
    const wrapper = mount(KellaiMessageComposer)
    expect(wrapper.find('textarea').exists()).toBe(false)
    await wrapper.get('select').setValue(deliveryTargetKey(contact))
    await wrapper.get('textarea').setValue('确认交付时间')
    expect(submit).not.toHaveBeenCalled()
    await wrapper.get('button').trigger('click')
    expect(submit).toHaveBeenCalledExactlyOnceWith({ customer_id: 7, connection_id: 'account-a', channel_type: 'chatwoot', contact_id: 'conversation-9', content: '确认交付时间' })
    store.activeConnectionId = 'account-b'
    await flushPromises()
    expect(wrapper.find('textarea').exists()).toBe(false)
    wrapper.unmount()
  })

  it.each([
    ['accepted', undefined, '渠道已受理', true],
    ['accepted', 'accepted', '渠道已受理', true],
    ['accepted', 'sent', '渠道确认已发出', true],
    ['accepted', 'delivered', '渠道确认送达', false],
    ['accepted', 'read', '渠道确认已读', false],
    ['accepted', 'failed', '发送失败', false],
    ['unknown', 'delivered', '发送结果未知', false],
    ['sending', 'read', '发送处理中', false],
    ['failed', 'delivered', '发送失败', false],
  ])('renders ledger %s with provider %s without inventing delivery confirmation', async (status, providerState, label, awaitingDelivery) => {
    const store = useKellaiStore()
    store.activeContactId = 7
    store.activeConnectionId = 'account-a'
    const key = deliveryTargetKey({ customer_id: 7, connection_id: 'account-a', channel_type: 'chatwoot', contact_id: 'conversation-9' })
    store.deliveries['request-original-123'] = {
      request_id: 'request-original-123', target_key: key, checking: false, error: '',
      receipt: { request_id: 'request-original-123', status: status as string, provider_state: providerState as string | undefined },
    }
    const wrapper = mount(KellaiMessageComposer)
    await flushPromises()
    const receipt = wrapper.get('.kellai-composer__receipt')
    expect(receipt.get('strong').text()).toBe(label)
    expect(receipt.text().includes('尚无送达确认')).toBe(awaitingDelivery)
    if (status === 'unknown' || status === 'sending') {
      expect(receipt.text()).toContain('请查询原请求回执，暂不重复发送')
      expect(receipt.text()).not.toContain('渠道确认送达')
      expect(receipt.text()).not.toContain('渠道确认已读')
    }
    expect(store.deliveries['request-original-123'].receipt.status).toBe(status)
    wrapper.unmount()
  })

  it('shows and queries each receipt independently for consecutive messages to the same target', async () => {
    const store = useKellaiStore()
    store.binding = { state: 'connected', connection: { connection_id: 'paired', authorized_scopes: ['messages.send'] } }
    store.activeContactId = 7
    store.activeConnectionId = 'account-a'
    const targetKey = deliveryTargetKey({ customer_id: 7, connection_id: 'account-a', channel_type: 'chatwoot', contact_id: 'conversation-9' })
    for (const id of ['first-request-123', 'second-request-123']) {
      store.deliveries[id] = { request_id: id, target_key: targetKey, checking: false, error: '', receipt: { request_id: id, status: 'accepted' } }
    }
    kellaiMocks.sendReceipt.mockResolvedValue({ request_id: 'first-request-123', status: 'accepted', provider_state: 'delivered' })
    const wrapper = mount(KellaiMessageComposer)
    expect(wrapper.findAll('.kellai-composer__receipt')).toHaveLength(2)
    await wrapper.findAll('.kellai-composer__receipt')[0].get('button').trigger('click')
    await flushPromises()
    expect(kellaiMocks.sendReceipt).toHaveBeenCalledExactlyOnceWith('first-request-123')
    const receipts = wrapper.findAll('.kellai-composer__receipt')
    expect(receipts[0].text()).toContain('first-request-123')
    expect(receipts[0].get('strong').text()).toBe('渠道确认送达')
    expect(receipts[1].text()).toContain('second-request-123')
    expect(receipts[1].get('strong').text()).toBe('渠道已受理')
    expect(kellaiMocks.sendMessage).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('starts read-only pairing and opens the local tool for explicit confirmation', async () => {
    kellaiMocks.status.mockResolvedValue({ state: 'not_connected', available_scopes: [{ id: 'messages.read', label: '读取联系人与消息', description: '按账号读取' }] })
    const openKellaiDesktop = vi.fn().mockResolvedValue({ ok: true })
    ;(window as Window & { xcagiDesktop?: unknown }).xcagiDesktop = { openKellaiDesktop }
    const wrapper = mount(KellaiCustomerInbox)
    await flushPromises()
    await wrapper.get('.kellai-inbox__button.is-primary').trigger('click')
    await flushPromises()
    expect(kellaiMocks.start).toHaveBeenCalledExactlyOnceWith(undefined)
    expect(openKellaiDesktop).toHaveBeenCalledOnce()
    expect(kellaiMocks.sendMessage).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
