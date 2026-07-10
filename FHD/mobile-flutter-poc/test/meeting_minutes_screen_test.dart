import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/meeting/meeting_minutes_docx.dart';
import 'package:xcagi_flutter_poc/src/features/meeting/meeting_minutes_exporter.dart';
import 'package:xcagi_flutter_poc/src/features/meeting/meeting_minutes_screen.dart';
import 'package:xcagi_flutter_poc/src/theme/app_theme.dart';

void main() {
  testWidgets('meeting minutes creates and exposes a Word document', (
    WidgetTester tester,
  ) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1100);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);
    final repository = _MeetingRepository();
    final exporter = _MeetingExporter();

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: MeetingMinutesScreen(
          repository: repository,
          exporter: exporter,
        ),
      ),
    );

    expect(find.text('录下来，小C帮你整理成 Word'), findsOneWidget);
    await tester.enterText(
      find.byKey(const ValueKey('meeting_transcript_field')),
      '团队确认本周完成移动端升级，并由张三负责真机验收。',
    );
    await tester.ensureVisible(
      find.byKey(const ValueKey('meeting_generate_word')),
    );
    await tester.tap(find.byKey(const ValueKey('meeting_generate_word')));
    await tester.pumpAndSettle();

    expect(repository.summaryCalls, 1);
    expect(exporter.draft, isNotNull);
    expect(exporter.draft!.summary, '确认移动端升级并安排真机验收。');
    expect(exporter.draft!.actionItems.single.owner, '张三');
    expect(find.byKey(const ValueKey('meeting_word_ready')), findsOneWidget);
  });
}

class _MeetingRepository extends MobileRepository {
  var summaryCalls = 0;

  @override
  Future<String> summarizeMeetingMinutes({
    required String title,
    required String transcript,
    String participants = '',
  }) async {
    summaryCalls += 1;
    return '''
【会议摘要】
确认移动端升级并安排真机验收。
【讨论要点】
- 完成小C舒适版
【决策事项】
- 本周交付
【待办事项】
- 完成真机验收｜张三｜周五
''';
  }
}

class _MeetingExporter extends MeetingMinutesExporter {
  MeetingMinutesDraft? draft;

  @override
  Future<String> createAndShare(MeetingMinutesDraft value) async {
    draft = value;
    return '/tmp/产品周会纪要.docx';
  }
}
