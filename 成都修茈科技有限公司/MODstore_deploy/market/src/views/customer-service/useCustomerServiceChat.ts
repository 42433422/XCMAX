/**
 * 对话主流程：草稿、发送管线、气泡点击、会话管理与工单展开联动（原单文件机械迁出）。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { Ref } from 'vue'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import { api } from '../../api'
import type { CustomerServiceIntakeConfirmation } from '../../api/workbench'
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

function receiptLabel(origin: unknown) {
  if (origin === 'admin_reply') return '管理员答复'
  if (origin === 'admin_disposition') return '管理员处置回执'
  if (origin === 'assistant_disposition') return 'AI 处置回执'
  if (origin === 'corp_download_verification') return '官网复测回执'
  return undefined
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
  const pendingConfirmation = ref<{
    message: UiMessage
    sessionId: number
    intake: CustomerServiceIntakeConfirmation
  } | null>(null)
  const intakeConfirmation = computed(() => {
    const offer = pendingConfirmation.value
    if (!offer || loading.value || readOnly.value || openedTicket.value
      || !activeSessionId.value || activeSessionId.value !== offer.sessionId
      || messages.value.at(-1) !== offer.message
      || draft.value || ctx.pendingImageDataUrl.value || ctx.imagePicking.value) return null
    return offer
  })
  let materialRevision = 0
  watch([draft, ctx.pendingImageDataUrl, ctx.imagePicking, () => route.query], () => {
    materialRevision++
    pendingConfirmation.value = null
  }, { flush: 'sync' })

  const quickPrompts = ['你好，想了解一下会员怎么买', '退款一般需要提供哪些信息？', '商品有问题想先了解怎么投诉', '账号权益没到账是怎么回事']

  onMounted(() => {
    hydrateFromQuery()
    void ctx.loadTickets()
  })

  onBeforeUnmount(() => {
    mounted = false
    conversationGeneration++
    pendingConfirmation.value = null
  })

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

  async function confirmIntake(message: UiMessage) {
    const offer = intakeConfirmation.value
    if (!offer || offer.message !== message) return
    await sendText('提交工单', { intakeConfirmation: offer.intake })
  }

  async function sendText(raw: string, extras?: {
    reason?: string
    intakeConfirmation?: CustomerServiceIntakeConfirmation
  }) {
    const text = String(raw || '').trim()
    const imageDataUrl = ctx.pendingImageDataUrl.value
    if ((!text && !imageDataUrl) || loading.value || readOnly.value || ctx.imagePicking.value) return
    const generation = conversationGeneration
    const sessionId = activeSessionId.value
    const ticketId = openedTicket.value?.id
    error.value = ''
    loading.value = true
    pendingConfirmation.value = null
    const userMsg: UiMessage = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: text || '[用户补充了图片资料]',
      imageDataUrl: imageDataUrl || null,
    }
    messages.value.push(userMsg)
    draft.value = ''
    ctx.clearPendingImage()
    const reportRevision = materialRevision
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
          ...(extras?.intakeConfirmation ? { intake_confirmation: extras.intakeConfirmation } : {}),
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
      const messagePayload = asUnknownRecord(responseMessage.payload)
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
        if ((ticketIsClosed(ticket) && messagePayload.origin !== 'assistant_disposition') || content === '已处理。') {
          content = composed
        }
      }
      const assistantMessage: UiMessage = {
        id: `a-${Date.now()}`,
        role: 'assistant',
        content,
        cards: [],
        receiptLabel: receiptLabel(messagePayload.origin),
      }
      messages.value.push(assistantMessage)
      const { source_message_id, kind } = asUnknownRecord(messagePayload.intake_confirmation)
      if (reportRevision === materialRevision && !openedTicket.value && activeSessionId.value
        && typeof source_message_id === 'number' && Number.isSafeInteger(source_message_id)
        && source_message_id > 0 && (kind === 'invalid' || kind === 'out_of_scope')) {
        pendingConfirmation.value = {
          message: assistantMessage,
          sessionId: activeSessionId.value,
          intake: { source_message_id, kind },
        }
      }
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
    pendingConfirmation.value = null
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
    openedTicket.value = { ...ticket, customer_acceptance: undefined }
    ctx.expandedTicketIds.value = new Set([...ctx.expandedTicketIds.value, ticketId])
    await reloadTicket(ticket)
  }

  async function reloadTicket(ticket: CustomerTicket) {
    const ticketId = Number(ticket.id)
    if (loading.value || Number(openedTicket.value?.id) !== ticketId) return null
    const generation = conversationGeneration
    loading.value = true
    error.value = ''
    try {
      const transcript = asUnknownRecord(await api.customerServiceTicketTranscript(ticketId))
      if (generation !== conversationGeneration) return null
      const current = asUnknownRecord(transcript.ticket)
      const sessionId = Number(transcript.session_id)
      if (Number(current.id) !== ticketId || !Number.isSafeInteger(sessionId) || sessionId <= 0
        || Number(current.session_id) !== sessionId
        || (ticket.session_id != null && Number(ticket.session_id) !== sessionId)
        || !Array.isArray(transcript.messages)) {
        throw new Error('返回的会话与原工单不一致')
      }
      const reloadedTicket: CustomerTicket = { ...ticket, ...current, customer_acceptance: current.customer_acceptance }
      openedTicket.value = reloadedTicket
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
          receiptLabel: message.role === 'assistant' ? receiptLabel(payload.origin) : undefined,
          customerDecision: message.role === 'user' && (payload.customer_decision === 'resolved'
            || payload.customer_decision === 'reopen') ? payload.customer_decision : undefined,
        }]
      })
      await scrollMessagesToEnd()
      return generation === conversationGeneration ? { ticket: reloadedTicket, messages: messages.value } : null
    } catch (cause: unknown) {
      if (generation === conversationGeneration) error.value = errorMessage(cause, '打开原客服会话失败')
      return null
    } finally {
      if (generation === conversationGeneration) loading.value = false
    }
  }

  return {
    draft, loading, error, activeSessionId, openedTicketRef, readOnly, messages, messagesEl, quickPrompts,
    hydrateFromQuery, queryContext, usePrompt, scrollMessagesToEnd, onBubbleClick,
    send, sendText, confirmIntake, intakeConfirmation, newSession, visibleCards, openTicket, reloadTicket,
    openedTicket,
  }
}

export type CustomerServiceChat = ReturnType<typeof useCustomerServiceChat>
