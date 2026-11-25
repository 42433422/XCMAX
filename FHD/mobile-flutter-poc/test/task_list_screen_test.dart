import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/features/tasks/native_task_workspace_screen.dart';
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
  TaskApi()
      : super(sessionStore: MemoryMobileSessionStore(MobileSessionData.empty));
  final requested = <String>[];
  bool denied = false;
  bool offline = false;
  String status = 'completed';
  @override
  Future<Map<String, Object?>> workspaceRequest(
    String path, {
    String method = 'GET',
    Map<String, String> query = const {},
    Map<String, Object?>? body,
    required int expectedGeneration,
    required String expectedBase,
    String activeModId = '',
  }) async {
    requested.add(path);
    if (offline) throw TimeoutException('network timeout');
    if (denied) {
      throw const MobileApiException(
          statusCode: 403, message: '没有权限', body: {});
    }
    return {
      'success': true,
      'data': {
        'task_id': 'task/a',
        'title': '整理考勤',
        'status': status,
        'capabilities': <String, bool>{'pause': status == 'running'}
      }
    };
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
    await tester.pumpWidget(const SizedBox());
    await repo.dispose();
    repo.api.dispose();
  });

  testWidgets('task list recovers by read-only polling after timeout', (
    tester,
  ) async {
    final api = TaskApi();
    final repo = Tasks(api)..load = () async => [task()];
    addTearDown(() async {
      await repo.dispose();
      api.dispose();
    });
    await tester.pumpWidget(MaterialApp(home: TaskListScreen(repository: repo)));
    await tester.pumpAndSettle();
    expect(repo.loads, 1);
    expect(find.text('整理考勤'), findsOneWidget);

    repo.load = () async => throw TimeoutException('network timeout');
    await tester.pump(const Duration(seconds: 15));
    await tester.pumpAndSettle();
    expect(repo.loads, 2);
    expect(find.text('整理考勤'), findsNothing);
    expect(find.text('暂无任务'), findsNothing);

    // First failure waits five seconds, without another parallel request.
    await tester.pump(const Duration(seconds: 4));
    expect(repo.loads, 2);
    repo.load = () async => [task()];
    await tester.pump(const Duration(seconds: 1));
    await tester.pumpAndSettle();
    expect(repo.loads, 3);
    expect(find.text('整理考勤'), findsOneWidget);
    expect(api.requested, isEmpty);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await tester.pump(const Duration(seconds: 60));
    expect(repo.loads, 3);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(repo.loads, 4);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('workspace reconciles original task and hides revoked snapshot', (
    tester,
  ) async {
    final api = TaskApi()..status = 'running';
    final repo = Tasks(api);
    addTearDown(() async {
      await repo.dispose();
      api.dispose();
    });
    await tester.pumpWidget(MaterialApp(
      home: NativeTaskWorkspaceScreen(taskId: 'task/a', repository: repo),
    ));
    await tester.pumpAndSettle();
    expect(find.text('状态：正在处理'), findsOneWidget);
    expect(api.requested.length, 1);

    api.offline = true;
    await tester.pump(const Duration(seconds: 15));
    await tester.pumpAndSettle();
    expect(find.text('状态待同步，暂不可执行任务操作'), findsOneWidget);
    final pause = tester.widget<OutlinedButton>(
      find.widgetWithText(OutlinedButton, '暂停'),
    );
    expect(pause.onPressed, isNull);
    expect(api.requested.length, 2);

    api.offline = false;
    api.status = 'completed';
    await tester.pump(const Duration(seconds: 5));
    await tester.pumpAndSettle();
    expect(find.text('状态：已完成'), findsOneWidget);
    expect(find.text('状态待同步，暂不可执行任务操作'), findsNothing);
    expect(api.requested.length, 3);

    api.denied = true;
    await tester.pump(const Duration(seconds: 15));
    await tester.pumpAndSettle();
    expect(find.text('整理考勤'), findsNothing);
    expect(find.textContaining('权限'), findsOneWidget);
    expect(api.requested.length, 4);
    expect(
      api.requested.toSet(),
      {'api/mobile/v1/workspace/agent/tasks/task%2Fa'},
    );
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets(
      'task opens native result and denied result cannot expose actions',
      (tester) async {
    final api = TaskApi();
    final repo = Tasks(api)..load = () async => [task()];
    addTearDown(() async {
      await repo.dispose();
      api.dispose();
    });
    await tester
        .pumpWidget(MaterialApp(home: TaskListScreen(repository: repo)));
    await tester.pumpAndSettle();
    await tester.tap(find.text('整理考勤'));
    await tester.pumpAndSettle();
    expect(find.byType(NativeTaskWorkspaceScreen), findsOneWidget);
    expect(
        api.requested.single, 'api/mobile/v1/workspace/agent/tasks/task%2Fa');
    Navigator.of(tester.element(find.byType(NativeTaskWorkspaceScreen))).pop();
    await tester.pumpAndSettle();
    api.denied = true;
    await tester.tap(find.text('整理考勤'));
    await tester.pumpAndSettle();
    expect(find.textContaining('权限'), findsOneWidget);
    expect(find.text('审批并执行'), findsNothing);
    api.denied = false;
    await tester.tap(find.byTooltip('刷新任务'));
    await tester.pumpAndSettle();
    expect(api.requested.length, 3);
    expect(find.text('状态：已完成'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });
}
