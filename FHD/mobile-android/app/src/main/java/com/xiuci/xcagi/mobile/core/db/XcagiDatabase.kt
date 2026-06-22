package com.xiuci.xcagi.mobile.core.db

import androidx.room.ColumnInfo
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import kotlinx.coroutines.flow.Flow

@Entity(tableName = "chat_cache")
data class ChatCacheEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val session_id: String = "default",
    val role: String,
    val text: String,
    val ts: Long = System.currentTimeMillis(),
)

@Entity(tableName = "conversation_list_state")
data class ConversationListStateEntity(
    @PrimaryKey val conversation_id: String,
    val last_message_at: Long,
    @ColumnInfo(name = "last_message_preview") val lastMessagePreview: String = "",
)

@Entity(tableName = "approval_cache")
data class ApprovalCacheEntity(
    @PrimaryKey val requestId: Int,
    val title: String,
    val status: String,
    val json: String,
    val ts: Long = System.currentTimeMillis(),
)

@Dao
interface ChatCacheDao {
    @Query("SELECT * FROM chat_cache ORDER BY id ASC LIMIT 200")
    suspend fun all(): List<ChatCacheEntity>

    @Query("SELECT * FROM chat_cache WHERE session_id = :sessionId ORDER BY id ASC LIMIT 200")
    fun observeBySession(sessionId: String): Flow<List<ChatCacheEntity>>

    @Query("SELECT * FROM chat_cache WHERE session_id = :sessionId ORDER BY id ASC LIMIT 200")
    suspend fun getBySession(sessionId: String): List<ChatCacheEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(row: ChatCacheEntity)

    @Query("DELETE FROM chat_cache")
    suspend fun clear()

    @Query("DELETE FROM chat_cache WHERE session_id = :sessionId")
    suspend fun clearSession(sessionId: String)
}

@Dao
interface ConversationListStateDao {
    @Query("SELECT * FROM conversation_list_state")
    fun observeAll(): Flow<List<ConversationListStateEntity>>

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertIfAbsent(row: ConversationListStateEntity): Long

    @Query(
        """
        UPDATE conversation_list_state
        SET last_message_at = :timestamp,
            last_message_preview = :preview
        WHERE conversation_id = :conversationId AND last_message_at < :timestamp
        """
    )
    suspend fun updateIfNewer(conversationId: String, timestamp: Long, preview: String)

    @Query(
        """
        UPDATE conversation_list_state
        SET last_message_preview = :preview,
            last_message_at = :timestamp
        WHERE conversation_id = :conversationId AND last_message_at <= :timestamp
        """
    )
    suspend fun upsertPreview(conversationId: String, timestamp: Long, preview: String)
}

@Entity(tableName = "shipment_cache")
data class ShipmentCacheEntity(
    @PrimaryKey val shipmentId: Int,
    val orderNumber: String,
    val status: String,
    val json: String,
    val ts: Long = System.currentTimeMillis(),
)

@Dao
interface ShipmentCacheDao {
    @Query("SELECT * FROM shipment_cache ORDER BY ts DESC LIMIT 100")
    suspend fun all(): List<ShipmentCacheEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(row: ShipmentCacheEntity)

    @Query("DELETE FROM shipment_cache")
    suspend fun clear()
}

@Dao
interface ApprovalCacheDao {
    @Query("SELECT * FROM approval_cache ORDER BY ts DESC LIMIT 100")
    suspend fun all(): List<ApprovalCacheEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(row: ApprovalCacheEntity)

    @Query("DELETE FROM approval_cache")
    suspend fun clear()
}

@Entity(
    tableName = "im_message_cache",
    primaryKeys = ["conversation_id", "message_id"],
)
data class ImMessageCacheEntity(
    val conversation_id: Int,
    val message_id: Long,
    val sender_user_id: Int,
    val body: String,
    val created_at: Long,
    val synced_at: Long,
)

@Entity(tableName = "im_read_state")
data class ImReadStateEntity(
    @PrimaryKey val conversation_id: Int,
    val last_read_message_id: Long,
    val synced_at: Long = System.currentTimeMillis(),
)

@Dao
interface ImMessageCacheDao {
    @Query("SELECT * FROM im_message_cache WHERE conversation_id = :conversationId ORDER BY message_id ASC")
    fun observeByConversation(conversationId: Int): Flow<List<ImMessageCacheEntity>>

    @Query(
        "SELECT * FROM im_message_cache WHERE conversation_id = :conversationId AND message_id = :messageId LIMIT 1",
    )
    suspend fun get(conversationId: Int, messageId: Long): ImMessageCacheEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(row: ImMessageCacheEntity)

    @Query("DELETE FROM im_message_cache WHERE conversation_id = :conversationId")
    suspend fun clearConversation(conversationId: Int)

    @Query("DELETE FROM im_message_cache")
    suspend fun clearAll()
}

@Dao
interface ImReadStateDao {
    @Query("SELECT * FROM im_read_state WHERE conversation_id = :conversationId LIMIT 1")
    fun observe(conversationId: Int): Flow<ImReadStateEntity?>

    @Query("SELECT * FROM im_read_state WHERE conversation_id = :conversationId LIMIT 1")
    suspend fun get(conversationId: Int): ImReadStateEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(row: ImReadStateEntity)

    @Query("DELETE FROM im_read_state")
    suspend fun clearAll()
}

@Entity(tableName = "mod_info_cache")
data class ModInfoCacheEntity(
    @PrimaryKey val id: String,
    val name: String,
    val version: String,
    val description: String,
    val author: String,
    @ColumnInfo(name = "primary_flag") val primary: Boolean,
    val industry: String,
    val avatarUrl: String?,
    val employeesJson: String,
    val cachedAt: Long,
)

@Dao
interface ModInfoCacheDao {
    @Query("SELECT * FROM mod_info_cache ORDER BY cachedAt DESC")
    suspend fun getAll(): List<ModInfoCacheEntity>

    @Query("SELECT * FROM mod_info_cache ORDER BY cachedAt DESC")
    fun observeAll(): Flow<List<ModInfoCacheEntity>>

    @Query("DELETE FROM mod_info_cache")
    suspend fun clear()

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(items: List<ModInfoCacheEntity>)
}

@Database(
    entities = [
        ChatCacheEntity::class,
        ApprovalCacheEntity::class,
        ShipmentCacheEntity::class,
        ImMessageCacheEntity::class,
        ImReadStateEntity::class,
        ModInfoCacheEntity::class,
        ConversationListStateEntity::class,
    ],
    version = 8,
    exportSchema = false,
)
abstract class XcagiDatabase : RoomDatabase() {
    abstract fun chatDao(): ChatCacheDao
    abstract fun approvalDao(): ApprovalCacheDao
    abstract fun shipmentDao(): ShipmentCacheDao
    abstract fun imMessageDao(): ImMessageCacheDao
    abstract fun imReadStateDao(): ImReadStateDao
    abstract fun modInfoCacheDao(): ModInfoCacheDao
    abstract fun conversationListStateDao(): ConversationListStateDao

    companion object {
        // 幂等守卫：install -r 保留旧 DB 时，列可能已存在，无条件 ADD COLUMN 会抛
        // "duplicate column name" 致开屏闪退。加列前先用 PRAGMA 检查列是否存在。
        private fun hasColumn(
            database: SupportSQLiteDatabase,
            table: String,
            column: String,
        ): Boolean {
            database.query("PRAGMA table_info(`$table`)").use { cursor ->
                val nameIdx = cursor.getColumnIndex("name")
                if (nameIdx < 0) return false
                while (cursor.moveToNext()) {
                    if (column == cursor.getString(nameIdx)) return true
                }
            }
            return false
        }

        val MIGRATION_3_4 = object : Migration(3, 4) {
            override fun migrate(database: SupportSQLiteDatabase) {
                if (!hasColumn(database, "chat_cache", "session_id")) {
                    database.execSQL(
                        "ALTER TABLE chat_cache ADD COLUMN session_id TEXT NOT NULL DEFAULT 'default'"
                    )
                }
            }
        }

        val MIGRATION_4_5 = object : Migration(4, 5) {
            override fun migrate(database: SupportSQLiteDatabase) {
                database.execSQL(
                    """
                    CREATE TABLE IF NOT EXISTS mod_info_cache (
                        id TEXT NOT NULL PRIMARY KEY,
                        name TEXT NOT NULL,
                        version TEXT NOT NULL,
                        description TEXT NOT NULL,
                        author TEXT NOT NULL,
                        primary_flag INTEGER NOT NULL,
                        industry TEXT NOT NULL,
                        avatarUrl TEXT,
                        cachedAt INTEGER NOT NULL
                    )
                    """.trimIndent()
                )
            }
        }

        val MIGRATION_5_6 = object : Migration(5, 6) {
            override fun migrate(database: SupportSQLiteDatabase) {
                if (!hasColumn(database, "mod_info_cache", "employeesJson")) {
                    database.execSQL(
                        "ALTER TABLE mod_info_cache ADD COLUMN employeesJson TEXT NOT NULL DEFAULT '[]'"
                    )
                }
            }
        }

        val MIGRATION_6_7 = object : Migration(6, 7) {
            override fun migrate(database: SupportSQLiteDatabase) {
                database.execSQL(
                    """
                    CREATE TABLE IF NOT EXISTS conversation_list_state (
                        conversation_id TEXT NOT NULL PRIMARY KEY,
                        last_message_at INTEGER NOT NULL
                    )
                    """.trimIndent()
                )
                database.execSQL(
                    """
                    INSERT OR REPLACE INTO conversation_list_state(conversation_id, last_message_at)
                    SELECT
                        CASE WHEN session_id = 'default' THEN 'pinned:assistant' ELSE session_id END,
                        MAX(ts)
                    FROM chat_cache
                    GROUP BY session_id
                    """.trimIndent()
                )
            }
        }

        val MIGRATION_7_8 = object : Migration(7, 8) {
            override fun migrate(database: SupportSQLiteDatabase) {
                if (!hasColumn(database, "conversation_list_state", "last_message_preview")) {
                    database.execSQL(
                        "ALTER TABLE conversation_list_state ADD COLUMN last_message_preview TEXT NOT NULL DEFAULT ''"
                    )
                }
            }
        }
    }
}
