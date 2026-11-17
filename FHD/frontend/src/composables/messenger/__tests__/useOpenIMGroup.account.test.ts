import { afterAll, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { apiFetch } from '@/utils/apiBase'
import { useOpenIMGroup, openimGroupUnread } from '../useOpenIMGroup'
const compileWasm = vi.spyOn(WebAssembly, 'compile').mockResolvedValue({} as WebAssembly.Module)
afterAll(() => compileWasm.mockRestore())
const fake = vi.hoisted(() => ({ callbacks: new Map<string, (event: unknown) => void>(), logout: vi.fn().mockResolvedValue(undefined), initFailure: false, history: vi.fn().mockResolvedValue({ data: { messageList: [], isEnd: true } }), read: vi.fn().mockResolvedValue(undefined), conversation: vi.fn(), conversations: vi.fn().mockResolvedValue({ data: [] }) }))
vi.mock('@/utils/apiBase', () => ({ apiFetch: vi.fn().mockResolvedValue({ ok: true, json: async () => ({
  enabled: true, userID: 'owner', token: 'synthetic', platformID: 5, apiAddr: '', wsAddr: '', groupID: 'remote', senders: { worker: 'employee' },
}) }) }))
vi.mock('@openim/wasm-client-sdk', () => ({
  CbEvents: Object.fromEntries(['OnConversationChanged', 'OnNewConversation', 'OnRecvNewMessage', 'OnConnectSuccess', 'OnConnecting', 'OnConnectFailed', 'OnKickedOffline', 'OnUserTokenExpired', 'OnUserTokenInvalid'].map(name => [name, name])),
  getSDK: () => { if (fake.initFailure) throw new Error('synthetic WebAssembly unavailable'); return ({
    on: (event: string, cb: (event: unknown) => void) => fake.callbacks.set(event, cb),
    off: (event: string) => fake.callbacks.delete(event),
    login: vi.fn().mockResolvedValue(undefined), logout: fake.logout,
    getOneConversation: fake.conversation,
    getAllConversationList: fake.conversations,
    getAdvancedHistoryMessageList: fake.history,
    markConversationMessageAsRead: fake.read,
  }) },
}))
it('falls back when the existing CSP forbids WASM compilation', async () => {
  compileWasm.mockRejectedValueOnce(new WebAssembly.CompileError('CSP blocked'))
  let transport!: ReturnType<typeof useOpenIMGroup>
  const wrapper = mount(defineComponent({ setup() { transport = useOpenIMGroup(vi.fn()); return () => null } }))
  try {
    expect(await transport.start('local')).toBe(false)
    expect(transport.active.value).toBe(false)
    expect(transport.error.value).toContain('主机消息同步')
  } finally { wrapper.unmount() }
})
it('uses host mode when WASM initialization fails without changing CSP', async () => {
  fake.initFailure = true
  let transport!: ReturnType<typeof useOpenIMGroup>
  const wrapper = mount(defineComponent({ setup() { transport = useOpenIMGroup(vi.fn()); return () => null } }))
  try {
    const started = transport.start('local')
    await flushPromises()
    document.querySelector<HTMLScriptElement>('script[src$="openim/wasm_exec.js"]')?.dispatchEvent(new Event('load'))
    expect(await started).toBe(false)
    expect(transport.active.value).toBe(false)
    expect(transport.connected.value).toBe(false)
    expect(transport.error.value).toContain('主机消息同步')
  } finally { fake.initFailure = false; wrapper.unmount() }
})
it('retires SDK callbacks on account changes even when an old queued callback arrives', async () => {
  fake.conversation.mockResolvedValue({ data: { conversationID: 'conversation' } })
  const receive = vi.fn()
  let transport!: ReturnType<typeof useOpenIMGroup>
  const wrapper = mount(defineComponent({ setup() { transport = useOpenIMGroup(receive); return () => null } }))
  try {
    const started = transport.start('local')
    await flushPromises()
    const script = document.querySelector<HTMLScriptElement>('script[src$="openim/wasm_exec.js"]')!
    script?.dispatchEvent(new Event('load'))
    await started
    expect(transport.connected.value).toBe(true)
    const late = fake.callbacks.get('OnRecvNewMessage')!
    const lateReconnect = fake.callbacks.get('OnConnectSuccess')!
    receive.mockClear()
    productReadAccountEpoch.value++
    late({ data: { groupID: 'remote', sendID: 'worker', customElem: { extension: 'xcagi-group-v1', data: JSON.stringify({ id: 'old', group_id: 'local', sender_id: 'employee', role: 'ai', body: 'old account result' }) } } })
    lateReconnect(undefined)
    await flushPromises()
    expect(receive).not.toHaveBeenCalled()
    expect(transport.connected.value).toBe(false)
    expect(transport.active.value).toBe(false)
    expect(fake.callbacks.has('OnRecvNewMessage')).toBe(false)
    expect(fake.logout).toHaveBeenCalled()
    script?.remove()
  } finally { wrapper.unmount() }
})

it('does not reactivate a retired account after delayed conversation lookup', async () => {
  let resolve!: (value: { data: { conversationID: string } }) => void
  fake.conversation.mockImplementationOnce(() => new Promise(r => { resolve = r }))
  fake.conversations.mockClear()
  const receive = vi.fn()
  let transport!: ReturnType<typeof useOpenIMGroup>
  const wrapper = mount(defineComponent({ setup() { transport = useOpenIMGroup(receive); return () => null } }))
  try {
    const started = transport.start('local')
    await flushPromises()
    expect(resolve).toBeDefined()
    productReadAccountEpoch.value++
    resolve({ data: { conversationID: 'old-conversation' } })
    await started
    await flushPromises()
    expect(fake.conversations).not.toHaveBeenCalled()
    expect(receive).not.toHaveBeenCalled()
    expect(transport.connected.value).toBe(false)
    expect(transport.active.value).toBe(false)
  } finally { wrapper.unmount() }
})


it('does not turn a forbidden transport response into host fallback', async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce({ ok: false, status: 403 } as Response)
  let transport!: ReturnType<typeof useOpenIMGroup>
  const wrapper = mount(defineComponent({ setup() { transport = useOpenIMGroup(vi.fn()); return () => null } }))
  try { await expect(transport.start('forbidden')).rejects.toThrow('消息服务连接失败') }
  finally { wrapper.unmount() }
})

it('syncs history, unread receipts and connection recovery without hiding errors', async () => {
  const row = { id: 'receipt', group_id: 'local', sender_id: 'employee', role: 'ai', body: 'result' }
  const message = { clientMsgID: 'oldest', groupID: 'remote', sendID: 'worker', customElem: { extension: 'xcagi-group-v1', data: JSON.stringify(row) } }
  fake.history.mockResolvedValue({ data: { messageList: [message], isEnd: false } })
  fake.conversation.mockResolvedValue({ data: { conversationID: 'conversation' } })
  fake.conversations.mockResolvedValue({ data: [{ groupID: 'remote', unreadCount: 3 }] })
  const receive = vi.fn()
  let transport!: ReturnType<typeof useOpenIMGroup>
  const wrapper = mount(defineComponent({ setup() { transport = useOpenIMGroup(receive); return () => null } }))
  try {
    await transport.history()
    expect(await transport.start('local')).toBe(true)
    expect(receive).toHaveBeenCalledWith([row])
    expect(transport.hasOlder.value).toBe(true)
    expect(openimGroupUnread.local).toBe(3)
    await transport.history(true)
    expect(fake.history).toHaveBeenLastCalledWith(expect.objectContaining({ startClientMsgID: 'oldest' }))
    fake.callbacks.get('OnConversationChanged')!({ data: [{ groupID: 'remote', unreadCount: 1 }] })
    expect(openimGroupUnread.local).toBe(1)
    fake.read.mockRejectedValueOnce(new Error('offline'))
    fake.callbacks.get('OnRecvNewMessage')!({ data: message })
    await flushPromises()
    expect(transport.error.value).toContain('已读状态同步失败')
    fake.callbacks.get('OnConnecting')!(undefined)
    expect(transport.connected.value).toBe(false)
    fake.callbacks.get('OnConnectSuccess')!(undefined)
    await flushPromises()
    expect(transport.connected.value).toBe(true)
    fake.history.mockRejectedValueOnce(new Error('offline'))
    document.dispatchEvent(new Event('visibilitychange'))
    await flushPromises()
    expect(transport.error.value).toContain('历史消息同步失败')
    fake.history.mockResolvedValueOnce({ data: { errCode: 500 } })
    await expect(transport.history()).rejects.toThrow('历史消息加载失败')
    fake.read.mockRejectedValueOnce(new Error('offline'))
    await transport.history()
    expect(transport.error.value).toContain('已读状态同步失败，请重新连接')
    fake.callbacks.get('OnUserTokenExpired')!(undefined)
    expect(transport.connected.value).toBe(false)
    expect(transport.error.value).toContain('消息连接已失效')
    productReadAccountEpoch.value++
    await flushPromises()
    expect(openimGroupUnread.local).toBeUndefined()
  } finally { wrapper.unmount() }
})
