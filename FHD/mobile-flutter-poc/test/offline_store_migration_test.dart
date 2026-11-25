import 'dart:io';

import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/data/offline/mobile_offline_store.dart';
import 'package:xcagi_flutter_poc/src/models/conversation.dart';

void main() {
  final fixedNow = DateTime.utc(2026, 11, 25, 12);

  Map<String, Object?> message(String id, int timestamp, String status) => {
        'id': id,
        'conversation_id': 'c1',
        'role': 'assistant',
        'body': id,
        'time_text': 'earlier',
        'ts': timestamp,
        'status': status,
        'turn_id': status == 'sent' ? '' : 'original-turn',
      };

  Future<void> verifyLegacyUpgrade({bool interrupted = false}) async {
    final dir = await Directory.systemTemp.createTemp('xcagi-mobile-v2-');
    final dbFile = File('${dir.path}/cache.sqlite');
    final old = MobileOfflineStore.forExecutor(
      NativeDatabase(dbFile, setup: (sqlite) {
        final cachedColumn =
            interrupted ? ', cached_at INTEGER NOT NULL DEFAULT 0' : '';
        sqlite.execute(
            'CREATE TABLE chat_messages (conversation_id TEXT NOT NULL, '
            'message_id TEXT NOT NULL, role TEXT NOT NULL, '
            'body TEXT NOT NULL, time_text TEXT NOT NULL, ts INTEGER NOT NULL, '
            'has_employee_profile INTEGER NOT NULL DEFAULT 0, '
            'status TEXT NOT NULL, '
            "turn_id TEXT NOT NULL DEFAULT ''$cachedColumn, "
            'PRIMARY KEY (conversation_id, message_id))');
        sqlite.execute(
            'CREATE TABLE conversation_states (conversation_id TEXT PRIMARY KEY, '
            "preview TEXT NOT NULL DEFAULT '', "
            'timestamp_ms INTEGER NOT NULL DEFAULT 0, '
            'updated_at INTEGER NOT NULL)');
        sqlite.execute(
            'CREATE TABLE inflight_tasks (conversation_id TEXT PRIMARY KEY, '
            'task_id TEXT NOT NULL, updated_at INTEGER NOT NULL)');
        sqlite.execute(
            'CREATE TABLE outbox_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, '
            'conversation_id TEXT NOT NULL, conversation_type TEXT NOT NULL, '
            'title TEXT NOT NULL, body TEXT NOT NULL, '
            'auth_generation INTEGER NOT NULL DEFAULT 0, '
            "idempotency_key TEXT NOT NULL DEFAULT '', "
            "status TEXT NOT NULL DEFAULT 'pending', "
            'attempts INTEGER NOT NULL DEFAULT 0, '
            "last_error TEXT NOT NULL DEFAULT '', "
            'created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)');
        sqlite.execute(
            'CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)');
        sqlite.execute(
            "INSERT INTO chat_messages VALUES "
            "('c1', 'sent-legacy', 'assistant', 'old display', 'earlier', "
            "1, 1, 'sent', 'old-turn'${interrupted ? ', 0' : ''})");
        sqlite.execute(
            "INSERT INTO chat_messages VALUES "
            "('c1', 'pending-legacy', 'assistant', 'unknown result', 'earlier', "
            "2, 1, 'pending', 'original-turn'${interrupted ? ', 0' : ''})");
        sqlite.execute(
            "INSERT INTO conversation_states VALUES ('c1', 'stale preview', 2, 1)");
        sqlite.execute(
            "INSERT INTO inflight_tasks VALUES ('c1', 'original-task', 1)");
        sqlite.execute(
            "INSERT INTO outbox_messages VALUES "
            "(23, 'c1', 'pinnedAssistant', '小C', 'write operation', 5, "
            "'original-turn', 'sending', 1, '', 1, 1)");
        sqlite.execute("PRAGMA user_version = 2");
      }),
      clock: () => fixedNow,
    );
    try {
      await old.ensureReady();
      // v2 confirmed display data has no trustworthy acquisition timestamp.
      final visible = await old.cachedMessages('c1');
      expect(visible.map((row) => row['id']), ['pending-legacy']);
      expect(await old.conversationState('c1'), isNull);
      expect(await old.latestMessagePreviews(), isEmpty);
      expect(await old.inflightTaskId('c1'), 'original-task');
      final outbox = (await old.pendingMessages()).single;
      expect(outbox.id, 23);
      expect(outbox.idempotencyKey, 'original-turn');
      expect(outbox.requiresReconciliation, isTrue);
      await old.markSending(23);
      expect((await old.pendingMessages()).single.requiresReconciliation, isTrue);
      await old.appendMessage('c1', message('fresh-v3', 3, 'sent'));
      expect((await old.cachedMessages('c1')).length, 2);
    } finally {
      await old.close();
    }
    final restored = MobileOfflineStore.forExecutor(
      NativeDatabase(dbFile), clock: () => fixedNow);
    try {
      await restored.ensureReady();
      expect((await restored.cachedMessages('c1'))
          .map((row) => row['id']), ['pending-legacy', 'fresh-v3']);
      expect(await restored.inflightTaskId('c1'), 'original-task');
      expect((await restored.pendingMessages()).single.idempotencyKey,
          'original-turn');
      expect((await restored.pendingMessages()).single.requiresReconciliation,
          isTrue);
    } finally {
      await restored.close();
      await dir.delete(recursive: true);
    }
  }

  test('file-backed SQLite v2 migrates to v3 without deleting original work',
      () async {
    await verifyLegacyUpgrade();
  });

  test('v2 partial column migration can be resumed safely', () async {
    await verifyLegacyUpgrade(interrupted: true);
  });

  test('TTL, replacement and trim cannot erase unresolved tasks', () async {
    final dir = await Directory.systemTemp.createTemp('xcagi-mobile-ttl-');
    final file = File('${dir.path}/cache.sqlite');
    var now = fixedNow;
    final store = MobileOfflineStore.forExecutor(
        NativeDatabase(file), clock: () => now);
    try {
      await store.ensureReady();
      await store.appendMessage('c1', message('confirmed', 1, 'sent'));
      await store.appendMessage('c1', message('unresolved', 2, 'pending'));
      await store.saveConversationState('c1',
          preview: 'cached preview', timestampMs: 2);
      await store.setInflightTaskId('c1', 'original-task');
      final outboxId = await store.enqueueMessage(
        conversationId: 'c1',
        conversationType: ConversationType.pinnedAssistant,
        title: '小C',
        body: 'write operation',
        authGeneration: 1,
        idempotencyKey: 'original-turn',
        requiresReconciliation: true,
      );
      now = now.add(const Duration(hours: 25));
      expect((await store.cachedMessages('c1')).single['id'], 'unresolved');
      expect(await store.conversationState('c1'), isNull);
      expect(await store.latestMessagePreviews(), isEmpty);
      await store.replaceMessages('c1', [
        message('unresolved', 2, 'sent'),
        message('remote-confirmed', 3, 'sent'),
      ]);
      expect((await store.cachedMessages('c1'))
          .firstWhere((row) => row['id'] == 'unresolved')['status'], 'pending');
      for (var i = 0; i < 90; i++) {
        await store.appendMessage('c1', message('remote-$i', i + 10, 'sent'));
      }
      expect((await store.cachedMessages('c1'))
          .where((row) => row['id'] == 'unresolved'), hasLength(1));
      await store.removeMessageByTimestamp('c1', 2);
      expect((await store.cachedMessages('c1'))
          .where((row) => row['id'] == 'unresolved'), hasLength(1));
      expect(await store.inflightTaskId('c1'), 'original-task');
      expect((await store.pendingMessages()).single.id, outboxId);
    } finally {
      await store.close();
    }
    now = now.add(const Duration(hours: 25));
    final restored = MobileOfflineStore.forExecutor(
        NativeDatabase(file), clock: () => now);
    try {
      await restored.ensureReady();
      expect((await restored.cachedMessages('c1')).single['id'], 'unresolved');
      expect(await restored.latestMessagePreviews(), isEmpty);
      expect(await restored.inflightTaskId('c1'), 'original-task');
      final pending = (await restored.pendingMessages()).single;
      expect(pending.idempotencyKey, 'original-turn');
      expect(pending.requiresReconciliation, isTrue);
    } finally {
      await restored.close();
      await dir.delete(recursive: true);
    }
  });

  test('concurrent reconnect queueing preserves a single idempotent row',
      () async {
    final store = MobileOfflineStore.forExecutor(NativeDatabase.memory());
    try {
      await store.ensureReady();
      final ids = await Future.wait(List.generate(
          4,
          (_) => store.enqueueMessage(
              conversationId: 'c1',
              conversationType: ConversationType.pinnedAssistant,
              title: '小C',
              body: 'write operation',
              authGeneration: 1,
              idempotencyKey: 'original-turn')));
      expect(ids.toSet(), hasLength(1));
      expect(await store.pendingMessageCount(), 1);
      await store.markReconciliationRequired(ids.first);
      await store.markSending(ids.first);
      final entry = (await store.pendingMessages()).single;
      expect(entry.requiresReconciliation, isTrue);
      expect(entry.idempotencyKey, 'original-turn');
      await store.removePendingByBody('c1', 'write operation');
      expect(await store.pendingMessageCount(), 1);
    } finally {
      await store.close();
    }
  });
}
