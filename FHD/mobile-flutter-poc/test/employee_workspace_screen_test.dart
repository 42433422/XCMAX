import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/ai_employee_profile.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/workspace/employee_workspace_screen.dart';
import 'package:xcagi_flutter_poc/src/features/webview/desktop_tool_webview_screen.dart';

const employee = AiEmployeeProfile(
  modId: 'account-mod',
  modName: '企业应用',
  modDescription: '',
  modVersion: '',
  modAuthor: '',
  industryName: '',
  employeeId: 'employee-one',
  name: '订单助理',
  title: '订单助理',
  summary: '核对订单与进度',
  apiBasePath: '/api/mod/account-mod',
  phoneChannel: 'chat',
  workflowPlaceholder: false,
  profileSource: 'installed',
  marketConnected: true,
  marketPkgId: '',
  marketVersion: '',
  marketAuthor: '',
  marketMaterialCategory: '',
  marketLicenseScope: '',
  marketSecurityLevel: '',
);

class Api extends MobileApiClient {
  Api()
      : super(
            sessionStore: MemoryMobileSessionStore(MobileSessionData.empty
                .copyWith(
                    userId: 1,
                    accountKind: 'enterprise',
                    accessToken: 'account-one')));
  bool enabled = false;
  bool failPrefs = false;
  Completer<Map<String, Object?>>? pending;
  final writes = <(String, bool)>[];
  Map<String, Object?> response() => {
        'success': true,
        'owner_id': 'owner-one',
        'data': {
          'workflow_ai_employees': {'employee-one': enabled}
        }
      };
  @override
  Future<Map<String, Object?>> workspacePreferences() async {
    if (failPrefs) throw StateError('offline');
    return response();
  }

  @override
  Future<Map<String, Object?>> setWorkspaceEmployeeEnabled(
      String id, bool value,
      {required int expectedGeneration, required String expectedBase}) async {
    writes.add((id, value));
    if (pending != null) return pending!.future;
    enabled = value;
    return response();
  }
}

class Repository extends MobileRepository {
  Repository(Api api) : super(client: api);
  @override
  Future<List<AiEmployeeProfile>> loadAiEmployees() async => [employee];
  @override
  Future<List<MobileTaskSummary>> loadTasks({int limit = 50}) async => [];
}

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
