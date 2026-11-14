import 'dart:io';

import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
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

  test('首次启动从会话 JSON 迁移缓存且只迁移一次', () async {
    const session = MobileSessionData(
      cachedChatMessages: {
        'c1': [
          {
            'id': 'legacy-1',
            'conversation_id': 'c1',
            'role': 'user',
            'body': '历史消息',
            'time_text': 't',
            'ts': 10,
            'has_employee_profile': false,
            'status': 'sent',
          },
        ],
      },
      conversationListStates: {
        'c1': {'preview': '历史预览', 'timestamp_ms': 10},
      },
      inflightRelayTasks: {'c1': 'task-legacy'},
    );

    expect(await store.importFromSession(session), isTrue);
    expect((await store.cachedMessages('c1')).length, 1);
    expect((await store.conversationState('c1'))?['preview'], '历史预览');
    expect(await store.inflightTaskId('c1'), 'task-legacy');

    expect(await store.importFromSession(session), isFalse);
  });

  test('离线错误判定覆盖常见网络异常', () {
    expect(isOfflineError(const SocketException('failed')), isTrue);
    expect(isOfflineError(Exception('Failed host lookup: xiu-ci.com')), isTrue);
    expect(isOfflineError(Exception('connection refused')), isTrue);
    expect(isOfflineError(Exception('服务器返回 500')), isFalse);
  });
}
