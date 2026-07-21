// Flutter 应用层崩溃守卫（Android + iOS 共享）。
//
// 替代原生 NSSetUncaughtExceptionHandler / Mach signal handler / Android
// Thread.UncaughtExceptionHandler，纯 Dart 实现应用层异常捕获。
//
// 捕获范围：
// - FlutterError.onError（Framework 异常，例如 widget build 失败）
// - PlatformDispatcher.instance.onError（未捕获的 Dart 异步异常）
// - Isolate.current.addErrorListener（Isolate 错误）
//
// 不捕获：
// - 原生层（Kotlin/Swift/ObjC）崩溃 → 由系统 crash log 处理
// - SIGABRT/SIGSEGV 等 Mach signal → 由系统进程终止处理
//
// 这些原生层崩溃会在下次启动时通过 truth.crashCount 反映
// （因为 incrementStartupCrash 在每次启动时自增）。

import 'dart:async';
import 'dart:isolate';

import 'package:flutter/foundation.dart';

import 'mobile_autonomy_store.dart';
import 'mobile_autonomy_types.dart';

/// Flutter 应用层崩溃守卫。
///
/// 使用方式（在 main() 中尽早调用）：
/// ```dart
/// final store = await SharedPreferencesAutonomyStore.create();
/// FlutterCrashGuard.install(store);
/// runApp(MyApp());
/// ```
class FlutterCrashGuard {
  FlutterCrashGuard._({
    required MobileAutonomyStore store,
    required double Function() nowResolver,
  })  : _store = store,
        _nowResolver = nowResolver;

  static FlutterCrashGuard? _instance;

  final MobileAutonomyStore _store;
  final double Function() _nowResolver;

  /// 安装崩溃守卫：注册三个错误处理器。
  ///
  /// 必须在 runApp() 之前调用。
  static Future<FlutterCrashGuard> install(
    MobileAutonomyStore store, {
    double Function()? nowResolver,
  }) async {
    if (_instance != null) return _instance!;
    final guard = FlutterCrashGuard._(
      store: store,
      nowResolver: nowResolver ??
          () => DateTime.now().millisecondsSinceEpoch.toDouble(),
    );
    _instance = guard;
    await guard._installHandlers();
    return guard;
  }

  /// 卸载崩溃守卫（仅供测试）。
  static Future<void> uninstall() async {
    _instance = null;
  }

  /// 当前实例（测试用）。
  static FlutterCrashGuard? get instance => _instance;

  Future<void> _installHandlers() async {
    // 1. Flutter Framework 异常（widget build / layout 失败等）
    FlutterError.onError = _handleFlutterError;

    // 2. 未捕获的 Dart 异步异常（Future throw 未 catch）
    PlatformDispatcher.instance.onError = _handlePlatformError;

    // 3. Isolate 错误（虽然 Flutter 主 isolate 较少用，但兜底）
    Isolate.current.addErrorListener(
      RawReceivePort((dynamic data) {
        final list = data as List<dynamic>;
        final error = list[0] as String;
        final stack = list[1] as String;
        _recordIsolateError(error, stack);
      }).sendPort,
    );
  }

  void _handleFlutterError(FlutterErrorDetails details) {
    final exception = details.exception;
    final stack = details.stack;
    _recordCrash(
      kind: 'flutter_error',
      detail: '$exception',
      stack: stack?.toString() ?? '',
    );
    // 调用默认 onError 保证日志输出
    FlutterError.presentError(details);
  }

  bool _handlePlatformError(Object error, StackTrace stack) {
    _recordCrash(
      kind: 'platform_error',
      detail: '$error',
      stack: stack.toString(),
    );
    return true; // 表示已处理，避免应用崩溃
  }

  void _recordIsolateError(String error, String stack) {
    _recordCrash(
      kind: 'isolate_error',
      detail: error,
      stack: stack,
    );
  }

  void _recordCrash({
    required String kind,
    required String detail,
    required String stack,
  }) {
    final now = _nowResolver();
    final entry = MobileAutonomyAuditEntry(
      ts: now,
      action: 'crash:$kind',
      risk: MobileAutonomyRiskLevel.high,
      detail: detail,
      payload: {
        'kind': kind,
        if (stack.isNotEmpty) 'stack': stack,
      },
    );
    // 异步记录，不阻塞当前错误处理流程
    _store.recordCrash(kind: kind, detail: detail).catchError((_) {});
    _store.appendAudit(entry).catchError((_) {});
  }
}
