import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:package_info_plus/package_info_plus.dart';

import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/features/update/android_package_update_installer.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('method channel updater forwards Android delta package config',
      () async {
    PackageInfo.setMockInitialValues(
      appName: 'XCAGI',
      packageName: 'com.xiuci.xcagi.mobile.enterprise',
      version: '10.0.1',
      buildNumber: '1783711621',
      buildSignature: 'release',
    );
    const channel = MethodChannel('xcagi/update_installer');
    final calls = <MethodCall>[];
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      calls.add(call);
      return '系统安装器已打开，请确认安装';
    });
    addTearDown(
      () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, null),
    );

    final message = await const MethodChannelAndroidPackageUpdateInstaller()
        .startPackageUpdate(
      const MobileUpdateCheckResult(
        available: true,
        force: false,
        versionName: '10.0.1',
        downloadUrl: 'https://xiu-ci.com/download/enterprise/app.apk',
        raw: {
          'apk_sha256':
              'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
          'apk_size': 123456,
          'apk_delta': {
            'available': true,
            'format': 'xcagi-copy-data-v1',
            'patch_url': 'https://xiu-ci.com/download/enterprise/app.xcapkdiff',
            'base_version_code': 10,
            'target_version_code': 11,
            'patch_sha256': 'patch-sha',
            'base_apk_sha256': 'base-sha',
            'target_apk_sha256': 'target-sha',
          },
        },
      ),
    );

    expect(message, '系统安装器已打开，请确认安装');
    expect(calls, hasLength(1));
    expect(calls.single.method, 'startPackageUpdate');
    final args = calls.single.arguments as Map<Object?, Object?>;
    expect(
        args['downloadUrl'], 'https://xiu-ci.com/download/enterprise/app.apk');
    expect(args['versionName'], '10.0.1');
    expect(args['currentVersionCode'], 1783711621);
    expect(
      args['apkSha256'],
      'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    );
    expect(args['apkSize'], 123456);
    final delta = args['delta'] as Map<Object?, Object?>;
    expect(delta['available'], isTrue);
    expect(delta['format'], 'xcagi-copy-data-v1');
    expect(
      delta['patch_url'],
      'https://xiu-ci.com/download/enterprise/app.xcapkdiff',
    );
    expect(delta['base_version_code'], 10);
    expect(delta['target_version_code'], 11);
    expect(delta['target_apk_sha256'], 'target-sha');
  });

  test('OTA check forwards the installed package build number', () async {
    PackageInfo.setMockInitialValues(
      appName: 'XCAGI',
      packageName: 'com.xiuci.xcagi.mobile.enterprise',
      version: '10.0.1',
      buildNumber: '1783711622',
      buildSignature: 'release',
    );
    final api = _CapturingUpdateApi();

    await api.checkForUpdateForInstalledBuild();

    expect(api.capturedVersionCode, 1783711622);
    expect(api.capturedSku, MobileAndroidBuild.productSku);
  });
}

class _CapturingUpdateApi extends MobileApiClient {
  int? capturedVersionCode;
  String? capturedSku;

  @override
  Future<MobileUpdateCheckResult> checkForUpdate({
    int currentVersionCode = MobileAndroidBuild.versionCode,
    String sku = MobileAndroidBuild.productSku,
  }) async {
    capturedVersionCode = currentVersionCode;
    capturedSku = sku;
    return const MobileUpdateCheckResult(
      available: false,
      force: false,
      versionName: '10.0.1',
      downloadUrl: '',
      raw: {},
    );
  }
}
