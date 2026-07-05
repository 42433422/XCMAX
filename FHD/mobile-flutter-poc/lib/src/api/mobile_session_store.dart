import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';

class MobileSessionData {
  const MobileSessionData({
    this.accessToken = '',
    this.refreshToken = '',
    this.sessionId = '',
    this.username = '',
    this.accountKind = '',
    this.userId = 0,
    this.marketAccessToken = '',
    this.marketRefreshToken = '',
    this.localAvatarSource = '',
    this.fhdHost = '',
    this.serverMode = '',
    this.relayDesktopId = '',
    this.relayBaseUrl = '',
    this.localBaseUrl = '',
    this.relaySessionToken = '',
    this.relayAccountId = '',
    this.relayTenantId = '',
    this.relayPairedAt = '',
    this.fcmToken = '',
    this.autoLanProbe = false,
    this.syncCursor = 0,
    this.lastSyncAt = '',
    this.autoSync = true,
    this.setupComplete = false,
    this.legalAcceptedVersion = '',
    this.themeMode = '',
    this.biometricEnabled = false,
    this.savedUsername = '',
    this.savedPassword = '',
    this.rememberPassword = false,
    this.autoLogin = false,
    this.walletBalanceJson = '',
    this.inflightRelayTasks = const {},
    this.cachedChatMessages = const {},
    this.conversationListStates = const {},
    this.cachedModInfos = const [],
  });

  final String accessToken;
  final String refreshToken;
  final String sessionId;
  final String username;
  final String accountKind;
  final int userId;
  final String marketAccessToken;
  final String marketRefreshToken;
  final String localAvatarSource;
  final String fhdHost;
  final String serverMode;
  final String relayDesktopId;
  final String relayBaseUrl;
  final String localBaseUrl;
  final String relaySessionToken;
  final String relayAccountId;
  final String relayTenantId;
  final String relayPairedAt;
  final String fcmToken;
  final bool autoLanProbe;
  final int syncCursor;
  final String lastSyncAt;
  final bool autoSync;
  final bool setupComplete;
  final String legalAcceptedVersion;
  final String themeMode;
  final bool biometricEnabled;
  final String savedUsername;
  final String savedPassword;
  final bool rememberPassword;
  final bool autoLogin;
  final String walletBalanceJson;
  final Map<String, String> inflightRelayTasks;
  final Map<String, List<Map<String, Object?>>> cachedChatMessages;
  final Map<String, Map<String, Object?>> conversationListStates;
  final List<Map<String, Object?>> cachedModInfos;

  static const empty = MobileSessionData();
  static const Object _unset = Object();

  bool get hasAuth =>
      accessToken.trim().isNotEmpty || marketAccessToken.trim().isNotEmpty;

  bool get hasIdentity =>
      username.trim().isNotEmpty ||
      accountKind.trim().isNotEmpty ||
      localAvatarSource.trim().isNotEmpty;

  bool get canAutoLoginForAndroid =>
      autoLogin && savedUsername.trim().isNotEmpty && savedPassword.isNotEmpty;

  String get androidServerModeLabel {
    if (relayDesktopId.trim().isNotEmpty) return '服务器中继 · 电脑执行端';
    final host = fhdHost.trim();
    if (host.isNotEmpty) return 'Agent 控制 · $host';
    final mode = serverMode.trim().toLowerCase();
    if (mode.isEmpty || mode == 'cloud') return '远程同步可用';
    return '本地连通待启';
  }

  factory MobileSessionData.fromJson(Map<String, Object?> json) {
    return MobileSessionData(
      accessToken: _readString(json, 'access_token'),
      refreshToken: _readString(json, 'refresh_token'),
      sessionId: _readString(json, 'session_id'),
      username: _readString(json, 'username'),
      accountKind: _readString(json, 'account_kind'),
      userId: _readInt(json, 'user_id'),
      marketAccessToken: _readString(json, 'market_access_token'),
      marketRefreshToken: _readString(json, 'market_refresh_token'),
      localAvatarSource: _readString(json, 'local_avatar_source'),
      fhdHost: _readString(json, 'fhd_host'),
      serverMode: _readString(json, 'server_mode'),
      relayDesktopId: _readString(json, 'relay_desktop_id'),
      relayBaseUrl: _readString(json, 'relay_base_url'),
      localBaseUrl: _readString(json, 'local_base_url'),
      relaySessionToken: _readString(json, 'relay_session_token'),
      relayAccountId: _readString(json, 'relay_account_id'),
      relayTenantId: _readString(json, 'relay_tenant_id'),
      relayPairedAt: _readString(json, 'relay_paired_at'),
      fcmToken: _readString(json, 'fcm_token'),
      autoLanProbe: _readBool(json, 'auto_lan_probe'),
      syncCursor: _readInt(json, 'sync_cursor'),
      lastSyncAt: _readString(json, 'last_sync_at'),
      autoSync:
          json.containsKey('auto_sync') ? _readBool(json, 'auto_sync') : true,
      setupComplete: _readBool(json, 'setup_complete'),
      legalAcceptedVersion: _readString(json, 'legal_accepted_version'),
      themeMode: _readString(json, 'theme_mode'),
      biometricEnabled: _readBool(json, 'biometric_enabled'),
      savedUsername: _readString(json, 'saved_username'),
      savedPassword: _readString(json, 'saved_password'),
      rememberPassword: _readBool(json, 'remember_password'),
      autoLogin: _readBool(json, 'auto_login'),
      walletBalanceJson: _readString(json, 'wallet_balance_json'),
      inflightRelayTasks: _readStringMap(json, 'inflight_relay_tasks'),
      cachedChatMessages: _readChatCache(json, 'cached_chat_messages'),
      conversationListStates: _readObjectMap(json, 'conversation_list_states'),
      cachedModInfos: _readObjectList(json, 'cached_mod_infos'),
    );
  }

  Map<String, Object?> toJson() => {
        'access_token': accessToken,
        'refresh_token': refreshToken,
        'session_id': sessionId,
        'username': username,
        'account_kind': accountKind,
        'user_id': userId,
        'market_access_token': marketAccessToken,
        'market_refresh_token': marketRefreshToken,
        'local_avatar_source': localAvatarSource,
        'fhd_host': fhdHost,
        'server_mode': serverMode,
        'relay_desktop_id': relayDesktopId,
        'relay_base_url': relayBaseUrl,
        'local_base_url': localBaseUrl,
        'relay_session_token': relaySessionToken,
        'relay_account_id': relayAccountId,
        'relay_tenant_id': relayTenantId,
        'relay_paired_at': relayPairedAt,
        'fcm_token': fcmToken,
        'auto_lan_probe': autoLanProbe,
        'sync_cursor': syncCursor,
        'last_sync_at': lastSyncAt,
        'auto_sync': autoSync,
        'setup_complete': setupComplete,
        'legal_accepted_version': legalAcceptedVersion,
        'theme_mode': themeMode,
        'biometric_enabled': biometricEnabled,
        'saved_username': savedUsername,
        'saved_password': savedPassword,
        'remember_password': rememberPassword,
        'auto_login': autoLogin,
        'wallet_balance_json': walletBalanceJson,
        'inflight_relay_tasks': inflightRelayTasks,
        'cached_chat_messages': cachedChatMessages,
        'conversation_list_states': conversationListStates,
        'cached_mod_infos': cachedModInfos,
      }..removeWhere((key, value) {
          if (value == null) return true;
          if (value is String) return value.trim().isEmpty;
          if (value is int) return value <= 0;
          if (value is Map) return value.isEmpty;
          return false;
        });

  MobileSessionData mergePreferNonBlank(MobileSessionData other) {
    return MobileSessionData(
      accessToken: _firstNonBlank(other.accessToken, accessToken),
      refreshToken: _firstNonBlank(other.refreshToken, refreshToken),
      sessionId: _firstNonBlank(other.sessionId, sessionId),
      username: _firstNonBlank(other.username, username),
      accountKind: _firstNonBlank(other.accountKind, accountKind),
      userId: other.userId > 0 ? other.userId : userId,
      marketAccessToken:
          _firstNonBlank(other.marketAccessToken, marketAccessToken),
      marketRefreshToken:
          _firstNonBlank(other.marketRefreshToken, marketRefreshToken),
      localAvatarSource:
          _firstNonBlank(other.localAvatarSource, localAvatarSource),
      fhdHost: _firstNonBlank(other.fhdHost, fhdHost),
      serverMode: _firstNonBlank(other.serverMode, serverMode),
      relayDesktopId: _firstNonBlank(other.relayDesktopId, relayDesktopId),
      relayBaseUrl: _firstNonBlank(other.relayBaseUrl, relayBaseUrl),
      localBaseUrl: _firstNonBlank(other.localBaseUrl, localBaseUrl),
      relaySessionToken:
          _firstNonBlank(other.relaySessionToken, relaySessionToken),
      relayAccountId: _firstNonBlank(other.relayAccountId, relayAccountId),
      relayTenantId: _firstNonBlank(other.relayTenantId, relayTenantId),
      relayPairedAt: _firstNonBlank(other.relayPairedAt, relayPairedAt),
      fcmToken: _firstNonBlank(other.fcmToken, fcmToken),
      autoLanProbe: other.autoLanProbe || autoLanProbe,
      syncCursor: other.syncCursor > 0 ? other.syncCursor : syncCursor,
      lastSyncAt: _firstNonBlank(other.lastSyncAt, lastSyncAt),
      autoSync: other.autoSync && autoSync,
      setupComplete: other.setupComplete || setupComplete,
      legalAcceptedVersion:
          _firstNonBlank(other.legalAcceptedVersion, legalAcceptedVersion),
      themeMode: _firstNonBlank(other.themeMode, themeMode),
      biometricEnabled: other.biometricEnabled || biometricEnabled,
      savedUsername: _firstNonBlank(other.savedUsername, savedUsername),
      savedPassword: _firstNonBlank(other.savedPassword, savedPassword),
      rememberPassword: other.rememberPassword || rememberPassword,
      autoLogin: other.autoLogin || autoLogin,
      walletBalanceJson:
          _firstNonBlank(other.walletBalanceJson, walletBalanceJson),
      inflightRelayTasks: {
        ...inflightRelayTasks,
        ...other.inflightRelayTasks,
      },
      cachedChatMessages: {
        ...cachedChatMessages,
        ...other.cachedChatMessages,
      },
      conversationListStates: {
        ...conversationListStates,
        ...other.conversationListStates,
      },
      cachedModInfos: other.cachedModInfos.isNotEmpty
          ? other.cachedModInfos
          : cachedModInfos,
    );
  }

  MobileSessionData copyWith({
    Object? accessToken = _unset,
    Object? refreshToken = _unset,
    Object? sessionId = _unset,
    Object? username = _unset,
    Object? accountKind = _unset,
    Object? userId = _unset,
    Object? marketAccessToken = _unset,
    Object? marketRefreshToken = _unset,
    Object? localAvatarSource = _unset,
    Object? fhdHost = _unset,
    Object? serverMode = _unset,
    Object? relayDesktopId = _unset,
    Object? relayBaseUrl = _unset,
    Object? localBaseUrl = _unset,
    Object? relaySessionToken = _unset,
    Object? relayAccountId = _unset,
    Object? relayTenantId = _unset,
    Object? relayPairedAt = _unset,
    Object? fcmToken = _unset,
    Object? autoLanProbe = _unset,
    Object? syncCursor = _unset,
    Object? lastSyncAt = _unset,
    Object? autoSync = _unset,
    Object? setupComplete = _unset,
    Object? legalAcceptedVersion = _unset,
    Object? themeMode = _unset,
    Object? biometricEnabled = _unset,
    Object? savedUsername = _unset,
    Object? savedPassword = _unset,
    Object? rememberPassword = _unset,
    Object? autoLogin = _unset,
    Object? walletBalanceJson = _unset,
    Object? inflightRelayTasks = _unset,
    Object? cachedChatMessages = _unset,
    Object? conversationListStates = _unset,
    Object? cachedModInfos = _unset,
  }) {
    return MobileSessionData(
      accessToken: identical(accessToken, _unset)
          ? this.accessToken
          : accessToken as String,
      refreshToken: identical(refreshToken, _unset)
          ? this.refreshToken
          : refreshToken as String,
      sessionId:
          identical(sessionId, _unset) ? this.sessionId : sessionId as String,
      username:
          identical(username, _unset) ? this.username : username as String,
      accountKind: identical(accountKind, _unset)
          ? this.accountKind
          : accountKind as String,
      userId: identical(userId, _unset) ? this.userId : userId as int,
      marketAccessToken: identical(marketAccessToken, _unset)
          ? this.marketAccessToken
          : marketAccessToken as String,
      marketRefreshToken: identical(marketRefreshToken, _unset)
          ? this.marketRefreshToken
          : marketRefreshToken as String,
      localAvatarSource: identical(localAvatarSource, _unset)
          ? this.localAvatarSource
          : localAvatarSource as String,
      fhdHost: identical(fhdHost, _unset) ? this.fhdHost : fhdHost as String,
      serverMode: identical(serverMode, _unset)
          ? this.serverMode
          : serverMode as String,
      relayDesktopId: identical(relayDesktopId, _unset)
          ? this.relayDesktopId
          : relayDesktopId as String,
      relayBaseUrl: identical(relayBaseUrl, _unset)
          ? this.relayBaseUrl
          : relayBaseUrl as String,
      localBaseUrl: identical(localBaseUrl, _unset)
          ? this.localBaseUrl
          : localBaseUrl as String,
      relaySessionToken: identical(relaySessionToken, _unset)
          ? this.relaySessionToken
          : relaySessionToken as String,
      relayAccountId: identical(relayAccountId, _unset)
          ? this.relayAccountId
          : relayAccountId as String,
      relayTenantId: identical(relayTenantId, _unset)
          ? this.relayTenantId
          : relayTenantId as String,
      relayPairedAt: identical(relayPairedAt, _unset)
          ? this.relayPairedAt
          : relayPairedAt as String,
      fcmToken:
          identical(fcmToken, _unset) ? this.fcmToken : fcmToken as String,
      autoLanProbe: identical(autoLanProbe, _unset)
          ? this.autoLanProbe
          : autoLanProbe as bool,
      syncCursor:
          identical(syncCursor, _unset) ? this.syncCursor : syncCursor as int,
      lastSyncAt: identical(lastSyncAt, _unset)
          ? this.lastSyncAt
          : lastSyncAt as String,
      autoSync: identical(autoSync, _unset) ? this.autoSync : autoSync as bool,
      setupComplete: identical(setupComplete, _unset)
          ? this.setupComplete
          : setupComplete as bool,
      legalAcceptedVersion: identical(legalAcceptedVersion, _unset)
          ? this.legalAcceptedVersion
          : legalAcceptedVersion as String,
      themeMode:
          identical(themeMode, _unset) ? this.themeMode : themeMode as String,
      biometricEnabled: identical(biometricEnabled, _unset)
          ? this.biometricEnabled
          : biometricEnabled as bool,
      savedUsername: identical(savedUsername, _unset)
          ? this.savedUsername
          : savedUsername as String,
      savedPassword: identical(savedPassword, _unset)
          ? this.savedPassword
          : savedPassword as String,
      rememberPassword: identical(rememberPassword, _unset)
          ? this.rememberPassword
          : rememberPassword as bool,
      autoLogin:
          identical(autoLogin, _unset) ? this.autoLogin : autoLogin as bool,
      walletBalanceJson: identical(walletBalanceJson, _unset)
          ? this.walletBalanceJson
          : walletBalanceJson as String,
      inflightRelayTasks: identical(inflightRelayTasks, _unset)
          ? this.inflightRelayTasks
          : inflightRelayTasks as Map<String, String>,
      cachedChatMessages: identical(cachedChatMessages, _unset)
          ? this.cachedChatMessages
          : cachedChatMessages as Map<String, List<Map<String, Object?>>>,
      conversationListStates: identical(conversationListStates, _unset)
          ? this.conversationListStates
          : conversationListStates as Map<String, Map<String, Object?>>,
      cachedModInfos: identical(cachedModInfos, _unset)
          ? this.cachedModInfos
          : cachedModInfos as List<Map<String, Object?>>,
    );
  }
}

abstract class MobileSessionStore {
  Future<MobileSessionData> load();

  Future<void> save(MobileSessionData data);

  Future<void> clear();
}

class FileMobileSessionStore implements MobileSessionStore {
  FileMobileSessionStore({String? filePath}) : _filePath = filePath;

  static const _channel = MethodChannel('xcagi/session_store');
  final String? _filePath;
  File? _cachedFile;

  @override
  Future<MobileSessionData> load() async {
    final file = await _file();
    if (!await file.exists()) return MobileSessionData.empty;
    final text = await file.readAsString();
    if (text.trim().isEmpty) return MobileSessionData.empty;
    final json = jsonDecode(text);
    if (json is! Map) return MobileSessionData.empty;
    return MobileSessionData.fromJson(
      json.map((key, value) => MapEntry(key.toString(), value)),
    );
  }

  @override
  Future<void> save(MobileSessionData data) async {
    final file = await _file();
    await file.parent.create(recursive: true);
    await file.writeAsString(jsonEncode(data.toJson()), flush: true);
  }

  @override
  Future<void> clear() async {
    final file = await _file();
    if (await file.exists()) await file.delete();
  }

  Future<File> _file() async {
    final cached = _cachedFile;
    if (cached != null) return cached;
    final explicit = _filePath?.trim();
    if (explicit != null && explicit.isNotEmpty) {
      return _cachedFile = File(explicit);
    }
    final path = await _channel.invokeMethod<String>('sessionFilePath');
    final resolved = path?.trim().isNotEmpty == true
        ? path!.trim()
        : '${Directory.systemTemp.path}/xcagi_session.json';
    return _cachedFile = File(resolved);
  }
}

class MemoryMobileSessionStore implements MobileSessionStore {
  MemoryMobileSessionStore([this._data = MobileSessionData.empty]);

  MobileSessionData _data;

  @override
  Future<MobileSessionData> load() async => _data;

  @override
  Future<void> save(MobileSessionData data) async {
    _data = data;
  }

  @override
  Future<void> clear() async {
    _data = MobileSessionData.empty;
  }
}

String _readString(Map<String, Object?> json, String key) =>
    json[key]?.toString().trim() ?? '';

int _readInt(Map<String, Object?> json, String key) {
  final value = json[key];
  if (value is int) return value;
  return int.tryParse(value?.toString() ?? '') ?? 0;
}

bool _readBool(Map<String, Object?> json, String key) {
  final value = json[key];
  if (value is bool) return value;
  if (value is num) return value != 0;
  final normalized = value?.toString().trim().toLowerCase() ?? '';
  if (const {'1', 'true', 'yes', 'on'}.contains(normalized)) return true;
  return false;
}

Map<String, String> _readStringMap(Map<String, Object?> json, String key) {
  final raw = json[key];
  if (raw is! Map) return const {};
  return raw.map(
    (key, value) => MapEntry(key.toString(), value?.toString().trim() ?? ''),
  )..removeWhere((_, value) => value.isEmpty);
}

Map<String, List<Map<String, Object?>>> _readChatCache(
  Map<String, Object?> json,
  String key,
) {
  final raw = json[key];
  if (raw is! Map) return const {};
  final result = <String, List<Map<String, Object?>>>{};
  for (final entry in raw.entries) {
    final value = entry.value;
    if (value is! List) continue;
    final rows = value
        .whereType<Map>()
        .map(
          (row) => row.map(
            (key, value) => MapEntry(key.toString(), value as Object?),
          ),
        )
        .toList(growable: false);
    if (rows.isNotEmpty) result[entry.key.toString()] = rows;
  }
  return result;
}

Map<String, Map<String, Object?>> _readObjectMap(
  Map<String, Object?> json,
  String key,
) {
  final raw = json[key];
  if (raw is! Map) return const {};
  final result = <String, Map<String, Object?>>{};
  for (final entry in raw.entries) {
    final value = entry.value;
    if (value is! Map) continue;
    final row = value.map(
      (key, value) => MapEntry(key.toString(), value as Object?),
    );
    if (row.isNotEmpty) result[entry.key.toString()] = row;
  }
  return result;
}

List<Map<String, Object?>> _readObjectList(
  Map<String, Object?> json,
  String key,
) {
  final raw = json[key];
  if (raw is! List) return const [];
  return raw
      .whereType<Map>()
      .map(
        (row) => row.map(
          (key, value) => MapEntry(key.toString(), value as Object?),
        ),
      )
      .where((row) => row.isNotEmpty)
      .toList(growable: false);
}

String _firstNonBlank(String first, String second) {
  final clean = first.trim();
  return clean.isNotEmpty ? clean : second.trim();
}
