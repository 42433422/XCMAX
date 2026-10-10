import '../api/mobile_api.dart';
import '../api/mobile_models.dart';

/// 同步冲突条目（`GET /api/mobile/v1/sync/conflicts` 的 items）。
class MobileSyncConflict {
  const MobileSyncConflict({
    required this.id,
    required this.entityType,
    required this.entityId,
    required this.note,
    required this.receivedAt,
  });

  final int id;
  final String entityType;
  final String entityId;
  final String note;
  final String receivedAt;

  factory MobileSyncConflict.fromJson(Map<String, Object?> json) {
    return MobileSyncConflict(
      id: _asInt(json['id']),
      entityType: _asString(json['entity_type']),
      entityId: _asString(json['entity_id']),
      note: _asString(json['conflict_note']),
      receivedAt: _asString(json['received_at']),
    );
  }

  String get title {
    final type = entityType.isEmpty ? '未知类型' : entityType;
    return entityId.isEmpty ? type : '$type #$entityId';
  }
}

class MobileSyncResult {
  const MobileSyncResult({
    required this.healthy,
    required this.pushed,
    required this.pulled,
    required this.cursor,
    required this.conflicts,
    required this.syncedAt,
    this.warning = '',
  });

  final bool healthy;
  final int pushed;
  final int pulled;
  final int cursor;
  final List<MobileSyncConflict> conflicts;
  final String syncedAt;

  /// 非致命提示（例如服务端报告同步服务不健康、冲突列表读取失败）。
  final String warning;

  String get summary {
    final base = '已同步：推送 $pushed 条，拉取 $pulled 条变更';
    if (conflicts.isNotEmpty) return '$base，${conflicts.length} 条冲突待处理';
    return '$base，无冲突';
  }
}

class MobileSyncException implements Exception {
  const MobileSyncException(this.step, this.message);

  /// status / push / pull
  final String step;
  final String message;

  String get stepLabel {
    switch (step) {
      case 'status':
        return '检查同步状态';
      case 'push':
        return '推送本地变更';
      case 'pull':
        return '拉取云端变更';
      default:
        return '同步';
    }
  }

  @override
  String toString() => '$stepLabel失败：$message';
}

/// 手机端“同步”按钮的真实流程：状态 → 推送 → 拉取（推进游标）→ 冲突。
///
/// App 目前没有离线写入队列，[outbox] 默认为空；推送仍会执行，以便服务端
/// 应用待处理的同步收件箱（`apply_inbox`），推送失败会中止并提示。
class MobileSyncFlow {
  const MobileSyncFlow(this._client);

  final MobileApiClient _client;

  Future<MobileSyncResult> run({
    List<Map<String, Object?>> outbox = const [],
    DateTime Function()? now,
  }) async {
    final session = await _client.loadSession();
    final sinceCursor = session.syncCursor < 0 ? 0 : session.syncCursor;

    final status = await _step('status', _client.syncStatus);
    final statusData = status.data ?? const <String, Object?>{};
    final healthy = statusData['healthy'] != false;

    final push = await _step('push', () => _client.syncPush(outbox));
    final pushData = push.data ?? const <String, Object?>{};
    final pushed = _asInt(pushData['written']);

    final pull = await _step(
      'pull',
      () => _client.syncPull(sinceCursor: sinceCursor),
    );
    final pullData = pull.data ?? const <String, Object?>{};
    final changes = pullData['changes'];
    final pulled = changes is List ? changes.length : 0;
    final pulledCursor = _asInt(pullData['cursor']);
    final cursor = pulledCursor > sinceCursor ? pulledCursor : sinceCursor;

    var conflicts = const <MobileSyncConflict>[];
    var warning = healthy ? '' : '服务端同步服务不健康';
    try {
      final envelope = await _client.syncConflicts();
      final data = envelope.data ?? const <String, Object?>{};
      final items = data['items'];
      if (items is List) {
        conflicts = items
            .whereType<Map>()
            .map(
              (row) => MobileSyncConflict.fromJson(
                row.map((k, v) => MapEntry(k.toString(), v)),
              ),
            )
            .toList(growable: false);
      }
      final err = _asString(data['error']);
      if (!envelope.success || err.isNotEmpty) {
        warning = _join(warning, err.isEmpty ? '冲突列表暂不可用' : err);
      }
    } catch (_) {
      warning = _join(warning, '冲突列表暂不可用');
    }

    final syncedAt = (now ?? DateTime.now)().toIso8601String();
    await _client.saveSyncState(syncCursor: cursor, lastSyncAt: syncedAt);
    return MobileSyncResult(
      healthy: healthy,
      pushed: pushed,
      pulled: pulled,
      cursor: cursor,
      conflicts: conflicts,
      syncedAt: syncedAt,
      warning: warning,
    );
  }

  Future<MobileEnvelope<Map<String, Object?>>> _step(
    String step,
    Future<MobileEnvelope<Map<String, Object?>>> Function() call,
  ) async {
    MobileEnvelope<Map<String, Object?>> envelope;
    try {
      envelope = await call();
    } on MobileApiException catch (error) {
      throw MobileSyncException(
        step,
        error.message.trim().isEmpty
            ? 'HTTP ${error.statusCode}'
            : error.message.trim(),
      );
    } catch (error) {
      throw MobileSyncException(step, _describe(error));
    }
    if (!envelope.success) {
      throw MobileSyncException(
        step,
        envelope.message.trim().isEmpty ? '服务端返回失败' : envelope.message.trim(),
      );
    }
    return envelope;
  }
}

String _describe(Object error) {
  final text = error.toString().replaceFirst('Exception: ', '').trim();
  if (text.contains('SocketException') || text.contains('TimeoutException')) {
    return '网络不可用，请检查网络后重试';
  }
  return text.isEmpty ? '未知错误' : text;
}

String _join(String a, String b) => a.isEmpty ? b : '$a；$b';

int _asInt(Object? value) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  return int.tryParse('${value ?? ''}') ?? 0;
}

String _asString(Object? value) => value == null ? '' : value.toString();
