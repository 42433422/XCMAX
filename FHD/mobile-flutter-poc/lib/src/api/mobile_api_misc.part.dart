part of 'mobile_api.dart';


class MobileApiException implements Exception {
  const MobileApiException({
    required this.statusCode,
    required this.message,
    required this.body,
    this.errorCode = '',
    this.retryAfterSeconds,
  });

  final int statusCode;
  final String message;
  final Map<String, Object?> body;

  /// 服务端稳定错误码（如 RATE_LIMITED / UNAUTHORIZED），用于区分限流与权限。
  final String errorCode;

  /// 429/503 建议等待秒数（来自 Retry-After 或响应体 retry_after）。
  final int? retryAfterSeconds;

  @override
  String toString() {
    final meta = [
      if (errorCode.isNotEmpty) errorCode,
      if (retryAfterSeconds != null) 'retry_after=${retryAfterSeconds}s',
    ].join(', ');
    final suffix = meta.isEmpty ? '' : ', $meta';
    return 'MobileApiException($statusCode$suffix): $message';
  }
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

String chatReceiptText(Object? result, String turnId, String fallback) {
  final receipt = _asObjectMap(result);
  Iterable<Map<String, Object?>> envelopes(Object? value, [int depth = 0]) sync* {
    final row = _asObjectMap(value);
    if (row.isEmpty) return;
    yield row;
    if (depth >= 3) return;
    for (final key in const ['data', 'result', 'payload', 'business_result']) {
      yield* envelopes(row[key], depth + 1);
    }
  }
  final rows = envelopes(receipt).toList();
  final states = rows.map((row) => (row['execution_state'] ?? row['agent_status'] ?? row['run_status'] ?? row['status'] ?? '')
      .toString().trim().toLowerCase()).where((state) => state.isNotEmpty).toList();
  var state = states.isEmpty ? '' : states.first;
  final hasExecution = rows.any((row) => const ['run_id', 'agent_run_id', 'task_id']
      .any((key) => (row[key]?.toString().trim() ?? '').isNotEmpty));
  final uncertain = rows.any((row) => row['requires_reconciliation'] == true ||
      row['reconciliation_required'] == true || row['outcome_unknown'] == true ||
      row['execution_outcome'] == 'unknown' || row['outcome'] == 'unknown') ||
      states.any((state) => state == 'unknown' || state == 'outcome_unknown') ||
      (state.isEmpty && hasExecution) ||
      (state == 'completed' && (rows.any((row) => row['success'] == false || row['pending_approval'] == true || row['requires_token'] == true) ||
          states.any((state) => state != 'completed')));
  if (uncertain || state == 'outcome_unknown') state = 'unknown';
  if (state.isNotEmpty && !const ['completed', 'failed', 'cancelled', 'interrupted', 'rejected'].contains(state)) {
    throw MobileApiException(statusCode: 409, errorCode: 'CHAT_RECEIPT_PENDING',
        message: state == 'unknown' ? '原任务结果待核对，请读取原任务状态，勿重复提交。'
            : _chatResultText(result).ifEmpty('原任务尚未完成，请核对原任务状态，勿重复提交。'),
        body: {...receipt, 'turn_id': turnId, 'execution_state': state,
          'requires_reconciliation': state == 'unknown'});
  }
  if (receipt['success'] == false || const ['failed', 'cancelled', 'interrupted', 'rejected'].contains(state)) {
    throw MobileApiException(statusCode: 409, errorCode: 'CHAT_RECEIPT_TERMINAL',
        message: _chatResultText(result).ifEmpty('原任务未完成，请查看任务回执。'),
        body: {...receipt, 'turn_id': turnId, 'execution_state': state});
  }
  return _chatResultText(result).ifEmpty(fallback);
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
