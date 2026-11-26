import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/features/chat/chat_screen.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/approval/approval_screens.dart';
import 'package:xcagi_flutter_poc/src/features/tasks/task_list_screen.dart';
import 'package:xcagi_flutter_poc/src/features/workspace/employee_workspace_screen.dart';
import 'package:xcagi_flutter_poc/src/models/conversation.dart';
import 'package:xcagi_flutter_poc/src/theme/app_theme.dart';
import '../test/employee_workspace_fixture.dart' as fixture;

const root = ValueKey('visual-root');

class VisualBusinessRepository extends fixture.Repository {
  VisualBusinessRepository(super.api, {this.fail = false});
  final bool fail;

  @override
  Future<List<ApprovalRequest>> loadApprovals() async {
    if (fail) throw const MobileRepositoryException('审批列表加载失败');
    return const [
      ApprovalRequest(id: 1, title: '示例审批', subtitle: '订单复核',
        status: '待审核', applicantName: '示例员工'),
    ];
  }

  @override
  Future<ApprovalDetail> loadApprovalDetail(int id) async => approval;

  @override
  Future<bool> hasUnknownApprovalOutcome(int id) async => false;

  @override
  Future<List<MobileTaskSummary>> loadTasks({int limit = 50}) async {
    if (fail) throw const MobileRepositoryException('任务列表加载失败');
    return [
      MobileTaskSummary.fromJson({
        'task_id': 'visual-task-1',
        'title': '整理考勤',
        'status': 'completed',
      }),
    ];
  }

  @override
  Future<List<MobileDesktopDevice>> loadDesktopDevices() async => [];
}

const approval = ApprovalDetail(
  id: 1, requestNo: 'A001', title: '示例审批', status: '待审核',
  applicantName: '示例员工', flowName: '', currentNodeName: '',
  submittedAt: '', description: '',
);

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
        // Verify the actual editable text, not the Text widget finder.
        final field = tester.widget<TextField>(find.byType(TextField));
        // Both maintained revisions use the same four-line composer contract.
        final captureSide = Platform.environment['VISUAL_CAPTURE_SIDE'] ?? 'candidate';
        if (captureSide != 'baseline' && captureSide != 'candidate') {
          throw StateError('Unknown VISUAL_CAPTURE_SIDE: $captureSide');
        }
        expect(field.maxLines, 4);
        expect(field.controller?.text, '整理订单\n核对库存\n列出异常');
        await capture(tester, 'chat-multiline-draft-$name');
        await tester.tap(find.byTooltip('更多工具'));
        await tester.pumpAndSettle();
        expect(find.text('聊天工具'), findsOneWidget);
        await capture(tester, 'chat-tools-$name');
      });
    }
    for (final size in [const Size(320, 900), const Size(844, 390),
        const Size(768, 1024)]) {
      final name = '$themeName-${size.width.toInt()}x${size.height.toInt()}';
      final scale = size.width == 320 ? 2.0 : 1.0;
      testWidgets('approval list and business error $name', (tester) async {
        final api = fixture.Api();
        final repo = VisualBusinessRepository(api);
        final failed = VisualBusinessRepository(api, fail: true);
        addTearDown(repo.dispose);
        addTearDown(failed.dispose);
        addTearDown(api.dispose);
        await show(tester, ApprovalListScreen(repository: repo),
            size, dark, scale);
        expect(find.text('示例审批'), findsOneWidget);
        await capture(tester, 'approval-list-$name');
        await tester.pumpWidget(const SizedBox());
        await show(tester, ApprovalListScreen(repository: failed),
            size, dark, scale);
        expect(find.text('重试'), findsOneWidget);
        await capture(tester, 'approval-error-$name');
        await tester.pumpWidget(const SizedBox());
      });
    }
    testWidgets('approval detail and confirmation $themeName', (tester) async {
      final api = fixture.Api();
      final repo = VisualBusinessRepository(api);
      addTearDown(repo.dispose);
      addTearDown(api.dispose);
      await show(tester, ApprovalDetailScreen(id: approval.id,
          initialDetail: approval, repository: repo),
          const Size(430, 932), dark, 1);
      expect(find.text('待审核'), findsOneWidget);
      await capture(tester, 'approval-detail-$themeName');
      await tester.ensureVisible(find.text('通过'));
      await tester.tap(find.text('通过'));
      await tester.pumpAndSettle();
      expect(find.text('确认通过'), findsOneWidget);
      await capture(tester, 'approval-confirm-$themeName');
      await tester.pumpWidget(const SizedBox());
    });
    testWidgets('task states $themeName', (tester) async {
      final api = fixture.Api();
      final repo = VisualBusinessRepository(api);
      final failed = VisualBusinessRepository(api, fail: true);
      addTearDown(repo.dispose);
      addTearDown(failed.dispose);
      addTearDown(api.dispose);
      await show(tester, TaskListScreen(repository: repo),
          const Size(430, 932), dark, 1);
      expect(find.text('整理考勤'), findsOneWidget);
      await capture(tester, 'task-list-$themeName');
      await tester.pumpWidget(const SizedBox());
      await show(tester, TaskListScreen(repository: failed),
          const Size(430, 932), dark, 1);
      expect(find.text('整理考勤'), findsNothing);
      expect(find.text('暂无任务'), findsNothing);
      await capture(tester, 'task-error-$themeName');
      await tester.pumpWidget(const SizedBox());
    });
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
