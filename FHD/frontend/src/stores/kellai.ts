/** Shared account-scoped state for the Kellai module and the existing IM entry. */
import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import api, {
  type KellaiBindingStatus, type KellaiChannel, type KellaiCustomer,
  type KellaiConversationMessage, type KellaiDataStatus, type KellaiSendInput, type KellaiSendReceipt,
} from '@/api/kellaiBinding'
import { useKellaiCopilot } from '@/components/im/kellaiInbox/useKellaiCopilot'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'

export const KELLAI_READ_SCOPES = ['customer_profiles.read', 'customer_conversations.read']
export const deliveryTargetKey = (input: Pick<KellaiSendInput, 'customer_id' | 'channel_type' | 'contact_id'>): string =>
  JSON.stringify([input.customer_id, input.channel_type, input.contact_id])

type Delivery = { request_id: string; receipt: KellaiSendReceipt; checking: boolean; error: string }
const unresolved = (status: string): boolean => !['accepted', 'delivered', 'failed', 'rejected', 'requires_desktop_execution'].includes(status)

export const useKellaiStore = defineStore('kellai', () => {
  const binding = ref<KellaiBindingStatus>({ state: 'not_connected' })
  const dataStatus = ref<KellaiDataStatus | null>(null)
  const customers = ref<KellaiCustomer[]>([])
  const messages = ref<KellaiConversationMessage[]>([])
  const channels = ref<KellaiChannel[]>([])
  const activeCustomerId = ref<number | null>(null)
  const busy = ref(false)
  const customersLoading = ref(false)
  const messagesLoading = ref(false)
  const error = ref('')
  const channelError = ref('')
  const deliveries = ref<Record<string, Delivery>>({})
  let revision = 0
  let conversationRevision = 0
  let consumers = 0
  let timer: ReturnType<typeof setInterval> | undefined
  const copilot = useKellaiCopilot({ activeCustomerId, messages, error })
  const scopes = computed(() => binding.value.connection?.authorized_scopes || [])
  const canSend = computed(() => scopes.value.includes('messages.send'))
  const activeCustomer = computed(() => customers.value.find(item => item.customer_id === activeCustomerId.value) || null)
  const orderedMessages = computed(() => [...messages.value].sort((a, b) => String(a.created_at || '').localeCompare(String(b.created_at || ''))))
  const statusLabel = computed(() => ({ connected: '已连接', pending: '等待授权', offline: '客来来未运行', not_connected: '未连接' })[binding.value.state])
  const current = () => { const saved = revision; return () => saved === revision }
  const deliveryStorageKey = () => `kellai-requests:${binding.value.connection?.connection_id || ''}`

  function saveRequests(): void {
    // Store only receipt identifiers, never message content or access tokens.
    try {
      sessionStorage.setItem(deliveryStorageKey(), JSON.stringify(Object.fromEntries(
        Object.entries(deliveries.value).map(([key, item]) => [key, item.request_id]),
      )))
    } catch { /* In-memory receipt recovery remains available when storage is disabled. */ }
  }

  function restoreRequests(): void {
    try {
      const saved: unknown = JSON.parse(sessionStorage.getItem(deliveryStorageKey()) || '{}')
      if (!saved || typeof saved !== 'object') return
      for (const [key, requestId] of Object.entries(saved)) {
        if (typeof requestId !== 'string' || !/^[A-Za-z0-9_-]{12,128}$/.test(requestId)) continue
        deliveries.value[key] = { request_id: requestId, receipt: { request_id: requestId, status: 'unknown' }, checking: false, error: '' }
      }
    } catch { /* Untrusted storage is not a source of send authorization. */ }
  }

  function clearConversation(): void {
    conversationRevision++
    messages.value = []
    messagesLoading.value = false
    copilot.resetConversationState()
  }

  function reset(): void {
    revision++
    binding.value = { state: 'not_connected' }
    dataStatus.value = null
    customers.value = []
    channels.value = []
    activeCustomerId.value = null
    deliveries.value = {}
    busy.value = false
    customersLoading.value = false
    error.value = ''
    channelError.value = ''
    clearConversation()
  }

  async function loadMessages(customerId = activeCustomerId.value): Promise<void> {
    if (!customerId) return
    const valid = current()
    const requestRevision = ++conversationRevision
    const applies = () => valid() && requestRevision === conversationRevision && activeCustomerId.value === customerId
    messagesLoading.value = true
    try {
      const [nextMessages, draft, overview] = await Promise.all([
        api.conversations(customerId, 100), api.latestDraft(customerId), api.followUpOverview(customerId),
      ])
      if (!applies()) return
      messages.value = nextMessages
      copilot.applyConversationData(draft, overview.tasks || [], overview.metrics)
    } catch (cause) {
      if (applies()) error.value = cause instanceof Error ? cause.message : '无法读取客户会话'
    } finally {
      if (applies()) messagesLoading.value = false
    }
  }

  async function refreshAll(): Promise<void> {
    if (busy.value) return
    const valid = current()
    busy.value = true
    error.value = ''
    channelError.value = ''
    try {
      const nextBinding = await api.status()
      if (!valid()) return
      const changed = nextBinding.connection?.connection_id !== binding.value.connection?.connection_id
      binding.value = nextBinding
      if (changed) {
        clearConversation()
        deliveries.value = {}
        if (nextBinding.state === 'connected') restoreRequests()
      }
      if (nextBinding.state !== 'connected') {
        dataStatus.value = null
        customers.value = []
        channels.value = []
        activeCustomerId.value = null
        clearConversation()
        return
      }
      customersLoading.value = true
      const [statusResult, customerResult, channelResult] = await Promise.allSettled([
        api.dataStatus(), api.customers(50), scopes.value.includes('channels.read') ? api.channels() : Promise.resolve([]),
      ])
      if (!valid()) return
      dataStatus.value = statusResult.status === 'fulfilled' ? statusResult.value : null
      customers.value = customerResult.status === 'fulfilled' ? customerResult.value : []
      channels.value = channelResult.status === 'fulfilled' ? channelResult.value : []
      if (channelResult.status === 'rejected') channelError.value = String(channelResult.reason?.message || '无法读取渠道能力')
      const readFailure = [statusResult, customerResult].find(result => result.status === 'rejected')
      if (readFailure?.status === 'rejected') error.value = String(readFailure.reason?.message || '无法读取客来来数据')
      if (!customers.value.some(item => item.customer_id === activeCustomerId.value)) {
        activeCustomerId.value = customers.value[0]?.customer_id || null
        clearConversation()
      }
      if (activeCustomerId.value) await loadMessages(activeCustomerId.value)
    } catch (cause) {
      if (valid()) {
        customers.value = []
        channels.value = []
        dataStatus.value = null
        clearConversation()
        error.value = cause instanceof Error ? cause.message : '无法读取客来来客户会话'
      }
    } finally {
      if (valid()) { busy.value = false; customersLoading.value = false }
    }
  }

  async function selectCustomer(customer: KellaiCustomer): Promise<void> {
    if (activeCustomerId.value === customer.customer_id && messages.value.length) return
    activeCustomerId.value = customer.customer_id
    error.value = ''
    clearConversation()
    await loadMessages(customer.customer_id)
  }

  async function openKellai(): Promise<void> {
    const desktop = (window as Window & { xcagiDesktop?: { openKellaiDesktop?: () => Promise<{ ok?: boolean; reason?: string }> } }).xcagiDesktop
    if (desktop?.openKellaiDesktop) {
      const result = await desktop.openKellaiDesktop()
      if (!result?.ok) throw new Error(result?.reason || '无法打开客来来桌面端')
      return
    }
    const opened = window.open('kellai://settings?tab=xcmax', '_blank', 'noopener,noreferrer')
    if (!opened) throw new Error('请使用 XCMAX 桌面端打开客来来，或在本机启动客来来完成授权与渠道配置')
  }

  async function handleOpenKellai(): Promise<void> {
    try { await openKellai() } catch (cause) { error.value = cause instanceof Error ? cause.message : '无法打开客来来' }
  }

  async function startBinding(requestedScopes?: string[]): Promise<void> {
    const valid = current()
    busy.value = true
    error.value = ''
    try {
      await api.start(requestedScopes)
      if (!valid()) return
      const status = await api.status()
      if (valid()) { binding.value = status; await openKellai() }
    } catch (cause) {
      if (valid()) error.value = cause instanceof Error ? cause.message : '无法发起客来来授权'
    } finally { if (valid()) busy.value = false }
  }

  async function disconnect(): Promise<void> {
    if (!window.confirm('解除后将停止读取和发送，清除本地客户摘要与跟进任务；已被渠道受理的消息无法撤回。')) return
    const valid = current()
    busy.value = true
    try {
      await api.disconnect()
      if (valid()) {
        try { sessionStorage.removeItem(deliveryStorageKey()) } catch { /* Storage may be disabled. */ }
        reset()
      }
    } catch (cause) {
      if (valid()) error.value = cause instanceof Error ? cause.message : '解除绑定失败'
    } finally { if (valid()) busy.value = false }
  }

  async function submitMessage(input: Omit<KellaiSendInput, 'client_request_id'>): Promise<void> {
    const key = deliveryTargetKey(input)
    if (!canSend.value || unresolved(deliveries.value[key]?.receipt.status || 'failed')) return
    const channel = channels.value.find(item => item.type === input.channel_type)
    if (!channel?.enabled || !channel.connected || !channel.capabilities.send) return
    const requestId = crypto.randomUUID()
    const valid = current()
    const connectionId = binding.value.connection?.connection_id
    const applies = () => valid() && connectionId === binding.value.connection?.connection_id && deliveries.value[key]?.request_id === requestId
    const delivery: Delivery = { request_id: requestId, receipt: { request_id: requestId, status: 'sending' }, checking: true, error: '' }
    deliveries.value[key] = delivery
    saveRequests()
    try {
      const receipt = await api.sendMessage({ ...input, client_request_id: requestId })
      if (applies()) deliveries.value[key].receipt = receipt
    } catch (cause) {
      if (applies()) {
        deliveries.value[key].receipt = { request_id: requestId, status: 'unknown' }
        deliveries.value[key].error = cause instanceof Error ? cause.message : '结果未知，请查询回执'
      }
    } finally { if (applies()) deliveries.value[key].checking = false }
  }

  async function queryReceipt(key: string): Promise<void> {
    const delivery = deliveries.value[key]
    if (!delivery || delivery.checking || !canSend.value) return
    const valid = current()
    delivery.checking = true
    try {
      const receipt = await api.sendReceipt(delivery.request_id)
      if (valid()) { delivery.receipt = receipt; delivery.error = '' }
    } catch (cause) {
      if (valid()) delivery.error = cause instanceof Error ? cause.message : '无法查询回执'
    } finally { if (valid()) delivery.checking = false }
  }

  function attach(): void {
    if (++consumers !== 1) return
    void refreshAll()
    timer = setInterval(() => { if (binding.value.pending || binding.value.state === 'pending') void refreshAll() }, 4000)
  }
  function detach(): void {
    consumers = Math.max(0, consumers - 1)
    if (!consumers && timer) { clearInterval(timer); timer = undefined }
  }
  watch(productReadAccountEpoch, () => { reset(); if (consumers) void refreshAll() }, { flush: 'sync' })

  return {
    binding, dataStatus, customers, messages, channels, activeCustomerId, busy, customersLoading,
    messagesLoading, error, channelError, deliveries, scopes, canSend, activeCustomer, orderedMessages, statusLabel,
    ...copilot, refreshAll, loadMessages, selectCustomer, startBinding, handleOpenKellai,
    disconnect, submitMessage, queryReceipt, attach, detach, reset,
  }
})
