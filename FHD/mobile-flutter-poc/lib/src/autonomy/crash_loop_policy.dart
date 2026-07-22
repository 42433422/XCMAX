// 移动端崩溃循环回滚策略（Android + iOS 共享）。
//
// 监听 `app_crash_loop` 信号，5 分钟窗口内 >= 3 次崩溃 → 输出 enterSafeMode 动作。
// 与桌面端 backend-crash.policy.ts 同阈值（5min/3次）。
//
// 纯函数设计：用 crashes.last.ts 作为 now，禁止 [DateTime.now]，保证测试可复现。

import 'mobile_autonomy_types.dart';

/// 5 分钟窗口（毫秒）。
const int kRollbackWindowMs = 5 * 60 * 1000;

/// 触发软回滚（SafeMode）的崩溃次数阈值。
const int kCrashThreshold = 3;

/// 移动端崩溃循环回滚策略。
///
/// 决策逻辑：
/// - 监听 `app_crash_loop` 信号
/// - 5 分钟窗口内 >= 3 次崩溃 → 输出 `enterSafeMode` 动作
/// - risk = medium（SafeMode 是软回滚，可重复进入）
/// - max_attempts = 3（比桌面端 1 更宽松）
/// - idempotencyKey = `enter-safe-mode:crash-loop`
class CrashLoopPolicy implements MobileAutonomyPolicy {
  const CrashLoopPolicy({
    this.windowMs = kRollbackWindowMs,
    this.threshold = kCrashThreshold,
  });

  @override
  String get id => 'mobile-crash-loop';

  @override
  List<String> get observedSignals => const ['app_crash_loop'];

  /// 崩溃计数窗口（毫秒）。
  final int windowMs;

  /// 触发 SafeMode 的崩溃次数阈值。
  final int threshold;

  @override
  MobileAutonomyPlan plan(
    List<MobileAutonomySignal> matched,
    MobileRuntimeTruthSnapshot truth,
  ) {
    // 用 lastCrashTs 作为 now（纯函数，禁止 DateTime.now）
    final crashSignals = matched.where((s) => s.kind == 'app_crash_loop').toList();
    final now = _deriveNow(crashSignals, truth);

    final crashes = crashSignals.where((s) {
      final crashTs = (s.payload['crash_ts'] as num?)?.toDouble() ?? s.ts;
      return (now - crashTs).abs() <= windowMs;
    }).toList();

    // 如果信号不足以触发，但 truth.crashCount >= threshold，也触发。
    // 取 crashes.length 与 truth.crashCount 的较大值：
    // - 多个独立 crash 信号 → crashes.length 准确
    // - controller 从 truth.crashCount 派生的单个聚合信号 → 用 truth.crashCount 更准
    // - truth 是运行态真相，应作为最终权威
    final crashCount = crashes.isNotEmpty
        ? (crashes.length > truth.crashCount ? crashes.length : truth.crashCount)
        : (truth.crashCount >= threshold ? truth.crashCount : 0);

    if (crashCount < threshold) {
      return MobileAutonomyPlan(
        diagnoses: [
          MobileAutonomyDiagnosis(
            id: 'below-threshold',
            severity: MobileAutonomySeverity.info,
            detail: 'crash_count=$crashCount < $threshold in window',
            payload: {
              'crash_count': crashCount,
              'threshold': threshold,
              'window_ms': windowMs,
            },
          ),
        ],
        actions: [],
      );
    }

    final detail = 'crash_count=$crashCount >= $threshold in ${windowMs}ms window; '
        'entering SafeMode';

    return MobileAutonomyPlan(
      diagnoses: [
        MobileAutonomyDiagnosis(
          id: 'crash-loop-detected',
          severity: MobileAutonomySeverity.crit,
          detail: detail,
          payload: {
            'crash_count': crashCount,
            'threshold': threshold,
            'window_ms': windowMs,
            'last_crash_kind': truth.lastCrashKind,
            'platform': truth.platform,
          },
        ),
      ],
      actions: [
        MobileAutonomyAction(
          type: MobileAutonomyActionType.enterSafeMode,
          risk: MobileAutonomyRiskLevel.medium,
          detail: detail,
          maxAttempts: 3,
          idempotencyKey: 'enter-safe-mode:crash-loop',
          payload: {
            'crash_count': crashCount,
            'window_ms': windowMs,
            'last_crash_kind': truth.lastCrashKind,
          },
        ),
      ],
    );
  }

  /// 派生 now 时间戳：优先用最后一个崩溃信号的 ts，
  /// 退化为 truth.timestampMs，最后退化到 0（测试场景）。
  double _deriveNow(
    List<MobileAutonomySignal> crashSignals,
    MobileRuntimeTruthSnapshot truth,
  ) {
    if (crashSignals.isEmpty) return truth.timestampMs;
    return crashSignals.fold<double>(
      0,
      (acc, s) => s.ts > acc ? s.ts : acc,
    );
  }
}
