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
    val cachedAt: Long,
)

@Dao
interface ModInfoCacheDao {
    @Query("SELECT * FROM mod_info_cache ORDER BY cachedAt DESC")
    suspend fun getAll(): List<ModInfoCacheEntity>

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
    ],
    version = 5,
    exportSchema = false,
)
abstract class XcagiDatabase : RoomDatabase() {
    abstract fun chatDao(): ChatCacheDao
    abstract fun approvalDao(): ApprovalCacheDao
    abstract fun shipmentDao(): ShipmentCacheDao
    abstract fun imMessageDao(): ImMessageCacheDao
    abstract fun imReadStateDao(): ImReadStateDao
    abstract fun modInfoCacheDao(): ModInfoCacheDao

    companion object {
        val MIGRATION_3_4 = object : Migration(3, 4) {
            override fun migrate(database: SupportSQLiteDatabase) {
                database.execSQL(
                    "ALTER TABLE chat_cache ADD COLUMN session_id TEXT NOT NULL DEFAULT 'default'"
                )
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
    }
}
