part of 'mobile_api.dart';

abstract class _ApiWorkBase extends _ApiPairingBase {
  _ApiWorkBase({
    super.config,
    super.sessionStore,
    super.httpClient,
    super.credentialCipher,
  });

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

  /// Native workbench requests retain the page's account and connection.
  Future<Map<String, Object?>> workspaceRequest(
    String path, {
    String method = 'GET',
    Map<String, String> query = const {},
    Map<String, Object?>? body,
    required int expectedGeneration,
    required String expectedBase,
    String activeModId = '',
  }) {
    if (activeModId.isNotEmpty &&
        !RegExp(r'^[a-zA-Z0-9_-]+$').hasMatch(activeModId)) {
      throw ArgumentError('无效应用');
    }
    final uri = Uri.parse(path);
    if (uri.hasScheme ||
        uri.hasAuthority ||
        !path.startsWith('api/') ||
        path.split('/').any((part) => part == '..' || part == '.') ||
        uri.pathSegments.any((part) => part == '..' || part == '.')) {
      throw ArgumentError('工作台接口必须属于当前服务');
    }
    if (authGeneration != expectedGeneration) {
      throw StateError('账号已切换，请重新打开');
    }
    return _sendJsonRequest(
        method: method,
        path: path,
        query: query,
        body: body,
        baseUrl: expectedBase,
        expectedConnectionBase: expectedBase,
        activeModId: activeModId);
  }

  Future<List<int>> workspaceFileRequest(
    String path, {
    Map<String, String> query = const {},
    List<int>? upload,
    String name = '',
    String field = 'file',
    required int expectedGeneration,
    required String expectedBase,
    String activeModId = '',
  }) async {
    if (activeModId.isNotEmpty &&
        !RegExp(r'^[a-zA-Z0-9_-]+$').hasMatch(activeModId)) {
      throw ArgumentError('无效应用');
    }
    final uri = Uri.parse(path);
    if (uri.hasScheme ||
        uri.hasAuthority ||
        !path.startsWith('api/') ||
        path.split('/').any((part) => part == '..' || part == '.') ||
        uri.pathSegments.any((part) => part == '..' || part == '.')) {
      throw ArgumentError('文件接口必须属于当前服务');
    }
    if (upload != null &&
        (upload.isEmpty || upload.length > 16 * 1024 * 1024)) {
      throw StateError('文件须为 1 字节至 16MB');
    }
    if (upload != null && !RegExp(r'^[a-z_]+$').hasMatch(field)) {
      throw ArgumentError('无效文件字段');
    }
    Future<void> check() async {
      final currentBase = await resolveSessionBaseUrl();
      if (expectedGeneration != authGeneration || currentBase != expectedBase) {
        throw StateError('账号或连接已切换，请重新打开页面');
      }
    }

    Future<List<int>> perform() async {
      await check();
      final request = await _open(upload == null ? 'GET' : 'POST', path,
          baseUrl: expectedBase, query: query);
      request.followRedirects = false;
      if (activeModId.isNotEmpty) {
        request.headers.set('X-XCAGI-Active-Mod-Id', activeModId);
      }
      try {
        await check();
      } catch (_) {
        unawaited(request.done.then<void>((_) {}, onError: (Object _) {}));
        request.abort();
        rethrow;
      }
      if (upload != null) {
        final boundary = 'xcagi-file-${DateTime.now().microsecondsSinceEpoch}';
        final safeName = name.replaceAll(RegExp(r'[\r\n"\\]'), '_');
        final bytes = <int>[
          ...utf8.encode(
              '--$boundary\r\nContent-Disposition: form-data; name="$field"; filename="$safeName"\r\nContent-Type: application/octet-stream\r\n\r\n'),
          ...upload,
          ...utf8.encode('\r\n--$boundary--\r\n'),
        ];
        request.headers.set(HttpHeaders.contentTypeHeader,
            'multipart/form-data; boundary=$boundary');
        request.contentLength = bytes.length;
        request.add(bytes);
      }
      final response = await request.close().timeout(_config.timeout);
      final bytes = <int>[];
      await for (final chunk in response.timeout(_config.timeout)) {
        if (bytes.length + chunk.length > 32 * 1024 * 1024) {
          request.abort();
          throw StateError('文件超过 32MB，请缩小导出范围');
        }
        bytes.addAll(chunk);
      }
      await check();
      if (response.statusCode < 200 || response.statusCode >= 300) {
        Map<String, Object?> body = {};
        try {
          body = _asObjectMap(jsonDecode(utf8.decode(bytes)));
        } catch (_) {}
        throw MobileApiException(
            statusCode: response.statusCode,
            message:
                body['message']?.toString() ?? '文件操作失败（${response.statusCode}）',
            body: body);
      }
      final contentType = response.headers.contentType?.mimeType ?? '';
      if (upload == null &&
          (contentType.contains('json') || contentType.contains('html'))) {
        throw StateError('服务未返回可下载的文件');
      }
      return bytes;
    }

    try {
      return await perform();
    } on MobileApiException catch (error) {
      if (!_isRetryableAuthError(error) ||
          expectedGeneration != authGeneration) {
        rethrow;
      }
      if (!await _refreshFhdAccessToken()) rethrow;
      return perform();
    }
  }

  Future<Map<String, Object?>> workspacePreferences() =>
      getJson('api/mobile/v1/workspace/prefs');

  Future<Map<String, Object?>> setWorkspaceEmployeeEnabled(
    String employeeId,
    bool enabled, {
    required int expectedGeneration,
    required String expectedBase,
  }) {
    if (authGeneration != expectedGeneration) {
      throw StateError('账号已切换，请重新打开');
    }
    return _sendJsonRequest(
      method: 'PATCH',
      path: 'api/mobile/v1/workspace/prefs',
      baseUrl: expectedBase,
      expectedConnectionBase: expectedBase,
      body: {
        'workflow_ai_employees': {employeeId: enabled}
      },
    );
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

  /// 统一员工目录：与桌面端员工工作台、信息页同源。
  Future<MobileEnvelope<List<Map<String, Object?>>>> employeeDirectory() async {
    final json = await getJson(XcagiMobileEndpoints.employeeDirectory);
    return MobileEnvelope.fromJson(json, (value) {
      final data = _asObjectMap(value);
      final rows = data['employees'];
      if (rows is! List) return const <Map<String, Object?>>[];
      return rows
          .whereType<Map>()
          .map((row) => Map<String, Object?>.from(row))
          .toList(growable: false);
    });
  }

  Future<MobileEnvelope<MobileTaskListData>> mobileTasks({
    int limit = 50,
  }) async {
    final json = await getJson(
      XcagiMobileEndpoints.tasks,
      query: {'limit': '$limit'},
    );
    return MobileEnvelope.fromJson(
      json,
      (value) => MobileTaskListData.fromJson(_asObjectMap(value)),
    );
  }

  Future<MobileEnvelope<MobileTaskSummary>> mobileTaskDetail(
    String taskId,
  ) async {
    final json = await getJson(XcagiMobileEndpoints.taskDetail(taskId));
    return MobileEnvelope.fromJson(
      json,
      (value) => MobileTaskSummary.fromJson(_asObjectMap(value)),
    );
  }

  Future<MobileEnvelope<MobileDesktopDeviceListData>>
      mobileDesktopDevices() async {
    final json = await getJson(XcagiMobileEndpoints.desktopDevices);
    return MobileEnvelope.fromJson(
      json,
      (value) => MobileDesktopDeviceListData.fromJson(_asObjectMap(value)),
    );
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
