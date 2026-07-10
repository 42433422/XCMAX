import 'package:flutter/services.dart';

import '../../api/mobile_api.dart';

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
    final currentVersionCode = await MobileAndroidBuild.installedVersionCode();
    final message = await _channel.invokeMethod<String>(
      'startPackageUpdate',
      {
        'downloadUrl': result.downloadUrl,
        'versionName': result.versionName,
        'currentVersionCode': currentVersionCode,
        'apkSha256': result.apkSha256,
        'apkSize': result.apkSize,
        'delta': result.apkDelta,
      },
    );
    return (message ?? '').trim();
  }
}
