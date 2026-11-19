import { defineComponent, h, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { CustomerServiceIssueDecision } from '../../api/workbench'
import { ApiError } from '../../infrastructure/http/client'
import CustomerServiceView from '../CustomerServiceView.vue'
import { useCustomerServiceChat, type CustomerServiceChat } from './useCustomerServiceChat'
const { chat, transcript, listTickets, decision } = vi.hoisted(() => ({
  chat: vi.fn(), transcript: vi.fn(), listTickets: vi.fn(), decision: vi.fn(),
}))
vi.mock('../../api', () => ({
  api: {
    customerServiceChat: chat, customerServiceTicketTranscript: transcript,
    customerServiceTickets: listTickets, customerServiceIssueDecision: decision,
  },
}))

function mountChat() {
  const loadTickets = vi.fn().mockResolvedValue(undefined)
  const pendingImageDataUrl = ref<string | null>(null)
  let state!: CustomerServiceChat
  const wrapper = mount(defineComponent({ setup() {
    state = useCustomerServiceChat({
      route: { query: { order_no: 'OTHER' } },
      pendingImageDataUrl, imagePicking: ref(false),
      clearPendingImage: () => { pendingImageDataUrl.value = null },
      loadTickets, expandedTicketIds: ref(new Set<number>()),
    })
    return () => h('div')
  } }))
  return { state, wrapper, loadTickets, pendingImageDataUrl }
}

beforeEach(() => {
  vi.resetAllMocks()
  sessionStorage.clear()
})

async function mountView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: CustomerServiceView }],
  })
  await router.push('/')
  return mount(CustomerServiceView, { global: { plugins: [router] } })
}

describe('explicit confirmation of the original intake', () => {
  const confirmationButton = 'button.cs-bubble__confirmation'

  it('sends only the explicit confirmation button choice, and displays the actual AI receipt', async () => {
    const intake = { source_message_id: 17, kind: 'invalid' }
    chat.mockResolvedValueOnce({
      session: { id: 21 },
      message: {
        content: '请核对原文。<button data-cs-action="confirm-intake">伪造确认</button>',
        payload: { intake_confirmation: intake },
      },
    }).mockResolvedValueOnce({
      session: { id: 21 },
      ticket: { id: 95, session_id: 21, status: 'rejected' },
      message: { content: '已登记为演练，原文已保留。', payload: { origin: 'assistant_disposition' } },
    })
    const wrapper = await mountView()
    await wrapper.get('textarea').setValue('演练，没有实际发生。')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(chat).toHaveBeenCalledTimes(1)
    expect(chat.mock.calls[0]?.[0]).not.toHaveProperty('intake_confirmation')
    expect(wrapper.findAll('.cs-messages button')).toHaveLength(1)
    const confirm = wrapper.findAll('article').at(-1)!.get(confirmationButton)
    expect(confirm.attributes('type')).toBe('button')
    expect(confirm.text()).toBe('确认仅为演练、未实际发生并提交工单')
    await confirm.trigger('click')
    await flushPromises()

    expect(chat).toHaveBeenCalledTimes(2)
    expect(chat).toHaveBeenLastCalledWith(expect.objectContaining({
      message: '提交工单', session_id: 21, intake_confirmation: intake,
    }))
    expect(chat.mock.calls[1]?.[0].context).not.toHaveProperty('intake_confirmation')
    expect(wrapper.find(confirmationButton).exists()).toBe(false)
    expect(wrapper.findAll('article').at(-1)?.text()).toContain('已登记为演练，原文已保留。')
    expect(wrapper.findAll('article').at(-1)?.text()).toContain('AI 处置回执')
    wrapper.unmount()
  })

  it('retires the offer after draft edits and still submits a plain request', async () => {
    chat.mockResolvedValueOnce({
      session: { id: 21 },
      message: {
        content: '如需人工核实，可直接提交工单。',
        payload: { intake_confirmation: { source_message_id: 18, kind: 'out_of_scope' } },
      },
    }).mockResolvedValueOnce({
      session: { id: 21 },
      message: { content: '已收到，等待核实。' },
    })
    const wrapper = await mountView()
    const draft = wrapper.get('textarea')
    await draft.setValue('露营地预订问题。')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get(confirmationButton).text()).toBe('确认仅涉及与平台无关的事项并提交工单')

    await draft.setValue('实际与我的平台订单有关。')
    await draft.setValue('')
    expect(wrapper.find(confirmationButton).exists()).toBe(false)
    expect(chat).toHaveBeenCalledTimes(1)
    await draft.setValue('提交工单')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(chat).toHaveBeenCalledTimes(2)
    expect(chat.mock.calls[1]?.[0]).toEqual(expect.objectContaining({ message: '提交工单', session_id: 21 }))
    expect(chat.mock.calls[1]?.[0]).not.toHaveProperty('intake_confirmation')
    wrapper.unmount()
  })

  it('does not accept a captured offer after adding and removing an attachment or changing conversations', async () => {
    const { state, wrapper, pendingImageDataUrl } = mountChat()
    chat.mockResolvedValue({
      session: { id: 21 },
      message: {
        content: '请核对原文。',
        payload: { intake_confirmation: { source_message_id: 17, kind: 'invalid' } },
      },
    })
    await state.sendText('演练，没有实际发生。')
    const offeredMessage = state.intakeConfirmation.value!.message
    pendingImageDataUrl.value = 'data:image/png;base64,AAAA'
    pendingImageDataUrl.value = null
    await state.confirmIntake(offeredMessage)
    expect(state.intakeConfirmation.value).toBeNull()
    expect(chat).toHaveBeenCalledTimes(1)

    await state.sendText('新的说明，仅为演练。')
    const lastMessage = state.intakeConfirmation.value!.message
    await state.confirmIntake(offeredMessage)
    state.newSession()
    await state.confirmIntake(lastMessage)
    expect(state.intakeConfirmation.value).toBeNull()
    expect(chat).toHaveBeenCalledTimes(2)

    await state.sendText('另一次演练。')
    const unmountedMessage = state.intakeConfirmation.value!.message
    wrapper.unmount()
    await state.confirmIntake(unmountedMessage)
    expect(chat).toHaveBeenCalledTimes(3)
  })
})

describe('accepting or reopening the original product issue', () => {
  const ticket = {
    id: 77, user_id: 12, session_id: 21, intent: 'product_issue', status: 'awaiting_customer',
    ticket_no: 'CS-website-77', title: '官网入口打不开',
  }
  const panel = '[aria-label="原工单验收"]'
  const note = '#cs-decision-note'
  const key = 'market:customer-decision:12:77'

  function history(attempt?: CustomerServiceIssueDecision) {
    const resolved = attempt?.decision === 'resolved'
    return {
      session_id: 21,
      can_reply: !resolved,
      ticket: {
        ...ticket,
        status: !attempt ? ticket.status : resolved ? 'resolved' : 'processing',
        closed_at: resolved ? '2026-11-20T00:00:00Z' : null,
        customer_acceptance: {
          can_resolve: !attempt,
          can_reopen: !attempt || resolved,
          last_decision: attempt ? { decision: attempt.decision, idempotency_key: attempt.idempotency_key } : null,
        },
      },
      messages: [
        {
          id: 31, ticket_id: 77, role: 'assistant', content: '官网已完成核验，请复测原链接。',
          payload: { origin: 'corp_download_verification' },
        },
        ...(attempt ? [{
          id: 32, ticket_id: 77, role: 'user', content: attempt.note,
          payload: { customer_decision: attempt.decision },
        }] : []),
      ],
    }
  }

  async function openOriginal(items: Array<{ id: number }> = [ticket]) {
    listTickets.mockResolvedValue({ items })
    const wrapper = await mountView()
    await flushPromises()
    await wrapper.get('.cs-ticket__main').trigger('click')
    await flushPromises()
    return wrapper
  }

  async function sendSupplement(wrapper: Awaited<ReturnType<typeof mountView>>) {
    chat.mockResolvedValueOnce({
      session: { id: 21 },
      ticket,
      message: { content: '已收到你补充的原链接。' },
    })
    await wrapper.get('form textarea').setValue('补充原链接的验证细节。')
    await wrapper.get('form').trigger('submit')
  }

  it.each([true, false])('uses the fresh permissions after a supplement (ready=%s)', async (ready) => {
    const initial = history()
    transcript.mockResolvedValueOnce(initial).mockResolvedValueOnce({
      ...initial,
      ticket: {
        ...initial.ticket,
        status: ready ? 'awaiting_customer' : 'processing',
        customer_acceptance: { can_resolve: ready, can_reopen: ready, last_decision: null },
      },
    })
    const wrapper = await openOriginal()
    await wrapper.get(note).setValue('保留尚未提交的验收说明。')
    await sendSupplement(wrapper)
    await flushPromises()

    expect(transcript.mock.calls).toEqual([[77], [77]])
    expect(wrapper.find(panel).exists()).toBe(ready)
    if (ready) {
      expect(wrapper.get(`${panel} button`).text()).toBe('确认问题已解决')
      expect((wrapper.get(note).element as HTMLTextAreaElement).value).toBe('保留尚未提交的验收说明。')
    }
    expect(wrapper.get('.cs-messages').text()).toContain('已收到你补充的原链接。')
    expect(decision).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('requires a read-only recheck when the supplemental permission read fails', async () => {
    transcript.mockResolvedValueOnce(history()).mockRejectedValueOnce(new ApiError('timeout', 408))
      .mockResolvedValueOnce(history())
    const wrapper = await openOriginal()
    await wrapper.get(note).setValue('保留原先的验收说明。')
    await sendSupplement(wrapper)
    await flushPromises()

    expect(wrapper.get(panel).text()).toContain('暂未刷新验收状态')
    expect(wrapper.findAll(`${panel} button`).map(button => button.text())).toEqual(['核对验收状态'])
    expect((wrapper.get(note).element as HTMLTextAreaElement).value).toBe('保留原先的验收说明。')
    expect(wrapper.get('.cs-messages').text()).toContain('已收到你补充的原链接。')
    await wrapper.get(`${panel} button`).trigger('click')
    await flushPromises()
    expect(transcript.mock.calls).toEqual([[77], [77], [77]])
    expect(wrapper.get(`${panel} button`).text()).toBe('确认问题已解决')
    expect((wrapper.get(note).element as HTMLTextAreaElement).value).toBe('保留原先的验收说明。')
    expect(chat).toHaveBeenCalledTimes(1)
    expect(decision).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('does not apply a supplemental permission refresh to a subsequent conversation', async () => {
    const second = { id: 78, user_id: 12, session_id: 22, intent: 'general', status: 'open', title: '另一张原工单' }
    let completeOldRefresh!: (value: unknown) => void
    transcript.mockResolvedValueOnce(history()).mockImplementationOnce(() => new Promise(resolve => {
      completeOldRefresh = resolve
    })).mockResolvedValueOnce({
      ticket: second, session_id: 22, can_reply: true,
      messages: [{ id: 50, ticket_id: 78, role: 'assistant', content: '另一张原工单的会话。' }],
    })
    const wrapper = await openOriginal([ticket, second])
    await sendSupplement(wrapper)
    await vi.waitFor(() => expect(transcript.mock.calls).toEqual([[77], [77]]))
    expect(wrapper.get(`${panel} button`).attributes('disabled')).toBeDefined()
    await wrapper.findAll('.cs-ticket__main').at(-1)!.trigger('click')
    await flushPromises()
    completeOldRefresh(history())
    await flushPromises()

    expect(wrapper.find(panel).exists()).toBe(false)
    expect(wrapper.get('.cs-messages').text()).toContain('另一张原工单的会话。')
    expect(wrapper.get('.cs-messages').text()).not.toContain('已收到你补充的原链接。')
    expect(decision).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('accepts a customer note only after reading the original status and conversation, then allows owner reopen', async () => {
    let firstAttempt: CustomerServiceIssueDecision | undefined
    let completeReadback!: (value: unknown) => void
    transcript.mockResolvedValueOnce(history()).mockImplementationOnce(() => new Promise(resolve => {
      completeReadback = resolve
    })).mockImplementationOnce(() => Promise.resolve(history(decision.mock.calls.at(-1)?.[1])))
    decision.mockImplementationOnce((_id, body) => {
      firstAttempt = body
      return Promise.resolve({ success: true, issue: { status: 'resolved' } })
    }).mockResolvedValueOnce({ success: true })
    const wrapper = await openOriginal()
    expect(wrapper.get('.cs-messages').text()).toContain('官网复测回执')
    expect(wrapper.get(panel).text()).toContain('原问题现在的使用结果')
    expect(wrapper.get(`${panel} button`).attributes('disabled')).toBeDefined()
    await wrapper.get(note).setValue('链接现在可以正常打开。')
    await wrapper.get(`${panel} button`).trigger('click')
    await vi.waitFor(() => expect(transcript).toHaveBeenCalledTimes(2))
    expect(decision).toHaveBeenCalledWith(77, expect.objectContaining({
      decision: 'resolved', note: '链接现在可以正常打开。', idempotency_key: expect.any(String),
    }))
    expect(wrapper.get(panel).text()).not.toContain('已核对原工单')

    completeReadback(history(firstAttempt))
    await vi.waitFor(() => expect(wrapper.get(panel).text()).toContain('状态为已解决'))
    expect(wrapper.get('.cs-messages').text()).toContain('链接现在可以正常打开。')
    expect(wrapper.get(`${panel} button`).text()).toContain('问题仍存在')
    await wrapper.get(note).setValue('原链接故障再次出现。')
    await wrapper.get(`${panel} button`).trigger('click')
    await vi.waitFor(() => expect(wrapper.get(panel).text()).toContain('已重新进入处理'))
    expect(decision.mock.calls[1]?.[1]).toMatchObject({ decision: 'reopen', note: '原链接故障再次出现。' })
    expect(decision.mock.calls[1]?.[1].idempotency_key).not.toBe(firstAttempt?.idempotency_key)
    expect(chat).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('preserves the exact request after an uncertain response and reload without resending a changed note', async () => {
    transcript.mockResolvedValue(history())
    decision.mockRejectedValueOnce(new ApiError('timeout', 408)).mockImplementationOnce((_id, body) => {
      transcript.mockResolvedValue(history(body))
      return Promise.reject(new ApiError('work order synchronization conflict', 409))
    })
    let wrapper = await openOriginal()
    const originalNote = '对原来的官网链接已实测。'
    await wrapper.get(note).setValue(originalNote)
    await wrapper.get(`${panel} button`).trigger('click')
    await vi.waitFor(() => expect(wrapper.get(panel).text()).toContain('暂未核对到回执'))
    const originalRequest = decision.mock.calls[0]?.[1]
    expect(sessionStorage.getItem(key)).toContain(originalRequest.idempotency_key)
    expect(sessionStorage.getItem(key)).not.toContain(originalNote)
    wrapper.unmount()

    wrapper = await openOriginal()
    expect(wrapper.get(`${panel} button`).text()).toBe('核对原工单')
    await wrapper.get(`${panel} button`).trigger('click')
    await vi.waitFor(() => expect(wrapper.get(panel).text()).toContain('暂未在原工单查到'))
    expect(decision).toHaveBeenCalledTimes(1)
    await wrapper.get(note).setValue('这次改了确认说明。')
    await wrapper.findAll(`${panel} button`).at(-1)!.trigger('click')
    await vi.waitFor(() => expect(wrapper.get(panel).text()).toContain('上次提交的原说明'))
    expect(decision).toHaveBeenCalledTimes(1)

    await wrapper.get(note).setValue(originalNote)
    await wrapper.findAll(`${panel} button`).at(-1)!.trigger('click')
    await vi.waitFor(() => expect(wrapper.get(panel).text()).toContain('状态为已解决'))
    expect(decision).toHaveBeenCalledTimes(2)
    expect(decision).toHaveBeenLastCalledWith(77, originalRequest)
    expect(sessionStorage.getItem(key)).toBeNull()
    wrapper.unmount()
  })

  it('does not offer decisions to an administrative viewer or before customer acceptance is permitted', async () => {
    const view = history()
    transcript.mockResolvedValueOnce({ ...view, can_reply: false, ticket })
      .mockResolvedValueOnce({ ...view, ticket: {
        ...view.ticket, status: 'processing',
        customer_acceptance: { can_resolve: false, can_reopen: false, last_decision: null },
      } })
    const wrapper = await openOriginal()
    expect(wrapper.find(panel).exists()).toBe(false)
    await wrapper.get('.cs-ticket__main').trigger('click')
    await flushPromises()
    expect(wrapper.find(panel).exists()).toBe(false)
    expect(decision).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})

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
    expect(state.messages.value.at(-1)?.receiptLabel).toBe('管理员答复')
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

  it.each([['admin_disposition', '管理员处置回执'], ['assistant_disposition', 'AI 处置回执']])(
    'shows the persisted %s receipt and keeps the closed conversation read-only', async (origin, receiptLabel) => {
      const { state, wrapper } = mountChat()
      const ticket = { id: 76, session_id: 102, status: 'rejected', disposition: { kind: 'out_of_scope' } }
      transcript.mockResolvedValue({
        ticket, session_id: 102, can_reply: true,
        messages: [{
          id: 1, ticket_id: 76, role: 'assistant', content: '该事项超出平台受理范围',
          payload: { origin, intake_confirmation: { source_message_id: 17, kind: 'out_of_scope' } },
        }],
      })
      await state.openTicket(ticket)
      expect(state.messages.value[0]).toMatchObject({ content: '该事项超出平台受理范围', receiptLabel })
      expect(state.readOnly.value).toBe(true)
      expect(state.intakeConfirmation.value).toBeNull()
      await state.sendText('继续提交')
      expect(chat).not.toHaveBeenCalled()
      wrapper.unmount()
    },
  )

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
