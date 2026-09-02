part of 'mobile_api.dart';

abstract class _ApiSessionPersistBase extends _ApiTransportBase {
  Future<void> persistLoginSession(
    Map<String, Object?>? data, {
    required String fallbackUsername,
    required String fallbackAccountKind,
  }) async {
    if (data == null || data.isEmpty) return;
    final user = _asObjectMap(data['user']);
    final accessToken = _readString(data, const ['access_token']);
    final marketToken = _readString(data, const ['market_access_token']);
    if (accessToken.isEmpty && marketToken.isEmpty) return;

    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    final next = current.mergePreferNonBlank(
      MobileSessionData(
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
      ),
    );
    await _saveSession(
      next.copyWith(
        setupComplete: fallbackAccountKind.trim().toLowerCase() == 'admin' ||
            fallbackAccountKind.trim().toLowerCase() == 'admin_portal' ||
            next.setupComplete,
        serverMode: _preferredServerModeAfterLogin(next),
      ),
    );
    await registerDeviceTokenIfNeeded();
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
    Map<String, Object?>? data,
  ) async {
    final cleanRelayId = relayId.trim().ifEmpty(_relayIdFromBindingData(data));
    if (cleanRelayId.isEmpty) return;
    final payload = data ?? const <String, Object?>{};
    final desktop = _asObjectMap(payload['desktop']);
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    await _saveSession(
      current.copyWith(
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
    );
  }

  Future<void> persistPairingSession(
    Map<String, Object?>? data, {
    String hostWithPort = '',
    bool clearRelayDesktop = false,
    bool setupComplete = false,
    bool preserveActiveAuth = false,
  }) async {
    final payload = data ?? const <String, Object?>{};
    final resolvedHost = hostWithPort.trim().ifEmpty(
          _hostPortFromPairingData(payload),
        );
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );

    var next = current;
    final access = _readString(payload, const ['access_token']);
    final user = _asObjectMap(payload['user']);
    if (!preserveActiveAuth && access.isNotEmpty) {
      next = next.copyWith(
        accessToken: access,
        refreshToken: _firstNonBlank([
          _readString(payload, const ['refresh_token']),
          current.refreshToken,
        ]),
        sessionId: _firstNonBlank([
          _readString(payload, const ['session_id', 'session_token']),
          current.sessionId,
        ]),
        username: _firstNonBlank([
          _readString(user, const ['username', 'display_name']),
          current.username,
          'mobile',
        ]),
        accountKind: _firstNonBlank([
          _readString(payload, const ['account_kind']),
          current.accountKind,
          'enterprise',
        ]),
        userId: _readInt(user, const ['id'], current.userId),
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
    await _saveSession(next);
    if (next.hasAuth) {
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
