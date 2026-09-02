part of 'mobile_api.dart';

abstract class _ApiWorkBase extends _ApiPairingBase {
  _ApiWorkBase({
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

  Future<MobileEnvelope<Map<String, Object?>>> approvals({
    int page = 1,
    int pageSize = 50,
  }) async {
    final json = await getJson(
      XcagiMobileEndpoints.approvalRequests,
      query: {'page': '$page', 'page_size': '$pageSize'},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<Map<String, Object?>> approvalDetail(int id) {
    return getJson(XcagiMobileEndpoints.approvalDetail(id));
  }

  Future<Map<String, Object?>> approveApproval({
    required int id,
    required int approverId,
    required String opinion,
  }) {
    return postJson(XcagiMobileEndpoints.approvalApprove(id), {
      'approver_id': approverId,
      'opinion': opinion.trim(),
    });
  }

  Future<Map<String, Object?>> rejectApproval({
    required int id,
    required int approverId,
    required String reason,
  }) {
    return postJson(XcagiMobileEndpoints.approvalReject(id), {
      'approver_id': approverId,
      'reason': reason.trim(),
    });
  }

  Future<MobileEnvelope<Map<String, Object?>>> customers({
    int page = 1,
    int perPage = 20,
  }) async {
    final json = await getJson(
      XcagiMobileEndpoints.customers,
      query: {'page': '$page', 'per_page': '$perPage'},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> shipments({
    int page = 1,
    int perPage = 20,
  }) async {
    final json = await getJson(
      XcagiMobileEndpoints.shipments,
      query: {'page': '$page', 'per_page': '$perPage'},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> bridgeRequests({
    int page = 1,
    int perPage = 20,
    String? status,
    String? requestType,
  }) async {
    final query = <String, String>{'page': '$page', 'per_page': '$perPage'};
    final cleanStatus = status?.trim();
    if (cleanStatus != null && cleanStatus.isNotEmpty) {
      query['status'] = cleanStatus;
    }
    final cleanRequestType = requestType?.trim();
    if (cleanRequestType != null && cleanRequestType.isNotEmpty) {
      query['request_type'] = cleanRequestType;
    }
    final json = await getJson(
      XcagiMobileEndpoints.serviceBridgeRequests,
      query: query,
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<Map<String, Object?>> legacyBridgeRequests({
    int page = 1,
    int perPage = 20,
    String? status,
    String? requestType,
  }) {
    final query = <String, String>{'page': '$page', 'per_page': '$perPage'};
    final cleanStatus = status?.trim();
    if (cleanStatus != null && cleanStatus.isNotEmpty) {
      query['status'] = cleanStatus;
    }
    final cleanRequestType = requestType?.trim();
    if (cleanRequestType != null && cleanRequestType.isNotEmpty) {
      query['request_type'] = cleanRequestType;
    }
    return getJson(
      XcagiMobileEndpoints.legacyServiceBridgeRequests,
      query: query,
    );
  }

  Future<MobileEnvelope<Map<String, Object?>>> bridgeRespond({
    required int id,
    required String response,
    String respondedBy = 'android',
  }) async {
    final json = await putJson(XcagiMobileEndpoints.serviceBridgeRespond(id), {
      'response': response.trim(),
      'responded_by':
          respondedBy.trim().isEmpty ? 'android' : respondedBy.trim(),
      'status': 'resolved',
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<Map<String, Object?>> legacyBridgeRespond({
    required int id,
    required String response,
    String respondedBy = 'android',
  }) {
    return putJson(XcagiMobileEndpoints.legacyServiceBridgeRespond(id), {
      'response': response.trim(),
      'responded_by':
          respondedBy.trim().isEmpty ? 'android' : respondedBy.trim(),
      'status': 'resolved',
    });
  }

  Future<Map<String, Object?>> inventoryItems() {
    return getJson(XcagiMobileEndpoints.inventoryItems);
  }

  Future<Map<String, Object?>> modsList() {
    return getJson(XcagiMobileEndpoints.legacyModsList);
  }

  Future<Map<String, Object?>> financeSummary() {
    return getJson(XcagiMobileEndpoints.financeSummary);
  }

  Future<Map<String, Object?>> marketAccountSync(Map<String, String> body) {
    return postJson(XcagiMobileEndpoints.marketAccountSync, body);
  }

  Future<Map<String, Object?>> marketSessionHandoff() {
    return getJson(XcagiMobileEndpoints.marketSessionHandoff);
  }

  Future<MobileEnvelope<Map<String, Object?>>> mobileMods() async {
    final json = await getJson(XcagiMobileEndpoints.mods);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> paymentPlans() async {
    final json = await getJson(XcagiMobileEndpoints.paymentPlans);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> paymentCheckout(
    Map<String, Object?> body,
  ) async {
    final json = await postJson(XcagiMobileEndpoints.paymentCheckout, body);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> paymentQuery(
    String outTradeNo,
  ) async {
    final json = await getJson(XcagiMobileEndpoints.paymentQuery(outTradeNo));
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<AiCircleListData>> circlePosts({int limit = 50}) async {
    final json = await getJson(
      XcagiMobileEndpoints.circlePosts,
      query: {'limit': '$limit'},
    );
    return MobileEnvelope.fromJson(
      json,
      (value) => AiCircleListData.fromJson(_asObjectMap(value)),
    );
  }

  Future<MobileEnvelope<Map<String, Object?>>> toggleCircleLike(
    int postId,
  ) async {
    final json = await postJson(XcagiMobileEndpoints.circleLike(postId), {});
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<Map<String, Object?>> imListConversations() {
    return getJson(XcagiMobileEndpoints.imConversations);
  }

  Future<Map<String, Object?>> imMarkRead(int conversationId) {
    return postJson(XcagiMobileEndpoints.imRead(conversationId), {});
  }

  Future<Map<String, Object?>> imCreateDirect(int peerUserId) {
    return postJson(XcagiMobileEndpoints.imDirect, {
      'peer_user_id': peerUserId,
    });
  }

  Future<Map<String, Object?>> imListMessages(
    int conversationId, {
    int limit = 50,
  }) {
    return getJson(
      XcagiMobileEndpoints.imMessages(conversationId),
      query: {'limit': '$limit'},
    );
  }

  Future<Map<String, Object?>> imSendMessage({
    required int conversationId,
    required String body,
  }) {
    return postJson(XcagiMobileEndpoints.imMessages(conversationId), {
      'body': body.trim(),
    });
  }

  Future<MobileEnvelope<Map<String, Object?>>> addCircleComment(
    int postId,
    String body,
  ) async {
    final text = body.trim();
    final json = await postJson(XcagiMobileEndpoints.circleComments(postId), {
      'body': text,
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }
}
