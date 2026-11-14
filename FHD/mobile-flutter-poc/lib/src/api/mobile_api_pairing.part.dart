part of 'mobile_api.dart';

abstract class _ApiPairingBase extends _ApiCsAuthBase {
  _ApiPairingBase({
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

  Future<MobileEnvelope<Map<String, Object?>>> exchangePairing({
    String nonce = '',
    String code = '',
    String baseUrl = '',
  }) async {
    final json = await postJson(
      XcagiMobileEndpoints.pairingExchange,
      {'nonce': nonce.trim(), 'code': code.trim()},
      baseUrl: baseUrl.trim().isEmpty ? null : baseUrl.trim(),
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> confirmAuthQr({
    required String qrId,
    required String username,
    required String password,
    required String accountKind,
  }) async {
    final json = await postJson(XcagiMobileEndpoints.authQrConfirm, {
      'qr_id': qrId.trim(),
      'username': username.trim(),
      'password': password,
      'account_kind': accountKind.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> syncStatus() async {
    final json = await getJson(XcagiMobileEndpoints.syncStatus);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> syncPull({
    int sinceCursor = 0,
  }) async {
    final json = await postJson(XcagiMobileEndpoints.syncPull, {
      'since_cursor': sinceCursor,
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> syncPush(
    List<Map<String, Object?>> items,
  ) async {
    final json = await postJson(XcagiMobileEndpoints.syncPush, {
      'items': items,
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> syncConflicts() async {
    final json = await getJson(XcagiMobileEndpoints.syncConflicts);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> relayBindAccount(
    String relayId, {
    String pairingCode = '',
  }) async {
    final generation = _authGeneration;
    final json = await postJson(
        XcagiMobileEndpoints.relayMobileBindAccount,
        {
          'relay_id': relayId.trim(),
          if (pairingCode.trim().isNotEmpty) 'pairing_code': pairingCode.trim(),
        },
        baseUrl: _config.baseUrl);
    final envelope = MobileEnvelope.fromJson(json, _asObjectMap);
    if (envelope.success) {
      final desktop = envelope.data?['desktop'];
      if (desktop is Map) {
        final publicKey = '${desktop['public_key'] ?? ''}'.trim();
        if (publicKey.isNotEmpty) {
          await RelayE2ee.pinDesktopKey(relayId.trim(), publicKey);
        }
      }
      await persistRelayBindingMeta(relayId.trim(), envelope.data,
          authGeneration: generation);
    }
    return envelope;
  }

  Future<MobileEnvelope<Map<String, Object?>>> relayDesktops() async {
    final json = await getJson(XcagiMobileEndpoints.relayMobileDesktops);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> relayCreateTask({
    required String relayId,
    required String kind,
    required Map<String, Object?> payload,
  }) async {
    final desktopPublicKey = await _relayDesktopPublicKey(relayId);
    final sealed = await RelayE2ee.sealPayload(payload, desktopPublicKey);
    await RelayE2ee.rememberTask(sealed);
    final json = await postJson(XcagiMobileEndpoints.relayTasks, {
      'relay_id': relayId.trim(),
      'kind': kind.trim(),
      'payload': sealed.envelope,
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<String> _relayDesktopPublicKey(String relayId) async {
    final clean = relayId.trim();
    final response = await relayDesktops();
    final items = response.data?['items'];
    String publicKey = '';
    if (items is List) {
      for (final item in items) {
        if (item is! Map) continue;
        if ('${item['relay_id'] ?? ''}'.trim() != clean) continue;
        publicKey = '${item['public_key'] ?? ''}'.trim();
        break;
      }
    }
    if (publicKey.isEmpty) {
      throw const RelayE2eeException(
        '电脑端尚未启用端到端加密，请更新电脑端并重新配对后再试。',
      );
    }
    await RelayE2ee.pinDesktopKey(clean, publicKey);
    return publicKey;
  }

  Future<MobileEnvelope<Map<String, Object?>>> relayTaskStatus(
    String taskId,
  ) async {
    final json = await getJson(XcagiMobileEndpoints.relayTaskStatus(taskId));
    final envelope = MobileEnvelope.fromJson(json, _asObjectMap);
    await _decryptRelayResult(envelope);
    return envelope;
  }

  Future<void> _decryptRelayResult(
    MobileEnvelope<Map<String, Object?>> envelope,
  ) async {
    final task = envelope.data?['task'];
    if (task is! Map) return;
    final result = task['result'];
    if (RelayE2ee.isE2eeError(result)) {
      task['result'] = <String, Object?>{
        'error': '电脑端无法解密任务，请重新配对后再试。',
      };
      return;
    }
    if (!RelayE2ee.isEnvelope(result)) return;
    final reference = '${result['ref'] ?? ''}'.trim();
    final keys = await RelayE2ee.taskKeys(reference);
    if (keys == null ||
        keys.privateKey.isEmpty ||
        keys.publicKey.isEmpty ||
        keys.desktopPublicKey.isEmpty) {
      task['result'] = <String, Object?>{
        'error': '任务结果无法解密，请在电脑端重新配对后再试。',
      };
      return;
    }
    try {
      task['result'] = await RelayE2ee.openResult(
        Map<String, Object?>.from(result as Map),
        ephemeralPrivateKey: keys.privateKey,
        ephemeralPublicKey: keys.publicKey,
        desktopPublicKey: keys.desktopPublicKey,
      );
    } on RelayE2eeException catch (error) {
      task['result'] = <String, Object?>{'error': error.message};
    }
  }

  Future<MobileEnvelope<Map<String, Object?>>> relayCancelTask(
    String taskId,
  ) async {
    final json = await postJson(
      XcagiMobileEndpoints.relayTaskCancel(taskId),
      <String, Object?>{},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> onboardingIndustries() async {
    final json = await getJson(XcagiMobileEndpoints.onboardingIndustries);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> industryBaseline(
    String industryId,
  ) async {
    final json = await getJson(
      XcagiMobileEndpoints.onboardingIndustryBaseline,
      query: {'industry_id': industryId.trim().isEmpty ? '通用' : industryId},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> selectOnboardingIndustry(
    String industryId,
  ) async {
    final json = await postJson(XcagiMobileEndpoints.onboardingSelectIndustry, {
      'industry_id': industryId.trim().isEmpty ? '通用' : industryId.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> installHostFoundation({
    String edition = 'generic',
  }) async {
    final json = await postJson(
      XcagiMobileEndpoints.installHostFoundation,
      const {},
      query: {'edition': edition},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> installIndustrySeed(
    String industryId,
  ) async {
    final json = await postJson(XcagiMobileEndpoints.installIndustrySeed, {
      'industry_id': industryId.trim().isEmpty ? '通用' : industryId.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> installMod({
    required String modId,
    required String industryId,
  }) async {
    final json = await postJson(XcagiMobileEndpoints.installMod, {
      'mod_id': modId.trim(),
      'industry_id': industryId.trim().isEmpty ? '通用' : industryId.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> installCustomerDeliverySeed({
    required String modId,
    required String industryId,
  }) async {
    final json =
        await postJson(XcagiMobileEndpoints.installCustomerDeliverySeed, {
      'mod_id': modId.trim(),
      'industry_id': industryId.trim().isEmpty ? '通用' : industryId.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }
}
