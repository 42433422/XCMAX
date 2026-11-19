import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:package_info_plus/package_info_plus.dart';

import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/features/update/package_update_installer.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('Android forwards the published target version to the OS installer',
      () async {
    const channel = MethodChannel('xcagi/update_installer');
    final calls = <MethodCall>[];
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(channel, (call) async {
      calls.add(call);
      return '系统安装器已打开，请确认安装';
    });
    addTearDown(() => messenger.setMockMethodCallHandler(channel, null));

    final message =
        await const PlatformPackageUpdateInstaller().startPackageUpdate(
      const MobileUpdateCheckResult(
        available: true,
        force: false,
        versionName: '1.0.0.7',
        downloadUrl: 'https://xiu-ci.com/download/enterprise/app.apk',
        raw: {},
        targetVersionCode: 11,
      ),
    );

    expect(message, '系统安装器已打开，请确认安装');
    expect(calls.single.method, 'startPackageUpdate');
    expect(calls.single.arguments, {
      'downloadUrl': 'https://xiu-ci.com/download/enterprise/app.apk',
      'targetVersionCode': 11,
    });
  });

  test('iOS opens the App Store listing and rejects an APK or lookalike host',
      () async {
    final urls = <Uri>[];
    final installer = PlatformPackageUpdateInstaller(launchStore: (url) async {
      urls.add(url);
      return true;
    });
    MobileUpdateCheckResult storeResult(String url) => MobileUpdateCheckResult(
          available: true,
          force: false,
          versionName: '1.0.7',
          downloadUrl: url,
          raw: const {},
          isAppStore: true,
        );

    const store = 'https://apps.apple.com/app/id123456';
    expect(await installer.startPackageUpdate(storeResult(store)), '已打开 App Store');
    for (final url in [
      'https://xiu-ci.com/download/enterprise/app.apk',
      'https://apps.apple.com.example.com/app/id123456',
    ]) {
      await expectLater(
        installer.startPackageUpdate(storeResult(url)),
        throwsFormatException,
      );
    }
    expect(urls, [Uri.parse(store)]);
  });

  test('Android compares the installed package build number', () async {
    final api = _UpdateApi({
      'latest_android_version': 123,
      'min_android_version': 11,
      'apk_download_url': 'https://xiu-ci.com/download/enterprise/app.apk',
    });
    addTearDown(api.dispose);
    setInstalledPackage(TargetPlatform.android);

    final update = await api.checkForUpdate();

    expect(api.query['platform'], 'android');
    expect(api.query['current_version_code'], '123');
    expect(update.available, isFalse);
  });

  test('iOS compares the native marketing version against the store channel',
      () async {
    final api = _UpdateApi({
      'latest_android_version': 456,
      'apk_download_url': 'https://xiu-ci.com/download/enterprise/app.apk',
    });
    addTearDown(api.dispose);
    setInstalledPackage(TargetPlatform.iOS);

    final unconfigured = await api.checkForUpdate();
    expect(api.query['platform'], 'ios');
    expect(unconfigured.channelAvailable, isFalse);
    expect(unconfigured.available, isFalse);

    api.metadata.addAll({
      'app_store_url': 'https://apps.apple.com/app/id123456',
      'latest_ios_version_name': '1.0.10',
    });
    final update = await api.checkForUpdate();
    expect(update.isAppStore, isTrue);
    expect(update.available, isTrue);
    expect(update.force, isFalse);

    api.metadata['latest_ios_version_name'] = '1.0.8';
    expect((await api.checkForUpdate()).available, isFalse);
  });
}

void setInstalledPackage(TargetPlatform platform) {
  debugDefaultTargetPlatformOverride = platform;
  addTearDown(() => debugDefaultTargetPlatformOverride = null);
  PackageInfo.setMockInitialValues(
    appName: 'XCAGI',
    packageName: 'com.xiuci.xcagi.mobile.enterprise',
    version: '1.0.9',
    buildNumber: '123',
    buildSignature: '',
  );
}

class _UpdateApi extends MobileApiClient {
  _UpdateApi(this.metadata);

  final Map<String, Object?> metadata;
  late Map<String, String> query;

  @override
  Future<Map<String, Object?>> getModstoreJson(
    String path, {
    Map<String, String> query = const {},
  }) async {
    expect(path, XcagiMobileEndpoints.appConfig);
    this.query = query;
    return metadata;
  }
}
