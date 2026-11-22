import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { deliveryTargetKey, useKellaiStore } from './kellai'

const api = vi.hoisted(() => ({
  status: vi.fn(), dataStatus: vi.fn(), customers: vi.fn(), channels: vi.fn(), conversations: vi.fn(),
  latestDraft: vi.fn(), followUpOverview: vi.fn(), generateDraft: vi.fn(), sendMessage: vi.fn(), sendReceipt: vi.fn(),
  start: vi.fn(), disconnect: vi.fn(),
}))
vi.mock('@/api/kellaiBinding', () => ({ default: api }))
const customer = { customer_id: 7, display_name: '客户甲' }
const recipient = { customer_id: 7, channel_type: 'chatwoot', contact_id: 'conversation-9', content: '已人工确认' }
const key = deliveryTargetKey(recipient)
const allScopes = ['customer_profiles.read', 'customer_conversations.read', 'channels.read', 'messages.send']
const connection = { state: 'connected', connection: { connection_id: 'conn-a', authorized_scopes: allScopes } }
const owner = { tenantId: 3, localUserId: 1, accountKind: 'enterprise' }
const storageKey = 'kellai-requests:[3,null,1,"enterprise","conn-a"]'
const channel = { id: 1, type: 'chatwoot', name: 'Chatwoot', connected: true, enabled: true, connection_id: 'team:chatwoot:primary', capabilities: { send: true, receive: true, contacts: true, sync: true } }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(next => { resolve = next }); return { promise, resolve } }

describe('Kellai shared account and delivery state', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
    sessionStorage.clear()
    setRuntimeTenantStorageScopeInput(owner)
    api.status.mockResolvedValue(connection)
    api.dataStatus.mockResolvedValue({ customer_count: 1, unread_message_count: 0 })
    api.customers.mockResolvedValue([customer])
    api.channels.mockResolvedValue([channel])
    api.conversations.mockResolvedValue([])
    api.latestDraft.mockResolvedValue(null)
    api.followUpOverview.mockResolvedValue({ tasks: [], metrics: null })
    api.sendMessage.mockImplementation(async (input: { client_request_id: string }) => ({ request_id: input.client_request_id, status: 'accepted', persisted: true }))
    api.sendReceipt.mockImplementation(async (request_id: string) => ({ request_id, status: 'unknown' }))
  })
  afterEach(() => vi.restoreAllMocks())

  it('shares one binding and never reads channel capability under the old read-only grant', async () => {
    api.status.mockResolvedValue({ ...connection, connection: { ...connection.connection, authorized_scopes: allScopes.slice(0, 2) } })
    const store = useKellaiStore()
    expect(useKellaiStore()).toBe(store)
    await store.refreshAll()
    expect(store.customers).toEqual([customer])
    expect(store.canSend).toBe(false)
    expect(api.channels).not.toHaveBeenCalled()
    await store.submitMessage(recipient)
    expect(api.sendMessage).not.toHaveBeenCalled()
  })

  it('retires old reads on an account A → B → A change', async () => {
    const old = deferred<typeof connection>()
    api.status.mockReturnValueOnce(old.promise)
    const store = useKellaiStore()
    const loading = store.refreshAll()
    productReadAccountEpoch.value++
    productReadAccountEpoch.value++
    api.customers.mockResolvedValue([{ customer_id: 9, display_name: '新账号客户' }])
    await store.refreshAll()
    old.resolve(connection)
    await loading
    expect(store.customers.map(item => item.customer_id)).toEqual([9])
    expect(store.busy).toBe(false)
  })

  it('ignores late conversation and AI draft responses for the previous customer', async () => {
    const store = useKellaiStore()
    await store.refreshAll()
    const late = deferred<Array<{ id: string; customer_id: number; direction: string; content: string }>>()
    api.conversations.mockReturnValueOnce(late.promise)
    const previous = store.loadMessages(7)
    api.conversations.mockResolvedValue([{ id: 'next', customer_id: 8, direction: 'inbound', content: '客户乙消息' }])
    await store.selectCustomer({ customer_id: 8, display_name: '客户乙' })
    late.resolve([{ id: 'old', customer_id: 7, direction: 'inbound', content: '客户甲私密消息' }])
    await previous
    expect(store.messages.map(item => item.id)).toEqual(['next'])
    const draft = deferred<unknown>()
    api.generateDraft.mockReturnValueOnce(draft.promise)
    const generating = store.generateCopilotDraft()
    await store.selectCustomer(customer)
    draft.resolve({ draft_id: 'old-draft', customer_id: 8, reply_draft: '旧客户回复' })
    await generating
    expect(store.copilotDraft).toBeNull()
  })

  it.each(['connected', 'offline'])('recovers the original unknown request after closing a window, initially %s', async initialState => {
    api.sendMessage.mockRejectedValueOnce(new Error('连接中断'))
    const store = useKellaiStore()
    await store.refreshAll()
    await store.submitMessage(recipient)
    const id = api.sendMessage.mock.calls[0][0].client_request_id
    expect(store.deliveries[id].receipt.status).toBe('unknown')
    await store.submitMessage(recipient)
    expect(api.sendMessage).toHaveBeenCalledTimes(1)
    expect(JSON.parse(localStorage.getItem(storageKey)!)).toEqual({ [id]: key })
    store.$dispose()
    sessionStorage.clear()
    setActivePinia(createPinia())
    api.status.mockResolvedValue({ ...connection, state: initialState })
    const recovered = useKellaiStore()
    await recovered.refreshAll()
    expect(recovered.deliveries[id].target_key).toBe(key)
    if (initialState === 'offline') {
      expect(api.sendReceipt).not.toHaveBeenCalled()
      api.status.mockResolvedValue(connection)
      await recovered.refreshAll()
    }
    expect(api.sendReceipt).toHaveBeenCalledExactlyOnceWith(id)
    expect(recovered.deliveries[id].receipt.status).toBe('unknown')
    await recovered.submitMessage(recipient)
    expect(api.sendMessage).toHaveBeenCalledTimes(1)
    api.sendReceipt.mockResolvedValue({ request_id: id, status: 'accepted', provider_message_id: 'provider-9', persisted: false })
    await recovered.queryReceipt(id)
    expect(api.sendReceipt).toHaveBeenCalledWith(id)
    expect(recovered.deliveries[id].receipt.status).toBe('accepted')
    expect(recovered.deliveries[id].receipt.persisted).toBe(false)
  })

  it('opens customers while historical receipts are slow, preserves dedupe and never runs a second recovery for the same scope', async () => {
    const ids = Array.from({ length: 6 }, (_, i) => `historical_request_${i}`)
    localStorage.setItem(storageKey, JSON.stringify(Object.fromEntries(ids.map(id => [id, key]))))
    const firstBatch = deferred<{ request_id: string; status: string }>()
    api.sendReceipt.mockImplementation((request_id: string) => ids.indexOf(request_id) < 4
      ? firstBatch.promise.then(receipt => ({ ...receipt, request_id }))
      : Promise.resolve({ request_id, status: 'delivered' }))
    const store = useKellaiStore()
    const opening = store.refreshAll()
    await flushPromises()
    expect(store.customers).toEqual([customer])
    expect(store.busy).toBe(false)
    expect(api.sendReceipt.mock.calls.map(([id]) => id)).toEqual(ids.slice(0, 4))
    await store.refreshAll()
    await store.submitMessage(recipient)
    expect(api.sendMessage).not.toHaveBeenCalled()
    expect(api.sendReceipt.mock.calls.map(([id]) => id)).toEqual(ids.slice(0, 4))
    firstBatch.resolve({ request_id: '', status: 'delivered' })
    await opening
    await flushPromises()
    expect(api.sendReceipt.mock.calls.map(([id]) => id)).toEqual(ids)
    expect(store.deliveries[ids[5]].receipt.status).toBe('delivered')
  })

  it('does not continue querying the old connection after its first recovery batch finishes late', async () => {
    const ids = Array.from({ length: 5 }, (_, i) => `historical_request_${i}`)
    localStorage.setItem(storageKey, JSON.stringify(Object.fromEntries(ids.map(id => [id, key]))))
    const late = deferred<{ request_id: string; status: string }>()
    api.sendReceipt.mockReturnValue(late.promise)
    const store = useKellaiStore()
    await store.refreshAll()
    expect(api.sendReceipt).toHaveBeenCalledTimes(4)
    api.status.mockResolvedValue({ ...connection, connection: { ...connection.connection, connection_id: 'conn-b' } })
    await store.refreshAll()
    late.resolve({ request_id: '', status: 'requires_desktop_execution' })
    await flushPromises()
    expect(api.sendReceipt).toHaveBeenCalledTimes(4)
    expect(store.deliveries).toEqual({})
    expect(JSON.parse(localStorage.getItem(storageKey)!)).toHaveProperty(ids[0], key)
    expect(localStorage.getItem(storageKey.replace('conn-a', 'conn-b'))).toBeNull()
  })

  it('isolates persistent request IDs by owner and connection and respects revoked send access', async () => {
    api.sendMessage.mockRejectedValueOnce(new Error('连接中断'))
    const store = useKellaiStore()
    await store.refreshAll()
    await store.submitMessage(recipient)
    const id = api.sendMessage.mock.calls[0][0].client_request_id
    setRuntimeTenantStorageScopeInput({ ...owner, localUserId: 2 })
    productReadAccountEpoch.value++
    await store.refreshAll()
    expect(store.deliveries).toEqual({})
    expect(api.sendReceipt).not.toHaveBeenCalled()
    setRuntimeTenantStorageScopeInput(owner)
    productReadAccountEpoch.value++
    await store.refreshAll()
    expect(store.deliveries[id].target_key).toBe(key)
    expect(api.sendReceipt).toHaveBeenCalledExactlyOnceWith(id)
    api.status.mockResolvedValue({ ...connection, connection: { ...connection.connection, connection_id: 'conn-b' } })
    await store.refreshAll()
    expect(store.deliveries).toEqual({})
    api.sendReceipt.mockClear()
    api.status.mockResolvedValue({ ...connection, connection: { ...connection.connection, authorized_scopes: allScopes.slice(0, 2) } })
    await store.refreshAll()
    await store.submitMessage(recipient)
    expect(store.deliveries[id].target_key).toBe(key)
    expect(api.sendReceipt).not.toHaveBeenCalled()
    expect(api.sendMessage).toHaveBeenCalledTimes(1)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    api.disconnect.mockResolvedValue(undefined)
    await store.disconnect()
    expect(localStorage.getItem(storageKey)).toBeNull()
    expect(store.deliveries).toEqual({})
  })

  it.each(['getItem', 'setItem'] as const)('does not post when persistent storage %s fails', async operation => {
    const store = useKellaiStore()
    await store.refreshAll()
    vi.spyOn(Storage.prototype, operation).mockImplementation(() => { throw new Error('storage unavailable') })
    await store.submitMessage(recipient)
    expect(api.sendMessage).not.toHaveBeenCalled()
    expect(store.deliveries).toEqual({})
    expect(store.error).toContain('请求号')
  })

  it.each(['delivered', 'failed'])('keeps both accepted requests when the first later becomes %s, including after reopening', async providerState => {
    const store = useKellaiStore()
    await store.refreshAll()
    const first = (await store.submitMessage(recipient))!
    const late = deferred<{ request_id: string; status: string; provider_state: string }>()
    api.sendReceipt.mockReturnValueOnce(late.promise)
    const checking = store.queryReceipt(first)
    const second = (await store.submitMessage({ ...recipient, content: '第二条已确认消息' }))!
    expect(first).not.toBe(second)
    expect(Object.keys(store.deliveries)).toEqual([first, second])
    expect(api.sendMessage).toHaveBeenCalledTimes(2)
    late.resolve({ request_id: first, status: 'accepted', provider_state: providerState })
    await checking
    expect(store.deliveries[first].receipt.provider_state).toBe(providerState)
    expect(store.deliveries[second].receipt).toEqual({ request_id: second, status: 'accepted', persisted: true })
    expect(JSON.parse(localStorage.getItem(storageKey)!)).toEqual({ [first]: key, [second]: key })
    store.$dispose()
    sessionStorage.clear()
    setActivePinia(createPinia())
    api.sendReceipt.mockClear()
    api.sendReceipt.mockImplementation(async (id: string) => {
      if (id === first) throw new Error('查询暂时中断')
      return { request_id: id, status: 'accepted' }
    })
    const recovered = useKellaiStore()
    await recovered.refreshAll()
    expect(api.sendReceipt.mock.calls.map(call => call[0])).toEqual([first, second])
    expect(recovered.deliveries[first].receipt.status).toBe('unknown')
    expect(recovered.deliveries[second].receipt.status).toBe('accepted')
    await recovered.submitMessage({ ...recipient, content: '尚不能提交的第三条' })
    expect(api.sendMessage).toHaveBeenCalledTimes(2)
    api.sendReceipt.mockResolvedValueOnce({ request_id: first, status: 'accepted', provider_state: providerState })
    await recovered.queryReceipt(first)
    expect(recovered.deliveries[first].receipt.provider_state).toBe(providerState)
    expect(recovered.deliveries[second].receipt).toEqual({ request_id: second, status: 'accepted' })
    expect(api.sendMessage).toHaveBeenCalledTimes(2)
  })

  it('preserves a legacy target-indexed request when adding the next accepted message', async () => {
    const original = 'legacy-request-123'
    localStorage.setItem(storageKey, JSON.stringify({ [key]: original }))
    api.sendReceipt.mockResolvedValue({ request_id: original, status: 'accepted' })
    const store = useKellaiStore()
    await store.refreshAll()
    expect(api.sendReceipt).toHaveBeenCalledExactlyOnceWith(original)
    const next = (await store.submitMessage(recipient))!
    expect(Object.keys(store.deliveries)).toEqual([original, next])
    expect(JSON.parse(localStorage.getItem(storageKey)!)).toEqual({ [original]: key, [next]: key })
  })

  it('limits receipt recovery concurrency without posting any restored request', async () => {
    const ids = Array.from({ length: 5 }, (_, index) => `restored-request-${index}`)
    localStorage.setItem(storageKey, JSON.stringify(Object.fromEntries(ids.map(id => [id, key]))))
    const batch = deferred<{ status: string }>()
    api.sendReceipt.mockImplementation(async (id: string) => ({ request_id: id, ...await batch.promise }))
    const store = useKellaiStore()
    const restoring = store.refreshAll()
    await flushPromises()
    expect(api.sendReceipt).toHaveBeenCalledTimes(4)
    expect(store.deliveries[ids[4]].receipt.status).toBe('unknown')
    await restoring
    batch.resolve({ status: 'accepted' })
    await flushPromises()
    expect(api.sendReceipt.mock.calls.map(call => call[0])).toEqual(ids)
    expect(api.sendMessage).not.toHaveBeenCalled()
  })

  it('does not restore a confirmed unexecuted desktop request as an unknown ledger entry', async () => {
    const native = { ...recipient, channel_type: 'wechat', contact_id: 'native-contact' }
    api.channels.mockResolvedValue([channel, { ...channel, type: 'wechat' }])
    const store = useKellaiStore()
    await store.refreshAll()
    const real = (await store.submitMessage(recipient))!
    api.sendMessage.mockImplementationOnce(async (input: { client_request_id: string }) => ({
      request_id: input.client_request_id, status: 'requires_desktop_execution', persisted: false,
    }))
    const unexecuted = (await store.submitMessage(native))!
    expect(store.deliveries[unexecuted].receipt.status).toBe('requires_desktop_execution')
    expect(JSON.parse(localStorage.getItem(storageKey)!)).toEqual({ [real]: key })
    store.$dispose()
    sessionStorage.clear()
    setActivePinia(createPinia())
    api.sendReceipt.mockResolvedValue({ request_id: real, status: 'accepted' })
    const recovered = useKellaiStore()
    await recovered.refreshAll()
    expect(Object.keys(recovered.deliveries)).toEqual([real])
    expect(api.sendReceipt).toHaveBeenCalledExactlyOnceWith(real)
    expect(recovered.blockedTargets.has(deliveryTargetKey(native))).toBe(false)
    expect(api.sendMessage).toHaveBeenCalledTimes(2)
  })

  it('retains a failed ledger receipt while allowing the next message to the same target', async () => {
    const store = useKellaiStore()
    await store.refreshAll()
    api.sendMessage.mockImplementationOnce(async (input: { client_request_id: string }) => ({
      request_id: input.client_request_id, status: 'failed', persisted: true, error: '渠道已明确拒绝',
    }))
    const failed = (await store.submitMessage(recipient))!
    expect(store.deliveries[failed].receipt.status).toBe('failed')
    expect(store.blockedTargets.has(key)).toBe(false)
    const next = (await store.submitMessage({ ...recipient, content: '下一条已确认消息' }))!
    expect(JSON.parse(localStorage.getItem(storageKey)!)).toEqual({ [failed]: key, [next]: key })
    store.$dispose()
    sessionStorage.clear()
    setActivePinia(createPinia())
    api.sendReceipt.mockImplementation(async (id: string) => ({ request_id: id, status: id === failed ? 'failed' : 'accepted' }))
    const recovered = useKellaiStore()
    await recovered.refreshAll()
    expect(api.sendReceipt.mock.calls.map(call => call[0])).toEqual([failed, next])
    expect(recovered.deliveries[failed].receipt.status).toBe('failed')
    expect(recovered.deliveries[next].receipt.status).toBe('accepted')
    expect(recovered.blockedTargets.has(key)).toBe(false)
    expect(api.sendMessage).toHaveBeenCalledTimes(2)
  })

  it('clears channel capabilities on failure and blocks sends to disabled channels', async () => {
    const store = useKellaiStore()
    await store.refreshAll()
    store.channels[0].connected = false
    await store.submitMessage(recipient)
    expect(api.sendMessage).not.toHaveBeenCalled()
    api.channels.mockRejectedValueOnce(new Error('客来来离线'))
    await store.refreshAll()
    expect(store.channels).toEqual([])
    expect(store.channelError).toBe('客来来离线')
    await store.submitMessage(recipient)
    expect(api.sendMessage).not.toHaveBeenCalled()
  })

  it('does not expose a send completion after the authenticated account changes', async () => {
    const pending = deferred<{ request_id: string; status: string }>()
    api.sendMessage.mockReturnValueOnce(pending.promise)
    const store = useKellaiStore()
    await store.refreshAll()
    const sending = store.submitMessage(recipient)
    await flushPromises()
    productReadAccountEpoch.value++
    pending.resolve({ request_id: 'private-receipt', status: 'accepted' })
    await sending
    expect(store.deliveries).toEqual({})
    expect(store.customers).toEqual([])
  })
})
