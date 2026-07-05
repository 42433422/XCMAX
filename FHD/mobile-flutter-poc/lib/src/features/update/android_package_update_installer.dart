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
    final message = await _channel.invokeMethod<String>(
      'startPackageUpdate',
      {
        'downloadUrl': result.downloadUrl,
        'versionName': result.versionName,
        'currentVersionCode': MobileAndroidBuild.versionCode,
        'delta': result.apkDelta,
      },
    );
    return (message ?? '').trim();
  }
}
