// MobileAutonomyController 单元测试。
//
// 使用 FakeAutonomyStore 替换真实持久化，验证：
// - ingest → tickOnce → enterSafeMode 被调用
// - 不匹配信号不触发 action
// - 重复信号 dedupKey 去重
// - max_attempts 超过后 escalate
// - cooldown 窗口内跳过执行
// - collectTruth 异常 fail-open
// - executeAction 异常 ok=false
// - enabled=false 时所有方法 noop

import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/autonomy/crash_loop_policy.dart';
import 'package:xcagi_flutter_poc/src/autonomy/mobile_autonomy_controller.dart';
import 'package:xcagi_flutter_poc/src/autonomy/mobile_autonomy_types.dart';

/// Fake store：所有状态保存在内存，可注入异常。
class FakeAutonomyStore implements MobileAutonomyStore {
  FakeAutonomyStore({
    this.crashCount = 0,
    this.bootCount = 0,
    this.lastCrashTs = 0,
    this.lastCrashKind = '',
    this.safeMode = false,
    this.collectTruthException,
    this.enterSafeModeException,
  });

  int crashCount;
  int bootCount;
  double lastCrashTs;
  String lastCrashKind;
  bool safeMode;

  /// 注入 collectTruth 异常（用于 fail-open 测试）。
  final Object? collectTruthException;

  /// 注入 enterSafeMode 异常（用于 executeAction 异常测试）。
  final Object? enterSafeModeException;

  final List<MobileAutonomyAuditEntry> audits = [];
  final List<String> enteredSafeModeDetails = [];
  int recordCrashCalls = 0;
  int recordStartupCompleteCalls = 0;
  int exitSafeModeCalls = 0;

  @override
  Future<MobileRuntimeTruthSnapshot> collectTruth() async {
    if (collectTruthException != null) throw collectTruthException!;
    return MobileRuntimeTruthSnapshot(
      platform: 'fake',
      bootCount: bootCount,
      crashCount: crashCount,
      lastCrashTs: lastCrashTs,
      lastCrashKind: lastCrashKind,
      lastGoodVersionCode: 0,
      lastGoodVersionName: '1.0.0',
      lastGoodTs: 0,
      currentVersionCode: 1,
      currentVersionName: '1.0.0',
      safeMode: safeMode,
      timestampMs: 1000000,
    );
  }

  @override
  Future<MobileRuntimeTruthSnapshot> incrementStartupCrash() async {
    bootCount += 1;
    crashCount += 1;
    return collectTruth();
  }

  @override
  Future<void> recordStartupComplete({
    required int versionCode,
    required String versionName,
  }) async {
    recordStartupCompleteCalls += 1;
    crashCount = 0;
    safeMode = false;
  }

  @override
  Future<void> recordCrash({required String kind, required String detail}) async {
    recordCrashCalls += 1;
    crashCount += 1;
    lastCrashKind = kind;
  }

  @override
  Future<void> enterSafeMode(String detail) async {
    if (enterSafeModeException != null) throw enterSafeModeException!;
    enteredSafeModeDetails.add(detail);
    safeMode = true;
  }

  @override
  Future<void> exitSafeMode() async {
    exitSafeModeCalls += 1;
    safeMode = false;
    crashCount = 0;
  }

  @override
  Future<void> appendAudit(MobileAutonomyAuditEntry entry) async {
    audits.add(entry);
  }

  @override
  Future<void> dispose() async {}
}

MobileAutonomySignal _crashSignal(double ts, {int crashCount = 1}) {
  return MobileAutonomySignal(
    kind: 'app_crash_loop',
    severity: MobileAutonomySeverity.crit,
    detail: 'crash',
    payload: {'crash_ts': ts, 'crash_count': crashCount},
    ts: ts,
  );
}

void main() {
  group('MobileAutonomyController', () {
    test('ingest + tickOnce triggers enterSafeMode when crash loop detected', () async {
      final store = FakeAutonomyStore();
      final controller = MobileAutonomyController(
        store: store,
        policies: const [CrashLoopPolicy()],
        options: const MobileAutonomyControllerOptions(tickIntervalMs: 0),
      );

      final now = 1000000.0;
      controller.ingest(_crashSignal(now - 240000));
      controller.ingest(_crashSignal(now - 120000));
      controller.ingest(_crashSignal(now));

      await controller.tickOnce();

      expect(store.enteredSafeModeDetails.length, 1);
      expect(store.audits.any((a) => a.action.startsWith('execute:')), isTrue);
      await controller.dispose();
    });

    test('unrelated signals do not trigger action', () async {
      final store = FakeAutonomyStore();
      final controller = MobileAutonomyController(
        store: store,
        policies: const [CrashLoopPolicy()],
        options: const MobileAutonomyControllerOptions(tickIntervalMs: 0),
      );

      controller.ingest(MobileAutonomySignal(
        kind: 'ota_failed',
        severity: MobileAutonomySeverity.warn,
        detail: 'ota',
        payload: {},
        ts: 1000000,
      ));

      await controller.tickOnce();

      expect(store.enteredSafeModeDetails, isEmpty);
      await controller.dispose();
    });

    test('duplicate signals are deduplicated by dedupKey', () async {
      final store = FakeAutonomyStore();
      final controller = MobileAutonomyController(
        store: store,
        policies: const [CrashLoopPolicy()],
        options: const MobileAutonomyControllerOptions(tickIntervalMs: 0),
      );

      final signal = _crashSignal(1000000);
      controller.ingest(signal);
      controller.ingest(signal); // 重复

      await controller.tickOnce();

      // 信号去重：只处理一次
      expect(controller.processedSignalKeysSnapshot.length, 1);
      await controller.dispose();
    });

    test('max_attempts exceeded → escalate', () async {
      final store = FakeAutonomyStore();
      final controller = MobileAutonomyController(
        store: store,
        policies: const [CrashLoopPolicy()],
        options: const MobileAutonomyControllerOptions(
          tickIntervalMs: 0,
          cooldownMs: 0, // 禁用 cooldown 以便快速达到 max_attempts
        ),
      );

      final now = 1000000.0;
      final signals = [
        _crashSignal(now - 240000),
        _crashSignal(now - 120000),
        _crashSignal(now),
      ];

      // tickOnce 三次，第三次应该 escalate
      for (var i = 0; i < 3; i++) {
        for (final s in signals) {
          // 每次重新 ingest 同样的信号，但用不同 ts 避免去重
          controller.ingest(MobileAutonomySignal(
            kind: s.kind,
            severity: s.severity,
            detail: s.detail,
            payload: s.payload,
            ts: s.ts + i, // 不同 ts 避免去重
          ));
        }
        await controller.tickOnce();
      }

      // 第四次 tickOnce：应该 escalate（max_attempts=3 已达到）
      // 用 i=3 的 ts 避免与前 3 次循环（i=0,1,2）的信号 dedupKey 冲突
      controller.ingest(_crashSignal(now - 240000 + 3, crashCount: 4));
      controller.ingest(_crashSignal(now - 120000 + 3, crashCount: 4));
      controller.ingest(_crashSignal(now + 3, crashCount: 4));
      await controller.tickOnce();

      final escalateAudit = store.audits.where(
        (a) => a.action == 'escalate:max_attempts_exceeded',
      );
      expect(escalateAudit.length, greaterThanOrEqualTo(1));
      await controller.dispose();
    });

    test('cooldown skips execution', () async {
      final store = FakeAutonomyStore();
      final controller = MobileAutonomyController(
        store: store,
        policies: const [CrashLoopPolicy()],
        options: const MobileAutonomyControllerOptions(
          tickIntervalMs: 0,
          cooldownMs: 60000, // 60s cooldown
        ),
      );

      final now = 1000000.0;
      final signals = [
        _crashSignal(now - 240000),
        _crashSignal(now - 120000),
        _crashSignal(now),
      ];

      // 第一次 tickOnce：执行 enterSafeMode
      for (final s in signals) {
        controller.ingest(s);
      }
      await controller.tickOnce();
      expect(store.enteredSafeModeDetails.length, 1);

      // 第二次 tickOnce（带新 ts 避免去重）：应该被 cooldown 跳过
      for (final s in signals) {
        controller.ingest(MobileAutonomySignal(
          kind: s.kind,
          severity: s.severity,
          detail: s.detail,
          payload: s.payload,
          ts: s.ts + 1,
        ));
      }
      await controller.tickOnce();
      // 仍然只执行了一次（cooldown 内）
      expect(store.enteredSafeModeDetails.length, 1);

      await controller.dispose();
    });

    test('collectTruth throws → fail-open with empty truth', () async {
      final store = FakeAutonomyStore(
        collectTruthException: Exception('storage corrupted'),
      );
      final controller = MobileAutonomyController(
        store: store,
        policies: const [CrashLoopPolicy()],
        options: const MobileAutonomyControllerOptions(tickIntervalMs: 0),
      );

      controller.ingest(_crashSignal(1000000));
      // 不应抛异常，应 fail-open
      await controller.tickOnce();
      expect(store.enteredSafeModeDetails, isEmpty);
      await controller.dispose();
    });

    test('enterSafeMode throws → audit recorded with ok=false', () async {
      final store = FakeAutonomyStore(
        enterSafeModeException: Exception('storage write failed'),
      );
      final controller = MobileAutonomyController(
        store: store,
        policies: const [CrashLoopPolicy()],
        options: const MobileAutonomyControllerOptions(
          tickIntervalMs: 0,
          cooldownMs: 0,
        ),
      );

      final now = 1000000.0;
      controller.ingest(_crashSignal(now - 240000));
      controller.ingest(_crashSignal(now - 120000));
      controller.ingest(_crashSignal(now));

      await controller.tickOnce();

      // 应该有 execute:enterSafeMode 审计，且 ok=false
      final executeAudit = store.audits.where(
        (a) => a.action == 'execute:enterSafeMode',
      );
      expect(executeAudit.length, 1);
      expect(executeAudit.single.payload['ok'], false);
      expect(executeAudit.single.payload['error'], isNotNull);
      await controller.dispose();
    });

    test('disabled controller: all methods are noop', () async {
      final store = FakeAutonomyStore();
      final controller = MobileAutonomyController(
        store: store,
        policies: const [CrashLoopPolicy()],
        options: const MobileAutonomyControllerOptions(
          tickIntervalMs: 0,
          enabled: false,
        ),
      );

      controller.ingest(_crashSignal(1000000));
      await controller.tickOnce();
      await controller.start();

      expect(store.enteredSafeModeDetails, isEmpty);
      expect(store.audits, isEmpty);
      expect(controller.signalsSnapshot, isEmpty); // ingest 被 noop
      await controller.dispose();
    });

    test('truth.crashCount fallback triggers enterSafeMode', () async {
      final store = FakeAutonomyStore(crashCount: 5, lastCrashTs: 1000000);
      final controller = MobileAutonomyController(
        store: store,
        policies: const [CrashLoopPolicy()],
        options: const MobileAutonomyControllerOptions(tickIntervalMs: 0),
      );

      // 不 ingest 任何信号，仅靠 truth.crashCount 触发
      await controller.tickOnce();

      expect(store.enteredSafeModeDetails.length, 1);
      await controller.dispose();
    });

    test('audit stream emits entries', () async {
      final store = FakeAutonomyStore();
      final controller = MobileAutonomyController(
        store: store,
        policies: const [CrashLoopPolicy()],
        options: const MobileAutonomyControllerOptions(
          tickIntervalMs: 0,
          cooldownMs: 0,
        ),
      );

      final emitted = <MobileAutonomyAuditEntry>[];
      final sub = controller.auditStream.listen(emitted.add);

      final now = 1000000.0;
      controller.ingest(_crashSignal(now - 240000));
      controller.ingest(_crashSignal(now - 120000));
      controller.ingest(_crashSignal(now));
      await controller.tickOnce();

      await sub.cancel();
      expect(emitted, isNotEmpty);
      await controller.dispose();
    });
  });
}
