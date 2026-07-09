import 'package:flutter/services.dart';

import '../../api/mobile_api.dart';
import 'android_installed_build_info.dart';

abstract class AndroidPackageUpdateInstaller {
  Future<String> startPackageUpdate(MobileUpdateCheckResult result);
}

class MethodChannelAndroidPackageUpdateInstaller
    implements AndroidPackageUpdateInstaller {
  const MethodChannelAndroidPackageUpdateInstaller({
    MethodChannel channel = const MethodChannel('xcagi/update_installer'),
  }) : _channel = channel;

  final MethodChannel _channel;

  @override
  Future<String> startPackageUpdate(MobileUpdateCheckResult result) async {
    final currentVersionCode = await AndroidInstalledBuildInfo.versionCode(
      fallback: MobileAndroidBuild.versionCode,
    );
    final message = await _channel.invokeMethod<String>(
      'startPackageUpdate',
      {
        'downloadUrl': result.downloadUrl,
        'versionName': result.versionName,
        'currentVersionCode': currentVersionCode,
        'delta': result.apkDelta,
      },
    );
    return (message ?? '').trim();
  }
}
