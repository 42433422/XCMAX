import 'dart:async';
import 'dart:typed_data';

import 'package:file_selector/file_selector.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/chat/chat_screen.dart';
import 'package:xcagi_flutter_poc/src/models/conversation.dart';
import 'package:xcagi_flutter_poc/src/theme/app_theme.dart';

const _conversation = ConversationItem(
  id: 'pinned:assistant',
  type: ConversationType.pinnedAssistant,
  title: '小C',
  subtitle: '',
  timestampText: '',
);

class _AttachmentApi extends MobileApiClient {
  _AttachmentApi()
      : super(
            sessionStore: MemoryMobileSessionStore(MobileSessionData.empty
                .copyWith(userId: 1, accessToken: 'test-account')));
  final names = <String>[];
  final pending = Completer<MobileChatAttachment>();

  @override
  Future<String> resolveSessionBaseUrl() async => 'https://example.invalid/';

  @override
  Future<MobileChatAttachment> uploadChatAttachment({
    required String name,
    required List<int> bytes,
    required String conversationId,
    int? expectedAuthGeneration,
    String? expectedBaseUrl,
  }) {
    names.add(name);
    return pending.future;
  }
}

class _Repository extends MobileRepository {
  _Repository(_AttachmentApi api, {this.draft = const {}})
      : super(client: api);

  final Map<String, Object?> draft;

  @override
  Future<Map<String, Object?>> loadChatComposerDraft(String conversationId) async =>
      draft;

  @override
  Future<void> saveChatComposerDraft(String conversationId, String text,
      {List<String> attachmentNames = const []}) async {}

  @override
  Future<List<ChatMessage>> loadInitialMessages(
          ConversationItem conversation) async =>
      [];

  @override
  Future<MobileMeData> loadMe() async => MobileMeData.adminFallback();
}

Future<void> _showChat(
    WidgetTester tester, _Repository repository,
    {Future<List<XFile>> Function()? picker}) async {
  await tester.pumpWidget(MaterialApp(
    theme: AppTheme.light(),
    home: ChatScreen(
      conversation: _conversation,
      initialMessages: const [],
      repository: repository,
      attachmentPicker: picker,
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('restored attachment names are removable and not ready receipts',
      (tester) async {
    final api = _AttachmentApi();
    final repository = _Repository(api, draft: const {
      'text': '核对附件',
      'attachment_names': ['previous.xlsx'],
    });
    addTearDown(repository.dispose);
    addTearDown(api.dispose);
    await _showChat(tester, repository);
    expect(find.text('previous.xlsx'), findsOneWidget);
    expect(find.text('已就绪'), findsNothing);
    expect(find.byTooltip('移除 previous.xlsx'), findsOneWidget);
    await tester.tap(find.byTooltip('移除 previous.xlsx'));
    await tester.pumpAndSettle();
    expect(find.text('previous.xlsx'), findsNothing);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });

  testWidgets('cancelled batch discards late receipt and never starts next file',
      (tester) async {
    final api = _AttachmentApi();
    final repository = _Repository(api);
    addTearDown(repository.dispose);
    addTearDown(api.dispose);
    await _showChat(tester, repository, picker: () async => [
      XFile.fromData(Uint8List.fromList([1]), name: 'first.txt'),
      XFile.fromData(Uint8List.fromList([2]), name: 'second.txt'),
    ]);
    await tester.tap(find.byTooltip('更多工具'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('chat_tool_card_添加文件')));
    await tester.pumpAndSettle();
    expect(api.names, ['first.txt']);
    await tester.tap(find.text('取消上传'));
    await tester.pumpAndSettle();
    expect(find.textContaining('服务端可能已接收当前文件'), findsOneWidget);
    api.pending.complete(MobileChatAttachment(
      uploadId: 'late-upload',
      name: 'first.txt',
      baseUrl: 'https://example.invalid/',
      authGeneration: api.authGeneration,
      conversationId: _conversation.id,
    ));
    await tester.pumpAndSettle();
    expect(api.names, ['first.txt']);
    expect(find.text('first.txt'), findsNothing);
    expect(find.text('second.txt'), findsNothing);
    expect(find.text('已就绪'), findsNothing);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
}
