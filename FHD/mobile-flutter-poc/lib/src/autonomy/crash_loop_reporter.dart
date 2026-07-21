// Phase 2：crash_loop 事件后端上报 helper。
//
// 纯 Dart 实现，使用 dart:io HttpClient（避免引入额外依赖）。
// fail-open：网络异常 / 服务端 5xx 不阻断本地 SafeMode 决策。
//
// 后端契约（建议）：
// POST {baseUrl}/api/mobile/v1/crash_loop
// Authorization: Bearer {accessToken}
// Content-Type: application/json
// Body: {
//   "platform": "android" | "ios",
//   "boot_count": int,
//   "crash_count": int,
//   "last_crash_kind": string,
//   "last_crash_ts": double,
//   "last_good_version_code": int,
//   "last_good_version_name": string,
//   "manual": bool,  // true=用户主动触发，false=自动触发
//   "ts": float
// }
// Response: 200 OK（任意 body）
//
// 当前为 stub 实现：后端接口未上线前所有请求 no-op，仅审计记录。

import 'dart:async';
import 'dart:convert';
import 'dart:io'
    show
        ContentType,
        HttpClient,
        HttpClientRequest,
        HttpClientResponse,
        HttpHeaders,
        HttpStatus;

import 'mobile_autonomy_types.dart';

/// crash_loop 后端上报配置。
class CrashLoopReporterOptions {
  const CrashLoopReporterOptions({
    this.baseUrl = 'https://xiu-ci.com/fhd-api',
    this.path = '/api/mobile/v1/crash_loop',
    this.timeoutMs = 8000,
    this.enabled = false, // 默认禁用，待后端接口上线后启用
  });

  /// 后端 base URL（不含 path）。
  final String baseUrl;

  /// crash_loop 接收端点 path。
  final String path;

  /// HTTP 请求超时（毫秒）。
  final int timeoutMs;

  /// 是否启用上报（false 时所有方法 no-op）。
  final bool enabled;
}

/// crash_loop 事件后端上报器。
///
/// 纯 Dart 实现，无原生通道。
/// 默认 [CrashLoopReporterOptions.enabled] = false（后端接口未上线）。
class CrashLoopReporter {
  CrashLoopReporter({
    required this.options,
    required Future<String?> Function() accessTokenResolver,
    required double Function() nowResolver,
    required String Function() platformResolver,
  })  : _accessTokenResolver = accessTokenResolver,
        _nowResolver = nowResolver,
        _platformResolver = platformResolver;

  final CrashLoopReporterOptions options;
  final Future<String?> Function() _accessTokenResolver;
  final double Function() _nowResolver;
  final String Function() _platformResolver;

  HttpClient? _httpClient;
  bool _disabledForSession = false;

  /// 上报 crash_loop 事件。
  ///
  /// fail-open：任何异常都不抛出，仅返回 false。
  /// 失败 5 次后会自动 disable 当前 session（避免反复重试消耗电量）。
  int _failureCount = 0;

  Future<bool> report({
    required MobileRuntimeTruthSnapshot truth,
    bool manual = false,
  }) async {
    if (!options.enabled || _disabledForSession) return false;

    final token = await _accessTokenResolver().catchError((_) => null);
    final payload = <String, dynamic>{
      'platform': _platformResolver(),
      'boot_count': truth.bootCount,
      'crash_count': truth.crashCount,
      'last_crash_kind': truth.lastCrashKind,
      'last_crash_ts': truth.lastCrashTs,
      'last_good_version_code': truth.lastGoodVersionCode,
      'last_good_version_name': truth.lastGoodVersionName,
      'current_version_code': truth.currentVersionCode,
      'current_version_name': truth.currentVersionName,
      'manual': manual,
      'ts': _nowResolver(),
    };

    try {
      _httpClient ??= HttpClient();
      final uri = Uri.parse('${options.baseUrl}${options.path}');
      final request = await _httpClient!.postUrl(uri).timeout(
        Duration(milliseconds: options.timeoutMs),
      );
      request.headers.contentType = ContentType.json;
      if (token != null && token.isNotEmpty) {
        request.headers.set(HttpHeaders.authorizationHeader, 'Bearer $token');
      }
      request.headers.set('X-XCAGI-Client', 'mobile');
      request.add(utf8.encode(jsonEncode(payload)));

      final HttpClientResponse response = await request.close().timeout(
        Duration(milliseconds: options.timeoutMs),
      );

      final ok = response.statusCode >= 200 && response.statusCode < 300;
      if (!ok) {
        _recordFailure();
      }
      // 消耗响应体
      await response.drain<void>();
      return ok;
    } catch (_) {
      _recordFailure();
      return false;
    }
  }

  void _recordFailure() {
    _failureCount += 1;
    if (_failureCount >= 5) {
      _disabledForSession = true;
    }
  }

  Future<void> dispose() async {
    _httpClient?.close();
    _httpClient = null;
  }
}
