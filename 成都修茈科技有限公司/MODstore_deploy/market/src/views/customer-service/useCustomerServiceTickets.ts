/**
 * 侧栏工单列表状态与动作（原单文件机械迁出）。
 */
import { computed, ref } from 'vue'
import { api } from '../../api'
import { ticketLifecycleLabel } from '../../utils/csTicketLifecycle'
import { asUnknownRecord } from '../../utils/typeNarrowing'
import type { CustomerTicket } from './customerServiceTypes'

export function useCustomerServiceTickets() {
  const tickets = ref<CustomerTicket[]>([])
  const expandedTicketIds = ref<Set<number>>(new Set())

  const allTicketsExpanded = computed(() => tickets.value.length > 0 && expandedTicketIds.value.size >= tickets.value.length)

  function isTicketExpanded(id: unknown) {
    return expandedTicketIds.value.has(Number(id))
  }

  function toggleTicket(id: unknown) {
    const n = Number(id)
    if (!n) return
    const next = new Set(expandedTicketIds.value)
    if (next.has(n)) next.delete(n)
    else next.add(n)
    expandedTicketIds.value = next
  }

  function toggleAllTickets() {
    if (allTicketsExpanded.value) {
      expandedTicketIds.value = new Set()
      return
    }
    expandedTicketIds.value = new Set(tickets.value.map((t) => Number(t.id)).filter((n) => n > 0))
  }

  function preferExpandWaitingTickets(items: CustomerTicket[]) {
    const waiting = items
      .filter((t) => ticketLifecycleLabel(t) === '待补充')
      .map((t) => Number(t.id))
      .filter((n) => n > 0)
    // 默认全收起；仅自动展开一条「待补充」，避免刷屏
    expandedTicketIds.value = new Set(waiting.slice(0, 1))
  }

  async function loadTickets() {
    try {
      const res = asUnknownRecord(await api.customerServiceTickets())
      tickets.value = Array.isArray(res.items) ? (res.items as CustomerTicket[]) : []
      preferExpandWaitingTickets(tickets.value)
    } catch {
      tickets.value = []
      expandedTicketIds.value = new Set()
    }
  }

  return {
    tickets, expandedTicketIds, allTicketsExpanded,
    isTicketExpanded, toggleTicket, toggleAllTickets, preferExpandWaitingTickets, loadTickets,
  }
}

export type CustomerServiceTickets = ReturnType<typeof useCustomerServiceTickets>
