import { defineComponent, h, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useCustomerServiceChat, type CustomerServiceChat } from './useCustomerServiceChat'
const { chat, transcript } = vi.hoisted(() => ({
  chat: vi.fn(), transcript: vi.fn(),
}))
vi.mock('../../api', () => ({
  api: { customerServiceChat: chat, customerServiceTicketTranscript: transcript },
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
    const screenshot = 'data:image/png;base64,AAAA'
    transcript.mockResolvedValue({
      ticket, session_id: 101, can_reply: true,
      messages: [
        { id: 1, ticket_id: 75, role: 'user', content: '原问题', payload: { image_data_url: screenshot } },
        { id: 2, ticket_id: 76, role: 'assistant', content: '其他工单的答复' },
        { id: 3, ticket_id: 75, role: 'assistant', content: '后台实际答复', payload: { origin: 'admin_reply' } },
      ],
    })
    chat.mockResolvedValue({ session: { id: 101 }, message: { content: '已经收到补充' } })

    await state.openTicket(ticket)

    expect(transcript).toHaveBeenCalledWith(75)
    expect(state.messages.value[0]?.imageDataUrl).toBe(screenshot)
    expect(state.openedTicketRef.value).toBe('编号 8819a0')
    expect(state.messages.value.map(message => message.content)).toEqual(['原问题', '后台实际答复'])
    expect(state.messages.value.at(-1)?.adminLabel).toBe('管理员答复')
    await state.sendText('补充原工单')
    expect(chat).toHaveBeenCalledWith(expect.objectContaining({
      session_id: 101, context: { channel: 'web', ticket_id: 75 },
    }))
    wrapper.unmount()
  })

  it('opens a cross-customer administrative transcript read-only and checks its session identity', async () => {
    const { state, wrapper } = mountChat()
    const ticket = { id: 75, session_id: 101, status: 'processing' }
    transcript.mockResolvedValueOnce({
      ticket, session_id: 404, can_reply: false,
      messages: [{ id: 1, ticket_id: 75, role: 'user', content: '错误会话' }],
    }).mockResolvedValueOnce({
      ticket, session_id: 101, can_reply: false,
      messages: [
        { id: 1, ticket_id: 75, role: 'user', content: '准确原单', payload: { image_data_url: 'data:image/svg+xml;base64,PHN2Zy8+' } },
        { id: 2, ticket_id: null, role: 'user', content: '未绑定的会话内容' },
      ],
    })
    await state.openTicket(ticket)
    expect(state.messages.value).toEqual([])
    expect(state.error.value).toContain('返回的会话与原工单不一致')
    await state.openTicket(ticket)
    expect(state.messages.value).toMatchObject([{ content: '准确原单', imageDataUrl: null }])
    expect(state.readOnly.value).toBe(true)
    await state.sendText('尝试代替客户补充')
    expect(chat).not.toHaveBeenCalled()
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
    transcript.mockResolvedValue({
      ticket, session_id: 102, can_reply: true,
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
    transcript.mockImplementation((id: number) => id === 1
      ? new Promise(resolve => { resolveHistory = resolve })
      : Promise.resolve({
          ticket: { id, session_id: 20 }, session_id: 20, can_reply: true,
          messages: [{ id: 20, ticket_id: 2, role: 'assistant', content: '第二张原单' }],
        }))
    chat.mockImplementation(() => new Promise(resolve => { resolveSend = resolve }))
    const first = state.openTicket({ id: 1 })
    await Promise.resolve()
    await state.openTicket({ id: 2 })
    resolveHistory({
      ticket: { id: 1, session_id: 10 }, session_id: 10, can_reply: true,
      messages: [{ id: 10, ticket_id: 1, role: 'assistant', content: '第一张原单' }],
    })
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
