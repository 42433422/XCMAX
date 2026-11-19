import 'package:flutter/services.dart';

import '../../api/mobile_api.dart';
import '../../platform/external_url_launcher.dart';

abstract class PackageUpdateInstaller {
  Future<String> startPackageUpdate(MobileUpdateCheckResult result);
}

class PlatformPackageUpdateInstaller implements PackageUpdateInstaller {
  const PlatformPackageUpdateInstaller({
    MethodChannel channel = const MethodChannel('xcagi/update_installer'),
    this.launchStore = launchExternalUrl,
  }) : _channel = channel;

  final MethodChannel _channel;
  final ExternalUrlLauncher launchStore;

  @override
  Future<String> startPackageUpdate(MobileUpdateCheckResult result) async {
    if (result.isAppStore) {
      final uri = Uri.tryParse(result.downloadUrl);
      if (uri == null ||
          uri.scheme != 'https' ||
          uri.host != 'apps.apple.com' ||
          uri.port != 443 ||
          uri.userInfo.isNotEmpty ||
          !uri.pathSegments.contains('app') ||
          !RegExp(r'^id[0-9]+$').hasMatch(uri.pathSegments.last)) {
        throw const FormatException('App Store 更新地址无效');
      }
      if (!await launchStore(uri)) throw StateError('无法打开 App Store');
      return '已打开 App Store';
    }
    final message = await _channel.invokeMethod<String>('startPackageUpdate', {
      'downloadUrl': result.downloadUrl,
      'targetVersionCode': result.targetVersionCode,
    });
    return (message ?? '').trim();
  }
}
