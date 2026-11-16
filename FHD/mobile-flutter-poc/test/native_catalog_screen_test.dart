import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/business/native_catalog_screen.dart';
import 'package:xcagi_flutter_poc/src/features/webview/desktop_tool_webview_screen.dart';

class CatalogApi extends MobileApiClient {
  CatalogApi()
      : super(
            sessionStore: MemoryMobileSessionStore(MobileSessionData.empty
                .copyWith(userId: 1, accessToken: 'one')));
  final calls = <({
    String path,
    String method,
    Map<String, String> query,
    Map<String, Object?>? body
  })>[];
  @override
  Future<List<int>> workspaceFileRequest(
    String path, {
    Map<String, String> query = const {},
    List<int>? upload,
    String name = '',
    String field = 'file',
    required int expectedGeneration,
    required String expectedBase,
    String activeModId = '',
  }) async {
    calls.add((path: path, method: 'DOWNLOAD', query: query, body: null));
    throw StateError('Test stops before platform sharing');
  }

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
    calls.add((path: path, method: method, query: query, body: body));
    if (method != 'GET') {
      return saving?.future ?? Future.value({'success': true});
    }
    if (path == 'api/mobile/v1/workspace/templates') {
      return {
        'success': true,
        'templates': [
          {
            'id': 'fs:a.docx',
            'filename': '企业价目.docx',
            'name': '企业价目',
            'category': 'word'
          },
          {
            'id': 'fs:b.docx',
            'filename': '   ',
            'name': '客户价格表',
            'category': 'word'
          },
          {'id': 'fs:price_list_c.docx', 'name': 'English', 'category': 'word'},
          {
            'id': 'virtual',
            'name': '虚拟价目',
            'category': 'word',
            'virtual': true
          },
          {'id': 'excel', 'name': 'Excel价目', 'category': 'excel'},
          {'id': 'other', 'name': '普通合同', 'category': 'word'},
        ]
      };
    }
    if (path == 'api/system/industry') {
      return {
        'success': true,
        'data': {
          'config': {
            'subsystems': {
              'products': {
                'fields': [
                  {
                    'key': 'specification',
                    'label': '班次',
                    'validators': [
                      {
                        'type': 'oneOf',
                        'params': ['早班', '晚班']
                      }
                    ]
                  }
                ]
              }
            }
          }
        }
      };
    }
    if (path.endsWith('/units')) {
      return {
        'success': true,
        'data': ['客户甲']
      };
    }
    if (fail) throw StateError('读取失败');
    if (path.endsWith('/records')) {
      return {
        'success': true,
        'data': [
          {
            'id': 9,
            'product_name': '出货产品',
            'purchase_unit': '客户甲',
            'quantity_tins': 2,
            'tin_spec': 5,
            'quantity_kg': 10,
            'unit_price': 8,
            'amount': 80,
            'status': 'pending'
          },
          {
            'id': 10,
            'product_name': '已打印产品',
            'purchase_unit': '客户甲',
            'quantity_tins': 1,
            'tin_spec': 5,
            'status': 'printed'
          },
        ]
      };
    }
    return {
      'success': true,
      'total': 31,
      'data': query['page'] == '2'
          ? [
              {'id': 2, 'name': '第二页'}
            ]
          : [
              {
                'id': 1,
                'name': '产品甲',
                'model_number': 'A01',
                'unit': '客户甲',
                'price': 12,
                'quantity': 4,
                'specification': '早班'
              }
            ]
    };
  }
}

Future<void> show(WidgetTester tester, CatalogApi api,
    {String resource = 'products'}) async {
  final repository = MobileRepository(client: api);
  addTearDown(() async {
    await repository.dispose();
    api.dispose();
  });
  await tester.pumpWidget(MaterialApp(
      home: NativeCatalogScreen(
          repository: repository,
          resource: resource,
          apiBase: 'api/mod/account-erp',
          title: resource == 'products' ? '产品' : '客户')));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
      'Word prices retain desktop Chinese and English template matching',
      (tester) async {
    final api = CatalogApi();
    await show(tester, api);
    await tester.tap(find.byTooltip('导入与导出'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('导出 Word 价格表'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    for (final title in ['企业价目', '客户价格表', 'English', '默认价格表模板']) {
      expect(find.text(title), findsOneWidget);
    }
    for (final title in ['虚拟价目', 'Excel价目', '普通合同']) {
      expect(find.text(title), findsNothing);
    }
    await tester.tap(find.text('客户价格表'));
    await tester.pumpAndSettle();
    expect(api.calls.last.method, 'DOWNLOAD');
    expect(api.calls.last.query['template_id'], 'b');
  });
  test('native routes retain exact authorized Mod and reject unrelated paths',
      () {
    expect(nativeCatalogRoute('/mod/customer-erp/products')?.base,
        'api/mod/customer-erp');
    expect(nativeCatalogRoute('/customers')?.resource, 'customers');
    for (final path in [
      'https://evil/products',
      '//evil/products',
      '/mod/a/tools',
      '/mod/a/products/../customers',
      '/mod/a%2Fb/products'
    ]) {
      expect(nativeCatalogRoute(path), isNull, reason: path);
    }
  });
  testWidgets(
      'shipment records require a unit, filter status, and delete by confirmed JSON body',
      (tester) async {
    final api = CatalogApi();
    await show(tester, api, resource: 'shipment-records');
    expect(find.text('请先选择购买单位'), findsOneWidget);
    expect(api.calls.where((c) => c.path.endsWith('/records')), isEmpty);
    await tester.tap(find.byType(DropdownButtonFormField<String>).first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('客户甲').last);
    await tester.pumpAndSettle();
    expect(api.calls.last.path,
        'api/mod/account-erp/shipment/shipment-records/records');
    expect(api.calls.last.query['unit_name'], '客户甲');
    await tester.tap(find.text('未打印'));
    await tester.pumpAndSettle();
    expect(find.text('已打印产品'), findsNothing);
    await tester.scrollUntilVisible(find.text('删除'), 200,
        scrollable: find
            .descendant(
                of: find.byType(ListView).last,
                matching: find.byType(Scrollable))
            .first);
    await tester.ensureVisible(find.widgetWithText(TextButton, '删除'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('删除'));
    await tester.pumpAndSettle();
    expect(api.calls.where((c) => c.method != 'GET'), isEmpty);
    await tester.tap(find.text('确认删除'));
    await tester.pumpAndSettle();
    final write = api.calls.firstWhere((c) => c.method == 'DELETE');
    expect(write.body, {'id': 9});
    expect(write.query, isEmpty);
  });
  testWidgets('native list supports server search and pagination within Mod',
      (tester) async {
    final api = CatalogApi();
    await show(tester, api);
    expect(find.byType(DesktopToolWebViewScreen), findsNothing);
    expect(find.text('班次：早班'), findsOneWidget);
    await tester.enterText(find.byType(TextField).first, '名称');
    await tester.testTextInput.receiveAction(TextInputAction.search);
    await tester.pumpAndSettle();
    expect(api.calls.last.query['keyword'], '名称');
    await tester.scrollUntilVisible(find.text('加载更多'), 200,
        scrollable: find
            .descendant(
                of: find.byType(ListView).last,
                matching: find.byType(Scrollable))
            .first);
    await tester.tap(find.text('加载更多'));
    await tester.pumpAndSettle();
    expect(api.calls.last.path, 'api/mod/account-erp/products/list');
    expect(api.calls.last.query['page'], '2');
    expect(find.text('第二页'), findsOneWidget);
  });
  testWidgets('native edit preserves fields and awaits successful save',
      (tester) async {
    final api = CatalogApi()..saving = Completer();
    await show(tester, api);
    await tester.tap(find.byTooltip('编辑 产品甲'));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('field-quantity')), findsNothing);
    await tester.enterText(find.byKey(const ValueKey('field-price')), '18.50');
    await tester.scrollUntilVisible(find.text('保存'), 200,
        scrollable: find
            .descendant(
                of: find.byType(ListView).last,
                matching: find.byType(Scrollable))
            .first);
    await tester.tap(find.text('保存'));
    await tester.pump();
    final write = api.calls.last;
    expect(write.path, 'api/mod/account-erp/products/update');
    expect(write.body, containsPair('id', 1));
    expect(write.body, containsPair('price', 18.5));
    expect(write.body, containsPair('specification', '早班'));
    expect(find.text('正在保存…'), findsOneWidget);
    api.saving!.complete({'success': true});
    await tester.pumpAndSettle();
    expect(find.text('正在保存…'), findsNothing);
    expect(api.calls.last.path, 'api/mod/account-erp/products/list');
  });
  testWidgets(
      'failed refresh blocks edits and deletion uses explicit confirmation',
      (tester) async {
    final api = CatalogApi();
    await show(tester, api);
    await tester.ensureVisible(find.widgetWithText(TextButton, '删除'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('删除'));
    await tester.pumpAndSettle();
    expect(api.calls.where((c) => c.method != 'GET'), isEmpty);
    await tester.tap(find.text('取消'));
    await tester.pumpAndSettle();
    api.fail = true;
    await tester.tap(find.byTooltip('刷新'));
    await tester.pumpAndSettle();
    expect(
        tester
            .widget<IconButton>(
                find.widgetWithIcon(IconButton, Icons.edit_outlined))
            .onPressed,
        isNull);
    expect(
        tester
            .widget<FilledButton>(find.widgetWithText(FilledButton, '新建'))
            .onPressed,
        isNull);
  });
  testWidgets('account switch clears native editor and ignores late save',
      (tester) async {
    final api = CatalogApi()..saving = Completer();
    await show(tester, api);
    await tester.tap(find.byTooltip('编辑 产品甲'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('保存'), 200,
        scrollable: find
            .descendant(
                of: find.byType(ListView).last,
                matching: find.byType(Scrollable))
            .first);
    await tester.tap(find.text('保存'));
    await tester.pump();
    await api.clearActiveAuth();
    await tester.pumpAndSettle();
    expect(find.text('产品甲'), findsNothing);
    expect(find.textContaining('账号或连接已切换'), findsWidgets);
    api.saving!.complete({'success': true});
    await tester.pumpAndSettle();
    expect(find.text('产品甲'), findsNothing);
  });
}
