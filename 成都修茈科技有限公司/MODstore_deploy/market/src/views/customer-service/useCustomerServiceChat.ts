/**
 * 对话主流程：草稿、发送管线、气泡点击、会话管理与工单展开联动（原单文件机械迁出）。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import type { Ref } from 'vue'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import { api } from '../../api'
import { shortTicketRef, ticketIsClosed } from '../../utils/csTicketLifecycle'
import { composeTicketUserMessage, toUserFacingCards } from '../../utils/csTicketSummary'
import { asUnknownRecord, errorMessage } from '../../utils/typeNarrowing'
import type { CustomerTicket, UiMessage } from './customerServiceTypes'

export interface CustomerServiceChatCtx {
  route: Pick<RouteLocationNormalizedLoaded, 'query'>
  pendingImageDataUrl: Ref<string | null>
  imagePicking: Ref<boolean>
  clearPendingImage: () => void
  loadTickets: () => Promise<void>
  expandedTicketIds: Ref<Set<number>>
}

export function useCustomerServiceChat(ctx: CustomerServiceChatCtx) {
  const { route } = ctx
  const draft = ref('')
  const loading = ref(false)
  const error = ref('')
  const activeSessionId = ref<number | null>(null)
  const openedTicket = ref<CustomerTicket | null>(null)
  const openedTicketCanReply = ref(false)
  const openedTicketRef = computed(() => openedTicket.value
    ? shortTicketRef({ ticket_no: openedTicket.value.ticket_no || openedTicket.value.id })
    : '')
  const readOnly = computed(() => !!openedTicket.value
    && (!openedTicketCanReply.value || !activeSessionId.value || ticketIsClosed(openedTicket.value)))
  let conversationGeneration = 0
  let mounted = true
  const messages = ref<UiMessage[]>([])
  const messagesEl = ref<HTMLElement | null>(null)

  const quickPrompts = ['你好，想了解一下会员怎么买', '退款一般需要提供哪些信息？', '商品有问题想先了解怎么投诉', '账号权益没到账是怎么回事']

  onMounted(() => {
    hydrateFromQuery()
    void ctx.loadTickets()
  })

  onBeforeUnmount(() => { mounted = false; conversationGeneration++ })

  function hydrateFromQuery() {
    const q = route.query || {}
    const parts = []
    if (q.order_no) parts.push(`订单号：${q.order_no}`)
    if (q.catalog_id) parts.push(`商品 ID：${q.catalog_id}`)
    if (q.item_name) parts.push(`商品名称：${q.item_name}`)
    if (q.complaint_type) parts.push(`问题类型：${q.complaint_type}`)
    if (parts.length) draft.value = `${parts.join('\n')}\n请帮我自动受理并给出处理结果。`
  }

  function queryContext() {
    const q = route.query || {}
    return {
      channel: 'web',
      scene: q.scene || undefined,
      order_no: q.order_no || undefined,
      catalog_id: q.catalog_id ? Number(q.catalog_id) : undefined,
      pkg_id: q.pkg_id || undefined,
      item_name: q.item_name || undefined,
      complaint_type: q.complaint_type || undefined,
      // 账号定制线（宿主入门第三步）：定制功能 Mod / 定制员工
      artifact: q.artifact || undefined,
      account_custom: q.account_custom || undefined,
    }
  }

  function usePrompt(text: string) {
    draft.value = text
  }

  async function scrollMessagesToEnd() {
    await nextTick()
    const el = messagesEl.value
    if (el) el.scrollTop = el.scrollHeight
  }

  function onBubbleClick(ev: MouseEvent, msg: UiMessage) {
    if (msg.role !== 'assistant' || openedTicket.value) return
    const target = ev.target as HTMLElement | null
    const link = target?.closest?.('[data-cs-action]') as HTMLElement | null
    if (!link) return
    ev.preventDefault()
    const action = String(link.getAttribute('data-cs-action') || '')
    if (action === 'submit-ticket') {
      const lastUser = [...messages.value]
        .reverse()
        .find((m) => m.role === 'user' && String(m.content || '').trim() && m.content !== '提交工单')
      void sendText('提交工单', {
        reason: String(lastUser?.content || '').trim() || undefined,
      })
    }
  }

  async function send() {
    await sendText(draft.value.trim())
  }

  async function sendText(raw: string, extras?: { reason?: string }) {
    const text = String(raw || '').trim()
    const imageDataUrl = ctx.pendingImageDataUrl.value
    if ((!text && !imageDataUrl) || loading.value || readOnly.value || ctx.imagePicking.value) return
    const generation = conversationGeneration
    const sessionId = activeSessionId.value
    const ticketId = openedTicket.value?.id
    error.value = ''
    loading.value = true
    const userMsg: UiMessage = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: text || '[用户补充了图片资料]',
      imageDataUrl: imageDataUrl || null,
    }
    messages.value.push(userMsg)
    draft.value = ''
    ctx.clearPendingImage()
    void scrollMessagesToEnd()
    try {
      const chatCtx = {
        ...(ticketId ? { channel: 'web', ticket_id: Number(ticketId) } : queryContext()),
        ...(extras?.reason ? { reason: extras.reason } : {}),
      }
      const res = asUnknownRecord(
        await api.customerServiceChat({
          message: text,
          session_id: sessionId,
          context: chatCtx,
          image_data_url: imageDataUrl || undefined,
        }),
      )
      const ticket = Object.keys(asUnknownRecord(res.ticket)).length ? (asUnknownRecord(res.ticket) as CustomerTicket) : null
      if (ticket && mounted) void ctx.loadTickets()
      if (generation !== conversationGeneration) return
      if (ticket && ticketId && Number(ticket.id) !== Number(ticketId)) {
        throw new Error('回执与当前原工单不一致，请核对我的工单')
      }
      const session = asUnknownRecord(res.session)
      if (sessionId && session.id && Number(session.id) !== sessionId) throw new Error('返回的客服会话不一致')
      const responseMessage = asUnknownRecord(res.message)
      activeSessionId.value = Number(session.id || sessionId || 0) || null
      if (ticket) {
        openedTicket.value = ticket
        openedTicketCanReply.value = true
      }
      // 对话里只用白话正文；不再堆「进度/下一步/已办理」多卡
      let content = String(responseMessage.content || '已处理。')
      if (ticket) {
        const fromCards = Array.isArray(res.cards) ? res.cards.map(asUnknownRecord) : []
        const decisionCard = fromCards.find((card) => card.type === 'decision')
        const actionsCard = fromCards.find((card) => card.type === 'actions')
        const composed = composeTicketUserMessage({
          ticket,
          decision: decisionCard || asUnknownRecord(res.decision),
          actions: Array.isArray(actionsCard?.items) ? actionsCard.items : Array.isArray(res.actions) ? res.actions : [],
        })
        if (ticketIsClosed(ticket) || content === '已处理。') content = composed
      }
      messages.value.push({
        id: `a-${Date.now()}`,
        role: 'assistant',
        content,
        cards: [],
      })
      await scrollMessagesToEnd()
    } catch (e: unknown) {
      const detail = errorMessage(e, 'AI 客服处理失败')
      const uncertain = /internal server error|\b5\d\d\b|timeout|timed out|failed to fetch|networkerror/i.test(detail)
      if (uncertain && mounted) void ctx.loadTickets()
      if (generation !== conversationGeneration) return
      error.value = uncertain
        ? '暂无法确认工单是否受理。请先查看右侧工单列表，勿重复提交；没有回执不代表未落单。'
        : detail
    } finally {
      if (generation === conversationGeneration) loading.value = false
    }
  }

  function newSession() {
    conversationGeneration++
    activeSessionId.value = null
    openedTicket.value = null
    openedTicketCanReply.value = false
    messages.value = []
    draft.value = ''
    ctx.clearPendingImage()
    error.value = ''
    loading.value = false
  }

  function visibleCards(msg: UiMessage) {
    return toUserFacingCards(Array.isArray(msg.cards) ? msg.cards : [])
  }

  async function openTicket(ticket: CustomerTicket) {
    const ticketId = Number(ticket.id)
    if (!Number.isSafeInteger(ticketId) || ticketId <= 0) return
    newSession()
    openedTicket.value = ticket
    loading.value = true
    const generation = conversationGeneration
    ctx.expandedTicketIds.value = new Set([...ctx.expandedTicketIds.value, ticketId])
    try {
      const transcript = asUnknownRecord(await api.customerServiceTicketTranscript(ticketId))
      if (generation !== conversationGeneration) return
      const current = asUnknownRecord(transcript.ticket)
      const sessionId = Number(transcript.session_id)
      if (Number(current.id) !== ticketId || !Number.isSafeInteger(sessionId) || sessionId <= 0
        || Number(current.session_id) !== sessionId
        || (ticket.session_id != null && Number(ticket.session_id) !== sessionId)
        || !Array.isArray(transcript.messages)) {
        throw new Error('返回的会话与原工单不一致')
      }
      openedTicket.value = { ...ticket, ...current }
      activeSessionId.value = sessionId
      openedTicketCanReply.value = transcript.can_reply === true
      messages.value = transcript.messages.map(asUnknownRecord).flatMap((message): UiMessage[] => {
        if ((message.ticket_id == null ? !openedTicketCanReply.value : Number(message.ticket_id) !== ticketId)
          || (message.role !== 'user' && message.role !== 'assistant')
          || typeof message.content !== 'string') return []
        const payload = asUnknownRecord(message.payload)
        const image = payload.image_data_url
        return [{
          id: `persisted-${message.id}`,
          role: message.role,
          content: message.content,
          imageDataUrl: message.role === 'user' && typeof image === 'string'
            && /^data:image\/(?:png|jpeg|webp|gif|bmp|avif);base64,/.test(image) ? image : null,
          adminLabel: payload.origin === 'admin_reply' ? '管理员答复'
            : payload.origin === 'admin_disposition' ? '管理员处置回执' : undefined,
        }]
      })
      await scrollMessagesToEnd()
    } catch (cause: unknown) {
      if (generation === conversationGeneration) error.value = errorMessage(cause, '打开原客服会话失败')
    } finally {
      if (generation === conversationGeneration) loading.value = false
    }
  }

  return {
    draft, loading, error, activeSessionId, openedTicketRef, readOnly, messages, messagesEl, quickPrompts,
    hydrateFromQuery, queryContext, usePrompt, scrollMessagesToEnd, onBubbleClick,
    send, sendText, newSession, visibleCards, openTicket,
  }
}

export type CustomerServiceChat = ReturnType<typeof useCustomerServiceChat>
