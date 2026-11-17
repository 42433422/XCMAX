import 'dart:typed_data';
import 'package:file_selector/file_selector.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/ai_employee_profile.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/chat/chat_screen.dart';
import 'package:xcagi_flutter_poc/src/models/conversation.dart';
import 'package:xcagi_flutter_poc/src/theme/app_theme.dart';

class _Api extends MobileApiClient {
  _Api()
      : super(
            sessionStore: MemoryMobileSessionStore(
                const MobileSessionData(accessToken: 'user')));
  int attempts = 0;
  bool failResolve = false;
  @override
  Future<String> resolveSessionBaseUrl() {
    if (failResolve) {
      throw const MobileApiException(
          statusCode: 503, message: '连接暂时不可用', body: {});
    }
    return super.resolveSessionBaseUrl();
  }

  @override
  Future<MobileChatAttachment> uploadChatAttachment(
      {required String name,
      required List<int> bytes,
      required String conversationId,
      int? expectedAuthGeneration,
      String? expectedBaseUrl}) async {
    if (++attempts == 1) {
      throw const MobileApiException(
          statusCode: 503, message: '上传失败', body: {});
    }
    return MobileChatAttachment(
        uploadId: 'owned',
        name: name,
        baseUrl: 'https://example.test/',
        authGeneration: 0,
        conversationId: conversationId);
  }
}

class _Repository extends MobileRepository {
  _Repository(_Api api) : super(client: api);
  @override
  Future<MobileMeData> loadMe() async => MobileMeData.adminFallback();

  final turnKeys = <String>[];
  final sentBodies = <String>[];
  final plainBodies = <String>[];
  @override
  Future<String> streamMessage({
    required ConversationItem conversation,
    required String body,
    int userId = 0,
    List<ChatMessage> recentMessages = const [],
    bool cacheUserMessage = true,
    void Function(String)? onToken,
    void Function(RelayTaskProgress)? onStatus,
    bool Function()? isCancelled,
  }) async {
    plainBodies.add(body);
    return '已收到';
  }

  @override
  Future<String> streamAttachedMessage({
    required ConversationItem conversation,
    required String body,
    required List<MobileChatAttachment> attachments,
    required String idempotencyKey,
    List<ChatMessage> recentMessages = const [],
    void Function(String)? onToken,
  }) async {
    turnKeys.add(idempotencyKey);
    sentBodies.add(body);
    if (turnKeys.length == 1) {
      throw const MobileApiException(
          statusCode: 502, message: '结果待核对', body: {});
    }
    return '已处理附件';
  }

  @override
  Future<void> removeQueuedMessage(String conversationId, String body) async {}
  @override
  Future<List<ChatMessage>> loadInitialMessages(
          ConversationItem conversation) async =>
      [];
  @override
  Future<List<AiEmployeeProfile>> loadAiEmployees() async => [];
}

void main() {
  for (final change in ['account', 'backend', 'tenant', 'error', 'unchanged']) {
    testWidgets('tool selection revalidates $change before executing',
        (tester) async {
      final api = _Api();
      final repo = _Repository(api);
      await tester.pumpWidget(MaterialApp(
        theme: AppTheme.light(),
        home: ChatScreen(
          conversation: const ConversationItem(
              id: 'pinned:assistant',
              type: ConversationType.pinnedAssistant,
              title: '小C',
              subtitle: '',
              timestampText: ''),
          initialMessages: const [],
          repository: repo,
        ),
      ));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), '继续旧任务');
      await tester.tap(find.byTooltip('更多工具'));
      await tester.pumpAndSettle();
      switch (change) {
        case 'account':
          await api.persistPairingSession({
            'access_token': 'other-account',
            'user': {'id': 2, 'username': 'other'},
          });
        case 'backend':
          await api.saveSession((await api.loadSession()).copyWith(
              serverMode: 'lan',
              fhdHost: '10.0.0.8:5000',
              localBaseUrl: 'http://10.0.0.8:5000/'));
        case 'tenant':
          await api.saveSession((await api.loadSession())
              .copyWith(relayTenantId: 'other-tenant'));
        case 'error':
          api.failResolve = true;
      }
      await tester.tap(find.text(change == 'backend' ? '验收回访' : '任务派工'));
      await tester.pumpAndSettle();
      expect(find.text('聊天工具'), findsNothing);
      if (change == 'unchanged') {
        expect(repo.plainBodies, ['帮我安排并完成这个任务：继续旧任务']);
      } else {
        expect(repo.plainBodies, isEmpty);
        expect(find.text('继续旧任务'), findsOneWidget);
        expect(
            find.text(change == 'error'
                ? '工具暂时不可用：服务器暂时不可用，请稍后重试'
                : '账号或连接已切换，请重新打开工具'),
            findsOneWidget);
      }
      api.failResolve = false;
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.runAsync(() async {
        await repo.dispose();
        api.dispose();
      });
    });
  }

  testWidgets('tool sheet cancellation keeps draft and honors reduced motion',
      (tester) async {
    final api = _Api();
    final repo = _Repository(api);
    var selections = 0;
    await tester.pumpWidget(MaterialApp(
      theme: AppTheme.light(),
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context).copyWith(disableAnimations: true),
        child: child!,
      ),
      home: ChatScreen(
        conversation: const ConversationItem(
            id: 'pinned:assistant',
            type: ConversationType.pinnedAssistant,
            title: '小C',
            subtitle: '',
            timestampText: ''),
        initialMessages: const [],
        repository: repo,
        attachmentPicker: () async {
          selections++;
          return [];
        },
      ),
    ));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '保留这份草稿');
    await tester.tap(find.byTooltip('更多工具'));
    await tester.pumpAndSettle();
    final route = ModalRoute.of(
        tester.element(find.byKey(const ValueKey('chat_tool_card_panel'))))!;
    expect(route.transitionDuration, Duration.zero);
    expect(find.text('聊天工具'), findsOneWidget);
    await tester.tap(find.byTooltip('关闭工具'));
    await tester.pumpAndSettle();
    expect(find.text('聊天工具'), findsNothing);
    expect(find.text('保留这份草稿'), findsOneWidget);
    expect(selections, 0);
    expect(api.attempts, 0);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.runAsync(() async {
      await repo.dispose();
      api.dispose();
    });
  });

  testWidgets(
      'attachment retry keeps turn key and new send creates another key',
      (tester) async {
    final api = _Api()..attempts = 1;
    final repo = _Repository(api);
    await tester.pumpWidget(MaterialApp(
        theme: AppTheme.light(),
        home: ChatScreen(
          conversation: const ConversationItem(
              id: 'pinned:assistant',
              type: ConversationType.pinnedAssistant,
              title: '小C',
              subtitle: '',
              timestampText: ''),
          initialMessages: const [],
          repository: repo,
          attachmentPicker: () async => [
            XFile.fromData(Uint8List.fromList([1]),
                name: 'report.csv', path: 'report.csv')
          ],
        )));
    await tester.pumpAndSettle();
    Future<void> attachAndSend() async {
      await tester.tap(find.byTooltip('更多工具'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('添加文件'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), '处理这份文件');
      await tester.pumpAndSettle();
      await tester.tap(find.text('发送'));
      await tester.pumpAndSettle();
    }

    await attachAndSend();
    expect(repo.turnKeys, hasLength(1));
    expect(repo.turnKeys.single, isNotEmpty);
    final failed = tester
        .widgetList<MessageBubble>(find.byType(MessageBubble))
        .singleWhere(
            (bubble) => bubble.message.status == ChatDeliveryStatus.failed);
    failed.onResend!();
    await tester.pumpAndSettle();
    expect(repo.turnKeys, hasLength(2));
    expect(repo.turnKeys[1], repo.turnKeys[0]);
    expect(repo.sentBodies[1], repo.sentBodies[0]);
    await attachAndSend();
    expect(repo.turnKeys, hasLength(3));
    expect(repo.turnKeys[2], isNot(repo.turnKeys[0]));
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.runAsync(() async {
      await repo.dispose();
      api.dispose();
    });
  });

  testWidgets('failed upload can retry, then remove the ready attachment',
      (tester) async {
    final api = _Api();
    final repo = _Repository(api);
    await tester.pumpWidget(MaterialApp(
        theme: AppTheme.light(),
        home: ChatScreen(
          conversation: const ConversationItem(
              id: 'pinned:assistant',
              type: ConversationType.pinnedAssistant,
              title: '小C',
              subtitle: '',
              timestampText: ''),
          initialMessages: const [],
          repository: repo,
          attachmentPicker: () async => [
            XFile.fromData(Uint8List.fromList([1, 2]),
                name: 'report.csv', path: 'report.csv')
          ],
        )));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('更多工具'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('添加文件'));
    await tester.pumpAndSettle();
    expect(api.attempts, 1);
    expect(find.text('2 B · 上传失败'), findsOneWidget);
    await tester.tap(find.text('重试'));
    await tester.pumpAndSettle();
    expect(api.attempts, 2);
    expect(find.text('report.csv'), findsOneWidget);
    expect(find.text('2 B · 已就绪'), findsOneWidget);
    await tester.tap(find.byTooltip('移除 report.csv'));
    await tester.pumpAndSettle();
    expect(find.byTooltip('移除 report.csv'), findsNothing);
    await tester.pump(const Duration(seconds: 5));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('更多工具'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('添加文件'));
    await tester.pumpAndSettle();
    expect(find.byTooltip('移除 report.csv'), findsOneWidget);
    await api.clearActiveAuth();
    await tester.pumpAndSettle();
    expect(find.byTooltip('移除 report.csv'), findsNothing);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets(
      'employee attachment action explicitly hands off before selecting files',
      (tester) async {
    var pickerCalls = 0;
    final api = _Api();
    await tester.pumpWidget(MaterialApp(
        theme: AppTheme.light(),
        home: ChatScreen(
          conversation: const ConversationItem(
              id: 'employee:mod:worker',
              type: ConversationType.aiTask,
              title: '员工',
              subtitle: '',
              timestampText: ''),
          initialMessages: const [],
          repository: _Repository(api),
          attachmentPicker: () async {
            pickerCalls++;
            return [];
          },
        )));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('更多工具'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('文件交给小C'));
    await tester.pumpAndSettle();
    expect(pickerCalls, 0);
    expect(api.attempts, 0);
    final visible = tester.widget<ChatScreen>(find.byType(ChatScreen).last);
    expect(visible.conversation.type, ConversationType.pinnedAssistant);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
