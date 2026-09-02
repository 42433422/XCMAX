part of 'mobile_session_store.dart';

String _readString(Map<String, Object?> json, String key) =>
    json[key]?.toString().trim() ?? '';

int _readInt(Map<String, Object?> json, String key) {
  final value = json[key];
  if (value is int) return value;
  return int.tryParse(value?.toString() ?? '') ?? 0;
}

bool _readBool(Map<String, Object?> json, String key) {
  final value = json[key];
  if (value is bool) return value;
  if (value is num) return value != 0;
  final normalized = value?.toString().trim().toLowerCase() ?? '';
  if (const {'1', 'true', 'yes', 'on'}.contains(normalized)) return true;
  return false;
}

Map<String, String> _readStringMap(Map<String, Object?> json, String key) {
  final raw = json[key];
  if (raw is! Map) return const {};
  return raw.map(
    (key, value) => MapEntry(key.toString(), value?.toString().trim() ?? ''),
  )..removeWhere((_, value) => value.isEmpty);
}

Map<String, List<Map<String, Object?>>> _readChatCache(
  Map<String, Object?> json,
  String key,
) {
  final raw = json[key];
  if (raw is! Map) return const {};
  final result = <String, List<Map<String, Object?>>>{};
  for (final entry in raw.entries) {
    final value = entry.value;
    if (value is! List) continue;
    final rows = value
        .whereType<Map>()
        .map(
          (row) => row.map(
            (key, value) => MapEntry(key.toString(), value as Object?),
          ),
        )
        .toList(growable: false);
    if (rows.isNotEmpty) result[entry.key.toString()] = rows;
  }
  return result;
}

Map<String, Map<String, Object?>> _readObjectMap(
  Map<String, Object?> json,
  String key,
) {
  final raw = json[key];
  if (raw is! Map) return const {};
  final result = <String, Map<String, Object?>>{};
  for (final entry in raw.entries) {
    final value = entry.value;
    if (value is! Map) continue;
    final row = value.map(
      (key, value) => MapEntry(key.toString(), value as Object?),
    );
    if (row.isNotEmpty) result[entry.key.toString()] = row;
  }
  return result;
}

List<Map<String, Object?>> _readObjectList(
  Map<String, Object?> json,
  String key,
) {
  final raw = json[key];
  if (raw is! List) return const [];
  return raw
      .whereType<Map>()
      .map(
        (row) =>
            row.map((key, value) => MapEntry(key.toString(), value as Object?)),
      )
      .where((row) => row.isNotEmpty)
      .toList(growable: false);
}

String _firstNonBlank(String first, String second) {
  final clean = first.trim();
  return clean.isNotEmpty ? clean : second.trim();
}
