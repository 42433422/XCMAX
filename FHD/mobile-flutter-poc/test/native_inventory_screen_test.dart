import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/business/native_inventory_screen.dart';

class _InventoryApi extends MobileApiClient {
  _InventoryApi()
      : super(
          sessionStore: MemoryMobileSessionStore(
            MobileSessionData.empty.copyWith(userId: 7, accessToken: 'one'),
          ),
        );

  final reads = <({String path, Map<String, String> query})>[];
  final writes = <({String path, Map<String, Object?>? body})>[];
  Completer<Map<String, Object?>>? receipt;

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
    expect(activeModId, 'xcagi-erp-domain-bridge');
    expect(expectedGeneration, authGeneration);
    if (method != 'GET') {
      writes.add((path: path, body: body));
      return receipt?.future ?? {'success': true};
    }
    reads.add((path: path, query: query));
    return {
      'success': true,
      'total': 1,
      'data': switch (path) {
        'api/inventory/warehouses' => [
            {'id': 9, 'name': '主仓库', 'status': 'active'},
          ],
        'api/inventory' => [
            {
              'id': 18,
              'product_id': 17,
              'product_name': '面漆',
              'product_code': 'X-71',
              'warehouse_id': 9,
              'warehouse_name': '主仓库',
              'batch_no': 'B-01',
              'location_id': 3,
              'quantity': 10,
              'available_quantity': 7,
              'unit': '桶',
            },
          ],
        'api/inventory/transactions' => [
            {
              'id': 21,
              'product_name': '面漆',
              'warehouse_id': 9,
              'transaction_type': 'out',
              'quantity': 2,
            },
          ],
        _ => <Object>[],
      },
    };
  }
}

Future<void> _open(WidgetTester tester, _InventoryApi api) async {
  await tester.binding.setSurfaceSize(const Size(375, 812));
  addTearDown(() => tester.binding.setSurfaceSize(null));
  final repository = MobileRepository(client: api);
  addTearDown(() async {
    await repository.dispose();
    api.dispose();
  });
  await tester.pumpWidget(MaterialApp(
    home: NativeInventoryScreen(
      repository: repository,
      title: '库存管理',
      activeModId: 'xcagi-erp-domain-bridge',
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  for (final incoming in [true, false]) {
    for (final quantity in [0.5, 1.5]) {
      testWidgets(
          '${incoming ? 'incoming' : 'outgoing'} stock accepts $quantity and rejects invalid quantities',
          (tester) async {
        final api = _InventoryApi();
        await _open(tester, api);
        final action = incoming ? '入库' : '出库';
        final rowAction = find.widgetWithText(TextButton, action);
        await tester.ensureVisible(rowAction);
        await tester.tap(rowAction);
        await tester.pumpAndSettle();
        final input = find.byKey(const ValueKey('quantity'));
        for (final invalid in ['0', '-0.5', 'NaN', 'Infinity']) {
          await tester.enterText(input, invalid);
          await tester.ensureVisible(find.text('保存'));
          await tester.tap(find.text('保存'));
          await tester.pumpAndSettle();
          expect(api.writes, isEmpty, reason: invalid);
        }
        await tester.enterText(input, '$quantity');
        await tester.ensureVisible(find.text('保存'));
        await tester.tap(find.text('保存'));
        await tester.pumpAndSettle();
        expect(api.writes, hasLength(1));
        expect(api.writes.single.path,
            'api/inventory/${incoming ? 'in' : 'out'}');
        expect(api.writes.single.body, containsPair('quantity', quantity));
        expect(api.writes.single.body, containsPair('product_id', 17));
        expect(api.writes.single.body, containsPair('warehouse_id', 9));
        expect(find.text('已$action'), findsOneWidget);
        expect(tester.takeException(), isNull);
      });
    }
  }

  testWidgets('inventory shows balances separately and scopes list filters',
      (tester) async {
    final api = _InventoryApi();
    await _open(tester, api);
    expect(find.text('库存台账'), findsOneWidget);
    expect(find.text('面漆'), findsOneWidget);
    expect(find.text('7 桶'), findsOneWidget);
    expect(find.text('10 桶'), findsOneWidget);
    final warehouse = find.byType(DropdownButtonFormField<String>);
    await tester.tap(warehouse);
    await tester.pumpAndSettle();
    await tester.tap(find.text('主仓库').last);
    await tester.pumpAndSettle();
    final search = find.byType(TextField);
    await tester.enterText(search, 'X-71');
    await tester.testTextInput.receiveAction(TextInputAction.search);
    await tester.pumpAndSettle();
    expect(api.reads.last.path, 'api/inventory');
    expect(api.reads.last.query, {
      'warehouse_id': '9',
      'keyword': 'X-71',
      'page': '1',
      'per_page': '20',
    });
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'stock row keeps its write context and uncertain result finds ledger',
      (tester) async {
    final api = _InventoryApi()..receipt = Completer();
    await _open(tester, api);
    final rowOut = find.widgetWithText(TextButton, '出库');
    await tester.ensureVisible(rowOut);
    await tester.tap(rowOut);
    await tester.pumpAndSettle();
    expect(find.text('出库 · 面漆 · X-71'), findsOneWidget);
    await tester.enterText(find.byKey(const ValueKey('quantity')), '2');
    await tester.ensureVisible(find.text('保存'));
    await tester.tap(find.text('保存'));
    await tester.pump();
    expect(api.writes.single.path, 'api/inventory/out');
    expect(api.writes.single.body, {
      'product_id': 17,
      'warehouse_id': 9,
      'batch_no': 'B-01',
      'location_id': 3,
      'quantity': 2,
      'remark': '',
    });
    api.receipt!.completeError(TimeoutException('response lost'));
    await tester.pumpAndSettle();
    expect(find.text('待核对流水'), findsOneWidget);
    await tester.tap(find.byTooltip('返回'));
    await tester.pumpAndSettle();
    final verify = find.text('核对该笔流水');
    await tester.ensureVisible(verify);
    await tester.tap(verify);
    await tester.pumpAndSettle();
    expect(api.reads.last.path, 'api/inventory/transactions');
    expect(api.reads.last.query, {
      'warehouse_id': '9',
      'product_id': '17',
      'transaction_type': 'out',
      'page': '1',
      'per_page': '20',
    });
    expect(api.writes, hasLength(1));
  });
}
