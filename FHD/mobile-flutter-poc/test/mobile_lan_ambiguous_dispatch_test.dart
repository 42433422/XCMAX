import 'dart:io';

import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/data/offline/mobile_offline_store.dart';
import 'package:xcagi_flutter_poc/src/models/conversation.dart';

class _SocketAfterSendApi extends MobileApiClient {
  _SocketAfterSendApi()
      : super(
          sessionStore: MemoryMobileSessionStore(
            const MobileSessionData(
              accessToken: 'owned',
              userId: 42,
              serverMode: 'lan',
              localBaseUrl: 'http://127.0.0.1:59999/',
            ),
          ),
        );

  int attemptedPosts = 0;
  int receiptReads = 0;
  bool receiptKnown = true;
  String lastTurn = '';

  @override
  Future<String> streamSuperEmployeeMessage(
    String tool,
    String body, {
    String baseUrl = '',
    String idempotencyKey = '',
    String conversationId = '',
    void Function(String token)? onToken,
    void Function(String status)? onStatus,
    bool Function()? isCancelled,
  }) async {
    attemptedPosts++;
    lastTurn = idempotencyKey;
    throw const SocketException('socket dropped after request may be accepted');
  }

  @override
  Future<String> readSuperEmployeeTurn({
    required String tool,
    required String conversationId,
    required String idempotencyKey,
    required String baseUrl,
    required String expectedConnectionBase,
  }) async {
    receiptReads++;
    expect(tool, 'Codex');
    expect(conversationId, 'pinned:codex');
    expect(idempotencyKey, 'stable-original-turn');
    expect(idempotencyKey, lastTurn);
    if (!receiptKnown) {
      throw const MobileApiException(
        statusCode: 409,
        errorCode: 'CHAT_RECEIPT_PENDING',
        message: '原任务结果待核对',
        body: {},
      );
    }
    return '原任务结果已核验';
  }
}

void main() {
  const conversation = ConversationItem(
    id: 'pinned:codex',
    type: ConversationType.pinnedCodex,
    title: 'Codex',
    subtitle: '',
    timestampText: '',
  );
  late MobileOfflineStore store;
  late _SocketAfterSendApi client;
  late MobileRepository repository;

  setUp(() async {
    store = MobileOfflineStore.forExecutor(NativeDatabase.memory());
    await store.ensureReady();
    MobileOfflineStore.installSharedForTest(store);
    client = _SocketAfterSendApi();
    repository = MobileRepository(client: client);
  });

  tearDown(() async {
    await repository.dispose();
    client.dispose();
    MobileOfflineStore.resetSharedForTest();
    await store.close();
  });

  test('socket failure reconciles original LAN turn, never dispatches relay', () async {
    final reply = await repository.streamMessage(
      conversation: conversation,
      body: '写入企业库存',
      idempotencyKey: 'stable-original-turn',
    );
    expect(reply, '原任务结果已核验');
    expect(client.attemptedPosts, 1);
    expect(client.receiptReads, 1);
  });

  test('unknown LAN receipt stays pending and never falls through to relay', () async {
    client.receiptKnown = false;
    await expectLater(
      repository.streamMessage(
        conversation: conversation,
        body: '写入企业库存',
        idempotencyKey: 'stable-original-turn',
      ),
      throwsA(isA<MobileApiException>()
          .having((error) => error.errorCode, 'code', 'CHAT_RECEIPT_PENDING')),
    );
    expect(client.attemptedPosts, 1);
    expect(client.receiptReads, 1);
    final originalDispatch = await store.turnDispatch(
      'pinned:codex', 'stable-original-turn');
    expect(originalDispatch['channel'], 'super');
    expect(originalDispatch['base_url'], 'http://127.0.0.1:59999/');
  });

  test('direct retry of an existing turn only reads the original receipt', () async {
    client.receiptKnown = false;
    await expectLater(
      repository.streamMessage(
        conversation: conversation,
        body: '写入企业库存',
        idempotencyKey: 'stable-original-turn',
      ),
      throwsA(isA<MobileApiException>()
          .having((error) => error.errorCode, 'code', 'CHAT_RECEIPT_PENDING')),
    );
    client.receiptKnown = true;
    expect(await repository.streamMessage(
      conversation: conversation,
      body: '写入企业库存',
      idempotencyKey: 'stable-original-turn',
    ), '原任务结果已核验');
    expect(client.attemptedPosts, 1);
    expect(client.receiptReads, 2);
  });

  test('legacy pending row never replays a possibly accepted original POST', () async {
    client.receiptKnown = false;
    await expectLater(
      repository.streamMessage(
        conversation: conversation,
        body: '写入企业库存',
        idempotencyKey: 'stable-original-turn',
      ),
      throwsA(isA<MobileApiException>()
          .having((error) => error.errorCode, 'code', 'CHAT_RECEIPT_PENDING')),
    );
    expect(client.attemptedPosts, 1);

    // Older versions could downgrade an ambiguous send to pending.
    final id = await store.enqueueMessage(
      conversationId: conversation.id,
      conversationType: conversation.type,
      title: conversation.title,
      body: '写入企业库存',
      authGeneration: client.authGeneration,
      idempotencyKey: 'stable-original-turn',
    );
    expect(id, greaterThan(0));
    expect((await store.pendingMessages()).single.requiresReconciliation, isFalse);
    expect(await repository.flushPendingMessages(), 0);
    expect(client.attemptedPosts, 1);
    expect(client.receiptReads, 2);
    expect((await store.pendingMessages()).single.requiresReconciliation, isTrue);

    client.receiptKnown = true;
    expect(await repository.flushPendingMessages(), 1);
    expect(client.attemptedPosts, 1);
    expect(client.receiptReads, 3);
    expect(await store.pendingMessageCount(), 0);
  });

  test('stale auth-generation backlog cannot starve current receipt GETs', () async {
    client.receiptKnown = false;
    await expectLater(
      repository.streamMessage(
        conversation: conversation,
        body: '写入企业库存',
        idempotencyKey: 'stable-original-turn',
      ),
      throwsA(isA<MobileApiException>()
          .having((error) => error.errorCode, 'code', 'CHAT_RECEIPT_PENDING')),
    );
    for (var i = 0; i < 6; i++) {
      await store.enqueueMessage(
        conversationId: conversation.id,
        conversationType: conversation.type,
        title: conversation.title,
        body: 'old write $i',
        authGeneration: client.authGeneration + 1,
        idempotencyKey: 'old-turn-$i',
        requiresReconciliation: true,
      );
    }
    await store.enqueueMessage(
      conversationId: conversation.id,
      conversationType: conversation.type,
      title: conversation.title,
      body: '写入企业库存',
      authGeneration: client.authGeneration,
      idempotencyKey: 'stable-original-turn',
      requiresReconciliation: true,
    );
    client.receiptKnown = true;
    expect(await repository.flushPendingMessages(), 1);
    expect(client.attemptedPosts, 1);
    expect(client.receiptReads, 2);
    expect(await store.pendingMessageCount(), 6);
    final remaining = await store.pendingMessages(limit: 10);
    expect(remaining.every((row) => row.requiresReconciliation), isTrue);
    expect(remaining.every((row) => row.idempotencyKey.startsWith('old-turn-')), isTrue);
  });

  test('credential generation mismatch does not discard unknown work', () async {
    final id = await store.enqueueMessage(
      conversationId: conversation.id,
      conversationType: conversation.type,
      title: conversation.title,
      body: '原工单不得丢失',
      authGeneration: client.authGeneration + 1,
      idempotencyKey: 'stable-original-turn',
      requiresReconciliation: true,
    );
    expect(await repository.flushPendingMessages(), 0);
    final pending = (await store.pendingMessages()).single;
    expect(pending.id, id);
    expect(pending.idempotencyKey, 'stable-original-turn');
    expect(pending.requiresReconciliation, isTrue);
    expect(client.attemptedPosts, 0);
    expect(client.receiptReads, 0);
  });

  test('weak reconnection retries only GET receipts with the same turn', () async {
    client.receiptKnown = false;
    await expectLater(
      repository.streamMessage(
        conversation: conversation,
        body: '写入企业库存',
        idempotencyKey: 'stable-original-turn',
      ),
      throwsA(isA<MobileApiException>()
          .having((error) => error.errorCode, 'code', 'CHAT_RECEIPT_PENDING')),
    );
    final id = await store.enqueueMessage(
      conversationId: conversation.id,
      conversationType: conversation.type,
      title: conversation.title,
      body: '写入企业库存',
      authGeneration: client.authGeneration,
      idempotencyKey: 'stable-original-turn',
    );
    for (var attempt = 0; attempt < 3; attempt++) {
      expect(await repository.flushPendingMessages(), 0);
      final pending = (await store.pendingMessages()).single;
      expect(pending.id, id);
      expect(pending.idempotencyKey, 'stable-original-turn');
      expect(pending.requiresReconciliation, isTrue);
      expect(client.attemptedPosts, 1);
    }
    client.receiptKnown = true;
    expect(await repository.flushPendingMessages(), 1);
    expect(client.receiptReads, 5);
    expect(client.attemptedPosts, 1);
    expect(await store.pendingMessageCount(), 0);
  });
}
