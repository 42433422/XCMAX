import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/tasks/native_task_workspace_screen.dart';

class ApprovalApi extends MobileApiClient {
  ApprovalApi()
    : super(
        sessionStore: MemoryMobileSessionStore(
          MobileSessionData.empty.copyWith(userId: 1, accessToken: 'synthetic'),
        ),
      );
  String run = 'run-a', revision = 'original';
  int snapshots = 0;
  final submitted = <String>[];
  bool reject = false;

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
    if (path.endsWith('/continue')) {
      final grant = body!['approval_grant'] as String;
      submitted.add(grant);
      if (reject || grant != '$run:$revision') {
        throw const MobileApiException(
          statusCode: 403,
          message: '审批内容已变化',
          body: {},
        );
      }
      return {'success': true};
    }
    final step = {
      'step_id': 'step-1',
      'status': 'waiting_user',
      'tool_id': 'synthetic_inventory',
      'action': 'stock_out',
      'description': '测试出库',
      'risk': 'high',
      'params': {'quantity': revision == 'original' ? 1 : 100},
    };
    final data = {
      'run_id': run,
      'steps': [step],
    };
    if (path.contains('/runs/')) {
      snapshots++;
      return {
        'success': true,
        'data': data,
        'approval': {
          'run_id': run,
          'step_id': 'step-1',
          'grant': '$run:$revision',
        },
      };
    }
    return {
      'success': true,
      'data': {
        'task_id': 'task-1',
        'title': '隔离审批测试',
        'status': 'waiting_user',
        'active_run_id': run,
        'active_run': data,
        'capabilities': {'approve': true},
      },
    };
  }
}

Future<void> showApproval(WidgetTester tester, ApprovalApi api) async {
  final repository = MobileRepository(client: api);
  addTearDown(() async {
    await repository.dispose();
    api.dispose();
  });
  await tester.pumpWidget(
    MaterialApp(
      home: NativeTaskWorkspaceScreen(taskId: 'task-1', repository: repository),
    ),
  );
  await tester.pumpAndSettle();
  await tester.tap(find.text('审批并执行'));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 300));
}

void main() {
  testWidgets('confirmation submits only the displayed action-bound grant', (
    tester,
  ) async {
    final api = ApprovalApi();
    await showApproval(tester, api);
    expect(
      find.descendant(
        of: find.byType(AlertDialog),
        matching: find.textContaining('数量：1'),
      ),
      findsOneWidget,
    );
    expect(api.snapshots, 1);
    await tester.tap(find.text('确认'));
    await tester.pumpAndSettle();
    expect(api.submitted, ['run-a:original']);
    expect(api.snapshots, 1);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets(
    'parameter change rejects old grant without silent approval refresh',
    (tester) async {
      final api = ApprovalApi();
      await showApproval(tester, api);
      api.revision = 'changed';
      await tester.tap(find.text('确认'));
      await tester.pumpAndSettle();
      expect(api.submitted, ['run-a:original']);
      expect(api.snapshots, 1);
      expect(find.textContaining('重新确认'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets('a replacement active run requires a new user decision', (
    tester,
  ) async {
    final api = ApprovalApi();
    await showApproval(tester, api);
    api.run = 'run-b';
    await tester.tap(find.text('确认'));
    await tester.pumpAndSettle();
    expect(api.submitted, isEmpty);
    expect(api.snapshots, 1);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('a rejected grant is never replaced automatically', (
    tester,
  ) async {
    final api = ApprovalApi()..reject = true;
    await showApproval(tester, api);
    await tester.tap(find.text('确认'));
    await tester.pumpAndSettle();
    expect(api.submitted, ['run-a:original']);
    expect(api.snapshots, 1);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('dismissal does not submit and reopening gets a fresh snapshot', (
    tester,
  ) async {
    final api = ApprovalApi();
    await showApproval(tester, api);
    await tester.tap(find.text('返回'));
    await tester.pumpAndSettle();
    expect(api.submitted, isEmpty);
    api.revision = 'changed';
    await tester.tap(find.text('审批并执行'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    expect(api.snapshots, 2);
    await tester.tap(find.text('确认'));
    await tester.pumpAndSettle();
    expect(api.submitted, ['run-a:changed']);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('account switch while confirming never submits approval', (
    tester,
  ) async {
    final api = ApprovalApi();
    await showApproval(tester, api);
    await api.clearActiveAuth();
    await tester.pump();
    await tester.tap(find.text('确认'));
    await tester.pumpAndSettle();
    expect(api.submitted, isEmpty);
    await tester.pumpWidget(const SizedBox());
  });
}
