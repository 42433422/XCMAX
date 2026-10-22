import { describe, expect, it, vi } from 'vitest'
import { effectScope, ref } from 'vue'
const send = vi.hoisted(() => vi.fn())
vi.mock('@/api/im', () => ({ sendEnterpriseCsMessage: send, fetchCsInboxMessages: vi.fn(), fetchImMessages: vi.fn(), markImRead: vi.fn(), replyCsInbox: vi.fn(), sendImMessage: vi.fn() }))
vi.mock('@/composables/useAppToast', () => ({ showAppToast: vi.fn() }))
import { useImConversationActions } from './useImConversationActions'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
function fixture() {
  const scope = effectScope()
  const o = { localUserId: ref(1), conversations: ref([]), activeConversationId: ref<number | null>(7), activeSystemEntry: ref(null), activeExternalEntry: ref(null), activeGroupChat: ref(false), messages: ref<any[]>([]), draft: ref('synthetic report'), busy: ref(false), hasMoreHistory: ref(false), dutyEmployeeDraft: ref(''), enterpriseCsError: ref(''), enterpriseCsUnconfirmed: ref(false), isCustomerEnterpriseCs: () => true, refreshEnterpriseCsThread: vi.fn().mockResolvedValue(undefined), startEnterpriseCsPolling: vi.fn(), stopEnterpriseCsPolling: vi.fn(), refreshCsInbox: vi.fn(), startCsInboxPolling: vi.fn(), stopCsInboxPolling: vi.fn(), restoreOverlappingAssistantFloat: vi.fn(), stopCodexPolling: vi.fn(), stopCodexTypewriter: vi.fn(), scrollToBottom: vi.fn(), loadConversations: vi.fn(), playOutgoing: vi.fn() }
  const actions = scope.run(() => useImConversationActions(o))!
  return { o, actions, scope }
}
describe('CS send recovery boundaries', () => {
  it('marks uncertainty before awaiting and blocks double dispatch', async () => {
    let resolve!: (v: any) => void
    send.mockImplementation(() => new Promise(r => { resolve = r }))
    const { o, actions, scope } = fixture()
    const first = actions.onSend(); expect(o.enterpriseCsUnconfirmed.value).toBe(true)
    await actions.onSend(); expect(send).toHaveBeenCalledTimes(1)
    o.draft.value = 'new draft'
    resolve({ message: { id: 1 }, conversation_id: 7 }); await first
    expect(o.draft.value).toBe('new draft'); expect(o.busy.value).toBe(false); expect(o.enterpriseCsUnconfirmed.value).toBe(false)
    scope.stop(); send.mockReset()
  })
  it('retires an old account request without leaving busy locked or inserting its result', async () => {
    let resolve!: (v: any) => void
    send.mockImplementation(() => new Promise(r => { resolve = r }))
    const { o, actions, scope } = fixture(); const pending = actions.onSend()
    productReadAccountEpoch.value++; expect(o.busy.value).toBe(false)
    resolve({ message: { id: 1 }, conversation_id: 7 }); await pending
    expect(o.messages.value).toEqual([]); expect(o.enterpriseCsUnconfirmed.value).toBe(true)
    scope.stop(); send.mockReset()
  })
})
