part of 'mobile_api.dart';

abstract class _ApiChatBase extends _ApiWorkBase {
  _ApiChatBase({
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
  }) async {
    final context = <String, Object?>{};
    if (recentMessages.isNotEmpty) {
      context['recent_messages'] = recentMessages;
    }
    final body = <String, Object?>{
      'message': message,
      'source': 'pro',
      'mode': 'professional',
      if (userId > 0) 'user_id': '$userId',
      if (context.isNotEmpty) 'context': context,
    };

    final request = await _open('POST', XcagiMobileEndpoints.aiChatStream);
    request.headers.set(HttpHeaders.acceptHeader, 'text/event-stream');
    if (userId > 0) {
      request.headers.set('X-User-ID', '$userId');
    }
    final bytes = utf8.encode(jsonEncode(body));
    request.contentLength = bytes.length;
    request.add(bytes);

    final response = await request.close().timeout(_config.timeout);
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
    final body = <String, Object?>{
      'message': message,
      'conversation_id': conversationId,
      'mod_id': modId,
      'employee_id': employeeId,
    };

    final request = await _open(
      'POST',
      XcagiMobileEndpoints.employeeChatStream(employeeId),
    );
    request.headers.set(HttpHeaders.acceptHeader, 'text/event-stream');
    if (userId > 0) {
      request.headers.set('X-User-ID', '$userId');
    }
    final bytes = utf8.encode(jsonEncode(body));
    request.contentLength = bytes.length;
    request.add(bytes);

    final response = await request.close().timeout(_config.timeout);
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
    final path = XcagiMobileEndpoints.superEmployeeStream(tool);
    final effectiveBaseUrl = baseUrl.trim().isEmpty ? null : baseUrl.trim();
    final request = await _open('POST', path, baseUrl: effectiveBaseUrl);
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

}
