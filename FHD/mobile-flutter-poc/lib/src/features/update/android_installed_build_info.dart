import 'package:flutter/services.dart';

/// 读取已安装 APK 的真实 versionCode（LAN 发布用时间戳，不能用 Dart 常量 10）。
class AndroidInstalledBuildInfo {
  const AndroidInstalledBuildInfo._();

  static const MethodChannel _channel = MethodChannel('xcagi/update_installer');

  static Future<int> versionCode({
    int fallback = 10,
  }) async {
    try {
      final value = await _channel.invokeMethod<dynamic>('getInstalledVersionCode');
      if (value is int && value > 0) return value;
      if (value is num && value.toInt() > 0) return value.toInt();
    } catch (_) {
      // 非 Android / 旧包无此方法时回落编译期锚点。
    }
    return fallback;
  }
}
