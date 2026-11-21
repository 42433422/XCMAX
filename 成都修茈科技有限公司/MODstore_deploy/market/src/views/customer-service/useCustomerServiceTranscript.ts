import { nextTick, reactive, ref } from 'vue'
import type { Ref } from 'vue'
import { api } from '../../api'
import { asUnknownRecord, errorMessage } from '../../utils/typeNarrowing'
import type { CustomerTicket, UiMessage } from './customerServiceTypes'

const imageType = /^image\/(?:png|jpeg|webp|gif|bmp|avif)$/

export function receiptLabel(origin: unknown) {
  if (origin === 'admin_reply') return '管理员答复'
  if (origin === 'admin_disposition') return '管理员处置回执'
  if (origin === 'assistant_disposition') return 'AI 处置回执'
  if (origin === 'corp_download_verification') return '官网复测回执'
  return undefined
}

function positiveId(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0
}

export async function fetchTicketTranscript(ticket: CustomerTicket, beforeId?: number, signal?: AbortSignal) {
  const ticketId = Number(ticket.id)
  const response = beforeId === undefined
    ? await api.customerServiceTicketTranscript(ticketId)
    : await api.customerServiceTicketTranscript(ticketId, beforeId, signal)
  const transcript = asUnknownRecord(response)
  const current = asUnknownRecord(transcript.ticket)
  const sessionId = Number(transcript.session_id)
  const cursor = transcript.next_before_id
  const nextBeforeId = positiveId(cursor) ? cursor : null
  if (Number(current.id) !== ticketId || !positiveId(sessionId)
    || Number(current.session_id) !== sessionId
    || (ticket.session_id != null && Number(ticket.session_id) !== sessionId)
    || (ticket.user_id != null && Number(ticket.user_id) !== Number(current.user_id))
    || !Array.isArray(transcript.messages)) {
    throw new Error('返回的会话与原工单不一致')
  }
  if (cursor != null && (nextBeforeId === null || (beforeId !== undefined && nextBeforeId >= beforeId))) {
    throw new Error('原客服会话的消息分页无效')
  }
  return {
    ticket: { ...ticket, ...current, customer_acceptance: current.customer_acceptance },
    sessionId,
    canReply: transcript.can_reply === true,
    messages: transcript.messages,
    nextBeforeId,
  }
}

type Transcript = Awaited<ReturnType<typeof fetchTicketTranscript>>
type PersistedMessage = UiMessage & { persistedId: number }

function readMessages(page: Transcript): PersistedMessage[] {
  const ticketId = Number(page.ticket.id)
  return page.messages.map(asUnknownRecord).flatMap(message => {
    if ((message.ticket_id == null ? !page.canReply : Number(message.ticket_id) !== ticketId)
      || (message.session_id != null && Number(message.session_id) !== page.sessionId)
      || (message.role !== 'user' && message.role !== 'assistant')
      || !positiveId(message.id) || typeof message.content !== 'string') return []
    const payload = asUnknownRecord(message.payload)
    const image = payload.image_data_url
    return [{
      id: `persisted-${message.id}`,
      persistedId: message.id,
      role: message.role,
      content: message.content,
      imageDataUrl: message.role === 'user' && typeof image === 'string'
        && /^data:image\/(?:png|jpeg|webp|gif|bmp|avif);base64,/.test(image) ? image : null,
      screenshotMessageId: message.role === 'user' && payload.has_screenshot === true ? message.id : undefined,
      receiptLabel: message.role === 'assistant' ? receiptLabel(payload.origin) : undefined,
      customerDecision: message.role === 'user' && (payload.customer_decision === 'resolved'
        || payload.customer_decision === 'reopen') ? payload.customer_decision : undefined,
    }]
  })
}

interface TranscriptContext {
  ticket: Ref<CustomerTicket | null>
  sessionId: Ref<number | null>
  messages: Ref<UiMessage[]>
  messagesEl: Ref<HTMLElement | null>
  loading: Ref<boolean>
  error: Ref<string>
}

export function useCustomerServiceTranscript(ctx: TranscriptContext) {
  const nextBeforeId = ref<number | null>(null)
  const loadingOlder = ref(false)
  const imageUrls = reactive(new Map<number, string>())
  const screenshotLoading = reactive(new Set<number>())
  let view = new AbortController()

  function clearTranscript() {
    view.abort()
    view = new AbortController()
    for (const url of imageUrls.values()) URL.revokeObjectURL(url)
    imageUrls.clear()
    screenshotLoading.clear()
    nextBeforeId.value = null
    loadingOlder.value = false
  }

  function mergePage(incoming: UiMessage[], keepOptimistic: boolean) {
    const rows = new Map<number, UiMessage>()
    for (const message of [...ctx.messages.value, ...incoming]) {
      if (message.persistedId !== undefined) rows.set(message.persistedId, message)
    }
    const persisted = [...rows].sort(([a], [b]) => a - b).map(([, message]) => message)
    ctx.messages.value = keepOptimistic
      ? [...persisted, ...ctx.messages.value.filter(message => message.persistedId === undefined)]
      : persisted
  }

  function applyLatestPage(page: Transcript) {
    const incoming = readMessages(page)
    const currentIds = new Set(ctx.messages.value.map(message => message.persistedId))
    if (!incoming.some(message => currentIds.has(message.persistedId))) {
      nextBeforeId.value = page.nextBeforeId
    }
    mergePage(incoming, false)
  }

  async function loadOlderMessages() {
    const ticket = ctx.ticket.value
    const beforeId = nextBeforeId.value
    if (!ticket || beforeId === null || loadingOlder.value || ctx.loading.value) return
    const signal = view.signal
    loadingOlder.value = true
    ctx.error.value = ''
    try {
      const page = await fetchTicketTranscript(ticket, beforeId, signal)
      if (signal.aborted || beforeId !== nextBeforeId.value || page.sessionId !== ctx.sessionId.value) return
      const el = ctx.messagesEl.value
      const priorHeight = el?.scrollHeight ?? 0
      const older = readMessages(page).filter(message => message.persistedId < beforeId)
      mergePage(older, true)
      nextBeforeId.value = page.nextBeforeId
      await nextTick()
      if (!signal.aborted && el) el.scrollTop += el.scrollHeight - priorHeight
    } catch (cause: unknown) {
      if (!signal.aborted) ctx.error.value = errorMessage(cause, '未能读取更早的消息，请重试')
    } finally {
      if (!signal.aborted) loadingOlder.value = false
    }
  }

  function screenshotUrl(message: UiMessage) {
    return message.imageDataUrl || imageUrls.get(message.screenshotMessageId ?? 0)
  }

  async function loadScreenshot(message: UiMessage) {
    const ticket = ctx.ticket.value
    const id = message.screenshotMessageId
    if (!ticket || id === undefined || screenshotUrl(message) || screenshotLoading.has(id)
      || !ctx.messages.value.includes(message)) return
    const signal = view.signal
    screenshotLoading.add(id)
    ctx.error.value = ''
    try {
      const image = await api.customerServiceTicketTranscriptImage(
        ticket.id, id, AbortSignal.any([signal, AbortSignal.timeout(15_000)]),
      )
      if (signal.aborted) return
      if (!image.size || !imageType.test(image.type)) throw new Error('返回的截图格式无效')
      imageUrls.set(id, URL.createObjectURL(image))
    } catch (cause: unknown) {
      if (!signal.aborted) ctx.error.value = errorMessage(cause, '未能读取原工单截图，请重试')
    } finally {
      if (!signal.aborted) screenshotLoading.delete(id)
    }
  }

  return {
    clearTranscript, applyLatestPage, nextBeforeId, loadingOlder, loadOlderMessages,
    screenshotUrl, screenshotLoading, loadScreenshot,
  }
}
