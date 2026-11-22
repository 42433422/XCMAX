/** Shared account-scoped state for the Kellai module and the existing IM entry. */
import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import api, {
  type KellaiBindingStatus, type KellaiChannel, type KellaiContact,
  type KellaiConversationMessage, type KellaiSendInput, type KellaiSendReceipt,
} from '@/api/kellaiBinding'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { getRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'

export const KELLAI_READ_SCOPES = ['channels.read', 'messages.read']
export const KELLAI_MESSAGE_MAX_LENGTH = 8000
export const deliveryTargetKey = (input: Pick<KellaiSendInput, 'customer_id' | 'connection_id' | 'channel_type' | 'contact_id'>): string =>
  JSON.stringify([input.customer_id, input.connection_id, input.channel_type, input.contact_id])

type Delivery = { request_id: string; target_key: string; receipt: KellaiSendReceipt; checking: boolean; error: string }
const unresolved = (status: string): boolean => !['accepted', 'delivered', 'failed', 'rejected', 'cancelled', 'requires_desktop_execution'].includes(status)
const grantRevoked = (cause: unknown): boolean => !!cause && typeof cause === 'object'
  && ['xcmax_grant_revoked', 'xcmax_grant_invalid', 'xcmax_reauthorization_required'].includes(String((cause as { code?: string }).code || ''))
const requestNotDispatched = (cause: unknown): boolean => grantRevoked(cause) || !!cause && typeof cause === 'object'
  && (cause as { requestNotDispatched?: boolean }).requestNotDispatched === true

export const useKellaiStore = defineStore('kellai', () => {
  const binding = ref<KellaiBindingStatus>({ state: 'not_connected' })
  const contacts = ref<KellaiContact[]>([])
  const messages = ref<KellaiConversationMessage[]>([])
  const channels = ref<KellaiChannel[]>([])
  const activeContactId = ref<number | null>(null)
  const activeConnectionId = ref<string | null>(null)
  const busy = ref(false)
  const contactsLoading = ref(false)
  const messagesLoading = ref(false)
  const error = ref('')
  const channelError = ref('')
  const deliveries = ref<Record<string, Delivery>>({})
  const blockedTargets = computed(() => new Set(Object.values(deliveries.value)
    .filter(item => unresolved(item.receipt.status)).map(item => item.target_key)))
  const unresolvedLegacy = computed(() => Object.values(deliveries.value)
    .some(item => unresolved(item.receipt.status) && JSON.parse(item.target_key)[1] === ''))
  let revision = 0
  let conversationRevision = 0
  let consumers = 0
  let deliveryScope = ''
  let receiptRecovery: (() => boolean) | undefined
  let timer: ReturnType<typeof setInterval> | undefined
  const scopes = computed(() => binding.value.connection?.authorized_scopes || [])
  const canSend = computed(() => binding.value.state === 'connected' && scopes.value.includes('messages.send'))
  const activeContact = computed(() => contacts.value.find(item => item.customer_id === activeContactId.value && item.connection_id === activeConnectionId.value) || null)
  const orderedMessages = computed(() => [...messages.value].sort((a, b) => String(a.created_at || '').localeCompare(String(b.created_at || ''))))
  const statusLabel = computed(() => ({ connected: '已连接', pending: '等待授权', offline: '客来来不可达', not_connected: '未连接', revoked: '授权已失效' })[binding.value.state])
  const current = () => { const saved = revision; return () => saved === revision }
  const deliveryStorageKey = (): string => {
    const identity = getRuntimeTenantStorageScopeInput()
    const connectionId = binding.value.connection?.connection_id
    if (!connectionId || !identity || (!identity.localUserId && !identity.marketUserId)) return ''
    return `kellai-requests:v2:${JSON.stringify([identity.tenantId ?? null, identity.marketUserId ?? null,
      identity.localUserId ?? null, identity.accountKind ?? ''])}`
  }

  function saveRequests(): boolean {
    // Store only receipt identifiers, never message content or access tokens.
    try {
      if (!deliveryStorageKey()) return false
      localStorage.setItem(deliveryStorageKey(), JSON.stringify(Object.fromEntries(
        Object.values(deliveries.value).filter(item => item.receipt.status !== 'requires_desktop_execution' && !(item.receipt.status === 'rejected' && item.receipt.persisted === false))
          .map(item => [item.request_id, item.target_key]),
      )))
      return true
    } catch { return false }
  }

  function applyReceipt(delivery: Delivery, receipt: KellaiSendReceipt): void {
    const target = JSON.parse(delivery.target_key) as [number, string, string, string]
    if (receipt.customer_id !== undefined && receipt.customer_id !== target[0]
      || receipt.channel_type !== undefined && receipt.channel_type !== target[2]
      || receipt.contact_id !== undefined && receipt.contact_id !== target[3]
      || target[1] && receipt.connection_id !== undefined && receipt.connection_id !== target[1]) {
      throw new Error('回执账号或联系人与原请求不符')
    }
    if (!target[1] && receipt.connection_id) {
      target[1] = receipt.connection_id
      delivery.target_key = JSON.stringify(target)
    }
    delivery.receipt = receipt
    delivery.error = ''
    if (!saveRequests()) delivery.error = '无法更新本机请求记录，请保留回执'
  }

  function restoreRequests(): boolean {
    const storageKey = deliveryStorageKey()
    if (!storageKey) return false
    if (deliveryScope !== storageKey) { deliveries.value = {}; deliveryScope = storageKey }
    try {
      const sources = [storageKey]
      const identity = JSON.parse(storageKey.slice('kellai-requests:v2:'.length))
      // One-time migration preserves unresolved sends across re-authorization.
      for (const key of Object.keys(localStorage)) {
        if (!key.startsWith('kellai-requests:[')) continue
        const previous: unknown = JSON.parse(key.slice('kellai-requests:'.length))
        if (Array.isArray(previous) && previous.length === 5
          && JSON.stringify(previous.slice(0, 4)) === JSON.stringify(identity)) sources.push(key)
      }
      for (const source of sources) {
        const saved: unknown = JSON.parse(localStorage.getItem(source) || '{}')
        if (!saved || typeof saved !== 'object' || Array.isArray(saved)) throw new Error('Invalid request record')
        for (const [storedKey, storedValue] of Object.entries(saved)) {
          // Earlier candidates stored one request per target; keep that ID on migration.
          const legacy = storedKey.startsWith('[')
          const requestId = legacy ? storedValue : storedKey
          let targetKey = legacy ? storedKey : storedValue
          if (typeof targetKey !== 'string') throw new Error('Invalid request record')
          const target: unknown = JSON.parse(targetKey)
          if (source !== storageKey && Array.isArray(target) && target.length === 3) target.splice(1, 0, '')
          if (!Array.isArray(target) || target.length !== 4 || !Number.isInteger(target[0])
            || target.slice(1).some(value => typeof value !== 'string')
            || typeof requestId !== 'string' || !/^[A-Za-z0-9_-]{12,128}$/.test(requestId)) throw new Error('Invalid request record')
          targetKey = JSON.stringify(target)
          const existing = deliveries.value[requestId]
          if (existing) {
            if (existing.target_key !== targetKey) throw new Error('Request target changed')
            continue
          }
          deliveries.value[requestId] = { request_id: requestId, target_key: targetKey, receipt: { request_id: requestId, status: 'unknown' }, checking: false, error: '' }
        }
      }
      if (sources.length > 1) {
        if (!saveRequests()) throw new Error('Cannot persist request migration')
        sources.slice(1).forEach(key => localStorage.removeItem(key))
      }
      return true
    } catch {
      error.value = '无法恢复原发送请求号，暂不能发送，请恢复本机存储后重试'
      return false
    }
  }

  function clearConversation(): void {
    conversationRevision++
    messages.value = []
    messagesLoading.value = false
  }

  function observeRevocation(cause: unknown): void {
    if (!grantRevoked(cause)) return
    binding.value = { ...binding.value, state: 'revoked', requires_reauthorization: true }
    contacts.value = []; channels.value = []
    activeContactId.value = null; activeConnectionId.value = null
    clearConversation()
  }

  function reset(): void {
    revision++
    binding.value = { state: 'not_connected' }
    contacts.value = []
    channels.value = []
    activeContactId.value = null
    activeConnectionId.value = null
    deliveries.value = {}
    deliveryScope = ''
    busy.value = false
    contactsLoading.value = false
    error.value = ''
    channelError.value = ''
    clearConversation()
  }

  async function loadMessages(customerId = activeContactId.value): Promise<void> {
    if (!customerId) return
    const connectionId = activeConnectionId.value
    if (!connectionId) return
    const valid = current()
    const requestRevision = ++conversationRevision
    const applies = () => valid() && requestRevision === conversationRevision && activeContactId.value === customerId && activeConnectionId.value === connectionId
    messagesLoading.value = true
    try {
      const nextMessages = await api.messages(customerId, connectionId, 100)
      if (!applies()) return
      messages.value = nextMessages
    } catch (cause) {
      if (applies()) { error.value = cause instanceof Error ? cause.message : '无法读取联系人消息'; observeRevocation(cause) }
    } finally {
      if (applies()) messagesLoading.value = false
    }
  }

  async function recoverReceipts(): Promise<void> {
    if (receiptRecovery?.() || !canSend.value || !deliveryScope) return
    const valid = current()
    const storageScope = deliveryScope
    const scopedDeliveries = deliveries.value
    const connectionId = binding.value.connection?.connection_id
    const applies = () => valid() && storageScope === deliveryScope && scopedDeliveries === deliveries.value
      && connectionId === binding.value.connection?.connection_id && binding.value.state === 'connected' && canSend.value
    receiptRecovery = applies
    try {
      const pending = Object.keys(deliveries.value).filter(id => unresolved(deliveries.value[id].receipt.status))
      for (let offset = 0; offset < pending.length && applies(); offset += 4) {
        await Promise.all(pending.slice(offset, offset + 4).map(queryReceipt))
      }
    } finally {
      if (receiptRecovery === applies) receiptRecovery = undefined
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
      }
      // Recover identifiers even when the first status after a restart is offline.
      if (nextBinding.connection?.connection_id) restoreRequests()
      if (nextBinding.state !== 'connected') {
        contacts.value = []
        channels.value = []
        activeContactId.value = null
        activeConnectionId.value = null
        clearConversation()
        return
      }
      // Request IDs already block duplicates; provider latency must not block local reads.
      void recoverReceipts()
      contactsLoading.value = true
      const [contactResult, channelResult] = await Promise.allSettled([
        scopes.value.includes('messages.read') ? api.contacts(100) : Promise.resolve([]),
        scopes.value.includes('channels.read') ? api.channels() : Promise.resolve([]),
      ])
      if (!valid() || binding.value.state !== 'connected') return
      contacts.value = contactResult.status === 'fulfilled' ? contactResult.value : []
      channels.value = channelResult.status === 'fulfilled' ? channelResult.value : []
      if (channelResult.status === 'rejected') channelError.value = String(channelResult.reason?.message || '无法读取渠道能力')
      if (contactResult.status === 'rejected') error.value = String(contactResult.reason?.message || '无法读取联系人')
      if (contactResult.status === 'rejected') observeRevocation(contactResult.reason)
      if (channelResult.status === 'rejected') observeRevocation(channelResult.reason)
      if (!contacts.value.some(item => item.customer_id === activeContactId.value && item.connection_id === activeConnectionId.value)) {
        activeContactId.value = null
        activeConnectionId.value = null
        clearConversation()
      }
      if (activeContactId.value) await loadMessages(activeContactId.value)
    } catch (cause) {
      if (valid()) {
        contacts.value = []
        channels.value = []
        clearConversation()
        error.value = cause instanceof Error ? cause.message : '无法读取客来来消息'
      }
    } finally {
      if (valid()) { busy.value = false; contactsLoading.value = false }
    }
  }

  async function selectContact(customer: KellaiContact): Promise<void> {
    if (activeContactId.value === customer.customer_id && activeConnectionId.value === customer.connection_id && messages.value.length) return
    activeContactId.value = customer.customer_id
    activeConnectionId.value = customer.connection_id
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
    if (!window.confirm('解除后将停止读取和发送；原发送请求记录保留用于核对，已被渠道受理的消息无法撤回。')) return
    const valid = current()
    busy.value = true
    try {
      await api.disconnect()
      if (valid()) {
        reset()
      }
    } catch (cause) {
      if (valid()) error.value = cause instanceof Error ? cause.message : '解除绑定失败'
    } finally { if (valid()) busy.value = false }
  }

  async function submitMessage(input: Omit<KellaiSendInput, 'client_request_id'>): Promise<string | undefined> {
    const key = deliveryTargetKey(input)
    if (!canSend.value) return
    if (!input.content.trim() || Array.from(input.content).length > KELLAI_MESSAGE_MAX_LENGTH) {
      error.value = `消息不能为空且不能超过 ${KELLAI_MESSAGE_MAX_LENGTH} 个字符`
      return
    }
    if (!restoreRequests()) { error.value ||= '账号或连接尚未确认，暂不能发送'; return }
    if (unresolvedLegacy.value) { error.value = '旧账号有未决发送，请先查询原回执'; return }
    if (blockedTargets.value.has(key)) return
    const channel = channels.value.find(item => item.connection_id === input.connection_id && item.channel_type === input.channel_type)
    if (!channel?.enabled || !channel.connected || !channel.capabilities.send) return
    if (!contacts.value.some(contact => contact.customer_id === input.customer_id && contact.connection_id === input.connection_id
      && contact.channel_type === input.channel_type && contact.contact_id === input.contact_id)) return
    const requestId = crypto.randomUUID()
    const valid = current()
    const connectionId = binding.value.connection?.connection_id
    const applies = () => valid() && connectionId === binding.value.connection?.connection_id && !!deliveries.value[requestId]
    const delivery: Delivery = { request_id: requestId, target_key: key, receipt: { request_id: requestId, status: 'sending' }, checking: true, error: '' }
    deliveries.value[requestId] = delivery
    if (!saveRequests()) {
      delete deliveries.value[requestId]
      error.value = '无法保存发送请求号，消息未发送，请检查本机存储后重试'
      return
    }
    try {
      const receipt = await api.sendMessage({ ...input, client_request_id: requestId })
      if (applies()) applyReceipt(deliveries.value[requestId], receipt)
    } catch (cause) {
      if (applies()) {
        // This ID was created just above and has had exactly one send attempt.
        // A denial of a later receipt read must never clear an unknown send.
        deliveries.value[requestId].receipt = requestNotDispatched(cause)
          ? { request_id: requestId, status: 'rejected', persisted: false }
          : { request_id: requestId, status: 'unknown' }
        deliveries.value[requestId].error = cause instanceof Error ? cause.message : '结果未知，请查询回执'
        observeRevocation(cause)
        if (requestNotDispatched(cause)) saveRequests()
      }
    } finally { if (applies()) deliveries.value[requestId].checking = false }
    return applies() ? requestId : undefined
  }

  async function queryReceipt(requestId: string): Promise<void> {
    const delivery = deliveries.value[requestId]
    if (!delivery || delivery.checking || !canSend.value) return
    const valid = current()
    const connectionId = binding.value.connection?.connection_id
    const applies = () => valid() && connectionId === binding.value.connection?.connection_id
      && deliveries.value[requestId] === delivery
    delivery.checking = true
    try {
      const receipt = await api.sendReceipt(delivery.request_id)
      if (applies()) applyReceipt(delivery, receipt)
    } catch (cause) {
      if (applies()) { delivery.error = cause instanceof Error ? cause.message : '无法查询回执'; observeRevocation(cause) }
    } finally { if (applies()) delivery.checking = false }
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
    binding, contacts, messages, channels, activeContactId, activeConnectionId, busy, contactsLoading,
    messagesLoading, error, channelError, deliveries, blockedTargets, unresolvedLegacy, scopes, canSend, activeContact, orderedMessages, statusLabel,
    refreshAll, loadMessages, selectContact, startBinding, handleOpenKellai,
    disconnect, submitMessage, queryReceipt, attach, detach, reset,
  }
})
