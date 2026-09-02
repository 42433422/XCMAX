part of 'mobile_api.dart';

abstract class _ApiCsAuthBase extends _ApiGroupsBase {
  _ApiCsAuthBase({
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

  Future<MobileEnvelope<Map<String, Object?>>> csInfo() async {
    final json = await getJson(XcagiMobileEndpoints.csInfo);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> csMessages({
    String? since,
  }) async {
    final query = since == null || since.trim().isEmpty
        ? const <String, String>{}
        : {'since': since.trim()};
    final json = await getJson(XcagiMobileEndpoints.csMessages, query: query);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> postCsMessage(
    String body,
  ) async {
    final json = await postJson(XcagiMobileEndpoints.csMessages, {
      'body': body.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> adminCsInbox() async {
    final json = await getJson(XcagiMobileEndpoints.adminCsInbox);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> adminCsMessages(int id) async {
    final json = await getJson(XcagiMobileEndpoints.adminCsInboxMessages(id));
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> replyAdminCs({
    required int id,
    required String body,
  }) async {
    final json = await postJson(XcagiMobileEndpoints.adminCsInboxReply(id), {
      'body': body.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> employeePendingQuestions({
    int limit = 50,
    bool includeHistory = false,
    String? employeeId,
  }) async {
    final json = await getJson(
      XcagiMobileEndpoints.adminEmployeePendingQuestions,
      query: {
        'limit': '$limit',
        'include_history': '$includeHistory',
        if (employeeId != null && employeeId.trim().isNotEmpty)
          'employee_id': employeeId.trim(),
      },
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> answerEmployeePendingQuestion({
    required int questionId,
    required String answer,
  }) async {
    final json = await postJson(
      XcagiMobileEndpoints.adminEmployeePendingQuestionAnswer(questionId),
      {'answer': answer.trim()},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> login({
    required String username,
    required String password,
    required String accountKind,
  }) async {
    final json = await postJson(XcagiMobileEndpoints.authLogin, {
      'username': username.trim(),
      'password': password,
      'account_kind': accountKind.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> validateSession() async {
    final json = await getJson(XcagiMobileEndpoints.authSessionValidate);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> oidcExchange({
    required String code,
    required String state,
  }) async {
    final json = await postJson(XcagiMobileEndpoints.authOidcExchange, {
      'code': code.trim(),
      'state': state.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> refreshSession(
    String refreshToken,
  ) async {
    final json = await postJson(XcagiMobileEndpoints.authRefresh, {
      'refresh_token': refreshToken.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> discoverHint() async {
    final json = await getJson(XcagiMobileEndpoints.hostDiscoverHint);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> me() async {
    final json = _withLocalAvatar(
      await getJson(XcagiMobileEndpoints.me),
      await resolvedLocalAvatarSource(),
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> register({
    required String username,
    required String password,
    required String email,
    required String industryId,
    required String budgetRange,
    required String accountKind,
  }) async {
    final json = await postJson(XcagiMobileEndpoints.authRegister, {
      'username': username.trim(),
      'password': password,
      'email': email.trim(),
      'industry_id': industryId.trim().isEmpty ? '通用' : industryId.trim(),
      'budget_range': budgetRange.trim(),
      'account_kind': accountKind.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<Map<String, Object?>> legacyRegister({
    required String username,
    required String password,
    String email = '',
    String verificationCode = '',
    String industryId = '',
    String budgetRange = '',
    String accountKind = 'enterprise',
  }) {
    return postJson(XcagiMobileEndpoints.legacyAuthRegister, {
      'username': username.trim(),
      'password': password,
      'email': email.trim(),
      'verification_code': verificationCode.trim(),
      'industry_id': industryId.trim(),
      'budget_range': budgetRange.trim(),
      'account_kind':
          accountKind.trim().isEmpty ? 'enterprise' : accountKind.trim(),
    });
  }

  Future<Map<String, Object?>> lanAccessRequest({
    required String deviceLabel,
    String note = '',
  }) {
    return postJson(XcagiMobileEndpoints.lanAccessRequests, {
      'device_label': deviceLabel.trim(),
      'note': note.trim(),
    });
  }

  Future<Map<String, Object?>> lanStatus() {
    return getJson(XcagiMobileEndpoints.lanStatus);
  }

  Future<MobileEnvelope<Map<String, Object?>>> sendPhoneCode(
    String phone,
  ) async {
    final json = await postJson(XcagiMobileEndpoints.marketSendPhoneCode, {
      'phone': phone.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> loginWithPhoneCode({
    required String phone,
    required String code,
    required String accountKind,
  }) async {
    final json = await postJson(XcagiMobileEndpoints.authLoginWithPhoneCode, {
      'phone': phone.trim(),
      'code': code.trim(),
      'account_kind': accountKind.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> deleteAccount(
    String password,
  ) async {
    final json = await postModstoreJson(XcagiMobileEndpoints.accountDelete, {
      'password': password,
    });
    final envelope = MobileEnvelope.fromJson(json, _asObjectMap);
    if (envelope.success) {
      await clearActiveAuth();
    }
    return envelope;
  }

  Future<MobileEnvelope<Map<String, Object?>>> exportAccountData() async {
    final json = await getModstoreJson(XcagiMobileEndpoints.accountExport);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

}
