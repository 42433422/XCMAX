import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/tasks/task_list_screen.dart';

MobileTaskSummary task({
  String id = 'task/a',
  String conversation = 'chat?b',
}) =>
    MobileTaskSummary.fromJson({
      'task_id': id,
      'title': '整理考勤',
      'conversation_id': conversation,
      'status': 'completed',
      'attention_state': 'result_unread',
    });

class TaskApi extends MobileApiClient {
  final requested = <String>[];
  bool denied = false;
  @override
  Future<MobileEnvelope<MobileTaskSummary>> mobileTaskDetail(
    String taskId,
  ) async {
    requested.add(taskId);
    return MobileEnvelope(
      success: !denied,
      message: denied ? '无权查看' : '',
      data: denied ? null : task(id: taskId),
      raw: const {},
    );
  }
}

class Tasks extends MobileRepository {
  Tasks(this.api) : super(client: api);
  final TaskApi api;
  Future<List<MobileTaskSummary>> Function() load = () async => [];
  int loads = 0;
  @override
  Future<List<MobileTaskSummary>> loadTasks({int limit = 50}) {
    loads++;
    return load();
  }

  @override
  Future<List<MobileDesktopDevice>> loadDesktopDevices() async => [];
}

void main() {
  test('workspace route preserves task and conversation identities', () {
    final uri = Uri.parse(task().workspacePath);
    expect(uri.pathSegments, ['workspaces', 'task/a']);
    expect(uri.queryParameters['conversation'], 'chat?b');
    expect(
      Uri.parse(
        task(conversation: '').workspacePath,
      ).queryParameters['conversation'],
      'task/a',
    );
    expect(
      XcagiMobileEndpoints.taskDetail('task/a?b'),
      'api/mobile/v1/tasks/task%2Fa%3Fb',
    );
  });

  testWidgets('loading, error retry, and empty states remain visible', (
    tester,
  ) async {
    final pending = Completer<List<MobileTaskSummary>>();
    final repo = Tasks(TaskApi())..load = () => pending.future;
    await tester.pumpWidget(
      MaterialApp(home: TaskListScreen(repository: repo)),
    );
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    pending.completeError(const MobileRepositoryException('任务列表加载失败'));
    await tester.pumpAndSettle();
    expect(find.text('下拉刷新，或点击重试'), findsOneWidget);
    expect(find.text('暂无任务'), findsNothing);
    repo.load = () async => [];
    await tester.tap(find.byIcon(Icons.refresh));
    await tester.pumpAndSettle();
    expect(repo.loads, 2);
    expect(find.text('暂无任务'), findsOneWidget);
    expect(find.byType(RefreshIndicator), findsOneWidget);
  });

  testWidgets(
    'task opens fresh detail; denied detail exposes no workspace action',
    (tester) async {
      final api = TaskApi();
      final repo = Tasks(api)..load = () async => [task()];
      await tester.pumpWidget(
        MaterialApp(home: TaskListScreen(repository: repo)),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('整理考勤'));
      await tester.pumpAndSettle();
      expect(api.requested, ['task/a']);
      expect(find.text('查看结果与操作'), findsOneWidget);
      Navigator.of(tester.element(find.text('查看结果与操作'))).pop();
      await tester.pumpAndSettle();
      api.denied = true;
      await tester.tap(find.text('整理考勤'));
      await tester.pumpAndSettle();
      expect(find.text('查看结果与操作'), findsNothing);
      expect(find.textContaining('权限'), findsOneWidget);
      api.denied = false;
      await tester.tap(find.text('重试'));
      await tester.pumpAndSettle();
      expect(api.requested.length, 3);
      expect(find.text('查看结果与操作'), findsOneWidget);
    },
  );
}
