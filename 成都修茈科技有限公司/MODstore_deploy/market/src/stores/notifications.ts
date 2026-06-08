import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '../api'

export const useNotificationStore = defineStore('notifications', () => {
  const unreadCount = ref(0)
  const loading = ref(false)
  const badgeText = computed(() => (unreadCount.value > 99 ? '99+' : String(unreadCount.value)))

  async function refreshUnread(): Promise<number> {
    loading.value = true
    try {
      const res = await api.notificationsList(true, 1)
      unreadCount.value = Number(res?.unread_count ?? 0) || 0
      return unreadCount.value
    } catch {
      unreadCount.value = 0
      return 0
    } finally {
      loading.value = false
    }
  }

  async function markRead(id: number | string): Promise<void> {
    await api.notificationMarkRead(id)
    unreadCount.value = Math.max(0, unreadCount.value - 1)
  }

  async function markAllRead(): Promise<void> {
    await api.notificationsMarkAllRead()
    unreadCount.value = 0
  }

  function clear(): void {
    unreadCount.value = 0
  }

  return { unreadCount, loading, badgeText, refreshUnread, markRead, markAllRead, clear }
})
