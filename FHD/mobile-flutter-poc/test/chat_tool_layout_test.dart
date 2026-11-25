import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/features/chat/chat_screen.dart';
import 'package:xcagi_flutter_poc/src/models/conversation.dart';
import 'package:xcagi_flutter_poc/src/theme/app_theme.dart';

void main() {
  testWidgets('composer grows for multiline drafts on a narrow viewport',
      (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(320, 700);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);
    await tester.pumpWidget(MaterialApp(
      theme: AppTheme.light(),
      home: const ChatScreen(
        conversation: ConversationItem(
            id: 'pinned:assistant',
            type: ConversationType.pinnedAssistant,
            title: '小C',
            subtitle: '',
            timestampText: ''),
        initialMessages: [],
      ),
    ));
    await tester.pumpAndSettle();
    final field = find.byType(TextField);
    final initialHeight = tester.getSize(field).height;
    await tester.enterText(field, '核对订单\n检查库存\n汇总异常');
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(field).textInputAction,
        TextInputAction.newline);
    expect(tester.getSize(field).height, greaterThan(initialHeight));
    expect(find.text('发送'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('does not send while the mobile IME is composing a candidate', (tester) async {
    await tester.pumpWidget(MaterialApp(
      theme: AppTheme.light(),
      home: const ChatScreen(
        conversation: ConversationItem(
            id: 'pinned:assistant',
            type: ConversationType.pinnedAssistant,
            title: '小C', subtitle: '', timestampText: ''),
        initialMessages: [],
      ),
    ));
    await tester.pumpAndSettle();
    final field = find.byType(TextField);
    await tester.enterText(field, '候选词');
    tester.testTextInput.updateEditingValue(const TextEditingValue(
      text: '候选词',
      selection: TextSelection.collapsed(offset: 3),
      composing: TextRange(start: 0, end: 3),
    ));
    await tester.pump();
    final existingCount = find.byType(MessageBubble).evaluate().length;
    await tester.tap(find.text('发送'));
    await tester.pump();
    expect(find.byType(MessageBubble).evaluate().length, existingCount);
    expect(tester.widget<TextField>(field).controller?.text, '候选词');
    expect(tester.takeException(), isNull);
  });

  testWidgets('chat tools fit a 320px screen at double text size',
      (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(320, 900);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);
    await tester.pumpWidget(MaterialApp(
      theme: AppTheme.light(),
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context)
            .copyWith(textScaler: const TextScaler.linear(2)),
        child: child!,
      ),
      home: const ChatScreen(
        conversation: ConversationItem(
            id: 'pinned:assistant',
            type: ConversationType.pinnedAssistant,
            title: '小C',
            subtitle: '',
            timestampText: ''),
        initialMessages: [],
      ),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('更多工具'));
    await tester.pumpAndSettle();
    expect(find.text('聊天工具'), findsOneWidget);
    final first = find.byKey(const ValueKey('chat_tool_card_新建对话'));
    final third = find.byKey(const ValueKey('chat_tool_card_添加文件'));
    expect(tester.getSize(first).height, greaterThan(92));
    expect(
        tester.getTopLeft(third).dy, greaterThan(tester.getTopLeft(first).dy));
    expect(tester.widget<Text>(find.text('新建对话')).maxLines, 2);
    await tester
        .ensureVisible(find.byKey(const ValueKey('chat_tool_card_问题修复')));
    await tester.pumpAndSettle();
    expect(find.text('问题修复').hitTestable(), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.tap(find.byTooltip('关闭工具'));
    await tester.pumpAndSettle();
    expect(find.text('聊天工具'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
