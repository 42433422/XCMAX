import 'dart:io';

import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/data/offline/mobile_offline_store.dart';
import 'package:xcagi_flutter_poc/src/models/conversation.dart';

void main() {
  late MobileOfflineStore store;

  setUp(() async {
    store = MobileOfflineStore.forExecutor(NativeDatabase.memory());
    await store.ensureReady();
  });

  tearDown(() async {
    await store.close();
  });

  Map<String, Object?> message(int ts, String body, {String role = 'user'}) => {
        'id': 'm-$ts',
        'conversation_id': 'c1',
        'role': role,
        'body': body,
        'time_text': 't$ts',
        'ts': ts,
        'has_employee_profile': role == 'assistant',
        'status': 'sent',
      };

  test('separate account/backend scopes never share messages or queued sends',
      () async {
    final first = await MobileOfflineStore.open(
        namespace: 'userA_backend1', executor: NativeDatabase.memory());
    final second = await MobileOfflineStore.open(
        namespace: 'userB_backend1', executor: NativeDatabase.memory());
    final otherBackend = await MobileOfflineStore.open(
        namespace: 'userA_backend2', executor: NativeDatabase.memory());
    try {
      await first.appendMessage('c1', message(1, 'private'));
      await first.enqueueMessage(
          conversationId: 'c1',
          conversationType: ConversationType.pinnedAssistant,
          title: '小C',
          body: 'private pending',
          authGeneration: 0);
      expect(await first.pendingMessageCount(), 1);
      expect(await second.cachedMessages('c1'), isEmpty);
      expect(await otherBackend.cachedMessages('c1'), isEmpty);
      expect((await first.cachedMessages('c1')).single['body'], 'private');
      expect(await second.pendingMessageCount(), 0);
      expect(await otherBackend.pendingMessageCount(), 0);
    } finally {
      await first.close();
      await second.close();
      await otherBackend.close();
    }
  });

  test('消息按时间顺序读取并返回旧缓存结构', () async {
    await store.appendMessage('c1', message(2, '第二条'));
    await store.appendMessage('c1', message(1, '第一条'));

    final rows = await store.cachedMessages('c1');

    expect(rows.map((row) => row['body']), ['第一条', '第二条']);
    expect(rows.first['id'], 'm-1');
    expect(rows.first['conversation_id'], 'c1');
    expect(rows.first['has_employee_profile'], isFalse);
  });

  test('每个会话只保留最近 80 条消息', () async {
    for (var i = 0; i < 85; i++) {
      await store.appendMessage('c1', message(i, 'm$i'));
    }

    final rows = await store.cachedMessages('c1');
    expect(rows.length, 80);
    expect(rows.first['body'], 'm5');
    expect(rows.last['body'], 'm84');
  });

  test('删除指定时间戳的消息', () async {
    await store.appendMessage('c1', message(1, 'a'));
    await store.appendMessage('c1', message(2, 'b'));

    await store.removeMessageByTimestamp('c1', 1);

    final rows = await store.cachedMessages('c1');
    expect(rows.map((row) => row['body']), ['b']);
  });

  test('会话列表状态按会话覆盖写入', () async {
    await store.saveConversationState('c1', preview: '旧预览', timestampMs: 1);
    await store.saveConversationState('c1', preview: '新预览', timestampMs: 2);

    final state = await store.conversationState('c1');

    expect(state?['preview'], '新预览');
    expect(state?['timestamp_ms'], 2);
  });

  test('进行中任务可写入与清除', () async {
    await store.setInflightTaskId('c1', 'task-1');
    expect(await store.inflightTaskId('c1'), 'task-1');

    await store.setInflightTaskId('c1', '');
    expect(await store.inflightTaskId('c1'), isEmpty);
  });

  test('待发送队列去重、计数与成功后删除', () async {
    final first = await store.enqueueMessage(
      conversationId: 'c1',
      conversationType: ConversationType.pinnedAssistant,
      title: '小 C',
      body: '离线消息',
      authGeneration: 3,
    );
    final duplicate = await store.enqueueMessage(
      conversationId: 'c1',
      conversationType: ConversationType.pinnedAssistant,
      title: '小 C',
      body: '离线消息',
      authGeneration: 3,
    );

    expect(first, greaterThan(0));
    expect(duplicate, first);
    expect(await store.pendingMessageCount(), 1);

    final pending = await store.pendingMessages();
    expect(pending.single.body, '离线消息');
    expect(pending.single.authGeneration, 3);
    expect(pending.single.conversationType, ConversationType.pinnedAssistant);

    await store.markSent(first);
    expect(await store.pendingMessageCount(), 0);
  });

  test('ambiguous transport outcome remains reconciliation-only across restarts', () async {
    final id = await store.enqueueMessage(
      conversationId: 'c1',
      conversationType: ConversationType.pinnedAssistant,
      title: '小C',
      body: '执行库存写入',
      authGeneration: 1,
      idempotencyKey: 'stable-turn',
      requiresReconciliation: true,
    );
    final queued = await store.pendingMessages();
    expect(queued.single.id, id);
    expect(queued.single.idempotencyKey, 'stable-turn');
    expect(queued.single.requiresReconciliation, isTrue);

    // A later enqueue attempt must not downgrade 'unknown' to sendable.
    final duplicate = await store.enqueueMessage(
      conversationId: 'c1',
      conversationType: ConversationType.pinnedAssistant,
      title: '小C',
      body: '执行库存写入',
      authGeneration: 1,
      idempotencyKey: 'stable-turn',
    );
    expect(duplicate, id);
    expect((await store.pendingMessages()).single.requiresReconciliation, isTrue);

    await store.markSending(id);
    // Sending interrupted by process exit must also require GET-only resume.
    expect((await store.pendingMessages()).single.requiresReconciliation, isTrue);
  });

  test('already queued unsent draft becomes reconciliation-only on ambiguity',
      () async {
    final id = await store.enqueueMessage(
      conversationId: 'c1',
      conversationType: ConversationType.pinnedAssistant,
      title: '小C',
      body: '执行任务',
      authGeneration: 1,
      idempotencyKey: 'turn-2',
    );
    expect((await store.pendingMessages()).single.requiresReconciliation, isFalse);
    final duplicate = await store.enqueueMessage(
      conversationId: 'c1',
      conversationType: ConversationType.pinnedAssistant,
      title: '小C',
      body: '执行任务',
      authGeneration: 1,
      idempotencyKey: 'turn-2',
      requiresReconciliation: true,
    );
    expect(duplicate, id);
    expect((await store.pendingMessages()).single.requiresReconciliation, isTrue);
  });

  test('重试达到上限后标记为 failed，不再进入待发送列表', () async {
    final id = await store.enqueueMessage(
      conversationId: 'c1',
      conversationType: ConversationType.pinnedAssistant,
      title: '聊天',
      body: '重试消息',
      authGeneration: 1,
    );

    for (var i = 0; i < 5; i++) {
      await store.markFailed(id, 'network down');
    }

    expect(await store.pendingMessageCount(), 0);
    expect(await store.pendingMessages(), isEmpty);
  });

  test('outbox preserves the original turn across a crash and read-back attempts', () async {
    final id = await store.enqueueMessage(conversationId: 'c1',
        conversationType: ConversationType.pinnedAssistant, title: '小C',
        body: '写入订单', authGeneration: 1, idempotencyKey: 'original-turn');
    await store.markSending(id);
    var entry = (await store.pendingMessages()).single;
    expect(entry.idempotencyKey, 'original-turn');
    expect(entry.requiresReconciliation, isTrue);
    await store.markFailed(id, '原回执暂不可读', requiresReconciliation: true);
    entry = (await store.pendingMessages()).single;
    expect(entry.idempotencyKey, 'original-turn');
    expect(entry.attempts, 1);
    expect(entry.requiresReconciliation, isTrue);
    for (var i = 0; i < 6; i++) {
      await store.markFailed(id, '回读暂不可达', requiresReconciliation: true);
    }
    expect((await store.pendingMessages()).single.requiresReconciliation, isTrue);
  });

  test('an undispatched connection failure may retry the same original key', () async {
    final id = await store.enqueueMessage(conversationId: 'c1',
        conversationType: ConversationType.pinnedAssistant, title: '小C',
        body: '未建立连接', authGeneration: 1, idempotencyKey: 'not-sent');
    await store.markSending(id);
    await store.markFailed(id, 'connection refused');
    final entry = (await store.pendingMessages()).single;
    expect(entry.requiresReconciliation, isFalse);
    expect(entry.idempotencyKey, 'not-sent');
  });

  test('cached pending receipt retains its turn across restart and update', () async {
    await store.appendMessage('c1', {...message(1, '回执待核对', role: 'assistant'),
      'turn_id': 'original-turn', 'status': 'pending'});
    final cached = (await store.cachedMessages('c1')).single;
    expect(cached['turn_id'], 'original-turn');
    expect(cached['status'], 'pending');
  });

  test('dispatch identity is stored separately for every original turn', () async {
    await store.saveTurnDispatch('pinned:codex', 'first', {
      'client_request_id': 'first', 'relay_id': 'original-relay',
      'base_url': 'https://original.example/', 'connection_base': 'https://original.example/',
      'scope': 'original-account', 'channel': 'relay',
    });
    await store.saveTurnDispatch('pinned:codex', 'second', {'client_request_id': 'second'});
    final original = await store.turnDispatch('pinned:codex', 'first');
    expect(original['relay_id'], 'original-relay');
    expect(original['base_url'], 'https://original.example/');
    expect(original['client_request_id'], 'first');
    expect(await store.turnDispatch('other-conversation', 'first'), isEmpty);
  });

  test('手动重发后可按内容清除排队记录', () async {
    await store.enqueueMessage(
      conversationId: 'c1',
      conversationType: ConversationType.pinnedAssistant,
      title: '小 C',
      body: '重复内容',
      authGeneration: 1,
    );

    await store.removePendingByBody('c1', '重复内容');

    expect(await store.pendingMessageCount(), 0);
  });

  test('离线错误判定覆盖常见网络异常', () {
    expect(isOfflineError(const SocketException('failed')), isTrue);
    expect(isOfflineError(Exception('Failed host lookup: xiu-ci.com')), isTrue);
    expect(isOfflineError(Exception('connection refused')), isTrue);
    expect(isOfflineError(Exception('服务器返回 500')), isFalse);
  });
}
