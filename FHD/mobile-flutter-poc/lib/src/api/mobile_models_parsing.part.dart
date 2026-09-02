// part 文件：员工消息与 JSON 解析工具函数。

part of 'mobile_models.dart';

class SuperEmployeeMessage {
  const SuperEmployeeMessage({
    required this.id,
    required this.role,
    required this.body,
    required this.createdAt,
  });

  final String id;
  final String role;
  final String body;
  final String createdAt;

  factory SuperEmployeeMessage.fromJson(Map<String, Object?> json) {
    return SuperEmployeeMessage(
      id: _readString(json, const [
        'id',
      ]).ifEmpty(_readString(json, const ['message_id', 'uuid'])),
      role: _readString(json, const ['role', 'sender']).ifEmpty('assistant'),
      body: _readString(json, const ['body', 'message', 'content', 'text']),
      createdAt: _readString(json, const ['created_at', 'time', 'timestamp']),
    );
  }
}

List<SuperEmployeeMessage> parseSuperEmployeeMessages(Object? value) {
  final data = _readMap(value);
  final rawMessages =
      data['messages'] ?? data['items'] ?? data['data'] ?? value;
  return _readList(rawMessages)
      .map(SuperEmployeeMessage.fromJson)
      .where((message) => message.body.trim().isNotEmpty)
      .toList(growable: false);
}

extension NonBlankString on String {
  String ifEmpty(String fallback) => trim().isEmpty ? fallback : trim();
}

String _firstNonBlank(List<String> values) {
  for (final value in values) {
    final trimmed = value.trim();
    if (trimmed.isNotEmpty) return trimmed;
  }
  return '';
}

String _readString(Map<String, Object?> json, List<String> keys) {
  for (final key in keys) {
    final value = json[key];
    if (value == null) continue;
    final text = value.toString().trim();
    if (text.isNotEmpty) return text;
  }
  return '';
}

String? _readOptionalString(Map<String, Object?> json, List<String> keys) {
  final value = _readString(json, keys);
  return value.isEmpty ? null : value;
}

int _readInt(Map<String, Object?> json, List<String> keys, int fallback) {
  for (final key in keys) {
    final value = json[key];
    if (value is int) return value;
    if (value is num) return value.toInt();
    if (value is String) {
      final parsed = int.tryParse(value.trim());
      if (parsed != null) return parsed;
    }
  }
  return fallback;
}

int? _readIntOrNull(Map<String, Object?> json, List<String> keys) {
  for (final key in keys) {
    final value = json[key];
    if (value is int) return value;
    if (value is num) return value.toInt();
    if (value is String) {
      final parsed = int.tryParse(value.trim());
      if (parsed != null) return parsed;
    }
  }
  return null;
}

double? _readDouble(Map<String, Object?> json, List<String> keys) {
  for (final key in keys) {
    final value = json[key];
    if (value is num) return value.toDouble();
    if (value is String) {
      final parsed = double.tryParse(value.trim().replaceAll(',', ''));
      if (parsed != null) return parsed;
    }
  }
  return null;
}

bool _readBool(
  Map<String, Object?> json,
  List<String> keys, {
  bool fallback = false,
}) {
  for (final key in keys) {
    final value = json[key];
    if (value is bool) return value;
    if (value is num) return value != 0;
    if (value is String) {
      final normalized = value.trim().toLowerCase();
      if (const ['1', 'true', 'yes', 'ok'].contains(normalized)) return true;
      if (const ['0', 'false', 'no'].contains(normalized)) return false;
    }
  }
  return fallback;
}

Map<String, Object?> _readMap(Object? value) {
  if (value is Map<String, Object?>) return value;
  if (value is Map) {
    return value.map((key, value) => MapEntry(key.toString(), value));
  }
  return const <String, Object?>{};
}

List<Map<String, Object?>> _readList(Object? value) {
  if (value is List) {
    return value
        .whereType<Map>()
        .map((row) => row.map((key, value) => MapEntry(key.toString(), value)))
        .toList(growable: false);
  }
  return const <Map<String, Object?>>[];
}

List<Object?> _readListValues(Object? value) {
  if (value is List) return value;
  return const <Object?>[];
}
