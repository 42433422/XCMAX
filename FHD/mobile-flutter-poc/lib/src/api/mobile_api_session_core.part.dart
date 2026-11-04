part of 'mobile_api.dart';

abstract class _ApiSessionCoreBase extends _ApiRootBase {
  _ApiSessionCoreBase({
    MobileApiConfig config = const MobileApiConfig(),
    MobileSessionStore? sessionStore,
    HttpClient? httpClient,
    PlatformCredentialCipher? credentialCipher,
  }) : super(
          config: config,
          sessionStore: sessionStore,
          httpClient: httpClient,
          credentialCipher: credentialCipher,
        );

  Future<MobileSessionData> loadSession({bool forceReload = false}) async {
    Future<void> pending;
    do {
      pending = _sessionWrites;
      await pending;
    } while (!identical(pending, _sessionWrites));
    final generation = _authGeneration;
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
    if (!identical(pending, _sessionWrites)) {
      return loadSession(forceReload: forceReload);
    }
    if (generation != _authGeneration) return _lastSession;
    final session = decodedStored.mergePreferNonBlank(_configSession());
    _rememberSession(session);
    return session;
  }

  Future<void> _updateSession(
    MobileSessionData? Function(MobileSessionData current) update, {
    int? authGeneration,
    bool passwordIsPlaintext = false,
  }) {
    final generation = authGeneration ?? _authGeneration;
    final write = _sessionWrites.then((_) async {
      if (generation != _authGeneration) return;
      final current = await _sessionStore.load().catchError(
            (_) => MobileSessionData.empty,
          );
      if (generation != _authGeneration) return;
      final candidate = update(current);
      if (candidate == null) return;
      var stored = candidate;
      if (stored.savedPassword.isNotEmpty &&
          (passwordIsPlaintext ||
              !stored.savedPassword.startsWith('enc:v1:'))) {
        try {
          stored = stored.copyWith(
            savedPassword: await _encodeSavedCredential(stored.savedPassword),
          );
        } catch (_) {
          stored = stored.copyWith(
            savedUsername: '',
            savedPassword: '',
            rememberPassword: false,
            autoLogin: false,
          );
        }
      }
      if (generation != _authGeneration) return;
      await _sessionStore.save(stored);
      final visible = await _decodeSavedCredential(stored);
      if (generation == _authGeneration) _rememberSession(visible);
    });
    // Keep later logout/login writes ordered even when an earlier write fails.
    _sessionWrites = write.catchError((Object _) {});
    return write;
  }

  int _beginAuthChange() {
    _refreshInFlight = null;
    return ++_authGeneration;
  }

  int get authGeneration => _authGeneration;

  /// Invalidate requests from earlier login attempts before issuing a new one.
  int beginLoginAttempt() => _beginAuthChange();

  /// Persist a session mutation while keeping the in-memory snapshot fresh.
  ///
  /// Callers must use this instead of `sessionStore.save(...)`: writing to the
  /// store directly leaves `loadSession()` serving a stale cached session, so
  /// consecutive mutations (e.g. caching the user message then the assistant
  /// reply) silently overwrite each other.
  Future<void> saveSession(MobileSessionData session, {int? authGeneration}) =>
      _updateSession((stored) {
        final current = stored.mergePreferNonBlank(_configSession());
        if (session.accessToken != current.accessToken ||
            session.refreshToken != current.refreshToken ||
            session.sessionId != current.sessionId ||
            session.userId != current.userId ||
            session.username != current.username ||
            session.marketAccessToken != current.marketAccessToken ||
            session.marketRefreshToken != current.marketRefreshToken)
          return null;
        return session;
      }, authGeneration: authGeneration, passwordIsPlaintext: true);

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
    final encrypted = await _credentialCipher.encrypt(password);
    if (!encrypted.startsWith('enc:v1:') ||
        encrypted.length <= 'enc:v1:'.length ||
        encrypted == password) {
      throw StateError('当前设备无法安全保存密码');
    }
    return encrypted;
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
    final cleanName = displayName.trim();
    await _updateSession(
      (current) => current.copyWith(
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
    int? authGeneration,
  }) async {
    await _updateSession(
      (current) => current.copyWith(
        savedUsername: rememberPassword ? username.trim() : '',
        savedPassword: rememberPassword ? password : '',
        rememberPassword: rememberPassword,
        autoLogin: rememberPassword && autoLogin,
      ),
      authGeneration: authGeneration,
      passwordIsPlaintext: true,
    );
  }

  Future<void> saveLocalSettings({
    String? themeMode,
    bool? biometricEnabled,
    String? serverMode,
  }) async {
    await _updateSession((current) {
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
      return next;
    });
  }

  Future<void> saveLegalAcceptedVersion(String version) async {
    await _updateSession(
        (current) => current.copyWith(legalAcceptedVersion: version.trim()));
  }

  Future<void> saveSetupComplete(bool complete) async {
    await _updateSession(
        (current) => current.copyWith(setupComplete: complete));
  }

  Future<void> saveFcmToken(String token) async {
    await _updateSession((current) => current.copyWith(fcmToken: token.trim()));
  }

  Future<void> saveAutoLanProbe(bool enabled) async {
    await _updateSession((current) => current.copyWith(autoLanProbe: enabled));
  }

  Future<void> saveSyncState({
    int? syncCursor,
    String? lastSyncAt,
    bool? autoSync,
  }) async {
    await _updateSession((current) {
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
      return next;
    });
  }

  Future<void> saveWalletBalanceJson(String json) async {
    await _updateSession(
        (current) => current.copyWith(walletBalanceJson: json.trim()));
  }

  MobileSessionData _withoutActiveAuth(MobileSessionData current) =>
      current.copyWith(
        accessToken: '',
        refreshToken: '',
        sessionId: '',
        username: '',
        accountKind: '',
        userId: 0,
        localAvatarSource: '',
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
      );

  Future<void> clearActiveAuth() async {
    final generation = _beginAuthChange();
    await _updateSession(_withoutActiveAuth, authGeneration: generation);
  }

  Future<void> cacheModInfos(List<Map<String, Object?>> mods) async {
    if (mods.isEmpty) return;
    await _updateSession((current) => current.copyWith(cachedModInfos: mods));
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
