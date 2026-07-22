// Flutter 移动端自治 controller。
//
// 与桌面端 autonomy/controller.ts 对齐（裁剪 impact-predictor 和 cross-tier-gate）。
// 跨平台纯 Dart 实现，不依赖任何原生 MethodChannel。
// 直接调用 [MobileAutonomyStore] 持久化 + [MobileAutonomyPolicy] 决策。

import 'dart:async';
import 'dart:collection';

import 'mobile_autonomy_types.dart';

/// 移动端自治 controller：信号去重 + policy 决策 + 动作执行 + 审计。
///
/// 使用方式：
/// ```dart
/// final controller = MobileAutonomyController(
///   store: store,
///   policies: [CrashLoopPolicy()],
/// );
/// await controller.start();
/// controller.ingest(signal);
/// await controller.tickOnce();
/// ```
class MobileAutonomyController {
  MobileAutonomyController({
    required MobileAutonomyStore store,
    required List<MobileAutonomyPolicy> policies,
    MobileAutonomyControllerOptions options =
        const MobileAutonomyControllerOptions(),
  })  : _store = store,
        _policies = List.unmodifiable(policies),
        _options = options;

  final MobileAutonomyStore _store;
  final List<MobileAutonomyPolicy> _policies;
  final MobileAutonomyControllerOptions _options;

  final Queue<MobileAutonomySignal> _pendingSignals = Queue();
  final Set<String> _processedSignalKeys = {};
  final Map<String, _ActionTracker> _actionTrackers = {};
  final StreamController<MobileAutonomyAuditEntry> _auditController =
      StreamController<MobileAutonomyAuditEntry>.broadcast();

  Timer? _tickTimer;
  bool _started = false;
  bool _disposed = false;

  /// 审计事件流（供 UI / 监控订阅）。
  Stream<MobileAutonomyAuditEntry> get auditStream => _auditController.stream;

  /// 当前未处理信号快照（仅供测试/调试）。
  List<MobileAutonomySignal> get signalsSnapshot =>
      List.unmodifiable(_pendingSignals);

  /// 已处理的信号 dedupKey 集合（仅供测试）。
  Set<String> get processedSignalKeysSnapshot =>
      Set.unmodifiable(_processedSignalKeys);

  /// 启动 controller：开始自动 tick。
  Future<void> start() async {
    if (_disposed || !_options.enabled || _started) return;
    _started = true;
    if (_options.tickIntervalMs > 0) {
      _tickTimer = Timer.periodic(
        Duration(milliseconds: _options.tickIntervalMs),
        (_) => tickOnce(),
      );
    }
  }

  /// 接收一个信号并入队。
  ///
  /// 相同 dedupKey 的信号只处理一次。
  void ingest(MobileAutonomySignal signal) {
    if (_disposed || !_options.enabled) return;
    if (_processedSignalKeys.contains(signal.dedupKey)) return;
    _pendingSignals.add(signal);
  }

  /// 单次决策 + 执行。
  ///
  /// 1. collectTruth 从 store 拉取运行态真相
  /// 2. 遍历 policy.plan() 生成动作
  /// 3. 执行动作（带 max_attempts + cooldown）
  /// 4. 写入审计
  Future<void> tickOnce() async {
    if (_disposed || !_options.enabled) return;

    final truth = await _safeCollectTruth();
    if (_pendingSignals.isEmpty && truth.crashCount == 0) return;

    final matched = _gatherMatchedSignals(truth);
    if (matched.isEmpty && truth.crashCount == 0) return;

    for (final policy in _policies) {
      final plan = _safePlan(policy, matched, truth);
      await _executePlan(plan, truth);
    }
  }

  /// 停止 controller：取消定时器，但不清空状态。
  Future<void> stop() async {
    _tickTimer?.cancel();
    _tickTimer = null;
    _started = false;
  }

  /// 释放资源：停止定时器 + 关闭审计流。
  Future<void> dispose() async {
    if (_disposed) return;
    _disposed = true;
    _tickTimer?.cancel();
    _tickTimer = null;
    await _auditController.close();
    await _store.dispose();
  }

  // ─── 内部方法 ──────────────────────────────────────────────────────

  Future<MobileRuntimeTruthSnapshot> _safeCollectTruth() async {
    try {
      return await _store.collectTruth();
    } catch (_) {
      return MobileRuntimeTruthSnapshot.empty();
    }
  }

  List<MobileAutonomySignal> _gatherMatchedSignals(
    MobileRuntimeTruthSnapshot truth,
  ) {
    final observed = _policies.expand((p) => p.observedSignals).toSet();
    final matched = <MobileAutonomySignal>[];

    while (_pendingSignals.isNotEmpty) {
      final signal = _pendingSignals.removeFirst();
      _processedSignalKeys.add(signal.dedupKey);
      if (observed.contains(signal.kind)) {
        matched.add(signal);
      }
    }

    // 如果 truth 显示 crash_count >= 阈值，自动派生 app_crash_loop 信号
    if (truth.crashCount > 0 && observed.contains('app_crash_loop')) {
      matched.add(MobileAutonomySignal(
        kind: 'app_crash_loop',
        severity: MobileAutonomySeverity.crit,
        detail: 'startup crash_count=${truth.crashCount}',
        payload: {
          'crash_ts': truth.lastCrashTs,
          'crash_count': truth.crashCount,
          'boot_count': truth.bootCount,
          'last_crash_kind': truth.lastCrashKind,
        },
        ts: truth.lastCrashTs > 0
            ? truth.lastCrashTs
            : DateTime.now().millisecondsSinceEpoch.toDouble(),
      ));
    }

    return matched;
  }

  MobileAutonomyPlan _safePlan(
    MobileAutonomyPolicy policy,
    List<MobileAutonomySignal> matched,
    MobileRuntimeTruthSnapshot truth,
  ) {
    try {
      return policy.plan(matched, truth);
    } catch (_) {
      return MobileAutonomyPlan.empty();
    }
  }

  Future<void> _executePlan(
    MobileAutonomyPlan plan,
    MobileRuntimeTruthSnapshot truth,
  ) async {
    for (final diagnosis in plan.diagnoses) {
      await _audit(
        MobileAutonomyAuditEntry(
          ts: DateTime.now().millisecondsSinceEpoch.toDouble(),
          action: 'diagnosis:${diagnosis.id}',
          risk: _severityToRisk(diagnosis.severity),
          detail: diagnosis.detail,
          payload: diagnosis.payload,
        ),
      );
    }
    for (final action in plan.actions) {
      await _executeWithGuard(action, truth);
    }
  }

  Future<void> _executeWithGuard(
    MobileAutonomyAction action,
    MobileRuntimeTruthSnapshot truth,
  ) async {
    final tracker = _actionTrackers.putIfAbsent(
      action.idempotencyKey,
      () => _ActionTracker(),
    );

    if (tracker.escalated) return;
    if (tracker.attempts >= action.maxAttempts) {
      // 超过最大尝试次数 → 升级为 escalate
      tracker.escalated = true;
      await _audit(
        MobileAutonomyAuditEntry(
          ts: DateTime.now().millisecondsSinceEpoch.toDouble(),
          action: 'escalate:max_attempts_exceeded',
          risk: MobileAutonomyRiskLevel.high,
          detail:
              'action=${action.idempotencyKey} attempts=${tracker.attempts} >= max=${action.maxAttempts}',
          payload: {'original_action': action.type.name},
        ),
      );
      return;
    }

    final now = DateTime.now().millisecondsSinceEpoch;
    if (tracker.lastExecutedAt != null &&
        now - tracker.lastExecutedAt! < _options.cooldownMs) {
      // 冷却中，跳过
      return;
    }

    tracker.attempts += 1;
    tracker.lastExecutedAt = now;

    final result = await _safeExecute(action, truth);
    await _audit(
      MobileAutonomyAuditEntry(
        ts: now.toDouble(),
        action: 'execute:${action.type.name}',
        risk: action.risk,
        detail: action.detail,
        payload: {
          'ok': result.ok,
          if (result.error != null) 'error': result.error,
          if (result.note != null) 'note': result.note,
          ...action.payload,
        },
      ),
    );
  }

  Future<MobileAutonomyActionResult> _safeExecute(
    MobileAutonomyAction action,
    MobileRuntimeTruthSnapshot truth,
  ) async {
    try {
      switch (action.type) {
        case MobileAutonomyActionType.enterSafeMode:
          await _store.enterSafeMode(action.detail);
          return MobileAutonomyActionResult(action: action, ok: true);

        case MobileAutonomyActionType.escalate:
          // Phase 2：上报后端，当前仅审计
          return MobileAutonomyActionResult(
            action: action,
            ok: true,
            note: 'escalate recorded (backend reporting is Phase 2)',
          );

        case MobileAutonomyActionType.noop:
          return MobileAutonomyActionResult(action: action, ok: true);

        default:
          return MobileAutonomyActionResult(
            action: action,
            ok: false,
            error: 'unsupported_action_type: ${action.type.name}',
          );
      }
    } catch (e) {
      return MobileAutonomyActionResult(
        action: action,
        ok: false,
        error: 'execute_threw: $e',
      );
    }
  }

  Future<void> _audit(MobileAutonomyAuditEntry entry) async {
    if (!_auditController.isClosed) {
      _auditController.add(entry);
    }
    try {
      await _store.appendAudit(entry);
    } catch (_) {
      // 审计写入失败不阻断决策流程
    }
  }

  MobileAutonomyRiskLevel _severityToRisk(MobileAutonomySeverity severity) {
    switch (severity) {
      case MobileAutonomySeverity.info:
        return MobileAutonomyRiskLevel.low;
      case MobileAutonomySeverity.warn:
        return MobileAutonomyRiskLevel.low;
      case MobileAutonomySeverity.crit:
        return MobileAutonomyRiskLevel.medium;
      case MobileAutonomySeverity.fatal:
        return MobileAutonomyRiskLevel.high;
    }
  }
}

/// 动作执行追踪器：记录尝试次数 + 上次执行时间 + 是否已升级。
class _ActionTracker {
  int attempts = 0;
  int? lastExecutedAt;
  bool escalated = false;
}
