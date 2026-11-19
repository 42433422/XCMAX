import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { api } from '../../api'
import type { CustomerServiceIssueDecision } from '../../api/workbench'
import { ApiError } from '../../infrastructure/http/client'
import { asUnknownRecord, errorMessage, isUnknownRecord } from '../../utils/typeNarrowing'
import type { CustomerTicket, UiMessage } from './customerServiceTypes'
import type { CustomerServiceChat } from './useCustomerServiceChat'

type Decision = CustomerServiceIssueDecision['decision']
type PendingDecision = Pick<CustomerServiceIssueDecision, 'decision' | 'idempotency_key'> & {
  noteDigest: string
}

function savedAttempt(scope: string): PendingDecision | undefined {
  try {
    const { decision, idempotency_key, noteDigest } = asUnknownRecord(JSON.parse(sessionStorage.getItem(scope) || 'null'))
    if ((decision === 'resolved' || decision === 'reopen')
      && typeof idempotency_key === 'string' && /^[a-f0-9-]{36}$/.test(idempotency_key)
      && typeof noteDigest === 'string' && /^[a-f0-9]{64}$/.test(noteDigest)) {
      return { decision, idempotency_key, noteDigest }
    }
  } catch {
    // A disallowed session store does not prevent a live attempt.
  }
  return undefined
}

async function noteDigest(note: string) {
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(note))
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, '0')).join('')
}

export function useCustomerServiceDecision(
  chat: Pick<CustomerServiceChat, 'openedTicket' | 'messages' | 'loading' | 'reloadTicket'>,
  loadTickets: () => Promise<void>,
) {
  const note = ref('')
  const notice = ref('')
  const inFlight = ref(false)
  const attempts = reactive(new Map<string, PendingDecision>())
  let mounted = true
  onBeforeUnmount(() => { mounted = false })
  const current = computed(() => {
    const ticket = chat.openedTicket.value
    if (ticket?.intent !== 'product_issue' || !isUnknownRecord(ticket.customer_acceptance)) return null
    const ownerId = Number(ticket.user_id)
    const ticketId = Number(ticket.id)
    if (!Number.isSafeInteger(ownerId) || ownerId <= 0 || !Number.isSafeInteger(ticketId) || ticketId <= 0) return null
    return { ticket, ticketId, scope: `market:customer-decision:${ownerId}:${ticketId}` }
  })
  const scope = computed(() => current.value?.scope || '')
  const acceptance = computed(() => asUnknownRecord(current.value?.ticket.customer_acceptance))
  const pending = computed(() => attempts.get(scope.value))
  const canResolve = computed(() => acceptance.value.can_resolve === true)
  const canReopen = computed(() => acceptance.value.can_reopen === true)
  const busy = computed(() => inFlight.value || chat.loading.value)
  const visible = computed(() => !!scope.value && (canResolve.value || canReopen.value || !!pending.value || !!notice.value))
  const validNote = computed(() => {
    const length = [...note.value.trim()].length
    return length >= 4 && length <= 2000
  })

  function remember(key: string, attempt?: PendingDecision) {
    if (attempt) attempts.set(key, attempt)
    else attempts.delete(key)
    try {
      if (attempt) sessionStorage.setItem(key, JSON.stringify(attempt))
      else sessionStorage.removeItem(key)
    } catch {
      // Keep the same attempt in this view if browser storage is unavailable.
    }
  }

  function settle(key: string, ticket: CustomerTicket, messages: UiMessage[]) {
    const attempt = attempts.get(key)
    const receipt = asUnknownRecord(asUnknownRecord(ticket.customer_acceptance).last_decision)
    if (!attempt || receipt.idempotency_key !== attempt.idempotency_key || receipt.decision !== attempt.decision
      || messages.findLast(message => message.customerDecision)?.customerDecision !== attempt.decision) {
      return false
    }
    remember(key)
    if (scope.value === key) {
      note.value = ''
      const resolved = ticket.status === 'resolved' && !!ticket.closed_at
      const reopened = ticket.status === 'processing' && !ticket.closed_at
      notice.value = attempt.decision === 'resolved' && resolved ? '已核对原工单，状态为已解决。'
        : attempt.decision === 'reopen' && reopened ? '已核对原工单，已重新进入处理。'
          : '原操作已记录，工单状态已有更新。'
    }
    return true
  }

  watch(scope, (key) => {
    note.value = ''
    notice.value = ''
    if (key && current.value) {
      const stored = savedAttempt(key)
      if (stored && !attempts.has(key)) attempts.set(key, stored)
      settle(key, current.value.ticket, chat.messages.value)
    }
  })

  async function reload(selection: NonNullable<typeof current.value>) {
    const readback = await chat.reloadTicket(selection.ticket)
    void loadTickets()
    if (!mounted || !readback || scope.value !== selection.scope) return 'unavailable'
    return settle(selection.scope, readback.ticket, readback.messages) ? 'recorded' : 'missing'
  }

  async function checkDecision() {
    const selection = current.value
    if (!selection || busy.value || !pending.value) return
    inFlight.value = true
    try {
      if (await reload(selection) !== 'recorded' && scope.value === selection.scope) {
        notice.value = '暂未在原工单查到此操作的回执。'
      }
    } finally {
      inFlight.value = false
    }
  }

  async function submitDecision(decision: Decision) {
    const selection = current.value
    if (!selection || busy.value || !validNote.value
      || !(decision === 'resolved' ? canResolve.value : canReopen.value)) return
    const key = selection.scope
    const trimmed = note.value.trim()
    const earlier = pending.value
    inFlight.value = true
    notice.value = ''
    try {
      const digest = await noteDigest(trimmed)
      if (!mounted || scope.value !== key) return
      if (earlier && (earlier.decision !== decision || earlier.noteDigest !== digest)) {
        notice.value = '请填写上次提交的原说明，才能按原请求重试。'
        return
      }
      const attempt = earlier || { decision, idempotency_key: crypto.randomUUID(), noteDigest: digest }
      remember(key, attempt)
      let rejection: unknown
      try {
        await api.customerServiceIssueDecision(selection.ticketId, {
          decision, note: trimmed, idempotency_key: attempt.idempotency_key,
        })
      } catch (cause: unknown) {
        rejection = cause
      }
      if (!mounted) return
      if (scope.value !== key) {
        void loadTickets()
        return
      }
      const readback = await reload(selection)
      if (readback === 'recorded' || scope.value !== key) return
      if (readback === 'missing' && rejection instanceof ApiError && [400, 401, 403, 404, 422].includes(rejection.status)) {
        remember(key)
        notice.value = errorMessage(rejection)
      } else {
        notice.value = '暂未核对到回执。请先核对原工单，或按原请求重试。'
      }
    } catch (cause: unknown) {
      if (scope.value === key) notice.value = errorMessage(cause, '无法提交工单验收')
    } finally {
      inFlight.value = false
    }
  }

  return { note, notice, pending, canResolve, canReopen, busy, visible, validNote, checkDecision, submitDecision }
}
