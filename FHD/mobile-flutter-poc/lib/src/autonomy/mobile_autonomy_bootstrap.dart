// 移动端自治 bootstrap：封装 controller + crash guard + 启动流程。
//
// 跨平台纯 Flutter 实现，Android + iOS 共享。

import 'dart:async';

import 'crash_loop_policy.dart';
import 'flutter_crash_guard.dart';
import 'mobile_autonomy_controller.dart';
import 'mobile_autonomy_store.dart';
import 'mobile_autonomy_types.dart';

/// 移动端自治 bootstrap 结果。
class MobileAutonomyBootstrap {
  MobileAutonomyBootstrap({
    required this.controller,
    required this.store,
    required this.crashGuard,
    required this.rollbackTriggered,
    required this.truthSnapshot,
  });

  final MobileAutonomyController controller;
  final MobileAutonomyStore store;
  final FlutterCrashGuard crashGuard;

  /// 是否在本次启动时触发了 SafeMode 软回滚。
  final bool rollbackTriggered;

  /// 启动时拉取的运行态真相快照。
  final MobileRuntimeTruthSnapshot truthSnapshot;

  /// 通知 store 启动完成（重置 crash_count + 记录 last_good）。
  Future<void> notifyStartupComplete() async {
    try {
      await store.recordStartupComplete(
        versionCode: truthSnapshot.currentVersionCode,
        versionName: truthSnapshot.currentVersionName,
      );
    } catch (_) {
      // fail-open
    }
  }

  /// 用户主动退出 SafeMode（点击"重试正常启动"按钮时调用）。
  Future<void> exitSafeMode() async {
    try {
      await store.exitSafeMode();
    } catch (_) {
      // fail-open
    }
  }

  /// 释放资源。
  Future<void> dispose() async {
    await controller.dispose();
  }
}

/// 启动移动端自治：
/// 1. 创建 store + crash guard + controller
/// 2. 自增 boot_count + crash_count（假设上次启动可能崩溃）
/// 3. 拉取 truth 快照
/// 4. 若 crash_count >= 3，触发 SafeMode 软回滚
/// 5. 启动 controller
///
/// [store] 可选：若 main() 已经创建了全局 store，传入复用；
/// 否则会自动创建新 store。
/// [crashGuard] 可选：若 main() 已经安装 crash guard，传入复用。
Future<MobileAutonomyBootstrap> bootstrapMobileAutonomy({
  SharedPreferencesAutonomyStore? store,
  FlutterCrashGuard? crashGuard,
}) async {
  // 1. 创建或复用 store
  final actualStore = store ?? await SharedPreferencesAutonomyStore.create();

  // 2. 复用或安装崩溃守卫
  final actualCrashGuard =
      crashGuard ?? await FlutterCrashGuard.install(actualStore);

  // 3. 自增启动计数（每次启动都假设上次可能崩溃）
  MobileRuntimeTruthSnapshot truth;
  try {
    truth = await actualStore.incrementStartupCrash();
  } catch (_) {
    // fail-open：读不到状态就当首次启动
    truth = MobileRuntimeTruthSnapshot.empty();
  }

  // 4. 创建 controller
  final controller = MobileAutonomyController(
    store: actualStore,
    policies: const [CrashLoopPolicy()],
  );

  // 5. 若检测到崩溃循环，触发 SafeMode
  var rollbackTriggered = false;
  if (truth.crashCount >= kCrashThreshold) {
    try {
      controller.ingest(MobileAutonomySignal(
        kind: 'app_crash_loop',
        severity: MobileAutonomySeverity.crit,
        detail: 'startup crash_count=${truth.crashCount} >= $kCrashThreshold',
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
      await controller.tickOnce();
      // 重新读取 truth 确认 SafeMode 是否真的进入
      final after = await actualStore.collectTruth();
      rollbackTriggered = after.safeMode;
    } catch (_) {
      // fail-open
    }
  }

  // 6. 启动 controller
  try {
    await controller.start();
  } catch (_) {
    // fail-open
  }

  return MobileAutonomyBootstrap(
    controller: controller,
    store: actualStore,
    crashGuard: actualCrashGuard,
    rollbackTriggered: rollbackTriggered,
    truthSnapshot: truth,
  );
}
