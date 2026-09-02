part of 'mobile_api.dart';

abstract class _ApiSessionCoreBase extends _ApiRootBase {
  Future<MobileSessionData> loadSession({bool forceReload = false}) async {
    if (!forceReload &&
        (_lastSession.hasAuth ||
            _lastSession.hasIdentity ||
            _lastSession.cachedModInfos.isNotEmpty)) {
      return _lastSession.mergePreferNonBlank(_configSession());
    }
    final stored = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    final decodedStored = await _decodeSavedCredential(stored);
    final session = decodedStored.mergePreferNonBlank(_configSession());
    _rememberSession(session);
    return session;
  }

  Future<void> _saveSession(
    MobileSessionData session, {
    MobileSessionData? notifyAs,
  }) async {
    await _sessionStore.save(session);
    _rememberSession(notifyAs ?? await _decodeSavedCredential(session));
  }

  /// Persist a session mutation while keeping the in-memory snapshot fresh.
  ///
  /// Callers must use this instead of `sessionStore.save(...)`: writing to the
  /// store directly leaves `loadSession()` serving a stale cached session, so
  /// consecutive mutations (e.g. caching the user message then the assistant
  /// reply) silently overwrite each other.
  Future<void> saveSession(MobileSessionData session) => _saveSession(session);

  Future<MobileSessionData> _decodeSavedCredential(
    MobileSessionData session,
  ) async {
    final stored = session.savedPassword;
    if (stored.isEmpty) return session;
    if (!stored.startsWith('enc:v1:')) return session;
    final decoded =
        await _credentialCipher.decrypt(stored).catchError((_) => '');
    if (decoded == stored) return session;
    return session.copyWith(savedPassword: decoded);
  }

  Future<String> _encodeSavedCredential(String password) async {
    if (password.isEmpty) return '';
    return _credentialCipher.encrypt(password).catchError((_) => password);
  }

  void _rememberSession(MobileSessionData session) {
    _lastSession = session;
    if (!_sessionChanges.isClosed) {
      _sessionChanges.add(session);
    }
  }

  Future<String> resolvedLocalAvatarSource() async =>
      (await loadSession()).localAvatarSource.trim();

  Future<void> saveLocalProfile({
    required String displayName,
    required String avatarSource,
  }) async {
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    final cleanName = displayName.trim();
    await _saveSession(
      current.copyWith(
        username: cleanName.isEmpty ? current.username : cleanName,
        localAvatarSource: avatarSource.trim(),
      ),
    );
  }

  Future<void> saveLoginPreferences({
    required String username,
    required String password,
    required bool rememberPassword,
    required bool autoLogin,
  }) async {
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    final storedPassword =
        rememberPassword ? await _encodeSavedCredential(password) : '';
    final notifySession = current.copyWith(
      savedUsername: rememberPassword ? username.trim() : '',
      savedPassword: rememberPassword ? password : '',
      rememberPassword: rememberPassword,
      autoLogin: autoLogin,
    );
    await _saveSession(
      current.copyWith(
        savedUsername: rememberPassword ? username.trim() : '',
        savedPassword: storedPassword,
        rememberPassword: rememberPassword,
        autoLogin: autoLogin,
      ),
      notifyAs: notifySession,
    );
  }

  Future<void> saveLocalSettings({
    String? themeMode,
    bool? biometricEnabled,
    String? serverMode,
  }) async {
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    var next = current;
    final rawTheme = themeMode;
    if (rawTheme != null) {
      next = next.copyWith(
        themeMode: rawTheme.trim().isEmpty ? 'system' : rawTheme.trim(),
      );
    }
    if (biometricEnabled != null) {
      next = next.copyWith(biometricEnabled: biometricEnabled);
    }
    if (serverMode != null) {
      final normalized = serverMode.trim().toLowerCase();
      next = next.copyWith(serverMode: normalized == 'lan' ? 'lan' : 'cloud');
    }
    await _saveSession(next);
  }

  Future<void> saveLegalAcceptedVersion(String version) async {
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    await _saveSession(current.copyWith(legalAcceptedVersion: version.trim()));
  }

  Future<void> saveSetupComplete(bool complete) async {
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    await _saveSession(current.copyWith(setupComplete: complete));
  }

  Future<void> saveFcmToken(String token) async {
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    await _saveSession(current.copyWith(fcmToken: token.trim()));
  }

  Future<void> saveAutoLanProbe(bool enabled) async {
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    await _saveSession(current.copyWith(autoLanProbe: enabled));
  }

  Future<void> saveSyncState({
    int? syncCursor,
    String? lastSyncAt,
    bool? autoSync,
  }) async {
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    var next = current;
    if (syncCursor != null) {
      next = next.copyWith(syncCursor: syncCursor < 0 ? 0 : syncCursor);
    }
    if (lastSyncAt != null) {
      next = next.copyWith(lastSyncAt: lastSyncAt.trim());
    }
    if (autoSync != null) {
      next = next.copyWith(autoSync: autoSync);
    }
    await _saveSession(next);
  }

  Future<void> saveWalletBalanceJson(String json) async {
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    await _saveSession(current.copyWith(walletBalanceJson: json.trim()));
  }

  Future<void> clearActiveAuth() async {
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    await _saveSession(
      current.copyWith(
        accessToken: '',
        refreshToken: '',
        sessionId: '',
        username: '',
        accountKind: '',
        userId: 0,
        marketAccessToken: '',
        marketRefreshToken: '',
        relayDesktopId: '',
        relayBaseUrl: '',
        localBaseUrl: '',
        relaySessionToken: '',
        relayAccountId: '',
        relayTenantId: '',
        relayPairedAt: '',
        inflightRelayTasks: const <String, String>{},
        walletBalanceJson: '',
        setupComplete: false,
        autoLogin: false,
        cachedChatMessages: const <String, List<Map<String, Object?>>>{},
        conversationListStates: const <String, Map<String, Object?>>{},
        cachedModInfos: const <Map<String, Object?>>[],
      ),
    );
  }

  Future<void> cacheModInfos(List<Map<String, Object?>> mods) async {
    if (mods.isEmpty) return;
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    await _saveSession(current.copyWith(cachedModInfos: mods));
  }


  MobileSessionData _configSession() {
    return MobileSessionData(
      accessToken: _config.accessToken,
      sessionId: _config.sessionId,
      marketAccessToken: _config.marketAccessToken,
      marketRefreshToken: _config.marketRefreshToken,
      localAvatarSource: _config.localAvatarSource,
      relayDesktopId: _config.relayId,
    );
  }
}
