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
  final detailFields = <String, Object?>{};
  Completer<Map<String, Object?>>? decision;
  Map<String, Object?> get row => {
        'id': 5,
        'title': '采购审批',
        'status': status,
        'applicant_id': 7,
        'current_approvers': [12],
        'request_no': 'A005',
        'business_type': 'purchase',
        'records': <Object>[],
        ...detailFields,
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

class FlowApi extends ApprovalApi {
  Map<String, Object?> flow = {
    'id': 8,
    'flow_name': '现有流程',
    'flow_key': 'existing_flow',
    'description': '原描述',
    'business_type': 'general',
    'is_active': false,
  };
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
    if (!path.contains('/flows')) {
      return super.workspaceRequest(
        path,
        method: method,
        query: query,
        body: body,
        expectedGeneration: expectedGeneration,
        expectedBase: expectedBase,
        activeModId: activeModId,
      );
    }
    expect(activeModId, 'xcagi-approval-bridge');
    calls.add((path: path, method: method, query: query, body: body));
    if (method == 'GET') {
      return {
        'success': true,
        'data': path.endsWith('/flows')
            ? [Map<String, Object?>.from(flow)]
            : {...flow, 'nodes': <Object>[]},
      };
    }
    final result = await (decision?.future ?? Future.value({'success': true}));
    if (result['success'] == true) {
      // Mirror the backend's distinct update and activation contracts.
      if (method == 'PUT') {
        for (final key in ['flow_name', 'description', 'business_type']) {
          if (body!.containsKey(key)) flow[key] = body[key];
        }
      } else if (method == 'PATCH' && path.endsWith('/active')) {
        flow['is_active'] = body!['is_active'];
      }
    }
    return result;
  }
}

Future<void> editFlow(WidgetTester tester, FlowApi api) async {
  await show(tester, api);
  await tester.tap(find.text('流程管理'));
  await tester.pumpAndSettle();
  await tester.tap(find.text('编辑流程'));
  await tester.pumpAndSettle();
}

Future<void> saveFlow(WidgetTester tester) async {
  await tester.scrollUntilVisible(
    find.text('保存流程'),
    200,
    scrollable: find
        .descendant(
          of: find.byType(ListView).last,
          matching: find.byType(Scrollable),
        )
        .first,
  );
  await tester.tap(find.text('保存流程'));
  await tester.pump();
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
    'existing flow saves only editable fields and refills after receipt',
    (tester) async {
      final api = FlowApi()..decision = Completer();
      await editFlow(tester, api);
      final key = tester.widget<TextFormField>(
        find.byKey(const ValueKey('flow_key')),
      );
      expect(
          tester
              .widget<TextField>(find.descendant(
                  of: find.byKey(const ValueKey('flow_key')),
                  matching: find.byType(TextField)))
              .readOnly,
          isTrue);
      expect(key.controller!.text, 'existing_flow');
      final active = tester.widget<SwitchListTile>(find.byType(SwitchListTile));
      expect(active.onChanged, isNull);
      expect(active.value, isFalse);
      await tester.enterText(find.byKey(const ValueKey('flow_name')), '更新名称');
      await saveFlow(tester);
      expect(find.text('编辑审批流程'), findsOneWidget);
      final writes = api.calls.where((c) => c.method != 'GET').toList();
      expect(writes, hasLength(1));
      expect(writes.single.method, 'PUT');
      expect(writes.single.path, 'api/mod/xcagi-approval-bridge/flows/8');
      expect(writes.single.body, {
        'flow_name': '更新名称',
        'description': '原描述',
        'business_type': 'general',
      });
      api.decision!.complete({'success': true});
      await tester.pumpAndSettle();
      expect(find.text('编辑审批流程'), findsNothing);
      expect(find.text('更新名称'), findsOneWidget);
      await tester.tap(find.text('编辑流程'));
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<TextFormField>(find.byKey(const ValueKey('flow_name')))
            .controller!
            .text,
        '更新名称',
      );
      expect(
        tester.widget<SwitchListTile>(find.byType(SwitchListTile)).value,
        isFalse,
      );
    },
  );

  testWidgets(
    'failed flow save preserves draft without activation side effect',
    (tester) async {
      final api = FlowApi()..decision = Completer();
      await editFlow(tester, api);
      await tester.enterText(find.byKey(const ValueKey('flow_name')), '未保存草稿');
      await saveFlow(tester);
      api.decision!.complete({'success': false, 'message': '保存被拒绝'});
      await tester.pumpAndSettle();
      expect(find.text('编辑审批流程'), findsOneWidget);
      expect(find.text('当前账号没有权限，请切换账号或重新绑定'), findsOneWidget);
      expect(api.flow['flow_name'], '现有流程');
      expect(api.calls.where((c) => c.method == 'PATCH'), isEmpty);
      await tester.scrollUntilVisible(
        find.byKey(const ValueKey('flow_name')),
        -200,
        scrollable: find
            .descendant(
              of: find.byType(ListView).last,
              matching: find.byType(Scrollable),
            )
            .first,
      );
      expect(
        tester
            .widget<TextFormField>(find.byKey(const ValueKey('flow_name')))
            .controller!
            .text,
        '未保存草稿',
      );
    },
  );

  testWidgets(
    'activation is a separate confirmed PATCH and waits for receipt',
    (tester) async {
      final api = FlowApi()..decision = Completer();
      await show(tester, api);
      await tester.tap(find.text('流程管理'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('启用'));
      await tester.pumpAndSettle();
      expect(api.calls.where((c) => c.method != 'GET'), isEmpty);
      await tester.tap(find.text('确认'));
      await tester.pump();
      final write = api.calls.singleWhere((c) => c.method != 'GET');
      expect(write.method, 'PATCH');
      expect(write.path, 'api/mod/xcagi-approval-bridge/flows/8/active');
      expect(write.body, {'is_active': true});
      expect(api.flow['is_active'], isFalse);
      api.decision!.complete({'success': true});
      await tester.pumpAndSettle();
      expect(api.flow['is_active'], isTrue);
      expect(find.text('停用'), findsOneWidget);
    },
  );

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
  testWidgets('sales approval summarizes precise amounts on a phone',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final api = ApprovalApi()
      ..detailFields.addAll({
        'business_type': 'workflow_tool',
        'description': '原始销售参数',
        'business_data': {
          'tool_id': 'sales',
          'action': 'create_order',
          'params': {
            'payload': {
              'order': {
                'customer_name': '蜀川商贸',
                'items': [
                  {
                    'product_name': '防水接头',
                    'model_number': 'R-22',
                    'quantity': '3',
                    'unit_price': '2.15',
                  },
                  {'product_name': '胶带', 'quantity': '1.5', 'unit_price': '3'},
                ],
              },
            },
          },
        },
      });
    await show(tester, api);
    await tester.tap(find.text('查看详情'));
    await tester.pumpAndSettle();
    expect(find.text('创建销售订单'), findsOneWidget);
    expect(find.text('蜀川商贸'), findsOneWidget);
    expect(find.text('通过').hitTestable(), findsOneWidget);
    await tester.scrollUntilVisible(
      find.text('10.95 CNY'),
      200,
      scrollable: find
          .descendant(
            of: find.byType(ListView).last,
            matching: find.byType(Scrollable),
          )
          .first,
    );
    expect(find.text('10.95 CNY'), findsOneWidget);
    expect(find.text('通过').hitTestable(), findsOneWidget);
  });

  testWidgets('expired workflow cannot approve and can still reject',
      (tester) async {
    final api = ApprovalApi()..detailFields['business_type'] = 'workflow_tool';
    await show(tester, api);
    await tester.tap(find.text('查看详情'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('通过'));
    await tester.pumpAndSettle();
    api.detailFields['runtime_available'] = false;
    await tester.tap(find.text('确认通过'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    await tester.pumpAndSettle();
    expect(api.calls.where((c) => c.method != 'GET'), isEmpty);
    expect(find.text('通过'), findsNothing);
    expect(find.text('拒绝').hitTestable(), findsOneWidget);
    expect(find.textContaining('请拒绝这条申请'), findsOneWidget);
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
