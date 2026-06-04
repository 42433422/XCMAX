package com.xiuci.xcagi.mobile.core.security

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** 应用锁会话：生物识别通过后在一段时间内免重复验证。 */
object AppLockSession {
    private const val PREFS = "xcagi_app_lock"
    private const val KEY_UNLOCK_UNTIL = "unlock_until"
    private const val KEY_BACKGROUND_AT = "background_at"
    private const val TTL_MS = 5 * 60 * 1000L

    private fun prefs(context: Context) = EncryptedSharedPreferences.create(
        context,
        PREFS,
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    fun markUnlocked(context: Context) {
        prefs(context).edit()
            .putLong(KEY_UNLOCK_UNTIL, System.currentTimeMillis() + TTL_MS)
            .remove(KEY_BACKGROUND_AT)
            .apply()
    }

    fun onBackground(context: Context) {
        prefs(context).edit()
            .putLong(KEY_BACKGROUND_AT, System.currentTimeMillis())
            .apply()
    }

    fun shouldReauthenticate(context: Context): Boolean {
        val p = prefs(context)
        val until = p.getLong(KEY_UNLOCK_UNTIL, 0L)
        if (until > System.currentTimeMillis()) return false
        val bg = p.getLong(KEY_BACKGROUND_AT, 0L)
        if (bg == 0L) return until == 0L
        return System.currentTimeMillis() - bg >= TTL_MS
    }

    fun clear(context: Context) {
        prefs(context).edit().clear().apply()
    }
}
