import { defineStore } from 'pinia'
import { ref, computed, type Ref } from 'vue'
import {
  wechatApi,
  type WechatContact,
  type WechatContactRuntime,
  type WorkModeFeedMessage,
  type WorkModeOrder,
  type WorkModeTaskAcquisition,
} from '@/api/wechat'
import { resolveErpApiPath } from '@/utils/erpDomainPaths'
import { asRecord } from '@/utils/typeGuards'

interface WorkModeState {
  isActive: boolean;
  contacts: WechatContact[];
  lastMessageSourceSize: number | null;
  pollingInterval: number | null;
  loading: boolean;
  error: string | null;
  isTaskAcquisition: boolean;
  currentOrder: WorkModeOrder | null;
}

export const useWorkModeStore = defineStore('workMode', () => {
  const isActive = ref(false)
  const contacts = ref<WechatContact[]>([])
  const lastMessageSourceSize = ref<number | null>(null)
  const pollingInterval = ref<number | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const isTaskAcquisition = ref(false)
  const currentOrder = ref<WorkModeOrder | null>(null)

  const starredContacts = computed(() => contacts.value.filter(c => c.is_starred))
  const unreadContacts = computed(() =>
    contacts.value.filter(c => ((c as WechatContactRuntime).unreadCount ?? 0) > 0),
  )

  async function startWorkMode() {
    isActive.value = true
    isTaskAcquisition.value = false
    currentOrder.value = null
    
    await loadContacts()
    await getMessageSourceSize()
    
    startPolling()
  }

  async function stopWorkMode() {
    isActive.value = false
    isTaskAcquisition.value = false
    currentOrder.value = null
    
    stopPolling()
  }

  async function loadContacts() {
    loading.value = true
    error.value = null
    try {
      const res = await wechatApi.getStarredContacts()
      contacts.value = res.data ?? []
    } catch (err) {
      error.value = err instanceof Error ? err.message : '加载联系人失败'
      console.error('Failed to load contacts:', err)
    } finally {
      loading.value = false
    }
  }

  async function getMessageSourceSize() {
    try {
      const res = await wechatApi.refreshMessagesCache()
      const data = asRecord(res.data)
      lastMessageSourceSize.value = typeof data.size === 'number' ? data.size : null
    } catch (err) {
      console.error('Failed to get message source size:', err)
    }
  }

  async function refreshMessagesCache() {
    await getMessageSourceSize()
  }

  async function fetchWorkModeFeed() {
    try {
      const response = await fetch(resolveErpApiPath('/api/work_mode/feed'))
      const data = asRecord(await response.json())
      if (Array.isArray(data.messages)) {
        processNewMessages(data.messages as WorkModeFeedMessage[])
      }
      if (data.taskAcquisition) {
        handleTaskAcquisition(data.taskAcquisition as WorkModeTaskAcquisition)
      }
    } catch (error) {
      console.error('Failed to fetch work mode feed:', error)
    }
  }

  function processNewMessages(messages: WorkModeFeedMessage[]) {
    messages.forEach(msg => {
      const contact = contacts.value.find(c => c.id === msg.contactId)
      if (contact) {
        const c = contact as WechatContactRuntime
        c.lastMessage = String(msg.content ?? '')
        c.lastMessageTime = String(msg.timestamp ?? '')
        c.unreadCount = (c.unreadCount || 0) + 1
      }
    })
  }

  function handleTaskAcquisition(taskData: WorkModeTaskAcquisition) {
    const content = String(taskData.content ?? '')
    if (isTaskAcquisitionMessage(content)) {
      isTaskAcquisition.value = true
      currentOrder.value = taskData.order ?? null
    }
  }

  function isTaskAcquisitionMessage(content: string): boolean {
    const keywords = ['订单', 'order', '购买', 'buy', '需要', 'need']
    return keywords.some(keyword => content.toLowerCase().includes(keyword))
  }

  async function sendMessage(contactId: number | string, message: string) {
    try {
      await wechatApi.sendMessage(String(contactId), message)
      
      const contact = contacts.value.find(c => c.id === contactId)
      if (contact) {
        const contactRuntime = contact as WechatContactRuntime
        contactRuntime.lastMessage = message
        contactRuntime.lastMessageTime = new Date().toISOString()
        contactRuntime.unreadCount = 0
      }
    } catch (err: unknown) {
      error.value = err instanceof Error ? err.message : '发送消息失败'
      console.error('Failed to send message:', err)
      throw err
    }
  }

  async function sendOpeningMessage(contactId: number | string) {
    const openingMessages = [
      '您好，有什么可以帮助您的吗？',
      '您好，请问有什么需求？',
      '您好，欢迎咨询！'
    ]
    
    const message = openingMessages[Math.floor(Math.random() * openingMessages.length)]
    await sendMessage(contactId, message)
  }

  function startPolling() {
    stopPolling()
    
    pollingInterval.value = window.setInterval(async () => {
      if (isActive.value) {
        await fetchWorkModeFeed()
      }
    }, 10000)
  }

  function stopPolling() {
    if (pollingInterval.value) {
      clearInterval(pollingInterval.value)
      pollingInterval.value = null
    }
  }

  function resetTaskAcquisition() {
    isTaskAcquisition.value = false
    currentOrder.value = null
  }

  async function downloadOrder(orderId: string | number) {
    try {
      const response = await fetch(resolveErpApiPath(`/api/shipment/download/${orderId}`))
      const blob = await response.blob()
      
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `order_${orderId}.xlsx`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(url)
    } catch (err) {
      error.value = err instanceof Error ? err.message : '下载订单失败'
      console.error('Failed to download order:', err)
      throw err
    }
  }

  return {
    isActive,
    contacts,
    lastMessageSourceSize,
    pollingInterval,
    loading,
    error,
    isTaskAcquisition,
    currentOrder,
    starredContacts,
    unreadContacts,
    startWorkMode,
    stopWorkMode,
    loadContacts,
    getMessageSourceSize,
    refreshMessagesCache,
    fetchWorkModeFeed,
    processNewMessages,
    handleTaskAcquisition,
    sendMessage,
    sendOpeningMessage,
    startPolling,
    stopPolling,
    resetTaskAcquisition,
    downloadOrder
  }
})
