part of 'mobile_repository.dart';

extension on WorkflowEmployeeInfo {
  String contactSubtitle(String source) {
    final summary = panelSummary.trim();
    if (summary.isNotEmpty) return summary;
    if (source.trim().isNotEmpty) return '来自 ${source.trim()}';
    return phoneChannel.contactChannelLabel();
  }
}

extension on String {
  String contactChannelLabel() {
    switch (trim()) {
      case 'admin-duty':
        return '服务器后台';
      case 'mobile':
      case 'mobile-chat':
        return '手机端会话';
      case '':
        return '';
      default:
        return trim();
    }
  }
}

extension on int {
  int ifZero(int fallback) => this == 0 ? fallback : this;

  int takeIfValidPort() => this > 0 && this <= 65535 ? this : 0;
}

extension on SuperEmployeeMessage {
  ChatMessage toChatMessage(String conversationId) {
    final normalizedRole = role.trim().toLowerCase();
    final chatRole = normalizedRole == 'user' || normalizedRole == 'human'
        ? ChatRole.user
        : ChatRole.assistant;

    return ChatMessage(
      id: id.ifEmpty('remote-${createdAt.hashCode}-${body.hashCode}'),
      conversationId: conversationId,
      role: chatRole,
      body: body,
      timeText: createdAt,
      hasEmployeeProfile: chatRole == ChatRole.assistant,
    );
  }
}

ChatMessage? _chatMessageFromCache(Map<String, Object?> json) {
  final body = _stringField(json, 'body').ifEmpty(_stringField(json, 'text'));
  if (body.trim().isEmpty) return null;
  final normalizedRole = _stringField(json, 'role').toLowerCase();
  final role = normalizedRole == 'user' || normalizedRole == 'human'
      ? ChatRole.user
      : normalizedRole == 'system'
          ? ChatRole.system
          : ChatRole.assistant;
  final statusText = _stringField(json, 'status').toLowerCase();
  final status = statusText == 'failed'
      ? ChatDeliveryStatus.failed
      : statusText == 'sending'
          ? ChatDeliveryStatus.sending
          : ChatDeliveryStatus.sent;
  final conversationId = _stringField(json, 'conversation_id');
  return ChatMessage(
    id: _stringField(
      json,
      'id',
    ).ifEmpty('cache-${conversationId.hashCode}-${body.hashCode}'),
    conversationId: conversationId,
    role: role,
    body: body,
    timeText: _stringField(
      json,
      'time_text',
    ).ifEmpty(_stringField(json, 'created_at')),
    hasEmployeeProfile: _boolField(
      json,
      'has_employee_profile',
      fallback: role == ChatRole.assistant,
    ),
    status: status,
    quote: _stringField(json, 'quote'),
    cacheTimestampMs: _cachedChatTimestampMs(json),
  );
}

int _cachedChatTimestampMs(Map<String, Object?> json) {
  final direct = _intField(json, 'ts');
  if (direct > 0) return direct;
  final timestampMs = _intField(json, 'timestamp_ms');
  if (timestampMs > 0) return timestampMs;
  final createdMs = _intField(json, 'created_at_ms');
  if (createdMs > 0) return createdMs;
  return _parseTimestampMs(
    _stringField(json, 'time_text').ifEmpty(_stringField(json, 'created_at')),
  );
}

int _parseTimestampMs(String value) {
  final text = value.trim();
  if (text.isEmpty || text == '刚刚') return 0;
  final numeric = int.tryParse(text);
  if (numeric != null) return numeric;
  return DateTime.tryParse(text)?.millisecondsSinceEpoch ?? 0;
}

ChatMessage _assistantMessage(String conversationId, String body) {
  return ChatMessage(
    id: 'remote-${DateTime.now().microsecondsSinceEpoch}',
    conversationId: conversationId,
    role: ChatRole.assistant,
    body: body,
    timeText: '刚刚',
    hasEmployeeProfile: true,
  );
}

List<Map<String, String>> _recentChatContext(List<ChatMessage> messages) {
  final rows = messages
      .where((message) => message.role != ChatRole.system)
      .where((message) => message.body.trim().isNotEmpty)
      .map(
        (message) => {
          'role': message.role == ChatRole.user ? 'user' : 'assistant',
          'content': _take(message.body, 500),
        },
      )
      .toList(growable: false);
  if (rows.length <= 6) return rows;
  return rows.sublist(rows.length - 6);
}

String _take(String value, int maxLength) {
  final text = value.trim();
  if (text.length <= maxLength) return text;
  return text.substring(0, maxLength);
}

String _assistantReplyFromMap(Map<String, Object?> json) {
  final assistant = _firstNestedReply(json, const [
    'assistant_message',
    'assistantMessage',
    'assistant',
  ]);
  if (assistant.isNotEmpty) return assistant;

  final direct = _firstString(json, const [
    'reply',
    'answer',
    'response',
    'body',
    'content',
    'text',
    'message',
  ]);
  if (direct.isNotEmpty) return direct;

  return _firstNestedReply(json, const ['data', 'result', 'codex']);
}

String _firstNestedReply(Map<String, Object?> json, List<String> keys) {
  for (final key in keys) {
    final value = json[key];
    if (value is String) {
      final text = value.trim();
      if (text.isNotEmpty) return text;
    }
    if (value is Map<String, Object?>) {
      final text = _assistantReplyFromMap(value);
      if (text.isNotEmpty) return text;
    }
    if (value is Map) {
      final text = _assistantReplyFromMap(
        value.map((key, value) => MapEntry(key.toString(), value)),
      );
      if (text.isNotEmpty) return text;
    }
  }
  return '';
}

String _firstString(Map<String, Object?> json, List<String> keys) {
  for (final key in keys) {
    final value = json[key];
    if (value is! String) continue;
    final text = value.trim();
    if (text.isNotEmpty) return text;
  }
  return '';
}

class MobileRepositoryException implements Exception {
  const MobileRepositoryException(this.message);

  final String message;

  @override
  String toString() => message;
}

/// Relay 任务进度快照，供 UI 显示长任务状态。
class RelayTaskProgress {
  const RelayTaskProgress({
    required this.taskId,
    required this.status,
    required this.toolLabel,
  });

  final String taskId;
  final String status;
  final String toolLabel;
}

class _MobileRepositoryCancelled implements Exception {
  const _MobileRepositoryCancelled();

  @override
  String toString() => 'cancelled';
}

void _throwIfCancelled(bool Function()? isCancelled) {
  if (isCancelled?.call() == true) {
    throw const _MobileRepositoryCancelled();
  }
}
