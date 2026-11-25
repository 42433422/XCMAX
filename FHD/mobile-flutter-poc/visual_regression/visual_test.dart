import 'dart:io';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/features/chat/chat_screen.dart';
import 'package:xcagi_flutter_poc/src/features/workspace/employee_workspace_screen.dart';
import 'package:xcagi_flutter_poc/src/models/conversation.dart';
import 'package:xcagi_flutter_poc/src/theme/app_theme.dart';
import '../test/employee_workspace_screen_test.dart' as fixture;

const root = ValueKey('visual-root');

Future<void> show(WidgetTester tester, Widget screen, Size size,
    bool dark, double textScale) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final theme = dark ? AppTheme.dark() : AppTheme.light();
  await tester.pumpWidget(RepaintBoundary(
    key: root,
    child: MaterialApp(
      theme: theme.copyWith(
        textTheme: theme.textTheme.apply(fontFamily: 'VisualCJK'),
        primaryTextTheme: theme.primaryTextTheme.apply(fontFamily: 'VisualCJK'),
      ),
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context).copyWith(
          disableAnimations: true, textScaler: TextScaler.linear(textScale),
        ),
        child: child!,
      ),
      home: screen,
    ),
  ));
  await tester.pumpAndSettle();
}

Future<void> capture(WidgetTester tester, String name) async {
  expect(tester.takeException(), isNull);
  await expectLater(find.byKey(root), matchesGoldenFile('goldens/$name.png'));
}

void main() {
  setUpAll(() async {
    final path = Platform.environment['VISUAL_FONT_PATH'];
    if (path == null) throw StateError('VISUAL_FONT_PATH is required');
    final loader = FontLoader('VisualCJK')
      ..addFont(Future.value(ByteData.sublistView(File(path).readAsBytesSync())));
    await loader.load();
    Directory('visual_regression/goldens').createSync(recursive: true);
  });

  for (final dark in [false, true]) {
    final themeName = dark ? 'dark' : 'light';
    for (final width in [320, 430]) {
      final size = Size(width.toDouble(), width == 320 ? 900 : 932);
      final textScale = width == 320 ? 2.0 : 1.0;
      final name = '$themeName-$width';
      testWidgets('chat and tools $name', (tester) async {
        await show(tester, const ChatScreen(
          conversation: ConversationItem(
            id: 'pinned:assistant', type: ConversationType.pinnedAssistant,
            title: '小C', subtitle: '', timestampText: '',
          ),
          initialMessages: [],
        ), size, dark, textScale);
        expect(find.byTooltip('更多工具'), findsOneWidget);
        await capture(tester, 'chat-empty-$name');
        await tester.enterText(find.byType(TextField), '请整理示例订单');
        FocusManager.instance.primaryFocus?.unfocus();
        await tester.pumpAndSettle();
        expect(find.text('请整理示例订单'), findsOneWidget);
        await capture(tester, 'chat-draft-$name');
        await tester.enterText(find.byType(TextField), '整理订单\n核对库存\n列出异常');
        FocusManager.instance.primaryFocus?.unfocus();
        await tester.pumpAndSettle();
        expect(find.text('整理订单\n核对库存\n列出异常'), findsOneWidget);
        await capture(tester, 'chat-multiline-draft-$name');
        await tester.tap(find.byTooltip('更多工具'));
        await tester.pumpAndSettle();
        expect(find.text('聊天工具'), findsOneWidget);
        await capture(tester, 'chat-tools-$name');
      });
    }
    testWidgets('employee workspace $themeName', (tester) async {
      final api = fixture.Api();
      final repo = fixture.Repository(api);
      addTearDown(repo.dispose);
      addTearDown(api.dispose);
      await show(tester, EmployeeWorkspaceScreen(repository: repo),
          const Size(430, 932), dark, 1);
      expect(find.text('订单助理'), findsOneWidget);
      await capture(tester, 'employee-$themeName');
      await tester.enterText(find.byType(TextField), '不存在');
      FocusManager.instance.primaryFocus?.unfocus();
      await tester.pumpAndSettle();
      expect(find.text('暂无符合条件的员工'), findsOneWidget);
      await capture(tester, 'employee-empty-$themeName');
    });
  }
}
