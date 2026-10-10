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

  // ProfileScreen 其余加载项保持离线安全。
  @override
  Future<MobileEnvelope<WalletBalanceData>> walletBalance() async =>
      MobileEnvelope<WalletBalanceData>(
        success: true,
        message: '',
        data: WalletBalanceData.mobileCurrentFallback(),
        raw: const {'ok': true},
      );

  @override
  Future<void> saveWalletBalanceJson(String json) async {}

  @override
  Future<MobileAppConfigData> appConfig({
    int currentVersionCode = MobileBuildConfig.versionCode,
    String sku = MobileBuildConfig.productSku,
  }) async =>
      const MobileAppConfigData(
        ok: true,
        legalVersion: '1',
        profilePage: MobileProfilePageConfig.disabled(),
        raw: {'ok': true},
      );

  @override
  Future<MobileEnvelope<Map<String, Object?>>> me() async =>
      const MobileEnvelope<Map<String, Object?>>(
        success: true,
        message: '',
        data: {
          'user': {'username': 'admin', 'display_name': 'admin'},
        },
        raw: {'ok': true},
      );
}

void main() {
  group('MobileSyncFlow', () {
    test('runs status → push → pull → conflicts and advances cursor', () async {
      final api = _FakeSyncApi(
        startCursor: 3,
        cursor: 9,
        changes: const [
          {'id': 4},
          {'id': 5},
        ],
        conflicts: const [
          {
            'id': 1,
            'entity_type': 'customer',
            'entity_id': '42',
            'conflict_note': '云端版本更新',
            'received_at': '2026-10-10 21:00:00',
          },
        ],
      );
      final result = await MobileSyncFlow(
        api,
      ).run(now: () => DateTime.utc(2026, 10, 10, 13));

      expect(api.calls, ['status', 'push', 'pull', 'conflicts', 'save']);
      expect(api.pulledSince, 3);
      expect(api.pushedItems, isEmpty);
      expect(result.pulled, 2);
      expect(result.cursor, 9);
      expect(result.conflicts.single.title, 'customer #42');
      expect(result.conflicts.single.note, '云端版本更新');
      expect(result.summary, contains('1 条冲突'));
      expect(api.session.syncCursor, 9);
      expect(api.session.lastSyncAt, '2026-10-10T13:00:00.000Z');
    });

    test('never moves the cursor backwards', () async {
      final api = _FakeSyncApi(startCursor: 7, cursor: 0);
      final result = await MobileSyncFlow(api).run();
      expect(result.cursor, 7);
      expect(result.summary, '已同步：推送 0 条，拉取 0 条变更，无冲突');
    });

    for (final step in ['status', 'push', 'pull']) {
      test('$step failure stops the flow and keeps the cursor', () async {
        final api = _FakeSyncApi(failStep: step, startCursor: 2, cursor: 9);
        await expectLater(
          MobileSyncFlow(api).run(),
          throwsA(
            isA<MobileSyncException>()
                .having((e) => e.step, 'step', step)
                .having((e) => e.toString(), 'text', contains('同步服务暂不可用')),
          ),
        );
        expect(api.calls, isNot(contains('save')));
        expect(api.session.syncCursor, 2);
      });
    }
  });

  group('Profile 同步 button', () {
    Future<void> pumpProfile(WidgetTester tester, MobileApiClient api) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = const Size(430, 1800);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetPhysicalSize);
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.light(),
          home: Scaffold(body: ProfileScreen(api: api)),
        ),
      );
      await tester.pumpAndSettle();
    }

    testWidgets('runs the real sync and shows status and conflicts', (
      tester,
    ) async {
      final api = _FakeSyncApi(
        cursor: 5,
        changes: const [
          {'id': 1},
        ],
        conflicts: const [
          {'id': 3, 'entity_type': 'order', 'entity_id': '7'},
        ],
      );
      await pumpProfile(tester, api);
      expect(api.calls, isEmpty, reason: '打开页面不应自动同步');
      expect(find.text('同步冲突'), findsNothing);

      await tester.tap(find.text('同步'));
      await tester.pumpAndSettle();

      expect(api.calls, containsAllInOrder(['status', 'push', 'pull']));
      expect(
        find.text('已同步：推送 0 条，拉取 1 条变更，1 条冲突待处理'),
        findsOneWidget,
      );
      expect(find.text('同步冲突'), findsOneWidget);
      expect(find.text('同步完成，有 1 条冲突待处理'), findsOneWidget);

      await tester.tap(find.text('同步冲突'));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const ValueKey('profile_sync_conflicts_sheet')),
        findsOneWidget,
      );
      expect(find.text('order #7'), findsOneWidget);
    });

    testWidgets('shows a failure hint when push fails', (tester) async {
      final api = _FakeSyncApi(failStep: 'push');
      await pumpProfile(tester, api);

      await tester.tap(find.text('同步'));
      await tester.pumpAndSettle();

      expect(find.text('同步失败，点「同步」重试'), findsOneWidget);
      expect(find.text('推送本地变更失败：同步服务暂不可用'), findsOneWidget);
      expect(api.calls, isNot(contains('pull')));
    });
  });
}
