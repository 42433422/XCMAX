import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/approval/native_approval_workspace.dart';
import 'package:xcagi_flutter_poc/src/features/webview/desktop_tool_webview_screen.dart';

class ApprovalApi extends MobileApiClient {
  ApprovalApi()
      : super(
            sessionStore: MemoryMobileSessionStore(MobileSessionData.empty
                .copyWith(userId: 999, accessToken: 'one')));
  final calls = <({
    String path,
    String method,
    Map<String, String> query,
    Map<String, Object?>? body
  })>[];
  String status = 'pending';
  Completer<Map<String, Object?>>? decision;
  Map<String, Object?> get row => {
        'id': 5,
        'title': '采购审批',
        'status': status,
        'applicant_id': 7,
        'current_approvers': [12],
        'request_no': 'A005',
        'business_type': 'purchase',
        'records': <Object>[]
      };
  @override
  Future<Map<String, Object?>> workspaceRequest(String path,
      {String method = 'GET',
      Map<String, String> query = const {},
      Map<String, Object?>? body,
      required int expectedGeneration,
      required String expectedBase,
      String activeModId = ''}) async {
    expect(activeModId, 'xcagi-approval-bridge');
    calls.add((path: path, method: method, query: query, body: body));
    if (path == 'api/auth/session/validate') {
      return {
        'success': true,
        'local_user_id': 12,
        'data': {'user_id': 999}
      };
    }
    if (method != 'GET') return decision?.future ?? {'success': true};
    if (path.endsWith('/requests/5')) return {'success': true, 'data': row};
    if (path.endsWith('/flows')) return {'success': true, 'data': <Object>[]};
    return {
      'success': true,
      'data': [row],
      'pagination': {'total': 51}
    };
  }
}

Future<void> show(WidgetTester tester, ApprovalApi api) async {
  final repo = MobileRepository(client: api);
  addTearDown(() async {
    await repo.dispose();
    api.dispose();
  });
  await tester.pumpWidget(MaterialApp(
      home: NativeApprovalWorkspace(
          repository: repo, apiBase: 'api/mod/xcagi-approval-bridge')));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
      'approval uses local validated identity, scoped native pages and pagination',
      (tester) async {
    final api = ApprovalApi();
    await show(tester, api);
    expect(api.calls.last.query['approver_id'], '12');
    expect(find.byType(DesktopToolWebViewScreen), findsNothing);
    await tester.tap(find.text('下一页'));
    await tester.pumpAndSettle();
    expect(api.calls.last.query['page'], '2');
    await tester.tap(find.text('我发起的'));
    await tester.pumpAndSettle();
    expect(api.calls.last.query['applicant_id'], '12');
    expect(api.calls.last.query['page'], '1');
  });
  testWidgets('approval rechecks current state and waits for decision receipt',
      (tester) async {
    final api = ApprovalApi()..decision = Completer();
    await show(tester, api);
    await tester.tap(find.text('查看详情'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('通过'));
    await tester.pumpAndSettle();
    expect(api.calls.where((c) => c.method != 'GET'), isEmpty);
    await tester.tap(find.text('确认通过'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    final writes = api.calls.where((c) => c.method != 'GET').toList();
    expect(writes, hasLength(1));
    expect(writes.single.body, {'approver_id': 12, 'opinion': '同意'});
    expect(api.calls[api.calls.length - 2].path,
        'api/mod/xcagi-approval-bridge/requests/5');
    expect(find.text('已通过'), findsNothing);
    api.status = 'approved';
    api.decision!.complete({'success': true});
    await tester.pumpAndSettle();
    expect(find.text('已通过'), findsOneWidget);
    expect(find.text('通过'), findsNothing);
  });
  testWidgets('stale approval and account switches cannot submit',
      (tester) async {
    final api = ApprovalApi();
    await show(tester, api);
    await tester.tap(find.text('查看详情'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('拒绝'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextFormField), '需要补充信息');
    api.status = 'withdrawn';
    await tester.tap(find.text('确认拒绝'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    await tester.pumpAndSettle();
    expect(api.calls.where((c) => c.method != 'GET'), isEmpty);
    expect(find.textContaining('状态或权限已变化'), findsOneWidget);
    await api.clearActiveAuth();
    await tester.pumpAndSettle();
    expect(find.text('采购审批'), findsNothing);
    expect(find.textContaining('账号或连接已切换'), findsOneWidget);
  });
  testWidgets('flow creation validates nodes and sends native form fields',
      (tester) async {
    final api = ApprovalApi();
    await show(tester, api);
    await tester.tap(find.text('流程管理'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('新建流程'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('flow_name')), '采购流程');
    await tester.enterText(
        find.byKey(const ValueKey('flow_key')), 'purchase_flow');
    await tester.scrollUntilVisible(
        find.widgetWithText(TextFormField, '节点名称'), 200,
        scrollable: find
            .descendant(
                of: find.byType(ListView).last,
                matching: find.byType(Scrollable))
            .first);
    await tester.enterText(find.widgetWithText(TextFormField, '节点名称'), '经理');
    await tester.scrollUntilVisible(
        find.widgetWithText(TextFormField, '审批人 ID'), 200,
        scrollable: find
            .descendant(
                of: find.byType(ListView).last,
                matching: find.byType(Scrollable))
            .first);
    await tester.enterText(
        find.widgetWithText(TextFormField, '审批人 ID'), '12,13');
    await tester.scrollUntilVisible(find.text('保存流程'), 200,
        scrollable: find
            .descendant(
                of: find.byType(ListView).last,
                matching: find.byType(Scrollable))
            .first);
    await tester.tap(find.text('保存流程'));
    await tester.pumpAndSettle();
    final body = api.calls.firstWhere((c) => c.method == 'POST').body!;
    expect((body['flow'] as Map)['flow_key'], 'purchase_flow');
    expect((body['nodes'] as List).single, {
      'node_name': '经理',
      'node_type': 'serial',
      'node_order': 1,
      'approver_type': 'user',
      'approver_ids': [12, 13],
      'is_active': true
    });
  });
}
