import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:drift/drift.dart';
import 'package:drift_flutter/drift_flutter.dart';

import '../../models/conversation.dart';

/// 移动端离线存储：消息缓存、会话列表状态、进行中任务与待发送队列。
///
/// 这些数据此前混在会话 JSON 文件里，导致每次会话写入都要重写整份聊天记录。
/// 这里使用 drift（成熟 SQLite 封装）单独建库，会话文件只保留凭证与偏好。
class MobileOfflineStore {
  MobileOfflineStore._(this._db, [this._namespace]);

  final String? _namespace;
  static final _scoped = <String, Future<MobileOfflineStore>>{};

  static const _databaseName = 'xcagi_mobile_cache';
  static const _maxMessagesPerConversation = 80;
  static const _maxQueuedAttempts = 5;

  static MobileOfflineStore? _shared;

  final _MobileOfflineDatabase _db;

  static Future<MobileOfflineStore> open(
      {String namespace = 'legacy', QueryExecutor? executor}) async {
    if (_shared != null) return _shared!; // Explicit test injection only.
    if (!RegExp(r'^[a-zA-Z0-9_-]+$').hasMatch(namespace)) {
      throw ArgumentError('Invalid cache scope');
    }
    return _scoped.putIfAbsent(namespace, () async {
      final store = MobileOfflineStore._(
        _MobileOfflineDatabase(
            executor ?? driftDatabase(name: '${_databaseName}_$namespace')),
        namespace,
      );
      try {
        await store._db.ensureReady();
        return store;
      } catch (_) {
        _scoped.remove(namespace);
        rethrow;
      }
    });
  }

  /// 测试或自定义执行器入口（例如 NativeDatabase.memory()）。
  static MobileOfflineStore forExecutor(QueryExecutor executor) =>
      MobileOfflineStore._(_MobileOfflineDatabase(executor));

  /// 单元测试注入内存库，避免依赖 path_provider 平台通道。
  static void installSharedForTest(MobileOfflineStore store) {
    _shared = store;
  }

  static void resetSharedForTest() {
    _shared = null;
  }

  Future<void> ensureReady() => _db.ensureReady();

  Future<void> close() async {
    await _db.close();
    if (identical(_shared, this)) _shared = null;
    if (_namespace != null) _scoped.remove(_namespace);
  }

  // ── 消息缓存 ────────────────────────────────────────────────

  Future<List<Map<String, Object?>>> cachedMessages(
      String conversationId) async {
    final rows = await _db.customSelect(
      'SELECT * FROM chat_messages WHERE conversation_id = ? '
      'ORDER BY ts ASC, message_id ASC',
      variables: [Variable<String>(conversationId)],
    ).get();
    return rows.map(_messageRow).toList(growable: false);
  }

  Future<void> appendMessage(
    String conversationId,
    Map<String, Object?> row,
  ) async {
    await _db.customUpdate(
      'INSERT OR REPLACE INTO chat_messages '
      '(conversation_id, message_id, role, body, time_text, ts, has_employee_profile, status, turn_id) '
      'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
      variables: [
        Variable<String>(conversationId),
        Variable<String>('${row['id'] ?? ''}'),
        Variable<String>('${row['role'] ?? ChatRole.user.name}'),
        Variable<String>('${row['body'] ?? ''}'),
        Variable<String>('${row['time_text'] ?? ''}'),
        Variable<int>(_asInt(row['ts'])),
        Variable<int>(row['has_employee_profile'] == true ? 1 : 0),
        Variable<String>('${row['status'] ?? ChatDeliveryStatus.sent.name}'),
        Variable<String>('${row['turn_id'] ?? ''}'),
      ],
    );
    await _trimMessages(conversationId);
  }

  Future<void> replaceMessages(
    String conversationId,
    List<Map<String, Object?>> rows,
  ) async {
    await _db.customUpdate(
      'DELETE FROM chat_messages WHERE conversation_id = ?',
      variables: [Variable<String>(conversationId)],
    );
    final tail = rows.length > _maxMessagesPerConversation
        ? rows.sublist(rows.length - _maxMessagesPerConversation)
        : rows;
    for (final row in tail) {
      await appendMessage(conversationId, row);
    }
  }

  Future<void> _trimMessages(String conversationId) async {
    await _db.customUpdate(
      'DELETE FROM chat_messages WHERE conversation_id = ? AND message_id NOT IN ('
      'SELECT message_id FROM chat_messages WHERE conversation_id = ? '
      'ORDER BY ts DESC, message_id DESC LIMIT $_maxMessagesPerConversation)',
      variables: [
        Variable<String>(conversationId),
        Variable<String>(conversationId)
      ],
    );
  }

  Future<void> removeMessageByTimestamp(
    String conversationId,
    int timestampMs,
  ) async {
    await _db.customUpdate(
      'DELETE FROM chat_messages WHERE conversation_id = ? AND ts = ?',
      variables: [Variable<String>(conversationId), Variable<int>(timestampMs)],
    );
  }

  // ── 会话列表状态 ────────────────────────────────────────────

  Future<Map<String, Object?>?> conversationState(String conversationId) async {
    final rows = await _db.customSelect(
      'SELECT preview, timestamp_ms FROM conversation_states WHERE conversation_id = ?',
      variables: [Variable<String>(conversationId)],
    ).get();
    if (rows.isEmpty) return null;
    final data = rows.first.data;
    return {
      'preview': data['preview'] ?? '',
      'timestamp_ms': data['timestamp_ms'] ?? 0,
    };
  }

  /// 一次读取全部会话的最近消息，供消息列表显示预览与时间。
  Future<Map<String, Map<String, Object?>>> latestMessagePreviews() async {
    final rows = await _db
        .customSelect(
          'SELECT conversation_id, body, role, MAX(ts) AS ts FROM chat_messages '
          'GROUP BY conversation_id',
        )
        .get();
    return {
      for (final row in rows)
        if ((row.data['conversation_id'] as String? ?? '').trim().isNotEmpty)
          row.data['conversation_id'] as String: {
            'body': row.data['body'] ?? '',
            'role': row.data['role'] ?? '',
            'ts': row.data['ts'] ?? 0,
          },
    };
  }

  Future<void> saveConversationState(
    String conversationId, {
    required String preview,
    required int timestampMs,
  }) async {
    await _db.customUpdate(
      'INSERT OR REPLACE INTO conversation_states '
      '(conversation_id, preview, timestamp_ms, updated_at) VALUES (?, ?, ?, ?)',
      variables: [
        Variable<String>(conversationId),
        Variable<String>(preview),
        Variable<int>(timestampMs),
        Variable<int>(DateTime.now().millisecondsSinceEpoch),
      ],
    );
  }

  // ── Scoped chat composer restoration ───────────────────────────
  // Draft text is local to this account/server database. Uploaded bytes and
  // reusable upload IDs are deliberately excluded: the remote upload receipt
  // can expire or be revoked while the app is closed.
  static const _draftLifetimeMs = 7 * 24 * 60 * 60 * 1000;
  static const _maxDraftChars = 16000;

  String _draftKey(String conversationId) =>
      'chat-draft:${jsonEncode(conversationId)}';

  Future<void> saveChatDraft(String conversationId, String text,
      {List<String> attachmentNames = const []}) async {
    final id = conversationId.trim();
    if (id.isEmpty) return;
    final safeNames = attachmentNames
        .where((name) => name.trim().isNotEmpty)
        .take(4)
        .map((name) => name.length > 180 ? name.substring(0, 180) : name)
        .toList(growable: false);
    final safeText = text.length > _maxDraftChars
        ? text.substring(0, _maxDraftChars) : text;
    if (safeText.isEmpty && safeNames.isEmpty) {
      await clearChatDraft(id);
      return;
    }
    final data = jsonEncode({
      'text': safeText,
      'attachment_names': safeNames,
      'expires_at': DateTime.now().millisecondsSinceEpoch + _draftLifetimeMs,
    });
    await _db.customUpdate(
      'INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)',
      variables: [Variable<String>(_draftKey(id)), Variable<String>(data)],
    );
  }

  Future<Map<String, Object?>> readChatDraft(String conversationId) async {
    final id = conversationId.trim();
    if (id.isEmpty) return const {};
    final rows = await _db.customSelect(
      'SELECT value FROM meta WHERE key = ?',
      variables: [Variable<String>(_draftKey(id))],
    ).get();
    if (rows.isEmpty) return const {};
    try {
      final raw = jsonDecode('${rows.single.data['value']}');
      if (raw is! Map) throw const FormatException('draft not an object');
      final expiresAt = raw['expires_at'];
      if (expiresAt is! int || expiresAt <= DateTime.now().millisecondsSinceEpoch) {
        await clearChatDraft(id);
        return const {};
      }
      final text = raw['text'];
      final names = raw['attachment_names'];
      return {
        'text': text is String ? text : '',
        'attachment_names': names is List
            ? names.whereType<String>().take(4).toList(growable: false)
            : const <String>[],
      };
    } catch (_) {
      await clearChatDraft(id);
      return const {};
    }
  }

  Future<void> clearChatDraft(String conversationId) async {
    final id = conversationId.trim();
    if (id.isEmpty) return;
    await _db.customUpdate(
      'DELETE FROM meta WHERE key = ?',
      variables: [Variable<String>(_draftKey(id))],
    );
  }

  // Unknown approval outcomes survive process restarts and credential
  // refresh. Never expire them by elapsed time: only the authenticated
  // server's terminal approval state can release a blocked decision.
  String _approvalOutcomeKey(int approvalId) => 'approval-outcome:$approvalId';

  Future<void> markUnknownApprovalOutcome(int approvalId) async {
    if (approvalId <= 0) throw ArgumentError.value(approvalId, 'approvalId');
    await _db.customUpdate(
      'INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)',
      variables: [
        Variable<String>(_approvalOutcomeKey(approvalId)),
        const Variable<String>('unknown'),
      ],
    );
  }

  Future<bool> hasUnknownApprovalOutcome(int approvalId) async {
    if (approvalId <= 0) return true;
    final rows = await _db.customSelect(
      'SELECT value FROM meta WHERE key = ?',
      variables: [Variable<String>(_approvalOutcomeKey(approvalId))],
    ).get();
    return rows.isNotEmpty;
  }

  Future<void> clearUnknownApprovalOutcome(int approvalId) async {
    if (approvalId <= 0) return;
    await _db.customUpdate(
      'DELETE FROM meta WHERE key = ?',
      variables: [Variable<String>(_approvalOutcomeKey(approvalId))],
    );
  }

  // ── 进行中的中继任务 ────────────────────────────────────────

  Future<void> saveTurnDispatch(String conversationId, String turnId,
      Map<String, Object?> dispatch) async {
    await _db.customUpdate('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)',
        variables: [Variable<String>('turn-dispatch:${jsonEncode([conversationId, turnId])}'),
          Variable<String>(jsonEncode(dispatch))]);
  }

  Future<Map<String, Object?>> turnDispatch(String conversationId, String turnId) async {
    final rows = await _db.customSelect('SELECT value FROM meta WHERE key = ?',
        variables: [Variable<String>('turn-dispatch:${jsonEncode([conversationId, turnId])}')]).get();
    if (rows.isEmpty) return const {};
    final value = jsonDecode('${rows.first.data['value']}');
    return value is Map ? Map<String, Object?>.from(value) : const {};
  }

  Future<String> inflightTaskId(String conversationId) async {
    final rows = await _db.customSelect(
      'SELECT task_id FROM inflight_tasks WHERE conversation_id = ?',
      variables: [Variable<String>(conversationId)],
    ).get();
    if (rows.isEmpty) return '';
    return (rows.first.data['task_id'] as String? ?? '').trim();
  }

  Future<void> setInflightTaskId(String conversationId, String taskId) async {
    if (taskId.trim().isEmpty) {
      await _db.customUpdate(
        'DELETE FROM inflight_tasks WHERE conversation_id = ?',
        variables: [Variable<String>(conversationId)],
      );
      return;
    }
    await _db.customUpdate(
      'INSERT OR REPLACE INTO inflight_tasks (conversation_id, task_id, updated_at) '
      'VALUES (?, ?, ?)',
      variables: [
        Variable<String>(conversationId),
        Variable<String>(taskId.trim()),
        Variable<int>(DateTime.now().millisecondsSinceEpoch),
      ],
    );
  }

  // ── 待发送队列 ──────────────────────────────────────────────

  Future<int> enqueueMessage({
    required String conversationId,
    required ConversationType conversationType,
    required String title,
    required String body,
    required int authGeneration,
    String idempotencyKey = '',
    bool requiresReconciliation = false,
  }) async {
    final text = body.trim();
    if (text.isEmpty) return 0;
    final key = idempotencyKey.trim();
    final existing = await _db.customSelect(
      'SELECT id FROM outbox_messages WHERE conversation_id = ? AND ${key.isEmpty ? 'body' : 'idempotency_key'} = ? '
      "AND status IN ('pending', 'sending', 'unknown') LIMIT 1",
      variables: [Variable<String>(conversationId), Variable<String>(key.isEmpty ? text : key)],
    ).get();
    if (existing.isNotEmpty) {
      final id = _asInt(existing.first.data['id']);
      if (requiresReconciliation) {
        // The request might have executed before its response was lost.
        await _db.customUpdate(
          "UPDATE outbox_messages SET status = 'unknown' WHERE id = ? AND status = 'pending'",
          variables: [Variable<int>(id)],
        );
      }
      return id;
    }
    final now = DateTime.now().millisecondsSinceEpoch;
    return _db.customInsert(
      'INSERT INTO outbox_messages '
      '(conversation_id, conversation_type, title, body, auth_generation, idempotency_key, status, attempts, '
      'last_error, created_at, updated_at) '
      "VALUES (?, ?, ?, ?, ?, ?, ?, 0, '', ?, ?)",
      variables: [
        Variable<String>(conversationId),
        Variable<String>(conversationType.name),
        Variable<String>(title),
        Variable<String>(text),
        Variable<int>(authGeneration),
        Variable<String>(idempotencyKey.trim().isEmpty
            ? 'mobile-outbox-$now-${Random.secure().nextInt(1 << 32).toRadixString(16)}'
            : idempotencyKey.trim()),
        Variable<String>(requiresReconciliation ? 'unknown' : 'pending'),
        Variable<int>(now),
        Variable<int>(now),
      ],
    );
  }

  Future<List<PendingOutboxMessage>> pendingMessages({int limit = 5}) async {
    final rows = await _db.customSelect(
      "SELECT * FROM outbox_messages WHERE status IN ('pending', 'sending', 'unknown') ORDER BY updated_at ASC, id ASC LIMIT ?",
      variables: [Variable<int>(limit)],
    ).get();
    return rows.map((row) {
      final data = row.data;
      return PendingOutboxMessage(
        id: _asInt(data['id']),
        conversationId: '${data['conversation_id'] ?? ''}',
        conversationType: _conversationType(data['conversation_type']),
        title: '${data['title'] ?? ''}',
        body: '${data['body'] ?? ''}',
        authGeneration: _asInt(data['auth_generation']),
        attempts: _asInt(data['attempts']),
        idempotencyKey: '${data['idempotency_key'] ?? ''}',
        requiresReconciliation: data['status'] != 'pending',
      );
    }).toList(growable: false);
  }

  Future<int> pendingMessageCount() async {
    final rows = await _db
        .customSelect(
          "SELECT COUNT(*) AS total FROM outbox_messages WHERE status IN ('pending', 'sending', 'unknown')",
        )
        .get();
    return _asInt(rows.first.data['total']);
  }

  Future<void> markSending(int id) => _updateOutbox(id, "status = 'sending'");

  Future<void> markSent(int id) async {
    await _db.customUpdate(
      'DELETE FROM outbox_messages WHERE id = ?',
      variables: [Variable<int>(id)],
    );
  }

  Future<void> markFailed(int id, String error, {bool requiresReconciliation = false, bool terminal = false}) async {
    await _db.customUpdate(
      'UPDATE outbox_messages SET attempts = attempts + 1, '
      "status = CASE WHEN ? = 1 THEN 'failed' WHEN ? = 1 THEN 'unknown' WHEN attempts + 1 >= $_maxQueuedAttempts THEN 'failed' ELSE 'pending' END, "
      'last_error = ?, updated_at = ? WHERE id = ?',
      variables: [
        Variable<int>(terminal ? 1 : 0),
        Variable<int>(requiresReconciliation ? 1 : 0),
        Variable<String>(error.length > 500 ? error.substring(0, 500) : error),
        Variable<int>(DateTime.now().millisecondsSinceEpoch),
        Variable<int>(id),
      ],
    );
  }

  Future<void> removePendingByBody(String conversationId, String body) async {
    await _db.customUpdate(
      "DELETE FROM outbox_messages WHERE conversation_id = ? AND body = ? AND status IN ('pending', 'sending', 'unknown')",
      variables: [
        Variable<String>(conversationId),
        Variable<String>(body.trim())
      ],
    );
  }

  Future<void> removePendingByTurn(String conversationId, String turnId) async {
    if (turnId.isEmpty) return;
    await _db.customUpdate('DELETE FROM outbox_messages WHERE conversation_id = ? AND idempotency_key = ?',
        variables: [Variable<String>(conversationId), Variable<String>(turnId)]);
  }

  Future<void> _updateOutbox(int id, String assignment) async {
    await _db.customUpdate(
      'UPDATE outbox_messages SET $assignment, updated_at = ? WHERE id = ?',
      variables: [
        Variable<int>(DateTime.now().millisecondsSinceEpoch),
        Variable<int>(id)
      ],
    );
  }

  // ── 映射与类型转换 ──────────────────────────────────────────

  Map<String, Object?> _messageRow(QueryRow row) {
    final data = row.data;
    return {
      'id': data['message_id'],
      'conversation_id': data['conversation_id'],
      'role': data['role'],
      'body': data['body'],
      'time_text': data['time_text'],
      'ts': data['ts'],
      'has_employee_profile': _asInt(data['has_employee_profile']) == 1,
      'status': data['status'],
      'turn_id': data['turn_id'],
    };
  }

  ConversationType _conversationType(Object? raw) {
    final name = '${raw ?? ''}';
    for (final type in ConversationType.values) {
      if (type.name == name) return type;
    }
    return ConversationType.pinnedAssistant;
  }

  int _asInt(Object? value) {
    if (value is int) return value;
    if (value is num) return value.toInt();
    return int.tryParse('${value ?? ''}') ?? 0;
  }
}

class PendingOutboxMessage {
  const PendingOutboxMessage({
    required this.id,
    required this.conversationId,
    required this.conversationType,
    required this.title,
    required this.body,
    required this.authGeneration,
    required this.attempts,
    this.idempotencyKey = '',
    this.requiresReconciliation = false,
  });

  final int id;
  final String conversationId;
  final ConversationType conversationType;
  final String title;
  final String body;
  final int authGeneration;
  final int attempts;
  final String idempotencyKey;
  final bool requiresReconciliation;
}

class _MobileOfflineDatabase extends GeneratedDatabase {
  _MobileOfflineDatabase(super.executor);

  @override
  Iterable<TableInfo<Table, dynamic>> get allTables => const [];

  @override
  int get schemaVersion => 2;

  @override
  MigrationStrategy get migration => MigrationStrategy(
        onCreate: (m) async {
          await m.database.customStatement(
            'CREATE TABLE IF NOT EXISTS chat_messages ('
            'conversation_id TEXT NOT NULL, '
            'message_id TEXT NOT NULL, '
            'role TEXT NOT NULL, '
            'body TEXT NOT NULL, '
            'time_text TEXT NOT NULL, '
            'ts INTEGER NOT NULL, '
            'has_employee_profile INTEGER NOT NULL DEFAULT 0, '
            'status TEXT NOT NULL, '
            "turn_id TEXT NOT NULL DEFAULT '', "
            'PRIMARY KEY (conversation_id, message_id))',
          );
          await m.database.customStatement(
            'CREATE INDEX IF NOT EXISTS idx_chat_messages_conv_ts '
            'ON chat_messages (conversation_id, ts)',
          );
          await m.database.customStatement(
            'CREATE TABLE IF NOT EXISTS conversation_states ('
            'conversation_id TEXT PRIMARY KEY, '
            "preview TEXT NOT NULL DEFAULT '', "
            'timestamp_ms INTEGER NOT NULL DEFAULT 0, '
            'updated_at INTEGER NOT NULL)',
          );
          await m.database.customStatement(
            'CREATE TABLE IF NOT EXISTS inflight_tasks ('
            'conversation_id TEXT PRIMARY KEY, '
            'task_id TEXT NOT NULL, '
            'updated_at INTEGER NOT NULL)',
          );
          await m.database.customStatement(
            'CREATE TABLE IF NOT EXISTS outbox_messages ('
            'id INTEGER PRIMARY KEY AUTOINCREMENT, '
            'conversation_id TEXT NOT NULL, '
            'conversation_type TEXT NOT NULL, '
            'title TEXT NOT NULL, '
            'body TEXT NOT NULL, '
            'auth_generation INTEGER NOT NULL DEFAULT 0, '
            "idempotency_key TEXT NOT NULL DEFAULT '', "
            "status TEXT NOT NULL DEFAULT 'pending', "
            'attempts INTEGER NOT NULL DEFAULT 0, '
            "last_error TEXT NOT NULL DEFAULT '', "
            'created_at INTEGER NOT NULL, '
            'updated_at INTEGER NOT NULL)',
          );
          await m.database.customStatement(
            'CREATE INDEX IF NOT EXISTS idx_outbox_status '
            'ON outbox_messages (status, created_at)',
          );
          await m.database.customStatement(
            'CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)',
          );
        },
        onUpgrade: (m, from, to) async {
          if (from < 2) {
            await m.database.customStatement(
                "ALTER TABLE chat_messages ADD COLUMN turn_id TEXT NOT NULL DEFAULT ''");
            await m.database.customStatement(
                "ALTER TABLE outbox_messages ADD COLUMN idempotency_key TEXT NOT NULL DEFAULT ''");
            await m.database.customStatement(
                "UPDATE outbox_messages SET idempotency_key = 'mobile-legacy-' || lower(hex(randomblob(16))) WHERE idempotency_key = ''");
            await m.database.customStatement(
                "UPDATE outbox_messages SET status = 'unknown' WHERE status = 'sending' OR (status = 'pending' AND attempts > 0)");
          }
        },
      );

  Future<void> ensureReady() async {
    await customSelect('SELECT 1').get();
  }
}

/// 判断一次发送失败是否属于「离线/网络不可达」，用于决定是否转入待发送队列。
bool isOfflineError(Object error) {
  if (error is SocketException ||
      error is HttpException ||
      error is TimeoutException) {
    return true;
  }
  final text = error.toString().toLowerCase();
  return text.contains('failed host lookup') ||
      text.contains('connection refused') ||
      text.contains('connection closed') ||
      text.contains('connection reset') ||
      text.contains('network is unreachable') ||
      text.contains('no route to host') ||
      text.contains('no address associated') ||
      text.contains('name or service not known') ||
      text.contains('temporary failure in name resolution') ||
      text.contains('socketexception') ||
      text.contains('os error') ||
      text.contains('timed out') ||
      text.contains('请求超时');
}
