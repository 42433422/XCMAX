import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_sync_flow.dart';
import 'package:xcagi_flutter_poc/src/features/profile/profile_screen.dart';
import 'package:xcagi_flutter_poc/src/theme/app_theme.dart';

MobileEnvelope<Map<String, Object?>> _ok(Map<String, Object?> data) =>
    MobileEnvelope<Map<String, Object?>>(
      success: true,
      message: 'success',
      data: data,
      raw: const {'success': true},
    );

class _FakeSyncApi extends MobileApiClient {
  _FakeSyncApi({
    this.failStep = '',
    this.conflicts = const [],
    this.changes = const [],
    this.cursor = 0,
    int startCursor = 0,
  }) : session = MobileSessionData(syncCursor: startCursor);

  final String failStep;
  final List<Map<String, Object?>> conflicts;
  final List<Map<String, Object?>> changes;
  final int cursor;
  MobileSessionData session;
  final calls = <String>[];
  int? pulledSince;
  List<Map<String, Object?>>? pushedItems;

  void _maybeFail(String step) {
    if (failStep == step) {
      throw const MobileApiException(
        statusCode: 500,
        message: '同步服务暂不可用',
        body: <String, Object?>{},
      );
    }
  }

  @override
  Future<MobileSessionData> loadSession({bool forceReload = false}) async =>
      session;

  @override
  Future<void> saveSyncState({
    int? syncCursor,
    String? lastSyncAt,
    bool? autoSync,
  }) async {
    calls.add('save');
    session = session.copyWith(
      syncCursor: syncCursor ?? session.syncCursor,
      lastSyncAt: lastSyncAt ?? session.lastSyncAt,
    );
  }

  @override
  Future<MobileEnvelope<Map<String, Object?>>> syncStatus() async {
    calls.add('status');
    _maybeFail('status');
    return _ok({'healthy': true, 'conflict_count': conflicts.length});
  }

  @override
  Future<MobileEnvelope<Map<String, Object?>>> syncPush(
    List<Map<String, Object?>> items,
  ) async {
    calls.add('push');
    pushedItems = items;
    _maybeFail('push');
    return _ok({'written': items.length, 'apply': const {}});
  }

  @override
  Future<MobileEnvelope<Map<String, Object?>>> syncPull({
    int sinceCursor = 0,
  }) async {
    calls.add('pull');
    pulledSince = sinceCursor;
    _maybeFail('pull');
    return _ok({'cursor': cursor, 'changes': changes});
  }

  @override
  Future<MobileEnvelope<Map<String, Object?>>> syncConflicts() async {
    calls.add('conflicts');
    return _ok({'items': conflicts});
  }

  // 个人页其余加载项离线失败即可（页面会吞掉错误）。
  @override
  Future<MobileEnvelope<WalletBalanceData>> walletBalance() => throw 'offline';

  @override
  Future<MobileEnvelope<Map<String, Object?>>> me() => throw 'offline';

  @override
  Future<MobileAppConfigData> appConfig({
    int currentVersionCode = 0,
    String sku = '',
  }) =>
      throw 'offline';
}

void main() {
  test('runs status → push → pull → conflicts and advances cursor', () async {
    final api = _FakeSyncApi(startCursor: 3, cursor: 9, changes: const [
      {'id': 4},
      {'id': 5},
    ], conflicts: const [
      {'entity_type': 'customer', 'entity_id': '42'},
    ]);
    final result = await runMobileSync(api);
    expect(api.calls, ['status', 'push', 'pull', 'conflicts', 'save']);
    expect(api.pulledSince, 3);
    expect(api.pushedItems, isEmpty);
    expect(result.summary, '已同步：推送 0 条，拉取 2 条变更，1 条冲突待处理');
    expect(api.session.syncCursor, 9);
    expect(api.session.lastSyncAt, isNotEmpty);
    // 游标只进不退。
    final again = _FakeSyncApi(startCursor: 7);
    await runMobileSync(again);
    expect(again.session.syncCursor, 7);
  });

  test('push failure stops the flow and keeps the cursor', () async {
    final api = _FakeSyncApi(failStep: 'push', startCursor: 2, cursor: 9);
    await expectLater(runMobileSync(api), throwsA('推送本地变更失败：同步服务暂不可用'));
    expect(api.calls, ['status', 'push']);
    expect(api.session.syncCursor, 2);
  });

  testWidgets('profile 同步 button runs sync and shows result and conflicts',
      (tester) async {
    tester.view.physicalSize = const Size(430, 1800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final api = _FakeSyncApi(conflicts: const [
      {'entity_type': 'order', 'entity_id': '7', 'conflict_note': '云端较新'},
    ]);
    await tester.pumpWidget(MaterialApp(
      theme: AppTheme.light(),
      home: Scaffold(body: ProfileScreen(api: api)),
    ));
    await tester.pumpAndSettle();
    expect(api.calls, isEmpty, reason: '打开页面不应自动同步');

    await tester.tap(find.text('同步'));
    await tester.pumpAndSettle();
    expect(find.text('已同步：推送 0 条，拉取 0 条变更，1 条冲突待处理'), findsOneWidget);
    expect(find.text('同步冲突 1 条'), findsOneWidget);
    expect(find.text('order #7 云端较新'), findsOneWidget);
  });

  testWidgets('profile 同步 button reports failure', (tester) async {
    final api = _FakeSyncApi(failStep: 'pull');
    await tester.pumpWidget(MaterialApp(
      theme: AppTheme.light(),
      home: Scaffold(body: ProfileScreen(api: api)),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.text('同步'));
    await tester.pumpAndSettle();
    expect(find.text('同步失败，点「同步」重试'), findsOneWidget);
    expect(find.text('拉取云端变更失败：同步服务暂不可用'), findsOneWidget);
  });
}
