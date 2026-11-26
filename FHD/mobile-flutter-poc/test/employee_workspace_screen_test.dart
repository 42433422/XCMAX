import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/features/workspace/employee_workspace_screen.dart';
import 'package:xcagi_flutter_poc/src/features/webview/desktop_tool_webview_screen.dart';

import 'employee_workspace_fixture.dart';

Future<void> show(WidgetTester tester, Api api) async {
  tester.view.physicalSize = const Size(430, 1400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final repository = Repository(api);
  addTearDown(repository.dispose);
  addTearDown(api.dispose);
  await tester.pumpWidget(
      MaterialApp(home: EmployeeWorkspaceScreen(repository: repository)));
  await tester.pumpAndSettle();
}

void main() {
  test('employee task identity and step status use explicit assignment data', () {
    final task = MobileTaskSummary.fromJson({
      'task_id': 't-1', 'status': 'running', 'employee_ids': ['employee-one', 'employee-two'],
      'employee_assignments': [{'employee_id': 'employee-one', 'status': 'completed'}, {'employee_id': 'employee-two', 'status': 'running'}],
    });
    expect(task.employeeIds, ['employee-one', 'employee-two']);
    expect(task.employeeStatus('employee-one'), 'completed');
    expect(task.employeeStatus('employee-two'), 'running');
    final uncertain = MobileTaskSummary.fromJson({'status': 'completed', 'outcome_uncertain': true});
    expect(uncertain.employeeStatus('employee-one'), 'unknown');
  });
  testWidgets('native employee cards search without creating a WebView',
      (tester) async {
    final api = Api();
    await show(tester, api);
    expect(find.text('订单助理'), findsOneWidget);
    expect(find.byType(DesktopToolWebViewScreen), findsNothing);
    await tester.enterText(find.byType(TextField), '不存在');
    await tester.pump();
    expect(find.text('订单助理'), findsNothing);
    expect(find.text('暂无符合条件的员工'), findsOneWidget);
  });

  testWidgets('switch updates only after desktop preference service confirms',
      (tester) async {
    final api = Api()..pending = Completer<Map<String, Object?>>();
    await show(tester, api);
    await tester.tap(find.byType(SwitchListTile));
    await tester.pump();
    expect(api.writes, [('employee-one', true)]);
    expect(tester.widget<SwitchListTile>(find.byType(SwitchListTile)).value,
        isFalse);
    api.enabled = true;
    api.pending!.complete(api.response());
    await tester.pumpAndSettle();
    expect(tester.widget<SwitchListTile>(find.byType(SwitchListTile)).value,
        isTrue);
  });

  testWidgets(
      'unknown preferences disable switches rather than inventing state',
      (tester) async {
    await show(tester, Api()..failPrefs = true);
    expect(tester.widget<SwitchListTile>(find.byType(SwitchListTile)).onChanged,
        isNull);
    expect(find.text('等待状态同步'), findsOneWidget);
    expect(find.text('订单助理'), findsOneWidget);
  });

  testWidgets(
      'account change removes previous employee data and rejects late save',
      (tester) async {
    final api = Api()..pending = Completer<Map<String, Object?>>();
    await show(tester, api);
    await tester.tap(find.byType(SwitchListTile));
    await tester.pump();
    await api.clearActiveAuth();
    await tester.pump();
    expect(find.text('订单助理'), findsNothing);
    expect(find.text('账号或连接已切换，请重新打开工作台'), findsOneWidget);
    api.enabled = true;
    api.pending!.complete(api.response());
    await tester.pumpAndSettle();
    expect(find.byType(SwitchListTile), findsNothing);
  });
}
