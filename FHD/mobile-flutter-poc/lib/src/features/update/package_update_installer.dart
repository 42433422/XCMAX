import 'package:flutter/services.dart';

import '../../api/mobile_api.dart';

abstract class PackageUpdateInstaller {
  Future<String> startPackageUpdate(MobileUpdateCheckResult result);
}

class MethodChannelPackageUpdateInstaller implements PackageUpdateInstaller {
  const MethodChannelPackageUpdateInstaller({
    MethodChannel channel = const MethodChannel('xcagi/update_installer'),
  }) : _channel = channel;

  final MethodChannel _channel;

  @override
  Future<String> startPackageUpdate(MobileUpdateCheckResult result) async {
    final message = await _channel.invokeMethod<String>('startPackageUpdate', {
      'downloadUrl': result.downloadUrl,
      'versionName': result.versionName,
      'currentVersionCode': MobileBuildConfig.versionCode,
      'delta': result.apkDelta,
    });
    return (message ?? '').trim();
  }
}
