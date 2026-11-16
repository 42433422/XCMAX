part of 'mobile_api.dart';

class MobileChatAttachment {
  const MobileChatAttachment(
      {required this.uploadId,
      required this.name,
      required this.baseUrl,
      required this.authGeneration,
      required this.conversationId});
  final String uploadId, name, baseUrl, conversationId;
  final int authGeneration;
}

abstract class _ApiChatBase extends _ApiWorkBase {
  _ApiChatBase({
    super.config,
    super.sessionStore,
    super.httpClient,
    super.credentialCipher,
  });

  Future<MobileChatAttachment> uploadChatAttachment({
    required String name,
    required List<int> bytes,
    required String conversationId,
    int? expectedAuthGeneration,
    String? expectedBaseUrl,
  }) async {
    if (bytes.isEmpty || bytes.length > 16 * 1024 * 1024) {
      throw const MobileApiException(
          statusCode: 413, message: '附件须为 1 字节至 16MB', body: {});
    }
    final generation = expectedAuthGeneration ?? _authGeneration;
    final session = await loadSession();
    if (!session.hasAuth) {
      throw const MobileApiException(
          statusCode: 401, message: '请先登录再上传附件', body: {});
    }
    final base = expectedBaseUrl ?? await resolveSessionBaseUrl();
    final boundary = 'xcagi-${DateTime.now().microsecondsSinceEpoch}';
    final safeName = name.replaceAll(RegExp(r'[\r\n"\\]'), '_');
    final payload = <int>[
      ...utf8.encode(
          '--$boundary\r\nContent-Disposition: form-data; name="file"; filename="$safeName"\r\nContent-Type: application/octet-stream\r\n\r\n'),
      ...bytes,
      ...utf8.encode('\r\n--$boundary--\r\n'),
    ];
    final request = await _open(
        'POST', 'api/platform-shell/chat-office-file-upload',
        baseUrl: base);
    final beforeSendBase = await resolveSessionBaseUrl();
    if (generation != _authGeneration || base != beforeSendBase) {
      request.abort();
      throw const MobileApiException(
          statusCode: 409, message: '账号已切换，请重新选择附件', body: {});
    }
    request.headers.set(HttpHeaders.contentTypeHeader,
        'multipart/form-data; boundary=$boundary');
    request.contentLength = payload.length;
    request.add(payload);
    final response = await _readJsonResponse(request);
    final afterUploadBase = await resolveSessionBaseUrl();
    if (generation != _authGeneration || base != afterUploadBase) {
      throw const MobileApiException(
          statusCode: 409, message: '账号或连接已切换，请重新上传附件', body: {});
    }
    final data = _asObjectMap(response['data']);
    final id = data['upload_id']?.toString().trim() ?? '';
    if (response['success'] == false || id.isEmpty) {
      throw MobileApiException(
          statusCode: 422,
          message:
              data['attachment_warning']?.toString() ?? '附件未取得有效凭证，请重新上传可读取的文件',
          body: {});
    }
    return MobileChatAttachment(
        uploadId: id,
        name: name,
        baseUrl: base,
        authGeneration: generation,
        conversationId: conversationId);
  }

  Future<String> streamAttachmentChat(
    String message, {
    required String conversationId,
    required List<MobileChatAttachment> attachments,
    required String idempotencyKey,
    List<Map<String, String>> recentMessages = const [],
    void Function(String)? onToken,
  }) async {
    final base = await resolveSessionBaseUrl();
    if (idempotencyKey.trim().isEmpty ||
        attachments.isEmpty ||
        attachments.length > 4 ||
        attachments.any((a) =>
            a.authGeneration != _authGeneration ||
            a.baseUrl != base ||
            a.conversationId != conversationId)) {
      throw const MobileApiException(
          statusCode: 409, message: '附件与当前账号、连接或会话不一致，请移除后重新上传', body: {});
    }
    return _streamChat(message,
        sessionId: conversationId,
        recentMessages: recentMessages,
        onToken: onToken,
        baseUrl: base,
        idempotencyKey: idempotencyKey,
        attachmentUploadIds:
            attachments.map((a) => a.uploadId).toSet().toList());
  }

  Future<Map<String, Object?>> chat(
    String message, {
    String? sessionId,
    Map<String, Object?> context = const {},
  }) {
    final cleanContext = Map<String, Object?>.of(context)
      ..removeWhere((key, value) => key.trim().isEmpty || value == null);
    return postJson(XcagiMobileEndpoints.aiChat, {
      'message': message,
      'body': message,
      'source': 'pro',
      'mode': 'professional',
      if (sessionId != null && sessionId.trim().isNotEmpty)
        'session_id': sessionId.trim(),
      if (cleanContext.isNotEmpty) 'context': cleanContext,
    });
  }

  Future<String> streamChat(
    String message, {
    String? sessionId,
    int userId = 0,
    List<Map<String, String>> recentMessages = const [],
    void Function(String token)? onToken,
  }) =>
      _streamChat(message,
          sessionId: sessionId,
          userId: userId,
          recentMessages: recentMessages,
          onToken: onToken);

  Future<String> _streamChat(
    String message, {
    String? sessionId,
    int userId = 0,
    List<Map<String, String>> recentMessages = const [],
    void Function(String)? onToken,
    String? baseUrl,
    List<String> attachmentUploadIds = const [],
    String idempotencyKey = '',
  }) async {
    final generation = _authGeneration;
    final context = <String, Object?>{
      if (idempotencyKey.isNotEmpty) 'idempotency_key': idempotencyKey,
      if (attachmentUploadIds.isNotEmpty)
        'attachment_upload_ids': attachmentUploadIds,
    };
    if (recentMessages.isNotEmpty) {
      context['recent_messages'] = recentMessages;
    }
    final body = <String, Object?>{
      'message': message,
      if (sessionId != null && sessionId.trim().isNotEmpty)
        'session_id': sessionId.trim(),
      'source': 'pro',
      'mode': 'professional',
      if (userId > 0) 'user_id': '$userId',
      if (context.isNotEmpty) 'context': context,
    };

    final streamBase = baseUrl ?? await resolveSessionBaseUrl();
    final request = await _open('POST', XcagiMobileEndpoints.aiChatStream,
        baseUrl: streamBase);
    final currentBase = await resolveSessionBaseUrl();
    if (generation != _authGeneration || streamBase != currentBase) {
      request.abort();
      throw const MobileApiException(
          statusCode: 409, message: '账号已切换，请重试', body: {});
    }
    request.headers.set(HttpHeaders.acceptHeader, 'text/event-stream');
    if (userId > 0) {
      request.headers.set('X-User-ID', '$userId');
    }
    final bytes = utf8.encode(jsonEncode(body));
    request.contentLength = bytes.length;
    request.add(bytes);

    final response = await request.close().timeout(_config.timeout);
    await _requireStreamScope(generation, streamBase);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final text = await utf8.decodeStream(response).timeout(_config.timeout);
      final body = _asObjectMap(text.trim().isEmpty ? null : jsonDecode(text));
      throw MobileApiException(
        statusCode: response.statusCode,
        message: body['message']?.toString() ??
            body['error']?.toString() ??
            'HTTP ${response.statusCode}',
        body: body,
      );
    }

    final buffer = StringBuffer();
    await for (final line
        in response.transform(utf8.decoder).transform(const LineSplitter())) {
      final eventBase = await resolveSessionBaseUrl();
      if (generation != _authGeneration || eventBase != streamBase) {
        throw const MobileApiException(
            statusCode: 409, message: '账号或连接已切换，请重试', body: {});
      }
      final trimmed = line.trim();
      if (!trimmed.startsWith('data:')) continue;
      final payload = trimmed.substring('data:'.length).trim();
      if (payload.isEmpty || payload == '[DONE]') continue;

      final json = _asObjectMap(jsonDecode(payload));
      final eventType = json['type']?.toString() ?? '';
      if (eventType.isNotEmpty) {
        switch (eventType) {
          case 'token':
            final token = json['text']?.toString() ?? '';
            if (token.isNotEmpty) {
              buffer.write(token);
              onToken?.call(token);
            }
            break;
          case 'done':
            final result = json['result'];
            final finalText = _chatResultText(
              result,
            ).ifEmpty(buffer.toString());
            return finalText.ifEmpty('（无回复）');
          case 'error':
            throw MobileApiException(
              statusCode: response.statusCode,
              message: json['message']?.toString() ?? 'stream error',
              body: json,
            );
        }
      } else {
        final error = json['error']?.toString() ?? '';
        if (error.isNotEmpty) {
          throw MobileApiException(
            statusCode: response.statusCode,
            message: error,
            body: json,
          );
        }
        final token = json['text']?.toString() ?? '';
        if (token.isNotEmpty) {
          buffer.write(token);
          onToken?.call(token);
        }
        if (json['done'] == true) {
          return buffer.toString().ifEmpty('（无回复）');
        }
      }
    }
    if (attachmentUploadIds.isNotEmpty) {
      throw const MobileApiException(
          statusCode: 502, message: '附件对话连接中断，结果待核对；附件已保留，请确认后重试', body: {});
    }
    return buffer.toString().ifEmpty('（无回复）');
  }

  Future<String> streamEmployeeChat({
    required String message,
    required String employeeId,
    required String modId,
    required String conversationId,
    int userId = 0,
    void Function(String token)? onToken,
  }) async {
    final generation = _authGeneration;
    final base = await resolveSessionBaseUrl();
    final body = <String, Object?>{
      'message': message,
      'conversation_id': conversationId,
      'mod_id': modId,
      'employee_id': employeeId,
    };

    final request = await _open(
      'POST',
      XcagiMobileEndpoints.employeeChatStream(employeeId),
      baseUrl: base,
    );
    await _requireStreamScope(generation, base, request: request);
    request.headers.set(HttpHeaders.acceptHeader, 'text/event-stream');
    if (userId > 0) {
      request.headers.set('X-User-ID', '$userId');
    }
    final bytes = utf8.encode(jsonEncode(body));
    request.contentLength = bytes.length;
    request.add(bytes);

    final response = await request.close().timeout(_config.timeout);
    await _requireStreamScope(generation, base);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final text = await utf8.decodeStream(response).timeout(_config.timeout);
      final body = _asObjectMap(text.trim().isEmpty ? null : jsonDecode(text));
      throw MobileApiException(
        statusCode: response.statusCode,
        message: body['message']?.toString() ??
            body['error']?.toString() ??
            'HTTP ${response.statusCode}',
        body: body,
      );
    }

    final buffer = StringBuffer();
    await for (final line
        in response.transform(utf8.decoder).transform(const LineSplitter())) {
      await _requireStreamScope(generation, base);
      final trimmed = line.trim();
      if (!trimmed.startsWith('data:')) continue;
      final payload = trimmed.substring('data:'.length).trim();
      if (payload.isEmpty || payload == '[DONE]') continue;

      final json = _asObjectMap(jsonDecode(payload));
      final eventType = json['type']?.toString() ?? '';
      switch (eventType) {
        case 'token':
          final token = json['text']?.toString() ?? '';
          if (token.isNotEmpty) {
            buffer.write(token);
            onToken?.call(token);
          }
          break;
        case 'done':
          final result = json['result'];
          final finalText = _chatResultText(result).ifEmpty(buffer.toString());
          return finalText.ifEmpty('（员工未回复）');
        case 'error':
          throw MobileApiException(
            statusCode: response.statusCode,
            message: json['message']?.toString() ?? '员工对话流错误',
            body: json,
          );
        default:
          final error = json['error']?.toString() ?? '';
          if (error.isNotEmpty) {
            throw MobileApiException(
              statusCode: response.statusCode,
              message: error,
              body: json,
            );
          }
          final token = json['text']?.toString() ?? '';
          if (token.isNotEmpty) {
            buffer.write(token);
            onToken?.call(token);
          }
          if (json['done'] == true) {
            return buffer.toString().ifEmpty('（员工未回复）');
          }
      }
    }
    return buffer.toString().ifEmpty('（员工未回复）');
  }

  Future<MobileEnvelope<List<SuperEmployeeMessage>>> superEmployeeMessages(
    String tool, {
    int limit = 80,
  }) async {
    final json = await getJson(
      XcagiMobileEndpoints.superEmployeeMessages(tool),
      query: {'limit': '$limit'},
    );
    return MobileEnvelope.fromJson(json, parseSuperEmployeeMessages);
  }

  Future<MobileEnvelope<Map<String, Object?>>> postSuperEmployeeMessage(
    String tool,
    String body, {
    String baseUrl = '',
  }) async {
    final json = await postJson(
      XcagiMobileEndpoints.superEmployeeMessages(tool),
      {
        'body': body,
        'message': body,
        'context': const {'source': 'mobile', 'client_surface': 'mobile'},
      },
      baseUrl: baseUrl.trim().isEmpty ? null : baseUrl.trim(),
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  /// LAN SSE 流式调用超级员工。逐 token 返回，与 streamChat 同样的 SSE 协议。
  /// 失败时抛 [MobileApiException]，由调用方决定是否回退到直答/relay。
  Future<String> streamSuperEmployeeMessage(
    String tool,
    String body, {
    String baseUrl = '',
    void Function(String token)? onToken,
    void Function(String status)? onStatus,
    bool Function()? isCancelled,
  }) async {
    final generation = _authGeneration;
    final sessionBase = await resolveSessionBaseUrl();
    final path = XcagiMobileEndpoints.superEmployeeStream(tool);
    final effectiveBaseUrl =
        baseUrl.trim().isEmpty ? sessionBase : baseUrl.trim();
    final request = await _open('POST', path, baseUrl: effectiveBaseUrl);
    await _requireStreamScope(generation, sessionBase, request: request);
    request.headers.set(HttpHeaders.acceptHeader, 'text/event-stream');
    final bytes = utf8.encode(
      jsonEncode({
        'body': body,
        'message': body,
        'context': const {'source': 'mobile', 'client_surface': 'mobile'},
      }),
    );
    request.contentLength = bytes.length;
    request.add(bytes);

    final response = await request.close().timeout(_config.timeout);
    await _requireStreamScope(generation, sessionBase);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final text = await utf8.decodeStream(response).timeout(_config.timeout);
      final errBody = _asObjectMap(
        text.trim().isEmpty ? null : jsonDecode(text),
      );
      throw MobileApiException(
        statusCode: response.statusCode,
        message: errBody['message']?.toString() ??
            errBody['error']?.toString() ??
            'HTTP ${response.statusCode}',
        body: errBody,
      );
    }

    final buffer = StringBuffer();
    await for (final line
        in response.transform(utf8.decoder).transform(const LineSplitter())) {
      await _requireStreamScope(generation, sessionBase);
      if (isCancelled != null && isCancelled()) {
        return buffer.toString();
      }
      final trimmed = line.trim();
      if (!trimmed.startsWith('data:')) continue;
      final payload = trimmed.substring('data:'.length).trim();
      if (payload.isEmpty || payload == '[DONE]') continue;

      final json = _asObjectMap(jsonDecode(payload));
      final eventType = json['type']?.toString() ?? '';
      switch (eventType) {
        case 'token':
          final token = json['text']?.toString() ?? '';
          if (token.isNotEmpty) {
            buffer.write(token);
            onToken?.call(token);
          }
          break;
        case 'status':
          final status = json['text']?.toString() ?? '';
          if (status.isNotEmpty) {
            onStatus?.call(status);
          }
          break;
        case 'done':
          final result = json['result'];
          final finalText = _chatResultText(result).ifEmpty(buffer.toString());
          return finalText.ifEmpty('（无回复）');
        case 'error':
          throw MobileApiException(
            statusCode: response.statusCode,
            message: json['message']?.toString() ?? 'stream error',
            body: json,
          );
      }
    }
    return buffer.toString().ifEmpty('（无回复）');
  }

  Future<void> _requireStreamScope(int generation, String base,
      {HttpClientRequest? request}) async {
    final currentBase = await resolveSessionBaseUrl();
    if (generation != _authGeneration || base != currentBase) {
      request?.abort();
      throw const MobileApiException(
          statusCode: 409, message: '账号或服务端已切换，请重新发送', body: {});
    }
  }
}
