import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
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

Widget _bubble(ChatDeliveryStatus status, VoidCallback onRead) =>
    MaterialApp(
      theme: AppTheme.light(),
      home: Scaffold(
        body: MessageBubble(
          message: ChatMessage(
            id: 'pending-turn',
            conversationId: 'pinned:assistant',
            role: ChatRole.assistant,
            body: '任务执行后等待原回执核对',
            timeText: '',
            status: status,
          ),
          conversation: _conversation,
          showAvatar: false,
          userAvatarUrl: '',
          aiAvatarUrl: null,
          aiContentDescription: '小C',
          hasEmployeeProfile: false,
          onReply: () {},
          onDelete: () {},
          onResend: onRead,
        ),
      ),
    );

void main() {
  testWidgets('unconfirmed turns expose a minimum 44px receipt action',
      (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(320, 800);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);
    var reads = 0;
    await tester.pumpWidget(_bubble(ChatDeliveryStatus.pending, () => reads++));
    await tester.pumpAndSettle();
    expect(find.text('结果待核对'), findsOneWidget);
    final button = find.widgetWithText(TextButton, '核对结果');
    expect(tester.getSize(button).height, greaterThanOrEqualTo(44));
    final semantics = tester.ensureSemantics();
    expect(
      find.bySemanticsLabel('原任务回执未核实，请先核对真实状态，不要重复提交'),
      findsOneWidget,
    );
    semantics.dispose();
    await tester.tap(button);
    expect(reads, 1);
    expect(tester.takeException(), isNull);

    await tester.pumpWidget(_bubble(ChatDeliveryStatus.failed, () => reads++));
    await tester.pumpAndSettle();
    expect(find.text('结果未确认'), findsOneWidget);
    await tester.tap(find.widgetWithText(TextButton, '核对结果'));
    expect(reads, 2);
    expect(tester.takeException(), isNull);
  });
}
