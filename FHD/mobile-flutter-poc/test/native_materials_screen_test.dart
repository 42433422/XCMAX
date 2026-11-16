import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/business/native_materials_screen.dart';
import 'package:xcagi_flutter_poc/src/features/webview/desktop_tool_webview_screen.dart';

class MaterialApi extends MobileApiClient {
  MaterialApi()
      : super(
            sessionStore: MemoryMobileSessionStore(MobileSessionData.empty
                .copyWith(userId: 1, accessToken: 'one')));
  final writes = <({String path, Map<String, Object?>? body})>[];
  final reads = <({String path, Map<String, String> query})>[];
  bool fail = false;
  Completer<Map<String, Object?>>? saving;
  @override
  Future<Map<String, Object?>> workspaceRequest(String path,
      {String method = 'GET',
      Map<String, String> query = const {},
      Map<String, Object?>? body,
      required int expectedGeneration,
      required String expectedBase,
      String activeModId = ''}) async {
    expect(activeModId, 'customer-erp');
    if (method != 'GET') {
      writes.add((path: path, body: body));
      return saving?.future ?? {'success': true};
    }
    reads.add((path: path, query: query));
    if (fail) throw StateError('读取失败');
    if (path == 'api/system/industry') {
      return {
        'success': true,
        'data': {'id': '考勤'}
      };
    }
    if (path == 'api/materials') {
      return {
        'success': true,
        'categories': ['资源'],
        'data': [
          {'id': 1, 'name': '测试资源', 'quantity': 4, 'price': 8, 'min_stock': 5}
        ]
      };
    }
    if (path == 'api/inventory/warehouses') {
      return {
        'success': true,
        'data': [
          {'id': 2, 'name': '主仓库', 'code': 'WH1'}
        ]
      };
    }
    if (path == 'api/inventory/locations') {
      return {
        'success': true,
        'data': [
          {'id': 3, 'name': '一号库位', 'code': 'A01', 'max_capacity': 20}
        ]
      };
    }
    return {'success': true, 'data': <Object>[]};
  }
}

Future<void> show(WidgetTester tester, MaterialApi api) async {
  final repo = MobileRepository(client: api);
  addTearDown(() async {
    await repo.dispose();
    api.dispose();
  });
  await tester.pumpWidget(MaterialApp(
      home: NativeMaterialsScreen(
          repository: repo, title: '排班资源', activeModId: 'customer-erp')));
  await tester.pumpAndSettle();
}

Future<void> scroll(WidgetTester tester, Finder finder) async {
  await tester.scrollUntilVisible(finder, 180,
      scrollable: find
          .descendant(
              of: find.byType(ListView).last, matching: find.byType(Scrollable))
          .first);
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
      'native resources respect industry labels, warnings, search and warehouse scope',
      (tester) async {
    final api = MaterialApi();
    await show(tester, api);
    expect(find.byType(DesktopToolWebViewScreen), findsNothing);
    expect(find.text('资源明细'), findsWidgets);
    expect(find.text('低于库存预警值'), findsOneWidget);
    await tester.enterText(find.byType(TextField).first, '测试');
    await tester.testTextInput.receiveAction(TextInputAction.search);
    await tester.pumpAndSettle();
    expect(api.reads.last.query['search'], '测试');
    await tester.tap(find.text('场所库位'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('管理库位'));
    await tester.pumpAndSettle();
    expect(api.reads.last.query['warehouse_id'], '2');
    expect(find.text('一号库位'), findsOneWidget);
  });
  testWidgets(
      'inventory operation validates positive quantity and awaits server receipt',
      (tester) async {
    final api = MaterialApi()..saving = Completer();
    await show(tester, api);
    await tester.tap(find.text('调拨'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('入库'));
    await tester.pumpAndSettle();
    for (final entry in {'product_id': '测试资源', 'warehouse_id': '主仓库'}.entries) {
      await tester.tap(find.byKey(ValueKey(entry.key)));
      await tester.pumpAndSettle();
      await tester.tap(find.text(entry.value).last);
      await tester.pumpAndSettle();
    }
    await tester.enterText(find.byKey(const ValueKey('quantity')), '0');
    await scroll(tester, find.text('保存'));
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.writes, isEmpty);
    await scroll(tester, find.byKey(const ValueKey('quantity')));
    await tester.enterText(find.byKey(const ValueKey('quantity')), '3');
    await scroll(tester, find.text('保存'));
    await tester.tap(find.text('保存'));
    await tester.pump();
    expect(api.writes.single.path, 'api/inventory/in');
    expect(api.writes.single.body, {
      'product_id': 1,
      'warehouse_id': 2,
      'quantity': 3,
      'batch_no': '',
      'remark': ''
    });
    expect(find.text('正在保存…'), findsOneWidget);
    api.saving!.complete({'success': true});
    await tester.pumpAndSettle();
    expect(find.text('正在保存…'), findsNothing);
  });
  testWidgets(
      'failed resource refresh disables writes and account change clears forms',
      (tester) async {
    final api = MaterialApi();
    await show(tester, api);
    api.fail = true;
    await tester.tap(find.byTooltip('刷新'));
    await tester.pumpAndSettle();
    expect(
        tester
            .widget<FilledButton>(find.widgetWithText(FilledButton, '添加'))
            .onPressed,
        isNull);
    api.fail = false;
    await tester.tap(find.byTooltip('刷新'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('添加'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('name')), '私有资源');
    await api.clearActiveAuth();
    await tester.pumpAndSettle();
    expect(find.text('私有资源'), findsNothing);
    expect(find.textContaining('账号或连接已切换'), findsOneWidget);
    expect(api.writes, isEmpty);
  });
}
