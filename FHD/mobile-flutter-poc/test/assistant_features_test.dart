import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/data/assistant_assets.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/chat/chat_screen.dart';
import 'package:xcagi_flutter_poc/src/models/conversation.dart';
import 'package:xcagi_flutter_poc/src/policy/pinned_ids.dart';
import 'package:xcagi_flutter_poc/src/theme/app_theme.dart';

void main() {
  testWidgets('small C online mode renders source cards', (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 900);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);
    final repository = _AssistantFeatureRepository();

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: ChatScreen(
          conversation: const ConversationItem(
            id: PinnedIds.assistant,
            type: ConversationType.pinnedAssistant,
            title: '小C助理',
            subtitle: '',
            timestampText: '',
          ),
          initialMessages: const [],
          repository: repository,
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const ValueKey('assistant_mode_online')));
    await tester.pump();
    await tester.enterText(find.byType(TextField).last, '今天有什么更新');
    await tester.pump();
    await tester.tap(find.text('发送'));
    await tester.pumpAndSettle();

    expect(repository.searchCalls, 1);
    expect(find.text('这是联网后的回答'), findsOneWidget);
    expect(find.text('来源'), findsOneWidget);
    expect(find.textContaining('官方更新'), findsOneWidget);
    expect(find.text('朗读'), findsOneWidget);
  });

  testWidgets('small C tool panel exposes files voice and memory', (
    tester,
  ) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 950);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: ChatScreen(
          conversation: const ConversationItem(
            id: PinnedIds.assistant,
            type: ConversationType.pinnedAssistant,
            title: '小C助理',
            subtitle: '',
            timestampText: '',
          ),
          initialMessages: const [],
          repository: _AssistantFeatureRepository(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('更多工具'));
    await tester.pumpAndSettle();

    expect(find.text('联网搜索'), findsOneWidget);
    expect(find.text('文件分析'), findsOneWidget);
    expect(find.text('语音对话'), findsOneWidget);
    expect(find.text('长期记忆'), findsOneWidget);
    expect(find.text('OCR 识别'), findsOneWidget);
  });
}

class _AssistantFeatureRepository extends MobileRepository {
  int searchCalls = 0;

  @override
  Future<List<ChatMessage>> loadInitialMessages(
    ConversationItem conversation,
  ) async =>
      const [];

  @override
  Future<MobileMeData> loadMe() async => MobileMeData.adminFallback();

  @override
  Future<AssistantEmployeeAvailability>
      loadAssistantEmployeeAvailability() async {
    return const AssistantEmployeeAvailability(
      onlineConversationIds: {PinnedIds.trae},
    );
  }

  @override
  Future<AssistantSearchResult> searchAssistantMessage({
    required String body,
    int userId = 0,
    List<ChatMessage> recentMessages = const [],
  }) async {
    searchCalls += 1;
    return const AssistantSearchResult(
      answer: '这是联网后的回答',
      provider: 'bing_rss',
      query: '今天有什么更新',
      sources: [
        ChatSource(
          title: '官方更新',
          url: 'https://example.com/update',
          snippet: '来自官方页面的摘要',
        ),
      ],
    );
  }
}
