part of 'mobile_api.dart';

abstract class _ApiSessionPersistBase extends _ApiTransportBase {
  _ApiSessionPersistBase({
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

  Future<int?> persistLoginSession(
    Map<String, Object?>? data, {
    required String fallbackUsername,
    required String fallbackAccountKind,
    int? authGeneration,
  }) async {
    if (data == null || data.isEmpty) return null;
    final user = _asObjectMap(data['user']);
    final accessToken = _readString(data, const ['access_token']);
    final marketToken = _readString(data, const ['market_access_token']);
    if (accessToken.isEmpty && marketToken.isEmpty) return null;
    if (authGeneration != null && authGeneration != _authGeneration)
      return null;
    // Requests issued while login was pending still belong to the previous account.
    final generation = _beginAuthChange();
    await _updateSession((current) {
      // Replace the full credential snapshot, including absent optional tokens.
      var next = current.copyWith(
        accessToken: accessToken,
        refreshToken: _readString(data, const ['refresh_token']),
        sessionId: _readString(data, const ['session_id']),
        username: _readString(user, const [
          'username',
          'name',
        ]).ifEmpty(fallbackUsername),
        accountKind: _readString(data, const [
          'account_kind',
        ]).ifEmpty(fallbackAccountKind),
        userId: _readInt(user, const ['id'], 0),
        marketAccessToken: marketToken,
        marketRefreshToken: _readString(data, const ['market_refresh_token']),
      );
      if (current.userId != next.userId ||
          current.username != next.username ||
          (current.accountKind.isNotEmpty &&
              current.accountKind != next.accountKind)) {
        final cleared = _withoutActiveAuth(current);
        next = cleared.copyWith(
          accessToken: next.accessToken,
          refreshToken: next.refreshToken,
          sessionId: next.sessionId,
          username: next.username,
          accountKind: next.accountKind,
          userId: next.userId,
          marketAccessToken: next.marketAccessToken,
          marketRefreshToken: next.marketRefreshToken,
          savedUsername: '',
          savedPassword: '',
          rememberPassword: false,
        );
      }
      return next.copyWith(
        setupComplete: fallbackAccountKind.trim().toLowerCase() == 'admin' ||
            fallbackAccountKind.trim().toLowerCase() == 'admin_portal' ||
            next.setupComplete,
        serverMode: _preferredServerModeAfterLogin(next),
      );
    }, authGeneration: generation);
    if (generation == _authGeneration) await registerDeviceTokenIfNeeded();
    return generation == _authGeneration ? generation : null;
  }

  Future<void> registerDeviceTokenIfNeeded({
    String pushProvider = 'fcm',
    String? pushToken,
  }) async {
    final session = await loadSession();
    final token = (pushToken ?? session.fcmToken).trim();
    if (token.isEmpty) return;
    try {
      await registerDevice({
        'fcm_token': token,
        'push_provider': pushProvider,
        'push_token': token,
        'product_sku': MobileBuildConfig.productSku,
        'device_label': 'XCAGI Flutter Mobile',
      });
    } catch (_) {
      // Push-token registration failure must not block the Flutter app.
    }
  }

  Future<void> persistRelayBindingMeta(
    String relayId,
    Map<String, Object?>? data, {
    int? authGeneration,
  }) async {
    final generation = authGeneration ?? _authGeneration;
    final cleanRelayId = relayId.trim().ifEmpty(_relayIdFromBindingData(data));
    if (cleanRelayId.isEmpty) return;
    final payload = data ?? const <String, Object?>{};
    final desktop = _asObjectMap(payload['desktop']);
    await _updateSession(
      (current) => current.copyWith(
        relayDesktopId: cleanRelayId,
        relayBaseUrl: _firstNonBlank([
          _readString(payload, const ['relay_base_url']),
          _readString(desktop, const ['relay_base_url']),
          current.relayBaseUrl,
        ]),
        localBaseUrl: _firstNonBlank([
          _readString(payload, const ['local_base_url']),
          _readString(desktop, const ['local_base_url']),
          current.localBaseUrl,
        ]),
        relaySessionToken: _firstNonBlank([
          _readString(payload, const ['session_token']),
          current.relaySessionToken,
        ]),
        relayAccountId: _firstNonBlank([
          _readString(payload, const ['account_id']),
          current.relayAccountId,
        ]),
        relayTenantId: _firstNonBlank([
          _readString(payload, const ['tenant_id']),
          current.relayTenantId,
        ]),
        relayPairedAt: _firstNonBlank([
          _readString(payload, const ['paired_at']),
          _readString(desktop, const ['paired_at']),
          current.relayPairedAt,
        ]),
      ),
      authGeneration: generation,
    );
  }

  Future<void> persistPairingSession(
    Map<String, Object?>? data, {
    String hostWithPort = '',
    bool clearRelayDesktop = false,
    bool setupComplete = false,
    bool preserveActiveAuth = false,
    int? authGeneration,
  }) async {
    final payload = data ?? const <String, Object?>{};
    final access = _readString(payload, const ['access_token']);
    final generation = authGeneration ??
        (!preserveActiveAuth && access.isNotEmpty
            ? _beginAuthChange()
            : _authGeneration);
    final resolvedHost = hostWithPort.trim().ifEmpty(
          _hostPortFromPairingData(payload),
        );
    var shouldRegisterDevice = false;
    await _updateSession((stored) {
      final current = !preserveActiveAuth && access.isNotEmpty
          ? _withoutActiveAuth(stored).copyWith(
              savedUsername: '', savedPassword: '', rememberPassword: false)
          : stored;
      var next = current;
      final user = _asObjectMap(payload['user']);
      if (!preserveActiveAuth && access.isNotEmpty) {
        next = next.copyWith(
          accessToken: access,
          refreshToken: _readString(payload, const ['refresh_token']),
          sessionId:
              _readString(payload, const ['session_id', 'session_token']),
          marketAccessToken:
              _readString(payload, const ['market_access_token']),
          marketRefreshToken:
              _readString(payload, const ['market_refresh_token']),
          username: _firstNonBlank([
            _readString(user, const ['username', 'display_name']),
            'mobile',
          ]),
          accountKind: _firstNonBlank([
            _readString(payload, const ['account_kind']),
            'enterprise',
          ]),
          userId: _readInt(user, const ['id'], 0),
        );
      }
      if (access.isNotEmpty || preserveActiveAuth) {
        next = next.copyWith(
          relayBaseUrl: _firstNonBlank([
            _readString(payload, const ['relay_base_url']),
            current.relayBaseUrl,
          ]),
          localBaseUrl: _firstNonBlank([
            _readString(payload, const ['local_base_url']),
            current.localBaseUrl,
          ]),
          relaySessionToken: _firstNonBlank([
            _readString(payload, const ['session_token']),
            _readString(payload, const ['session_id']),
            current.relaySessionToken,
          ]),
          relayAccountId: _firstNonBlank([
            _readString(payload, const ['account_id']),
            current.relayAccountId,
          ]),
          relayTenantId: _firstNonBlank([
            _readString(payload, const ['tenant_id']),
            current.relayTenantId,
          ]),
          relayPairedAt: _firstNonBlank([
            _readString(payload, const ['paired_at']),
            current.relayPairedAt,
          ]),
        );
      }

      if (resolvedHost.isNotEmpty) {
        next = next.copyWith(
          fhdHost: resolvedHost,
          serverMode: 'lan',
          inflightRelayTasks: const <String, String>{},
        );
      }
      if (clearRelayDesktop) {
        next = next.copyWith(
          relayDesktopId: '',
          inflightRelayTasks: const <String, String>{},
        );
      }
      if (setupComplete) {
        next = next.copyWith(setupComplete: true);
      }
      shouldRegisterDevice = next.hasAuth;
      return next;
    }, authGeneration: generation);
    if (generation == _authGeneration && shouldRegisterDevice) {
      await registerDeviceTokenIfNeeded();
    }
  }

  Future<MobileEnvelope<Map<String, Object?>>> registerDevice(
    Map<String, Object?> body,
  ) async {
    final json = await postJson(XcagiMobileEndpoints.devicesRegister, body);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }
}
