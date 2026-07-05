import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/features/update/android_package_update_installer.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('method channel updater forwards Android delta package config',
      () async {
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
    expect(args['currentVersionCode'], MobileAndroidBuild.versionCode);
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
}
