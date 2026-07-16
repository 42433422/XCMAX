package com.xiuci.xcagi.mobile.navigation

import com.xiuci.xcagi.mobile.core.db.NotificationCacheEntity
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 通知与公告页不再使用硬编码样例数据，改为读取本机 [NotificationCacheEntity]
 * （落库自服务端一次性推送 `/api/mobile/v1/notifications/pending`）。
 * 这里锁定 channel → [NotificationType] 的映射，以及实体到 UI 模型的转换契约。
 */
class NotificationMappingTest {
    @Test
    fun `maps known server channels to expected notification types`() {
        assertEquals(NotificationType.ALERT, channelToNotificationType("xcagi_approval"))
        assertEquals(NotificationType.SYSTEM, channelToNotificationType("xcagi_sync"))
        assertEquals(NotificationType.ANNOUNCEMENT, channelToNotificationType("xcagi_chat"))
        assertEquals(NotificationType.SYSTEM, channelToNotificationType("xcagi_system"))
    }

    @Test
    fun `falls back to SYSTEM for unknown or blank channel`() {
        assertEquals(NotificationType.SYSTEM, channelToNotificationType("some_unknown_channel"))
        assertEquals(NotificationType.SYSTEM, channelToNotificationType(""))
    }

    @Test
    fun `converts cache entity to notification item preserving read state and timestamp`() {
        val entity = NotificationCacheEntity(
            id = 42L,
            title = "审批待处理",
            body = "有一条采购申请等待您审批",
            route = "xcagi://approval/42",
            channel = "xcagi_approval",
            createdAt = 1_700_000_000_000L,
            read = true,
        )

        val item = entity.toNotificationItem()

        assertEquals("42", item.id)
        assertEquals(NotificationType.ALERT, item.type)
        assertEquals("审批待处理", item.title)
        assertEquals("有一条采购申请等待您审批", item.content)
        assertEquals(1_700_000_000_000L, item.timestamp)
        assertEquals(true, item.read)
    }

    @Test
    fun `blank title falls back to a generic label`() {
        val entity = NotificationCacheEntity(
            id = 1L,
            title = "",
            body = "body",
            route = "",
            channel = "xcagi_system",
            createdAt = 0L,
        )

        assertEquals("通知", entity.toNotificationItem().title)
    }
}
