import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/meeting/meeting_minutes_docx.dart';
import 'package:xcagi_flutter_poc/src/features/meeting/meeting_minutes_exporter.dart';
import 'package:xcagi_flutter_poc/src/features/meeting/meeting_minutes_screen.dart';
import 'package:xcagi_flutter_poc/src/theme/app_theme.dart';

void main() {
  test('meeting summary keeps a dedicated server-bound chat session', () async {
    final api = _MeetingApi();
    final repository = MobileRepository(client: api);

    final result = await repository.summarizeMeetingMinutes(
      title: '产品周会',
      participants: '张三、李四',
      transcript: '确认周五完成真机验收。',
    );

    expect(result, '整理完成');
    expect(api.sessionId, startsWith('meeting-minutes-'));
    expect(api.context, {
      'source': 'mobile_meeting_minutes',
      'client_surface': 'mobile',
    });
    expect(api.prompt, contains('确认周五完成真机验收。'));
  });

  test('meeting transcript merge replaces overlapping restart fragments', () {
    expect(
      mergeMeetingTranscript('第一项确认\n大家确认', '大家确认本周完成'),
      '第一项确认\n大家确认本周完成',
    );
    expect(
      mergeMeetingTranscript('大家确认本周完成', '大家确认'),
      '大家确认本周完成',
    );
    expect(
      mergeMeetingTranscript('第一项', '第二项'),
      '第一项\n第二项',
    );
  });

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
    expect(
      find.text(
          '选择“小C智能整理”时，转写文本会发送到企业端/服务端并按系统审计策略留痕；本应用不保存原始音频，系统语音识别服务会处理音频。'),
      findsOneWidget,
    );
    expect(
      find.text('语音转写为试用能力，系统可能因停顿自动重启；长会建议每 5–10 分钟分段确认。'),
      findsOneWidget,
    );
    await tester.enterText(
      find.byKey(const ValueKey('meeting_transcript_field')),
      '团队确认本周完成移动端升级，并由张三负责真机验收。',
    );
    await tester.ensureVisible(
      find.byKey(const ValueKey('meeting_generate_word')),
    );
    await tester.tap(find.byKey(const ValueKey('meeting_generate_word')));
    await tester.pumpAndSettle();
    expect(find.text('选择 Word 整理方式'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('meeting_mode_smart')));
    await tester.pumpAndSettle();

    expect(repository.summaryCalls, 1);
    expect(exporter.draft, isNotNull);
    expect(exporter.draft!.summary, '确认移动端升级并安排真机验收。');
    expect(exporter.draft!.actionItems.single.owner, '张三');
    expect(find.byKey(const ValueKey('meeting_word_ready')), findsOneWidget);
  });

  testWidgets(
      'meeting minutes can generate locally without uploading transcript', (
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
    await tester.enterText(
      find.byKey(const ValueKey('meeting_transcript_field')),
      '仅保存在本机的会议内容。',
    );
    await tester.ensureVisible(
      find.byKey(const ValueKey('meeting_generate_word')),
    );
    await tester.tap(find.byKey(const ValueKey('meeting_generate_word')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('meeting_mode_local')));
    await tester.pumpAndSettle();

    expect(repository.summaryCalls, 0);
    expect(exporter.draft, isNotNull);
    expect(exporter.draft!.transcript, '仅保存在本机的会议内容。');
    expect(find.byKey(const ValueKey('meeting_word_ready')), findsOneWidget);
  });
}

class _MeetingApi extends MobileApiClient {
  String prompt = '';
  String? sessionId;
  Map<String, Object?> context = const {};

  @override
  Future<Map<String, Object?>> chat(
    String message, {
    String? sessionId,
    Map<String, Object?> context = const {},
  }) async {
    prompt = message;
    this.sessionId = sessionId;
    this.context = context;
    return {'response': '整理完成'};
  }
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
