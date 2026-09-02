part of 'mobile_api.dart';


class MobileApiException implements Exception {
  const MobileApiException({
    required this.statusCode,
    required this.message,
    required this.body,
  });

  final int statusCode;
  final String message;
  final Map<String, Object?> body;

  @override
  String toString() => 'MobileApiException($statusCode): $message';
}

Map<String, Object?> _asObjectMap(Object? value) {
  if (value is Map<String, Object?>) return value;
  if (value is Map) {
    return value.map((key, value) => MapEntry(key.toString(), value));
  }
  return const <String, Object?>{};
}

String _chatResultText(Object? result) {
  if (result == null) return '';
  if (result is String) return result.trim();
  final map = _asObjectMap(result);
  for (final key in const ['response', 'reply', 'message', 'content', 'text']) {
    final value = map[key]?.toString().trim() ?? '';
    if (value.isNotEmpty) return value;
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

String _relayIdFromBindingData(Map<String, Object?>? data) {
  final payload = data ?? const <String, Object?>{};
  return _firstNonBlank([
    _readString(payload, const ['relay_id']),
    _readString(_asObjectMap(payload['relay']), const ['relay_id']),
    _readString(_asObjectMap(payload['desktop']), const ['relay_id']),
  ]);
}

String _hostPortFromPairingData(Map<String, Object?> data) {
  final baseUrl = _firstNonBlank([
    _readString(data, const ['api_base_url']),
    _readString(data, const ['base_url']),
  ]);
  final fromBase = _hostPortFromApiBase(baseUrl);
  final host = _firstNonBlank([
    _readString(data, const ['host']),
    fromBase.$1,
  ]);
  if (host.isEmpty) return '';
  final port = _readInt(data, const ['port'], fromBase.$2);
  return _compactHostPort(host, port);
}

(String, int) _hostPortFromApiBase(String raw) {
  if (raw.trim().isEmpty) return ('', 0);
  final normalized = raw.contains('://') ? raw.trim() : 'http://${raw.trim()}';
  final uri = Uri.tryParse(normalized);
  if (uri == null) return ('', 0);
  final host = uri.host.trim();
  if (host.isEmpty) return ('', 0);
  final port = uri.hasPort
      ? uri.port
      : switch (uri.scheme.toLowerCase()) {
          'https' => 443,
          'http' => 80,
          _ => 0,
        };
  return (host, port);
}

String _compactHostPort(String host, int port) {
  final bare = host
      .trim()
      .replaceFirst(RegExp(r'^https?://'), '')
      .split('/')
      .first
      .split(':')
      .first
      .trim();
  if (bare.isEmpty) return '';
  if (port <= 0 || port > 65535) return bare;
  return '$bare:$port';
}

String _preferredServerModeAfterLogin(MobileSessionData session) {
  return MobileAuthRoutingPolicy.preferredServerModeAfterLogin(
    isEnterprise: MobileProductSkuConfig.isEnterprise(
      buildSku: MobileBuildConfig.productSku,
    ),
    configuredHost: session.fhdHost,
    currentMode: session.serverMode,
  );
}

String _firstNonBlank(List<String> values) {
  for (final value in values) {
    final clean = value.trim();
    if (clean.isNotEmpty) return clean;
  }
  return '';
}

bool _readBool(Map<String, Object?> json, List<String> keys) {
  for (final key in keys) {
    final value = json[key];
    if (value is bool) return value;
    if (value is num) return value != 0;
    if (value is String) {
      final normalized = value.trim().toLowerCase();
      if (['1', 'true', 'yes', 'on'].contains(normalized)) return true;
      if (['0', 'false', 'no', 'off'].contains(normalized)) return false;
    }
  }
  return false;
}
