import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/tasks/native_task_workspace_screen.dart';
import 'native_task_approval_snapshot_test.dart' show ApprovalApi;

class ClarificationApi extends ApprovalApi {
  String stepId = 'question-1', fieldType = 'integer';
  Completer<void>? gate;
  Object? answerFailure;
  String targetCustomer = 'original';
  String attention = '';
  bool clarification = true, failRead = false;
  int reads = 0;
  final answers = <Map<String, Object?>>[];
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
    if (path.endsWith('/clarification')) {
      answers.add({'path': path, ...?body});
      if (answerFailure != null) throw answerFailure!;
      return {'success': true};
    }
    if (path.endsWith('/read')) {
      reads++;
      if (failRead) {
        throw const MobileApiException(
            statusCode: 503, message: '暂不可用', body: {});
      }
      attention = '';
      return {'success': true};
    }
    await gate?.future;
    final result = await super.workspaceRequest(path,
        method: method,
        query: query,
        body: body,
        expectedGeneration: expectedGeneration,
        expectedBase: expectedBase);
    final task = result['data'] as Map<String, Object?>;
    task['attention_state'] = attention;
    if (clarification) {
      final active = task['active_run'] as Map<String, Object?>;
      active['final_output'] = {
        'clarification': {
          'step_id': stepId,
          'question': '补齐数量和客户',
          'fields': [
            {'key': 'quantity', 'label': '数量', 'type': fieldType},
            {'key': 'unit_name', 'label': '客户', 'type': 'string'},
          ],
        }
      };
      active['steps'] = [
        {
          'step_id': stepId,
          'status': 'waiting_user',
          'tool_id': 'clarify',
          'action': 'ask',
          'params': {'target_node_id': 'target'},
        },
        {
          'step_id': 'target-step',
          'node_id': 'target',
          'status': 'pending',
          'tool_id': 'synthetic',
          'action': 'create',
          'params': {'customer': targetCustomer},
        }
      ];
    }
    return result;
  }
}

Future<void> openTask(WidgetTester tester, ClarificationApi api) async {
  final repo = MobileRepository(client: api);
  addTearDown(() async {
    await repo.dispose();
    api.dispose();
  });
  await tester.pumpWidget(MaterialApp(
      home: NativeTaskWorkspaceScreen(taskId: 'task-1', repository: repo)));
  await tester.pumpAndSettle();
}

Future<void> openQuestion(WidgetTester tester) async {
  await tester.tap(find.text('补充任务信息'));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 300));
}

Future<void> fill(WidgetTester tester) async {
  await tester.enterText(find.byType(TextFormField).at(0), '2');
  await tester.enterText(
      find.byType(TextFormField).at(1), ' synthetic customer ');
}

void main() {
  for (final failure in ['timeout', '503']) {
    testWidgets(
        '$failure after clarification POST cannot be replayed after refresh',
        (tester) async {
      final api = ClarificationApi()
        ..answerFailure = failure == 'timeout'
            ? TimeoutException('synthetic response loss')
            : const MobileApiException(
                statusCode: 503, message: 'synthetic unavailable', body: {});
      await openTask(tester, api);
      await openQuestion(tester);
      await fill(tester);
      await tester.tap(find.text('补充信息并继续'));
      await tester.pumpAndSettle();
      expect(api.answers.length, 1);
      api.answerFailure = null;
      await tester.tap(find.byTooltip('刷新任务'));
      await tester.pumpAndSettle();
      final button = find.widgetWithText(OutlinedButton, '补充任务信息');
      expect(tester.widget<OutlinedButton>(button).onPressed, isNull);
      await tester.tap(button);
      await tester.pumpAndSettle();
      expect(api.answers.length, 1);
      expect(find.byType(AlertDialog), findsNothing);
      await tester.pumpWidget(const SizedBox());
    });
  }
  testWidgets(
      'same run and question with changed target parameters rejects old answer',
      (tester) async {
    final api = ClarificationApi();
    await openTask(tester, api);
    await openQuestion(tester);
    await fill(tester);
    api.targetCustomer = 'replacement';
    await tester.tap(find.text('补充信息并继续'));
    await tester.pumpAndSettle();
    expect(api.answers, isEmpty);
    expect(find.textContaining('待回答问题已变化'), findsOneWidget);
    expect(api.run, 'run-a');
    expect(api.stepId, 'question-1');
    await tester.pumpWidget(const SizedBox());
  });

  for (final type in ['boolean', 'object', 'array']) {
    testWidgets('unsupported $type fields are blocked explicitly',
        (tester) async {
      final api = ClarificationApi()..fieldType = type;
      await openTask(tester, api);
      await tester.tap(find.text('补充任务信息'));
      await tester.pumpAndSettle();
      expect(find.textContaining('请打开任务对话'), findsOneWidget);
      expect(api.answers, isEmpty);
      await tester.pumpWidget(const SizedBox());
    });
  }
  for (final leave in ['route', 'account']) {
    testWidgets(
        '$leave change before rendering unread result does not acknowledge',
        (tester) async {
      final api = ClarificationApi()
        ..clarification = false
        ..attention = 'result_unread'
        ..gate = Completer<void>();
      final repo = MobileRepository(client: api),
          navigator = GlobalKey<NavigatorState>();
      addTearDown(() async {
        await repo.dispose();
        api.dispose();
      });
      await tester.pumpWidget(
          MaterialApp(navigatorKey: navigator, home: const Scaffold()));
      unawaited(navigator.currentState!.push(MaterialPageRoute<void>(
          builder: (_) =>
              NativeTaskWorkspaceScreen(taskId: 'task-1', repository: repo))));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));
      if (leave == 'route') {
        navigator.currentState!.pop();
      } else {
        await api.clearActiveAuth();
      }
      await tester.pump();
      api.gate!.complete();
      await tester.pumpAndSettle();
      expect(api.reads, 0);
      await tester.pumpWidget(const SizedBox());
    });
  }

  testWidgets('missing fields replace approval with typed exact-step answer',
      (tester) async {
    final api = ClarificationApi();
    await openTask(tester, api);
    expect(find.text('审批并执行'), findsNothing);
    await openQuestion(tester);
    await tester.tap(find.text('补充信息并继续'));
    await tester.pump();
    expect(api.answers, isEmpty);
    await tester.enterText(find.byType(TextFormField).at(0), '2.5');
    await tester.enterText(find.byType(TextFormField).at(1), 'synthetic');
    await tester.tap(find.text('补充信息并继续'));
    await tester.pump();
    expect(api.answers, isEmpty);
    await fill(tester);
    await tester.tap(find.text('补充信息并继续'));
    await tester.pumpAndSettle();
    expect(api.answers.single['step_id'], 'question-1');
    expect(api.answers.single['parameters'],
        {'quantity': 2, 'unit_name': 'synthetic customer'});
    expect(api.submitted, isEmpty);
    expect(
        tester
            .widget<OutlinedButton>(
                find.widgetWithText(OutlinedButton, '补充任务信息'))
            .onPressed,
        isNull);
    await tester.pumpWidget(const SizedBox());
  });
  for (final change in ['run', 'step', 'account']) {
    testWidgets('$change change while answering cannot submit old values',
        (tester) async {
      final api = ClarificationApi();
      await openTask(tester, api);
      await openQuestion(tester);
      await fill(tester);
      if (change == 'run') api.run = 'new-run';
      if (change == 'step') api.stepId = 'new-question';
      if (change == 'account') await api.clearActiveAuth();
      await tester.tap(find.text('补充信息并继续'));
      await tester.pumpAndSettle();
      expect(api.answers, isEmpty);
      await tester.pumpWidget(const SizedBox());
    });
  }
  testWidgets('dismissed question submits nothing', (tester) async {
    final api = ClarificationApi();
    await openTask(tester, api);
    await openQuestion(tester);
    await tester.tap(find.text('返回'));
    await tester.pumpAndSettle();
    expect(api.answers, isEmpty);
    await tester.pumpWidget(const SizedBox());
  });
  testWidgets('opening unread result acknowledges once, not approval attention',
      (tester) async {
    final api = ClarificationApi()
      ..clarification = false
      ..attention = 'result_unread';
    await openTask(tester, api);
    expect(api.reads, 1);
    await tester.tap(find.byTooltip('刷新任务'));
    await tester.pumpAndSettle();
    expect(api.reads, 1);
    api.attention = 'approval_required';
    await tester.tap(find.byTooltip('刷新任务'));
    await tester.pumpAndSettle();
    expect(api.reads, 1);
    await tester.pumpWidget(const SizedBox());
  });
  testWidgets(
      'failed read acknowledgement stays retryable without hiding result',
      (tester) async {
    final api = ClarificationApi()
      ..clarification = false
      ..attention = 'result_unread'
      ..failRead = true;
    await openTask(tester, api);
    expect(api.reads, 1);
    expect(find.textContaining('已读状态未同步'), findsOneWidget);
    api.failRead = false;
    await tester.tap(find.byTooltip('刷新任务'));
    await tester.pumpAndSettle();
    expect(api.reads, 2);
    await tester.pumpWidget(const SizedBox());
  });
}
