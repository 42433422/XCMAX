import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Flutter Android Runner keeps the platform integration contract', () {
    final manifest = File(
      'android/app/src/main/AndroidManifest.xml',
    ).readAsStringSync();
    final strings = File(
      'android/app/src/main/res/values/strings.xml',
    ).readAsStringSync();
    final networkSecurity = File(
      'android/app/src/main/res/xml/network_security_config.xml',
    ).readAsStringSync();
    final updateFilePaths = File(
      'android/app/src/main/res/xml/update_file_paths.xml',
    ).readAsStringSync();
    final filePaths = File(
      'android/app/src/main/res/xml/file_paths.xml',
    ).readAsStringSync();
    final gradle = File('android/app/build.gradle.kts').readAsStringSync();
    final mainDart = File('lib/main.dart').readAsStringSync();
    // part 化拆分后，契约口径为整个 library（主文件 + 全部 part）。
    final startupShell = [
      'lib/src/app/mobile_startup_shell.dart',
      'lib/src/app/mobile_startup_shell_state.part.dart',
      'lib/src/app/mobile_startup_shell_screens.part.dart',
    ].map((p) => File(p).readAsStringSync()).join();
    final backgroundWork = File(
      'android/app/src/main/kotlin/com/xiuci/xcagi/xcagi_flutter_poc/XcagiBackgroundWork.kt',
    ).readAsStringSync();
    final mainActivity = File(
      'android/app/src/main/kotlin/com/xiuci/xcagi/xcagi_flutter_poc/MainActivity.kt',
    ).readAsStringSync();

    expect(strings, contains('<string name="app_name">XCAGI</string>'));
    expect(gradle, contains('namespace = "com.xiuci.xcagi.mobile"'));
    expect(
      gradle,
      contains('applicationId = "com.xiuci.xcagi.mobile.enterprise"'),
    );
    expect(gradle, contains('targetSdk = 35'));
    expect(gradle, contains('versionCode = injectedVersionCode'));
    expect(gradle, contains('versionName = injectedVersionName'));
    expect(gradle, contains('devVersionCode()'));
    expect(gradle, contains('androidx.datastore:datastore-preferences:1.1.1'));
    expect(mainActivity, contains('package com.xiuci.xcagi.mobile'));
    expect(backgroundWork, contains('package com.xiuci.xcagi.mobile'));
    expect(mainDart, contains('MobileStartupApp'));
    expect(startupShell, contains("title: 'XCAGI'"));
    expect(startupShell, contains('resolveMobileStartupRoute'));
    expect(startupShell, contains('LegalConsentScreen'));
    expect(startupShell, contains('resolveMobileDeepLinkDestination'));
    expect(mainActivity, contains('xcagi/deep_link'));
    expect(mainActivity, contains('parseDeepLinkRoute'));
    expect(mainActivity, contains('onNewIntent'));
    expect(startupShell, contains('PlatformBackgroundWorkScheduler'));
    expect(mainActivity, contains('xcagi/background_work'));
    expect(mainActivity, contains('XcagiBackgroundWork.reconcile'));
    expect(mainActivity, contains('xcagi/credential_cipher'));
    expect(mainActivity, contains('AndroidKeyStore'));
    expect(mainActivity, contains('enc:v1:'));
    expect(mainActivity, contains('PreferenceDataStoreFactory.create'));
    expect(
      mainActivity,
      contains('datastore/xcagi_session_enterprise.preferences_pb'),
    );
    expect(mainActivity, contains('xcagi_session.json'));
    expect(mainActivity, contains('xcagi_session_legacy_migrated'));
    expect(mainActivity, contains('fhd_access_token'));
    expect(mainActivity, contains('market_token'));
    expect(mainActivity, contains('legal_accepted_version'));
    expect(mainActivity, contains('relay_desktop_id'));
    expect(mainActivity, contains('wallet_balance_json'));
    expect(mainActivity, contains('inflight_relay_tasks'));
    expect(mainDart, isNot(contains('Flutter POC')));
    expect(manifest, contains('android:label="@string/app_name"'));
    expect(manifest, contains('android:allowBackup="false"'));
    expect(manifest, contains('android:launchMode="singleTask"'));
    expect(manifest, isNot(contains('android:taskAffinity=""')));
    expect(manifest, contains('android.permission.ACCESS_NETWORK_STATE'));
    expect(manifest, contains('android.permission.VIBRATE'));
    expect(manifest, contains('android.permission.POST_NOTIFICATIONS'));
    expect(manifest, contains('android.permission.REQUEST_INSTALL_PACKAGES'));
    expect(
      manifest,
      contains('android.hardware.camera" android:required="false"'),
    );
    expect(manifest, contains('android.speech.RecognitionService'));
    expect(manifest, contains('android.speech.action.RECOGNIZE_SPEECH'));
    expect(
      manifest,
      contains('android:scheme="https" android:host="xiu-ci.com"'),
    );
    expect(manifest, contains('android:pathPrefix="/app"'));
    expect(manifest, contains('android:scheme="xcagi"'));
    expect(manifest, contains('android:name="ICP_LICENSE"'));
    expect(manifest, contains('android:name="APP_FILING_URL"'));
    expect(manifest, contains('androidx.core.content.FileProvider'));
    expect(manifest, contains('\${applicationId}.fileprovider'));
    expect(manifest, contains('@xml/file_paths'));
    expect(manifest, contains('\${applicationId}.update.fileprovider'));
    expect(manifest, contains('@xml/update_file_paths'));
    expect(gradle, contains('androidx.biometric:biometric'));
    expect(gradle, contains('androidx.work:work-runtime-ktx'));
    expect(backgroundWork, contains('PeriodicWorkRequestBuilder'));
    expect(backgroundWork, contains('xcagi_mobile_sync'));
    expect(backgroundWork, contains('xcagi_push_poll'));
    expect(backgroundWork, contains('xcagi_lan_probe'));
    expect(backgroundWork, contains('api/mobile/v1/sync/pull'));
    expect(backgroundWork, contains('api/mobile/v1/notifications/pending'));
    expect(networkSecurity, contains('cleartextTrafficPermitted="true"'));
    expect(
      networkSecurity,
      contains('<domain includeSubdomains="true">xiu-ci.com</domain>'),
    );
    expect(updateFilePaths, contains('path="updates/"'));
    expect(filePaths, contains('<external-files-path'));
    expect(filePaths, contains('path="updates/"'));
  });

  test('Flutter Android launcher icons exist for every density', () {
    for (final density in ['mdpi', 'hdpi', 'xhdpi', 'xxhdpi', 'xxxhdpi']) {
      final flutterIcon = File(
        'android/app/src/main/res/mipmap-$density/ic_launcher.png',
      ).readAsBytesSync();
      expect(flutterIcon, isNotEmpty, reason: 'launcher $density is empty');
    }
  });
}
