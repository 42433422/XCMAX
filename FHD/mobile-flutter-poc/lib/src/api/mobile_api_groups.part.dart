part of 'mobile_api.dart';

abstract class _ApiGroupsBase extends _ApiNavBase {
  _ApiGroupsBase({
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

  Future<MobileEnvelope<Map<String, Object?>>> aiGroups() async {
    final json = await getJson(XcagiMobileEndpoints.aiGroups);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> aiGroupCandidates() async {
    final json = await getJson(XcagiMobileEndpoints.aiGroupCandidates);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> createAiGroup(
    String name,
  ) async {
    final json = await postJson(XcagiMobileEndpoints.aiGroups, {
      'name': name.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> aiGroupMessages(
    String groupId, {
    int limit = 100,
  }) async {
    final json = await getJson(
      XcagiMobileEndpoints.aiGroupMessages(groupId),
      query: {'limit': '$limit'},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> postAiGroupMessage({
    required String groupId,
    required String message,
    List<String> mentions = const [],
    bool dispatch = false,
    String branchContext = '',
    Map<String, String> context = const {},
  }) async {
    final branch = branchContext.trim();
    final json = await postJson(XcagiMobileEndpoints.aiGroupMessages(groupId), {
      'message': message.trim(),
      'sender_name': '我',
      'mentions': mentions,
      'dispatch': dispatch,
      'branch_context': branch,
      'branch': branch,
      'context': context,
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> addAiGroupMember({
    required String groupId,
    required String employeeId,
    required String modId,
    required String name,
    required String avatar,
    required String summary,
  }) async {
    final json = await postJson(XcagiMobileEndpoints.aiGroupMembers(groupId), {
      'employee_id': employeeId.trim(),
      'mod_id': modId.trim(),
      'name': name.trim(),
      'avatar': avatar.trim(),
      'summary': summary.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> removeAiGroupMember({
    required String groupId,
    required String employeeId,
  }) async {
    final json = await deleteJson(
      XcagiMobileEndpoints.aiGroupMember(
        groupId: groupId,
        employeeId: employeeId,
      ),
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> toggleAiGroupPin(
    String groupId,
  ) async {
    final json = await putJson(XcagiMobileEndpoints.aiGroupPin(groupId), {});
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> markAiGroupUnread(
    String groupId,
  ) async {
    final json = await postJson(
      XcagiMobileEndpoints.aiGroupMarkUnread(groupId),
      {},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> markAiGroupRead(
    String groupId,
  ) async {
    final json = await postJson(
      XcagiMobileEndpoints.aiGroupMarkRead(groupId),
      {},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> toggleAiGroupFollowed(
    String groupId,
  ) async {
    final json = await putJson(
      XcagiMobileEndpoints.aiGroupFollowed(groupId),
      {},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> toggleAiGroupHidden(
    String groupId,
  ) async {
    final json = await putJson(XcagiMobileEndpoints.aiGroupHidden(groupId), {});
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> deleteAiGroup(
    String groupId,
  ) async {
    final json = await deleteJson(XcagiMobileEndpoints.aiGroupDelete(groupId));
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> toggleConversationPin(
    String conversationId,
  ) async {
    final json = await putJson(
      XcagiMobileEndpoints.conversationPin(conversationId),
      {},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> markConversationUnread(
    String conversationId,
  ) async {
    final json = await postJson(
      XcagiMobileEndpoints.conversationMarkUnread(conversationId),
      {},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> markConversationRead(
    String conversationId,
  ) async {
    final json = await postJson(
      XcagiMobileEndpoints.conversationMarkRead(conversationId),
      {},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> toggleConversationFollowed(
    String conversationId,
  ) async {
    final json = await putJson(
      XcagiMobileEndpoints.conversationFollowed(conversationId),
      {},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> toggleConversationHidden(
    String conversationId,
  ) async {
    final json = await putJson(
      XcagiMobileEndpoints.conversationHidden(conversationId),
      {},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> deleteConversation(
    String conversationId,
  ) async {
    final json = await deleteJson(
      XcagiMobileEndpoints.conversationDelete(conversationId),
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

}
