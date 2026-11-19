import { defineComponent, h, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useCustomerServiceChat, type CustomerServiceChat } from './useCustomerServiceChat'
const { chat, ticketDetail, sessionDetail } = vi.hoisted(() => ({
  chat: vi.fn(), ticketDetail: vi.fn(), sessionDetail: vi.fn(),
}))
vi.mock('../../api', () => ({
  api: { customerServiceChat: chat, customerServiceTicketDetail: ticketDetail, customerServiceSessionDetail: sessionDetail },
}))

function mountChat() {
  const loadTickets = vi.fn().mockResolvedValue(undefined)
  let state!: CustomerServiceChat
  const wrapper = mount(defineComponent({ setup() {
    state = useCustomerServiceChat({
      route: { query: { order_no: 'OTHER' } },
      pendingImageDataUrl: ref(null), imagePicking: ref(false),
      clearPendingImage: vi.fn(), loadTickets, expandedTicketIds: ref(new Set<number>()),
    })
    return () => h('div')
  } }))
  return { state, wrapper, loadTickets }
}

beforeEach(() => vi.resetAllMocks())

describe('customer ticket submission acknowledgement', () => {
  it.each(['Internal Server Error', 'HTTP 503', 'Failed to fetch'])(
    'reads back after %s without retrying or claiming a receipt', async (failure) => {
      const { state, wrapper, loadTickets } = mountChat()
      chat.mockRejectedValue(new Error(failure))
      await state.sendText('提交工单')
      expect(chat).toHaveBeenCalledTimes(1)
      expect(loadTickets).toHaveBeenCalledTimes(2) // mount + read-only reconciliation
      expect(state.error.value).toContain('暂无法确认')
      expect(state.error.value).toContain('勿重复提交')
      expect(state.loading.value).toBe(false)
      expect(state.messages.value.map(message => message.role)).toEqual(['user'])
      wrapper.unmount()
    },
  )
})

describe('opening original customer-service conversations', () => {
  it('reads the persisted reply, keeps the selected original ticket, and omits other tickets’ messages', async () => {
    const { state, wrapper } = mountChat()
    const ticket = { id: 75, session_id: 101, ticket_no: 'CS-shared-8819a0', status: 'processing' }
    ticketDetail.mockResolvedValue({ ticket })
    sessionDetail.mockResolvedValue({
      session: { id: 101 },
      messages: [
        { id: 1, ticket_id: 75, role: 'user', content: '原问题' },
        { id: 2, ticket_id: 76, role: 'assistant', content: '其他工单的答复' },
        { id: 3, ticket_id: 75, role: 'assistant', content: '后台实际答复', payload: { origin: 'admin_reply' } },
      ],
    })
    chat.mockResolvedValue({ session: { id: 101 }, message: { content: '已经收到补充' } })

    await state.openTicket(ticket)

    expect(ticketDetail).toHaveBeenCalledWith(75)
    expect(sessionDetail).toHaveBeenCalledWith(101)
    expect(state.openedTicketRef.value).toBe('编号 8819a0')
    expect(state.messages.value.map(message => message.content)).toEqual(['原问题', '后台实际答复'])
    expect(state.messages.value.at(-1)?.adminLabel).toBe('管理员答复')
    await state.sendText('补充原工单')
    expect(chat).toHaveBeenCalledWith(expect.objectContaining({
      session_id: 101, context: { channel: 'web', ticket_id: 75 },
    }))
    wrapper.unmount()
  })

  it('binds the conversation to the original number once a ticket is created', async () => {
    const { state, wrapper } = mountChat()
    const ticket = { id: 75, session_id: 101, ticket_no: 'CS-shared-8819a0', status: 'processing' }
    chat.mockResolvedValue({ session: { id: 101 }, ticket, message: { content: '已受理' } })
    await state.sendText('提报官网故障')
    expect(state.openedTicketRef.value).toBe('编号 8819a0')
    await state.sendText('补充第二次复现')
    expect(chat).toHaveBeenLastCalledWith(expect.objectContaining({
      session_id: 101, context: { channel: 'web', ticket_id: 75 },
    }))
    wrapper.unmount()
  })

  it('shows the persisted disposition receipt and keeps the closed conversation read-only', async () => {
    const { state, wrapper } = mountChat()
    const ticket = { id: 76, session_id: 102, status: 'rejected', disposition: { kind: 'out_of_scope' } }
    ticketDetail.mockResolvedValue({ ticket })
    sessionDetail.mockResolvedValue({
      session: { id: 102 },
      messages: [{
        id: 1, ticket_id: 76, role: 'assistant', content: '该事项超出平台受理范围',
        payload: { origin: 'admin_disposition' },
      }],
    })
    await state.openTicket(ticket)
    expect(state.messages.value[0]).toMatchObject({ content: '该事项超出平台受理范围', adminLabel: '管理员处置回执' })
    expect(state.readOnly.value).toBe(true)
    await state.sendText('继续提交')
    expect(chat).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('ignores stale transcript and send responses after opening another ticket or starting a new session', async () => {
    const { state, wrapper } = mountChat()
    let resolveHistory!: (value: unknown) => void
    let resolveSend!: (value: unknown) => void
    ticketDetail.mockImplementation((id: number) => Promise.resolve({ ticket: { id, session_id: id * 10 } }))
    sessionDetail.mockImplementation((id: number) => id === 10
      ? new Promise(resolve => { resolveHistory = resolve })
      : Promise.resolve({ session: { id }, messages: [{ id: 20, role: 'assistant', content: '第二张原单' }] }))
    chat.mockImplementation(() => new Promise(resolve => { resolveSend = resolve }))
    const first = state.openTicket({ id: 1 })
    await Promise.resolve()
    await state.openTicket({ id: 2 })
    resolveHistory({ session: { id: 10 }, messages: [{ id: 10, role: 'assistant', content: '第一张原单' }] })
    await first
    expect(state.activeSessionId.value).toBe(20)
    expect(state.messages.value[0]?.content).toBe('第二张原单')

    const send = state.sendText('原单补充')
    state.newSession()
    resolveSend({ session: { id: 20 }, message: { content: '旧会话回执' } })
    await send
    expect(state.activeSessionId.value).toBeNull()
    expect(state.messages.value).toEqual([])
    expect(state.loading.value).toBe(false)
    wrapper.unmount()
  })
})
