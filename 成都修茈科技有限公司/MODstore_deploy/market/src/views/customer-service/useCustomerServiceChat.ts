/**
 * 对话主流程：草稿、发送管线、气泡点击、会话管理与工单展开联动（原单文件机械迁出）。
 */
import { nextTick, onMounted, ref } from 'vue'
import type { Ref } from 'vue'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import { api } from '../../api'
import { composeTicketUserMessage, toUserFacingCards } from '../../utils/csTicketSummary'
import { asUnknownRecord, errorMessage } from '../../utils/typeNarrowing'
import type { CustomerTicket, UiMessage } from './customerServiceTypes'

export interface CustomerServiceChatCtx {
  route: RouteLocationNormalizedLoaded
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
  const messages = ref<UiMessage[]>([])
  const messagesEl = ref<HTMLElement | null>(null)

  const quickPrompts = ['你好，想了解一下会员怎么买', '退款一般需要提供哪些信息？', '商品有问题想先了解怎么投诉', '账号权益没到账是怎么回事']

  onMounted(() => {
    hydrateFromQuery()
    void ctx.loadTickets()
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
    if (msg.role !== 'assistant') return
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
    if ((!text && !imageDataUrl) || loading.value || ctx.imagePicking.value) return
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
    await scrollMessagesToEnd()
    try {
      const chatCtx = {
        ...queryContext(),
        ...(extras?.reason ? { reason: extras.reason } : {}),
      }
      const res = asUnknownRecord(
        await api.customerServiceChat({
          message: text,
          session_id: activeSessionId.value,
          context: chatCtx,
          image_data_url: imageDataUrl || undefined,
        }),
      )
      const session = asUnknownRecord(res.session)
      const responseMessage = asUnknownRecord(res.message)
      const ticket = Object.keys(asUnknownRecord(res.ticket)).length ? (asUnknownRecord(res.ticket) as CustomerTicket) : null
      activeSessionId.value = Number(session.id || activeSessionId.value || 0) || null
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
        const st = String(ticket.status || '').toLowerCase()
        // 已结案用侧栏口径摘要；跟进中优先后端话术（含问题复述），避免盖成「已处理完成」
        if (['resolved', 'closed', 'done', 'rejected'].includes(st)) {
          content = composed
        } else if (!content || content === '已处理。') {
          content = composed
        }
      }
      messages.value.push({
        id: `a-${Date.now()}`,
        role: 'assistant',
        content,
        cards: [],
      })
      // 先结束「处理中」，侧栏刷新失败/慢不得挡住对话
      loading.value = false
      if (ticket) {
        void ctx.loadTickets()
      }
      await scrollMessagesToEnd()
    } catch (e: unknown) {
      error.value = errorMessage(e, 'AI 客服处理失败')
      loading.value = false
    }
  }

  function newSession() {
    activeSessionId.value = null
    messages.value = []
    error.value = ''
  }

  function visibleCards(msg: UiMessage) {
    return toUserFacingCards(Array.isArray(msg.cards) ? msg.cards : [])
  }

  async function openTicket(ticket: CustomerTicket) {
    const tid = Number(ticket?.id || 0)
    if (tid) {
      const next = new Set(ctx.expandedTicketIds.value)
      next.add(tid)
      ctx.expandedTicketIds.value = next
    }
    try {
      const res = asUnknownRecord(await api.customerServiceTicketDetail(ticket.id))
      const t = Object.keys(asUnknownRecord(res.ticket)).length ? asUnknownRecord(res.ticket) : ticket
      const decision = Array.isArray(res.decisions) && res.decisions[0] ? asUnknownRecord(res.decisions[0]) : null
      const actions = Array.isArray(res.actions) ? res.actions : []
      messages.value.push({
        id: `t-${Date.now()}`,
        role: 'assistant',
        content: composeTicketUserMessage({ ticket: t, decision, actions }),
        cards: [],
      })
      await scrollMessagesToEnd()
    } catch (e: unknown) {
      error.value = errorMessage(e, '打开进度失败')
    }
  }

  return {
    draft, loading, error, activeSessionId, messages, messagesEl, quickPrompts,
    hydrateFromQuery, queryContext, usePrompt, scrollMessagesToEnd, onBubbleClick,
    send, sendText, newSession, visibleCards, openTicket,
  }
}

export type CustomerServiceChat = ReturnType<typeof useCustomerServiceChat>
