package com.xiuci.xcagi.mobile.core.im

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.xiuci.xcagi.mobile.core.db.ImMessageCacheEntity
import com.xiuci.xcagi.mobile.core.db.ImReadStateEntity
import com.xiuci.xcagi.mobile.core.db.XcagiDatabase
import com.xiuci.xcagi.mobile.core.work.MobileSyncWorker
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class ImRepository @Inject constructor(
    private val db: XcagiDatabase,
    private val imWebSocket: ImWebSocketClient,
    @ApplicationContext private val context: Context,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var wsAttached = false

    fun observeMessages(conversationId: Int): Flow<List<ImMessageCacheEntity>> =
        db.imMessageDao().observeByConversation(conversationId)

    fun observeReadState(conversationId: Int): Flow<ImReadStateEntity?> =
        db.imReadStateDao().observe(conversationId)

    fun attachWebSocketListener() {
        if (wsAttached) return
        wsAttached = true
        scope.launch {
            imWebSocket.events.collectLatest { event ->
                when (val parsed = ImWebSocketClient.parseEvent(event)) {
                    is ImWsEvent.Message -> {
                        upsertMessage(parsed.toEntity(), parsed.updatedAtMs)
                        requestPullHint()
                    }
                    is ImWsEvent.Read -> {
                        upsertReadState(parsed.conversationId, parsed.lastReadMessageId, parsed.updatedAtMs)
                    }
                    null -> Unit
                }
            }
        }
    }

    suspend fun seedMessagesFromNetwork(rows: List<Map<String, Any?>>) {
        rows.forEach { row -> upsertMessage(rowToEntity(row), syncedAt = System.currentTimeMillis()) }
    }

    suspend fun cacheSentMessage(row: Map<String, Any?>) {
        upsertMessage(rowToEntity(row), syncedAt = System.currentTimeMillis())
    }

    suspend fun applySyncMessage(payload: Map<String, Any?>, entityId: String, changeCreatedAt: String?) {
        val messageId = entityId.toLongOrNull()
            ?: (payload["message_id"] as? Number)?.toLong()
            ?: (payload["id"] as? Number)?.toLong()
            ?: return
        val conversationId = (payload["conversation_id"] as? Number)?.toInt() ?: return
        val updatedAtMs = (payload["updated_at_ms"] as? Number)?.toLong()
            ?: parseTimestampMs(payload["created_at"])
            ?: parseTimestampMs(changeCreatedAt)
            ?: System.currentTimeMillis()
        upsertMessage(
            ImMessageCacheEntity(
                conversation_id = conversationId,
                message_id = messageId,
                sender_user_id = (payload["sender_user_id"] as? Number)?.toInt() ?: 0,
                body = payload["body"]?.toString() ?: "",
                created_at = parseTimestampMs(payload["created_at"]) ?: updatedAtMs,
                synced_at = updatedAtMs,
            ),
            updatedAtMs,
        )
    }

    suspend fun applySyncReadState(payload: Map<String, Any?>, entityId: String, changeCreatedAt: String?) {
        val conversationId = (payload["conversation_id"] as? Number)?.toInt()
            ?: entityId.substringBefore(':').toIntOrNull()
            ?: entityId.toIntOrNull()
            ?: return
        val lastRead = (payload["last_read_message_id"] as? Number)?.toLong()
            ?: (payload["last_message_id"] as? Number)?.toLong()
            ?: return
        val updatedAtMs = (payload["updated_at_ms"] as? Number)?.toLong()
            ?: parseTimestampMs(changeCreatedAt)
            ?: System.currentTimeMillis()
        upsertReadState(conversationId, lastRead, updatedAtMs)
    }

    suspend fun clearAll() {
        db.imMessageDao().clearAll()
        db.imReadStateDao().clearAll()
    }

    /** 删除一条 IM 消息（长按菜单「删除」）。 */
    suspend fun removeMessage(conversationId: Int, messageId: Long) {
        db.imMessageDao().deleteOne(conversationId, messageId)
    }

    private suspend fun upsertMessage(row: ImMessageCacheEntity, syncedAt: Long = row.synced_at) {
        val existing = db.imMessageDao().get(row.conversation_id, row.message_id)
        if (existing != null && existing.synced_at > syncedAt) return
        db.imMessageDao().insert(row.copy(synced_at = syncedAt))
    }

    private suspend fun upsertReadState(conversationId: Int, lastReadMessageId: Long, updatedAtMs: Long) {
        val existing = db.imReadStateDao().get(conversationId)
        if (existing != null && existing.synced_at > updatedAtMs) return
        db.imReadStateDao().insert(
            ImReadStateEntity(
                conversation_id = conversationId,
                last_read_message_id = lastReadMessageId,
                synced_at = updatedAtMs,
            ),
        )
    }

    private fun requestPullHint() {
        runCatching {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()
            val req = OneTimeWorkRequestBuilder<MobileSyncWorker>()
                .setConstraints(constraints)
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork(
                "xcagi_im_pull_hint",
                ExistingWorkPolicy.KEEP,
                req,
            )
        }
    }

    private fun rowToEntity(row: Map<String, Any?>): ImMessageCacheEntity {
        val messageId = (row["id"] as? Number)?.toLong() ?: 0L
        val conversationId = (row["conversation_id"] as? Number)?.toInt() ?: 0
        return ImMessageCacheEntity(
            conversation_id = conversationId,
            message_id = messageId,
            sender_user_id = (row["sender_user_id"] as? Number)?.toInt() ?: 0,
            body = row["body"]?.toString() ?: "",
            created_at = parseTimestampMs(row["created_at"]) ?: System.currentTimeMillis(),
            synced_at = System.currentTimeMillis(),
        )
    }

    companion object {
        fun parseTimestampMs(value: Any?): Long? {
            return when (value) {
                is Number -> value.toLong()
                is String -> {
                    val raw = value.trim()
                    if (raw.isEmpty()) null
                    else {
                        raw.toLongOrNull()?.let { numeric ->
                            if (numeric in 1..9_999_999_999L) numeric * 1000L else numeric
                        }
                            ?: runCatching { Instant.parse(raw).toEpochMilli() }.getOrNull()
                            ?: runCatching {
                                LocalDateTime.parse(raw.take(19), DateTimeFormatter.ISO_LOCAL_DATE_TIME)
                                    .atZone(ZoneId.systemDefault())
                                    .toInstant()
                                    .toEpochMilli()
                            }.getOrNull()
                    }
                }
                else -> null
            }
        }
    }
}

sealed class ImWsEvent {
  data class Message(
    val conversationId: Int,
    val messageId: Long,
    val senderUserId: Int,
    val body: String,
    val createdAtMs: Long,
    val updatedAtMs: Long,
  ) : ImWsEvent() {
    fun toEntity() = ImMessageCacheEntity(
      conversation_id = conversationId,
      message_id = messageId,
      sender_user_id = senderUserId,
      body = body,
      created_at = createdAtMs,
      synced_at = updatedAtMs,
    )
  }

  data class Read(
    val conversationId: Int,
    val lastReadMessageId: Long,
    val updatedAtMs: Long,
  ) : ImWsEvent()
}
