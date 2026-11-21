import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/data/offline/mobile_offline_store.dart';
import 'package:xcagi_flutter_poc/src/models/conversation.dart';

const _conversation = ConversationItem(
  id: 'pinned:assistant',
  type: ConversationType.pinnedAssistant,
  title: '小C',
  subtitle: '',
  timestampText: '',
);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  for (final change in ['logout', 'backend']) {
    test('attachment reply cannot enter cache after $change during cache open',
        () async {
      final api = _ReplyApi();
      final store = MobileOfflineStore.forExecutor(NativeDatabase.memory());
      final repository = _CacheRaceRepository(api, store, (count) async {
        if (change == 'logout') {
          await api.clearActiveAuth();
        } else {
          await api.saveLocalSettings(serverMode: 'cloud');
        }
      });
      addTearDown(() async {
        await repository.dispose();
        api.dispose();
        await store.close();
      });
      final receipt = await _receipt(api);
      await expectLater(
          repository.streamAttachedMessage(
              conversation: _conversation,
              body: 'private attachment question',
              idempotencyKey: 'turn-test',
              attachments: [receipt]),
          throwsA(isA<MobileRepositoryException>()));
      expect(await store.cachedMessages(_conversation.id), isEmpty);
      expect((await api.loadSession()).cachedChatMessages, isEmpty);
    });
  }

  test('account switch between cached user and assistant cannot cache reply',
      () async {
    final api = _ReplyApi();
    final store = MobileOfflineStore.forExecutor(NativeDatabase.memory());
    final repository = _CacheRaceRepository(api, store, (count) async {
      if (count == 2) await api.clearActiveAuth();
    });
    addTearDown(() async {
      await repository.dispose();
      api.dispose();
      await store.close();
    });
    await expectLater(
        repository.streamAttachedMessage(
            conversation: _conversation,
            body: 'private attachment question',
            idempotencyKey: 'turn-test',
            attachments: [await _receipt(api)]),
        throwsA(isA<MobileRepositoryException>()));
    final rows = await store.cachedMessages(_conversation.id);
    expect(rows, hasLength(1));
    expect(rows.single['role'], ChatRole.user.name);
    expect(rows.single['body'], 'private attachment question');
  });

  test('normal chat never dispatches old draft after account changes in cache',
      () async {
    final api = _ReplyApi();
    final store = MobileOfflineStore.forExecutor(NativeDatabase.memory());
    final repository =
        _CacheRaceRepository(api, store, (_) => api.clearActiveAuth());
    addTearDown(() async {
      await repository.dispose();
      api.dispose();
      await store.close();
    });
    await expectLater(
        repository.streamMessage(
            conversation: _conversation, body: 'old account draft', userId: 1),
        throwsA(isA<MobileRepositoryException>()));
    expect(api.normalCalls, 0);
    expect(await store.cachedMessages(_conversation.id), isEmpty);
  });

  test('normal chat rejects reply when backend changes while awaiting result',
      () async {
    final api = _ReplyApi();
    api.beforeNormalReply = () => api.saveLocalSettings(serverMode: 'cloud');
    final store = MobileOfflineStore.forExecutor(NativeDatabase.memory());
    final repository = _CacheRaceRepository(api, store, (_) async {});
    addTearDown(() async {
      await repository.dispose();
      api.dispose();
      await store.close();
    });
    await expectLater(
        repository.streamMessage(
            conversation: _conversation, body: 'old backend draft', userId: 1),
        throwsA(isA<MobileRepositoryException>()));
    expect(api.normalCalls, 1);
    final rows = await store.cachedMessages(_conversation.id);
    expect(rows, hasLength(1));
    expect(rows.single['role'], ChatRole.user.name);
  });
}

Future<MobileChatAttachment> _receipt(MobileApiClient api) async =>
    MobileChatAttachment(
      uploadId: 'owned-upload',
      name: 'report.csv',
      baseUrl: await api.resolveSessionBaseUrl(),
      authGeneration: api.authGeneration,
      conversationId: _conversation.id,
    );

class _ReplyApi extends MobileApiClient {
  _ReplyApi()
      : super(
          config: const MobileApiConfig(baseUrl: 'https://cloud.example/'),
          sessionStore: MemoryMobileSessionStore(const MobileSessionData(
            accessToken: 'account-a',
            userId: 1,
            serverMode: 'lan',
            localBaseUrl: 'http://192.168.1.2:5112/',
          )),
        );

  int normalCalls = 0;
  Future<void> Function()? beforeNormalReply;

  @override
  Future<String> streamChat(String message,
      {
    String idempotencyKey = '',
    bool resumeOnly = false,
      String? sessionId,
      int userId = 0,
      List<Map<String, String>> recentMessages = const [],
      void Function(String)? onToken}) async {
    normalCalls++;
    await beforeNormalReply?.call();
    return 'private ordinary reply';
  }

  @override
  Future<String> streamAttachmentChat(String message,
          {
    bool resumeOnly = false,
          required String conversationId,
          required List<MobileChatAttachment> attachments,
          required String idempotencyKey,
          List<Map<String, String>> recentMessages = const [],
          void Function(String)? onToken}) async =>
      'private attachment reply';
}

class _CacheRaceRepository extends MobileRepository {
  _CacheRaceRepository(MobileApiClient api, this.store, this.onOpen)
      : super(client: api);

  final MobileOfflineStore store;
  final Future<void> Function(int) onOpen;
  int opens = 0;

  @override
  Future<MobileOfflineStore?> openOfflineStore({String? expectedScope}) async {
    await onOpen(++opens);
    return store;
  }
}
