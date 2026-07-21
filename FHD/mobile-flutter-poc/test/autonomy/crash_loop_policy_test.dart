// CrashLoopPolicy 单元测试。
//
// 验证决策逻辑：
// - 空信号 / 不相关信号 → 无 action
// - 5min 窗口内 < 3 次崩溃 → 无 action
// - 5min 窗口内 >= 3 次崩溃 → enterSafeMode action
// - 5min 窗口外的崩溃 → 不计入窗口
// - truth.crashCount >= threshold 兜底触发
// - 纯函数确定性：相同输入产生相同输出
// - 信号顺序无关性

import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/autonomy/crash_loop_policy.dart';
import 'package:xcagi_flutter_poc/src/autonomy/mobile_autonomy_types.dart';

MobileRuntimeTruthSnapshot _truth({
  String platform = 'android',
  int bootCount = 5,
  int crashCount = 0,
  double lastCrashTs = 0,
  String lastCrashKind = '',
  int lastGoodVersionCode = 9,
  String lastGoodVersionName = '1.0.0',
  double lastGoodTs = 0,
  int currentVersionCode = 10,
  String currentVersionName = '1.0.1',
  bool safeMode = false,
  double timestampMs = 1000000,
}) {
  return MobileRuntimeTruthSnapshot(
    platform: platform,
    bootCount: bootCount,
    crashCount: crashCount,
    lastCrashTs: lastCrashTs,
    lastCrashKind: lastCrashKind,
    lastGoodVersionCode: lastGoodVersionCode,
    lastGoodVersionName: lastGoodVersionName,
    lastGoodTs: lastGoodTs,
    currentVersionCode: currentVersionCode,
    currentVersionName: currentVersionName,
    safeMode: safeMode,
    timestampMs: timestampMs,
  );
}

MobileAutonomySignal _crashSignal({
  required double ts,
  int crashCount = 1,
  String kind = 'app_crash_loop',
}) {
  return MobileAutonomySignal(
    kind: kind,
    severity: MobileAutonomySeverity.crit,
    detail: 'crash',
    payload: {
      'crash_ts': ts,
      'crash_count': crashCount,
    },
    ts: ts,
  );
}

void main() {
  group('CrashLoopPolicy', () {
    test('id and observedSignals', () {
      const policy = CrashLoopPolicy();
      expect(policy.id, 'mobile-crash-loop');
      expect(policy.observedSignals, ['app_crash_loop']);
    });

    test('empty signals + crashCount=0 returns no actions', () {
      const policy = CrashLoopPolicy();
      final plan = policy.plan([], _truth(crashCount: 0));
      expect(plan.actions, isEmpty);
      expect(plan.diagnoses.single.id, 'below-threshold');
    });

    test('unrelated signals ignored', () {
      const policy = CrashLoopPolicy();
      final unrelated = MobileAutonomySignal(
        kind: 'ota_failed',
        severity: MobileAutonomySeverity.warn,
        detail: 'ota',
        payload: {},
        ts: 1000000,
      );
      final plan = policy.plan([unrelated], _truth());
      expect(plan.actions, isEmpty);
    });

    test('below threshold (2 crashes in window) returns info only', () {
      const policy = CrashLoopPolicy();
      final now = 1000000.0;
      final signals = [
        _crashSignal(ts: now - 60000),
        _crashSignal(ts: now - 30000),
      ];
      final plan = policy.plan(signals, _truth(timestampMs: now));
      expect(plan.actions, isEmpty);
      expect(plan.diagnoses.single.severity, MobileAutonomySeverity.info);
      expect(plan.diagnoses.single.payload['crash_count'], 2);
    });

    test('3 crashes in 5min window triggers enterSafeMode', () {
      const policy = CrashLoopPolicy();
      final now = 1000000.0;
      final signals = [
        _crashSignal(ts: now - 240000), // 4 min ago
        _crashSignal(ts: now - 120000), // 2 min ago
        _crashSignal(ts: now),          // now
      ];
      final plan = policy.plan(signals, _truth(timestampMs: now));

      expect(plan.actions.length, 1);
      final action = plan.actions.single;
      expect(action.type, MobileAutonomyActionType.enterSafeMode);
      expect(action.risk, MobileAutonomyRiskLevel.medium);
      expect(action.maxAttempts, 3);
      expect(action.idempotencyKey, 'enter-safe-mode:crash-loop');
      expect(action.payload['crash_count'], 3);

      expect(plan.diagnoses.single.id, 'crash-loop-detected');
      expect(plan.diagnoses.single.severity, MobileAutonomySeverity.crit);
    });

    test('crashes beyond 5min window ignored', () {
      const policy = CrashLoopPolicy();
      final now = 1000000.0;
      final signals = [
        _crashSignal(ts: now - 400000), // 6.6 min ago, beyond window
        _crashSignal(ts: now - 200000), // 3.3 min ago
        _crashSignal(ts: now),
      ];
      // 仅 2 次在窗口内 → 不触发
      final plan = policy.plan(signals, _truth(timestampMs: now));
      expect(plan.actions, isEmpty);
      expect(plan.diagnoses.single.payload['crash_count'], 2);
    });

    test('truth.crashCount fallback triggers when signals empty', () {
      const policy = CrashLoopPolicy();
      final truth = _truth(crashCount: 5, lastCrashTs: 1000000);
      final plan = policy.plan([], truth);

      expect(plan.actions.length, 1);
      expect(plan.actions.single.type, MobileAutonomyActionType.enterSafeMode);
      expect(plan.actions.single.payload['crash_count'], 5);
    });

    test('truth.crashCount below threshold does not trigger', () {
      const policy = CrashLoopPolicy();
      final truth = _truth(crashCount: 2);
      final plan = policy.plan([], truth);
      expect(plan.actions, isEmpty);
    });

    test('5 crashes still single action (idempotency)', () {
      const policy = CrashLoopPolicy();
      final now = 1000000.0;
      final signals = [
        _crashSignal(ts: now - 240000),
        _crashSignal(ts: now - 180000),
        _crashSignal(ts: now - 120000),
        _crashSignal(ts: now - 60000),
        _crashSignal(ts: now),
      ];
      final plan = policy.plan(signals, _truth(timestampMs: now));
      expect(plan.actions.length, 1);
      expect(plan.actions.single.payload['crash_count'], 5);
    });

    test('pure function: same input → same output', () {
      const policy = CrashLoopPolicy();
      final now = 1000000.0;
      final signals = [
        _crashSignal(ts: now - 60000),
        _crashSignal(ts: now - 30000),
        _crashSignal(ts: now),
      ];
      final truth = _truth(timestampMs: now);

      final plan1 = policy.plan(signals, truth);
      final plan2 = policy.plan(signals, truth);

      expect(plan1.actions.length, plan2.actions.length);
      expect(plan1.actions.single.idempotencyKey,
          plan2.actions.single.idempotencyKey);
      expect(plan1.diagnoses.single.detail, plan2.diagnoses.single.detail);
    });

    test('signal order independence', () {
      const policy = CrashLoopPolicy();
      final now = 1000000.0;
      final signals = [
        _crashSignal(ts: now),
        _crashSignal(ts: now - 120000),
        _crashSignal(ts: now - 240000),
      ];
      final plan = policy.plan(signals, _truth(timestampMs: now));
      expect(plan.actions.length, 1);
      expect(plan.actions.single.payload['crash_count'], 3);
    });

    test('custom window and threshold', () {
      const policy = CrashLoopPolicy(windowMs: 60000, threshold: 2);
      final now = 1000000.0;
      final signals = [
        _crashSignal(ts: now - 30000),
        _crashSignal(ts: now),
      ];
      final plan = policy.plan(signals, _truth(timestampMs: now));
      expect(plan.actions.length, 1);
      expect(plan.actions.single.payload['crash_count'], 2);
    });

    test('payload.crash_ts overrides signal.ts for window check', () {
      const policy = CrashLoopPolicy();
      final now = 1000000.0;
      // signal.ts 在窗口内，但 payload.crash_ts 在窗口外
      final signals = [
        MobileAutonomySignal(
          kind: 'app_crash_loop',
          severity: MobileAutonomySeverity.crit,
          detail: 'crash',
          payload: {'crash_ts': now - 400000}, // 6.6 min ago
          ts: now, // signal.ts 在 now
        ),
        _crashSignal(ts: now - 30000),
        _crashSignal(ts: now),
      ];
      // payload.crash_ts 在窗口外，但其他 2 个在窗口内 → 不触发
      final plan = policy.plan(signals, _truth(timestampMs: now));
      expect(plan.actions, isEmpty);
    });
  });
}
