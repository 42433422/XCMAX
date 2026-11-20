import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/business/native_orders_screen.dart';
import 'package:xcagi_flutter_poc/src/features/webview/desktop_tool_webview_screen.dart';

class Api extends MobileApiClient {
  Api()
      : super(
            sessionStore: MemoryMobileSessionStore(MobileSessionData.empty
                .copyWith(userId: 1, accessToken: 'one')));
  final writes = <Map<String, Object?>>[];
  final paths = <String>[];
  final deletes = <String>[];
  Completer<Map<String, Object?>>? generation;
  bool fail = false, missingTemplate = false;
  String unitName = '客户甲';
  @override
  Future<Map<String, Object?>> workspaceRequest(String path,
      {String method = 'GET',
      Map<String, String> query = const {},
      Map<String, Object?>? body,
      required int expectedGeneration,
      required String expectedBase,
      String activeModId = ''}) async {
    paths.add(path);
    expect(activeModId, 'tenant-erp');
    if (method == 'DELETE') deletes.add(path);
    if (path.endsWith('/generate')) {
      writes.add(body!);
      return generation!.future;
    }
    if (path == 'api/mobile/v1/workspace/templates') {
      return {
        'success': true,
        'templates': [
          if (!missingTemplate)
            {
              'id': 'db:1',
              'name': '企业发货单',
              'category': 'excel',
              'business_scope': 'orders'
            }
        ]
      };
    }
    if (path.endsWith('/purchase_units')) {
      return {
        'success': true,
        'data': [
          if (unitName.isNotEmpty)
            {'unit_name': unitName, 'contact_person': '张先生'}
        ]
      };
    }
    if (path.endsWith('/next_number')) {
      return {
        'success': true,
        'data': {'order_number': '20261117A001'}
      };
    }
    if (path.endsWith('/products/list')) {
      return {
        'success': true,
        'data': [
          {
            'id': 1,
            'name': '产品甲',
            'model_number': 'A01',
            'specification': '5',
            'price': 8
          },
          {
            'id': 2,
            'name': '产品乙',
            'model_number': 'B02',
            'specification': '2',
            'price': 3,
          },
        ],
        'total': 2
      };
    }
    if (fail) throw StateError('读取失败');
    return {
      'success': true,
      'data': {
        'success': true,
        'data': [
          {
            'id': 2,
            'order_number': '历史单号',
            'purchase_unit': '客户甲',
            'total_amount': 40
          }
        ]
      }
    };
  }
}

Future<void> show(WidgetTester tester, Api api, {bool direct = false}) async {
  final repo = MobileRepository(client: api);
  addTearDown(() async {
    await repo.dispose();
    api.dispose();
  });
  await tester.pumpWidget(MaterialApp(
    home: direct
        ? NativeOrderFormScreen(repository: repo, apiBase: 'api/mod/tenant-erp')
        : NativeOrdersScreen(repository: repo, apiBase: 'api/mod/tenant-erp'),
  ));
  await tester.pumpAndSettle();
}

void main() {
  for (final nextUnit in ['客户改名', '']) {
    testWidgets(
        'option refresh clears removed selection ($nextUnit) but preserves draft',
        (tester) async {
      await tester.binding.setSurfaceSize(const Size(1000, 1800));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final api = Api();
      await show(tester, api);
      await tester.tap(find.text('新建订单'));
      await tester.pumpAndSettle();
      await tester.tap(find.byType(DropdownButtonFormField<String>).first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('企业发货单').last);
      await tester.pumpAndSettle();
      await tester.tap(find.byType(DropdownButtonFormField<String>).last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('客户甲').last);
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('选择产品'));
      await tester.tap(find.text('选择产品'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('产品甲'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('添加所选产品（1）'));
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip('刷新选项'));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(
          tester
              .state<FormFieldState<String>>(
                  find.byType(DropdownButtonFormField<String>).first)
              .value,
          'db:1');
      expect(
          tester
              .state<FormFieldState<String>>(
                  find.byType(DropdownButtonFormField<String>).last)
              .value,
          '客户甲');
      api.unitName = nextUnit;
      api.missingTemplate = true;
      await tester.tap(find.byTooltip('刷新选项'));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      for (final field
          in find.byType(DropdownButtonFormField<String>).evaluate()) {
        expect((field as StatefulElement).state, isA<FormFieldState<String>>());
        expect((field.state as FormFieldState<String>).value, isNull);
      }
      expect(find.text('产品甲'), findsOneWidget);
      expect(find.text('订单编号：20261117A001'), findsOneWidget);
      expect(find.textContaining('张先生'), findsNothing);
      await tester.tap(find.text('生成发货单'));
      await tester.pumpAndSettle();
      expect(api.writes, isEmpty);
    });
  }

  testWidgets('orders normalize the real Mod envelope and never open WebView',
      (tester) async {
    final api = Api();
    await show(tester, api);
    expect(find.text('历史单号'), findsOneWidget);
    expect(find.byType(DesktopToolWebViewScreen), findsNothing);
    await tester.enterText(find.byType(TextField), '客户甲');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    expect(api.paths.last, 'api/mod/tenant-erp/orders/search');
    api.fail = true;
    await tester.tap(find.byTooltip('刷新'));
    await tester.pumpAndSettle();
    expect(
        tester
            .widget<FilledButton>(find.widgetWithText(FilledButton, '新建订单'))
            .onPressed,
        isNull);
  });
  testWidgets('direct opening loads the order form in its Mod workspace',
      (tester) async {
    final api = Api();
    await show(tester, api, direct: true);
    expect(find.text('新建发货单'), findsOneWidget);
    expect(find.text('订单编号：20261117A001'), findsOneWidget);
    expect(api.paths, contains('api/mod/tenant-erp/purchase_units'));
    expect(api.paths, isNot(contains('api/mod/tenant-erp/orders')));
  });

  testWidgets('deletes by the record id while confirming the displayed number',
      (tester) async {
    final api = Api();
    await show(tester, api);
    await tester.tap(find.byTooltip('订单 历史单号 的操作'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('删除'));
    await tester.pumpAndSettle();
    expect(find.text('删除订单 历史单号？'), findsOneWidget);
    await tester.tap(find.text('确认删除'));
    await tester.pumpAndSettle();
    expect(api.deletes, ['api/mod/tenant-erp/shipment/orders/2']);
  });

  testWidgets(
      'native shipment form calculates amounts and waits for server receipt',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final api = Api()..generation = Completer();
    await show(tester, api);
    await tester.tap(find.text('新建订单'));
    await tester.pumpAndSettle();
    await tester.tap(find.byType(DropdownButtonFormField<String>).first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('企业发货单').last);
    await tester.pumpAndSettle();
    await tester.tap(find.byType(DropdownButtonFormField<String>).last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('客户甲').last);
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('选择产品'));
    await tester.tap(find.text('选择产品'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('产品甲'));
    await tester.tap(find.text('产品乙'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('添加所选产品（2）'));
    await tester.pumpAndSettle();
    expect(find.text('¥46.00'), findsOneWidget);
    await tester.tap(find.text('生成发货单'));
    await tester.pump();
    expect(api.writes, hasLength(1));
    final body = api.writes.single;
    expect(body['unit_name'], '客户甲');
    expect(body['order_number'], '20261117A001');
    expect(body['template_id'], 'db:1');
    final products = body['products'] as List;
    expect(products, hasLength(2));
    expect(products.first, {
      'name': '产品甲',
      'model_number': 'A01',
      'quantity_tins': 1,
      'tin_spec': 5,
      'quantity_kg': 5,
      'unit_price': 8,
      'amount': 40
    });
    expect(products.last['model_number'], 'B02');
    expect(products.last['amount'], 6);
    expect(find.text('发货单已生成'), findsNothing);
    api.generation!.complete({'success': true, 'doc_name': '出货单.xlsx'});
    await tester.pumpAndSettle();
    expect(find.text('发货单已生成'), findsOneWidget);
    await tester.tap(find.text('继续开单'));
    await tester.pumpAndSettle();
    expect(find.text('产品甲'), findsNothing);
    expect(find.text('生成发货单'), findsOneWidget);
    expect(
        api.paths.where((path) => path.endsWith('/next_number')), hasLength(2));
    expect(api.writes, hasLength(1));
  });
}
