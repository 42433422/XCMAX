part of 'mobile_api.dart';

abstract class _ApiPairingBase extends _ApiCsAuthBase {
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

  Future<MobileEnvelope<Map<String, Object?>>> pairingLookup({
    required String code,
    String baseUrl = '',
  }) async {
    final json = await postJson(
      XcagiMobileEndpoints.pairingLookup,
      {'code': code.trim()},
      baseUrl: baseUrl.trim().isEmpty ? null : baseUrl.trim(),
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> issuePairing() async {
    final json = await postJson(XcagiMobileEndpoints.pairingIssue, const {});
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
    String relayId,
  ) async {
    final json = await postJson(XcagiMobileEndpoints.relayMobileBindAccount, {
      'relay_id': relayId.trim(),
    });
    final envelope = MobileEnvelope.fromJson(json, _asObjectMap);
    if (envelope.success) {
      await persistRelayBindingMeta(relayId.trim(), envelope.data);
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
    final json = await postJson(XcagiMobileEndpoints.relayTasks, {
      'relay_id': relayId.trim(),
      'kind': kind.trim(),
      'payload': payload,
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> relayTaskStatus(
    String taskId,
  ) async {
    final json = await getJson(XcagiMobileEndpoints.relayTaskStatus(taskId));
    return MobileEnvelope.fromJson(json, _asObjectMap);
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
