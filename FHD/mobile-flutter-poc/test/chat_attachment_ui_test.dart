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
    expect(find.text('report.csv · 上传失败，点击重试'), findsOneWidget);
    await tester.tap(find.text('report.csv · 上传失败，点击重试'));
    await tester.pumpAndSettle();
    expect(api.attempts, 2);
    expect(find.text('report.csv'), findsOneWidget);
    final chip = tester.widget<InputChip>(find.byType(InputChip));
    expect(chip.onDeleted, isNotNull);
    chip.onDeleted!();
    await tester.pumpAndSettle();
    expect(find.byType(InputChip), findsNothing);
    await tester.pump(const Duration(seconds: 5));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('更多工具'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('添加文件'));
    await tester.pumpAndSettle();
    expect(find.byType(InputChip), findsOneWidget);
    await api.clearActiveAuth();
    await tester.pumpAndSettle();
    expect(find.byType(InputChip), findsNothing);
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
