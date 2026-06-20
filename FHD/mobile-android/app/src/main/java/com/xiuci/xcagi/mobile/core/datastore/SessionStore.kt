package com.xiuci.xcagi.mobile.core.datastore

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.xiuci.xcagi.mobile.BuildConfig
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.dataStore: DataStore<Preferences> by
        preferencesDataStore(
                "xcagi_session_${BuildConfig.PRODUCT_SKU}",
        )

@Singleton
class SessionStore
@Inject
constructor(
        @ApplicationContext private val context: Context,
) {
    private val fhdHost = stringPreferencesKey("fhd_host")
    private val fhdAccess = stringPreferencesKey("fhd_access_token")
    private val fhdRefresh = stringPreferencesKey("fhd_refresh_token")
    private val fhdSession = stringPreferencesKey("fhd_session_id")
    private val fhdUsername = stringPreferencesKey("fhd_username")
    private val marketToken = stringPreferencesKey("market_token")
    private val marketRefresh = stringPreferencesKey("market_refresh_token")
    private val serverMode = stringPreferencesKey("server_mode")
    private val accountKind = stringPreferencesKey("account_kind")
    private val userIdKey = intPreferencesKey("user_id")
    private val fcmTokenKey = stringPreferencesKey("fcm_token")
    private val setupCompleteKey = booleanPreferencesKey("setup_complete")
    private val autoLanProbeKey = booleanPreferencesKey("auto_lan_probe")
    private val syncCursorKey = intPreferencesKey("sync_cursor")
    private val lastSyncAtKey = stringPreferencesKey("last_sync_at")
    private val autoSyncKey = booleanPreferencesKey("auto_sync")
    private val legalAcceptedVersionKey = stringPreferencesKey("legal_accepted_version")
    private val themeModeKey = stringPreferencesKey("theme_mode")
    private val biometricEnabledKey = booleanPreferencesKey("biometric_enabled")
    private val savedUsernameKey = stringPreferencesKey("saved_username")
    private val savedPasswordKey = stringPreferencesKey("saved_password")
    private val rememberPassKey = booleanPreferencesKey("remember_password")
    private val autoLoginKey = booleanPreferencesKey("auto_login")
    private val avatarUriKey = stringPreferencesKey("avatar_uri")
    private val relayDesktopIdKey = stringPreferencesKey("relay_desktop_id")
    private val relayBaseUrlKey = stringPreferencesKey("relay_base_url")
    private val localBaseUrlKey = stringPreferencesKey("local_base_url")
    private val relaySessionTokenKey = stringPreferencesKey("relay_session_token")
    private val relayAccountIdKey = stringPreferencesKey("relay_account_id")
    private val relayTenantIdKey = stringPreferencesKey("relay_tenant_id")
    private val relayPairedAtKey = stringPreferencesKey("relay_paired_at")
    private val walletBalanceJsonKey = stringPreferencesKey("wallet_balance_json")

    val fhdHostFlow: Flow<String> = context.dataStore.data.map { it[fhdHost] ?: "" }
    val userIdFlow: Flow<Int> = context.dataStore.data.map { it[userIdKey] ?: 0 }
    val fhdAccessFlow: Flow<String> = context.dataStore.data.map { it[fhdAccess] ?: "" }
    val serverModeFlow: Flow<String> = context.dataStore.data.map { it[serverMode] ?: "cloud" }
    val accountKindFlow: Flow<String> = context.dataStore.data.map { it[accountKind] ?: "" }
    val marketTokenFlow: Flow<String> = context.dataStore.data.map { it[marketToken] ?: "" }
    val marketRefreshFlow: Flow<String> = context.dataStore.data.map { it[marketRefresh] ?: "" }
    val fhdUsernameFlow: Flow<String> = context.dataStore.data.map { it[fhdUsername] ?: "" }

    val isLoggedInFlow: Flow<Boolean> =
            context.dataStore.data.map {
                !(it[fhdAccess].isNullOrBlank()) || !(it[marketToken].isNullOrBlank())
            }

    /** 已完成引导：显式标记或已保存电脑主机。 */
    val isSetupCompleteFlow: Flow<Boolean> =
            context.dataStore.data.map { prefs ->
                prefs[setupCompleteKey] == true || !(prefs[fhdHost].isNullOrBlank())
            }

    val autoLanProbeFlow: Flow<Boolean> = context.dataStore.data.map { it[autoLanProbeKey] == true }

    val syncCursorFlow: Flow<Int> = context.dataStore.data.map { it[syncCursorKey] ?: 0 }

    val lastSyncAtFlow: Flow<String> = context.dataStore.data.map { it[lastSyncAtKey] ?: "" }

    val autoSyncFlow: Flow<Boolean> = context.dataStore.data.map { it[autoSyncKey] != false }

    val legalAcceptedVersionFlow: Flow<String> =
            context.dataStore.data.map { it[legalAcceptedVersionKey] ?: "" }

    val themeModeFlow: Flow<String> = context.dataStore.data.map { it[themeModeKey] ?: "system" }

    val biometricEnabledFlow: Flow<Boolean> =
            context.dataStore.data.map { it[biometricEnabledKey] == true }

    val savedUsernameFlow: Flow<String> = context.dataStore.data.map { it[savedUsernameKey] ?: "" }
    // 密码经 AndroidKeyStore AES/GCM 加密后落盘；读取时解密（历史明文自动兼容）。
    val savedPasswordFlow: Flow<String> =
            context.dataStore.data.map { CredentialCipher.decrypt(it[savedPasswordKey] ?: "") }
    val rememberPassFlow: Flow<Boolean> = context.dataStore.data.map { it[rememberPassKey] == true }
    val autoLoginFlow: Flow<Boolean> = context.dataStore.data.map { it[autoLoginKey] == true }
    val avatarUriFlow: Flow<String> = context.dataStore.data.map { it[avatarUriKey] ?: "" }
    val relayDesktopIdFlow: Flow<String> = context.dataStore.data.map { it[relayDesktopIdKey] ?: "" }
    val relayBaseUrlFlow: Flow<String> = context.dataStore.data.map { it[relayBaseUrlKey] ?: "" }
    val localBaseUrlFlow: Flow<String> = context.dataStore.data.map { it[localBaseUrlKey] ?: "" }
    val relaySessionTokenFlow: Flow<String> =
            context.dataStore.data.map { it[relaySessionTokenKey] ?: "" }
    val relayAccountIdFlow: Flow<String> =
            context.dataStore.data.map { it[relayAccountIdKey] ?: "" }
    val relayTenantIdFlow: Flow<String> = context.dataStore.data.map { it[relayTenantIdKey] ?: "" }
    val relayPairedAtFlow: Flow<String> = context.dataStore.data.map { it[relayPairedAtKey] ?: "" }

    suspend fun isSetupComplete(): Boolean = isSetupCompleteFlow.first()

    suspend fun setSetupComplete(complete: Boolean = true) {
        context.dataStore.edit { it[setupCompleteKey] = complete }
    }

    suspend fun setAutoLanProbe(enabled: Boolean) {
        context.dataStore.edit { it[autoLanProbeKey] = enabled }
    }

    suspend fun setSyncCursor(cursor: Int) {
        context.dataStore.edit { it[syncCursorKey] = cursor }
    }

    suspend fun syncCursor(): Int = syncCursorFlow.first()

    suspend fun setLastSyncAt(iso: String) {
        context.dataStore.edit { it[lastSyncAtKey] = iso }
    }

    suspend fun setAutoSync(enabled: Boolean) {
        context.dataStore.edit { it[autoSyncKey] = enabled }
    }

    suspend fun setFhdHost(host: String) {
        context.dataStore.edit { prefs ->
            val value = host.trim()
            if (value.isBlank()) prefs.remove(fhdHost)
            else prefs[fhdHost] = value
        }
    }

    suspend fun fhdHost(): String = fhdHostFlow.first()

    suspend fun saveFhdAuth(
            access: String,
            refresh: String,
            sessionId: String,
            username: String,
            userId: Int = 0,
    ) {
        context.dataStore.edit {
            it[fhdAccess] = access
            it[fhdRefresh] = refresh
            it[fhdSession] = sessionId
            it[fhdUsername] = username
            if (userId > 0) it[userIdKey] = userId
        }
    }

    val fcmTokenFlow: Flow<String> = context.dataStore.data.map { it[fcmTokenKey] ?: "" }

    suspend fun setFcmToken(token: String) {
        context.dataStore.edit { it[fcmTokenKey] = token }
    }

    suspend fun fcmToken(): String = fcmTokenFlow.first()

    suspend fun setMarketToken(token: String) {
        context.dataStore.edit { it[marketToken] = token.trim() }
    }

    suspend fun setMarketTokens(access: String, refresh: String = "") {
        context.dataStore.edit {
            it[marketToken] = access.trim()
            if (refresh.isNotBlank()) it[marketRefresh] = refresh.trim()
        }
    }

    suspend fun marketAccessToken(): String = marketTokenFlow.first()

    suspend fun marketRefreshToken(): String = marketRefreshFlow.first()

    suspend fun setServerMode(mode: String) {
        context.dataStore.edit { it[serverMode] = mode }
    }

    suspend fun setAccountKind(kind: String) {
        val normalized = kind.trim().lowercase()
        context.dataStore.edit { prefs ->
            if (normalized.isBlank()) {
                prefs.remove(accountKind)
            } else {
                prefs[accountKind] = normalized
            }
        }
    }

    suspend fun accountKind(): String = accountKindFlow.first()

    suspend fun setUserId(id: Int) {
        context.dataStore.edit { it[userIdKey] = id }
    }

    suspend fun setDisplayName(name: String) {
        context.dataStore.edit { it[fhdUsername] = name.trim() }
    }

    suspend fun setAvatarUri(uri: String) {
        context.dataStore.edit { prefs ->
            val value = uri.trim()
            if (value.isBlank()) prefs.remove(avatarUriKey)
            else prefs[avatarUriKey] = value
        }
    }

    suspend fun setRelayDesktopId(relayId: String) {
        context.dataStore.edit { prefs ->
            val value = relayId.trim()
            if (value.isBlank()) prefs.remove(relayDesktopIdKey)
            else prefs[relayDesktopIdKey] = value
        }
    }

    suspend fun setRelayBaseUrl(url: String) {
        context.dataStore.edit { prefs ->
            val value = url.trim()
            if (value.isBlank()) prefs.remove(relayBaseUrlKey)
            else prefs[relayBaseUrlKey] = value
        }
    }

    suspend fun setLocalBaseUrl(url: String) {
        context.dataStore.edit { prefs ->
            val value = url.trim()
            if (value.isBlank()) prefs.remove(localBaseUrlKey)
            else prefs[localBaseUrlKey] = value
        }
    }

    suspend fun setRelaySessionToken(token: String) {
        context.dataStore.edit { prefs ->
            val value = token.trim()
            if (value.isBlank()) prefs.remove(relaySessionTokenKey)
            else prefs[relaySessionTokenKey] = value
        }
    }

    suspend fun setRelayAccountId(accountId: String) {
        context.dataStore.edit { prefs ->
            val value = accountId.trim()
            if (value.isBlank()) prefs.remove(relayAccountIdKey)
            else prefs[relayAccountIdKey] = value
        }
    }

    suspend fun setRelayTenantId(tenantId: String) {
        context.dataStore.edit { prefs ->
            val value = tenantId.trim()
            if (value.isBlank()) prefs.remove(relayTenantIdKey)
            else prefs[relayTenantIdKey] = value
        }
    }

    suspend fun setRelayPairedAt(timestamp: String) {
        context.dataStore.edit { prefs ->
            val value = timestamp.trim()
            if (value.isBlank()) prefs.remove(relayPairedAtKey)
            else prefs[relayPairedAtKey] = value
        }
    }

    suspend fun relayDesktopId(): String = relayDesktopIdFlow.first()
    suspend fun relayBaseUrl(): String = relayBaseUrlFlow.first()
    suspend fun localBaseUrl(): String = localBaseUrlFlow.first()
    suspend fun relaySessionToken(): String = relaySessionTokenFlow.first()
    suspend fun relayAccountId(): String = relayAccountIdFlow.first()
    suspend fun relayTenantId(): String = relayTenantIdFlow.first()
    suspend fun relayPairedAt(): String = relayPairedAtFlow.first()

    suspend fun legalAcceptedVersion(): String = legalAcceptedVersionFlow.first()

    suspend fun setLegalAcceptedVersion(version: String) {
        context.dataStore.edit { it[legalAcceptedVersionKey] = version.trim() }
    }

    suspend fun setThemeMode(mode: String) {
        context.dataStore.edit { it[themeModeKey] = mode }
    }

    suspend fun setBiometricEnabled(enabled: Boolean) {
        context.dataStore.edit { it[biometricEnabledKey] = enabled }
    }

    /** 保存登录凭证（记住密码）；密码以 AndroidKeyStore 加密后落盘，不再明文存储。 */
    suspend fun saveCredentials(username: String, password: String) {
        context.dataStore.edit {
            it[savedUsernameKey] = username.trim()
            it[savedPasswordKey] = CredentialCipher.encrypt(password)
            it[rememberPassKey] = true
        }
    }

    /** 清除保存的凭证（取消记住密码时调用） */
    suspend fun clearSavedCredentials() {
        context.dataStore.edit {
            it.remove(savedUsernameKey)
            it.remove(savedPasswordKey)
            it[rememberPassKey] = false
        }
    }

    /** 设置免登录状态 */
    suspend fun setAutoLogin(enabled: Boolean) {
        context.dataStore.edit { it[autoLoginKey] = enabled }
    }

    /** 读取已保存的用户名 */
    suspend fun savedUsername(): String = savedUsernameFlow.first()

    /** 读取已保存的密码 */
    suspend fun savedPassword(): String = savedPasswordFlow.first()

    /** 是否记住密码 */
    suspend fun isRememberPass(): Boolean = rememberPassFlow.first()

    /** 是否开启免登录 */
    suspend fun isAutoLogin(): Boolean = autoLoginFlow.first()

    /** 检查是否可以自动登录：有保存的账号密码 + 免登录开启 */
    suspend fun canAutoLogin(): Boolean {
        val u = savedUsernameFlow.first()
        val p = savedPasswordFlow.first()
        return autoLoginFlow.first() && u.isNotBlank() && p.isNotBlank()
    }

    /** 钱包余额缓存 JSON（冷启动秒出用）。空字符串表示无缓存。 */
    val walletBalanceJsonFlow: Flow<String> =
            context.dataStore.data.map { it[walletBalanceJsonKey] ?: "" }

    suspend fun setWalletBalanceJson(json: String) {
        context.dataStore.edit { prefs ->
            val value = json.trim()
            if (value.isBlank()) prefs.remove(walletBalanceJsonKey)
            else prefs[walletBalanceJsonKey] = value
        }
    }

    suspend fun walletBalanceJson(): String = walletBalanceJsonFlow.first()

    suspend fun clear() {
        context.dataStore.edit { it.clear() }
    }

    suspend fun accessToken(): String = fhdAccessFlow.first()

    suspend fun fhdSessionId(): String = context.dataStore.data.map { it[fhdSession] ?: "" }.first()
}
