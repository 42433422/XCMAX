import { describe, expect, it, vi } from 'vitest'
import { useNotificationStore } from './notifications'
import { api } from '../api'

vi.mock('../api', () => ({
  api: {
    notificationsList: vi.fn(),
    notificationMarkRead: vi.fn(),
    notificationsMarkAllRead: vi.fn(),
  },
}))

describe('notification store', () => {
  it('refreshes unread count and badge text', async () => {
    vi.mocked(api.notificationsList).mockResolvedValue({ unread_count: 120 })
    const store = useNotificationStore()

    await store.refreshUnread()

    expect(store.unreadCount).toBe(120)
    expect(store.badgeText).toBe('99+')
  })

  it('updates unread count after marking notifications read', async () => {
    const store = useNotificationStore()
    store.unreadCount = 2

    await store.markRead(1)
    expect(store.unreadCount).toBe(1)

    await store.markAllRead()
    expect(store.unreadCount).toBe(0)
  })
})
