import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/features/call/voice_call_screen.dart';
import 'package:xcagi_flutter_poc/src/theme/app_theme.dart';

void main() {
  Future<void> openSheet(
    WidgetTester tester, {
    required VoidCallback onVoice,
  }) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: Builder(
            builder: (context) => TextButton(
              onPressed: () => showCallOptionsSheet(context, onVoice: onVoice),
              child: const Text('通话'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('通话'));
    await tester.pumpAndSettle();
  }

  testWidgets('通话入口同时给出语音与视频两个选择', (tester) async {
    await openSheet(tester, onVoice: () {});
    expect(find.text('语音通话'), findsOneWidget);
    expect(find.text('视频通话'), findsOneWidget);
    expect(find.text('未解锁'), findsOneWidget);
  });

  testWidgets('点击语音通话关闭选择并进入语音', (tester) async {
    var started = 0;
    await openSheet(tester, onVoice: () => started += 1);
    await tester.tap(find.byKey(const ValueKey('call_option_voice')));
    await tester.pumpAndSettle();
    expect(started, 1);
    expect(find.text('语音通话'), findsNothing);
  });

  testWidgets('视频通话显示未解锁且不可点击', (tester) async {
    var started = 0;
    await openSheet(tester, onVoice: () => started += 1);
    await tester.tap(find.byKey(const ValueKey('call_option_video')));
    await tester.pumpAndSettle();
    expect(started, 0);
    expect(find.text('视频通话'), findsOneWidget);
  });
}
