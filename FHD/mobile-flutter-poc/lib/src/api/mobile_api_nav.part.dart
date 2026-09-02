part of 'mobile_api.dart';

abstract class _ApiNavBase extends _ApiSessionPersistBase {
  Future<MobileEnvelope<AdminMobileHomeData>> adminHome() async {
    final json = await getJson(XcagiMobileEndpoints.adminHome);
    return MobileEnvelope.fromJson(
      json,
      (value) => AdminMobileHomeData.fromJson(_asObjectMap(value)),
    );
  }

  Future<MobileEnvelope<Map<String, Object?>>> home() async {
    final json = await getJson(XcagiMobileEndpoints.home);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> platformShell() async {
    final json = await getJson(XcagiMobileEndpoints.platformShell);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<WalletBalanceData>> walletBalance() async {
    final json = await getJson(XcagiMobileEndpoints.walletBalance);
    return MobileEnvelope.fromJson(
      json,
      (value) => WalletBalanceData.fromJson(_asObjectMap(value)),
    );
  }

  Future<MobileEnvelope<Map<String, Object?>>> gitBranches() async {
    final json = await getJson(XcagiMobileEndpoints.gitBranches);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }


  Future<MobileAppConfigData> appConfig({
    int currentVersionCode = MobileBuildConfig.versionCode,
    String sku = MobileBuildConfig.productSku,
  }) async {
    final json = await getModstoreJson(
      XcagiMobileEndpoints.appConfig,
      query: {
        'platform': 'android',
        'sku': sku,
        'current_version_code': currentVersionCode.toString(),
      },
    );
    final data = MobileAppConfigData.fromJson(json);
    MobileProductSkuConfig.setRemoteSku(data.sku);
    return data;
  }

  Future<MobileUpdateCheckResult> checkForUpdate({
    int currentVersionCode = MobileBuildConfig.versionCode,
    String sku = MobileBuildConfig.productSku,
  }) async {
    final json = await getModstoreJson(
      XcagiMobileEndpoints.appConfig,
      query: {
        'platform': 'android',
        'sku': sku,
        'current_version_code': currentVersionCode.toString(),
      },
    );
    MobileProductSkuConfig.setRemoteSku(_readString(json, const ['sku']));
    final latestVersionCode = _readInt(
        json,
        const [
          'latest_android_version',
        ],
        0);
    final minVersionCode = _readInt(json, const ['min_android_version'], 0);
    final forceUpdate = _readBool(json, const ['force_update']);
    final forceRequired = currentVersionCode < minVersionCode ||
        (forceUpdate && currentVersionCode < latestVersionCode);
    final available = forceRequired || currentVersionCode < latestVersionCode;
    final latestVersionName = _readString(json, const [
      'latest_android_version_name',
    ]).ifEmpty(latestVersionCode.toString());

    return MobileUpdateCheckResult(
      available: available,
      force: forceRequired,
      versionName: latestVersionName,
      downloadUrl: _readString(json, const ['apk_download_url']),
      raw: json,
    );
  }

  Future<MobileEnvelope<Map<String, Object?>>> submitFeedback(
    String message, {
    String contact = '',
  }) async {
    final json = await postModstoreJson(XcagiMobileEndpoints.appFeedback, {
      'message': message.trim(),
      'contact': contact.trim(),
      'app_version': MobileBuildConfig.versionName,
      'sku': MobileBuildConfig.productSku,
      'platform': 'android',
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<MobileNavMenuData>> navMenu() async {
    final json = await getJson(XcagiMobileEndpoints.navMenu);
    return MobileEnvelope.fromJson(
      json,
      (value) => MobileNavMenuData.fromJson(_asObjectMap(value)),
    );
  }

  Future<MobileEnvelope<PendingNotificationsData>> pendingNotifications({
    int limit = 50,
  }) async {
    final json = await getJson(
      XcagiMobileEndpoints.notificationsPending,
      query: {'limit': '$limit'},
    );
    return MobileEnvelope.fromJson(
      json,
      (value) => PendingNotificationsData.fromJson(_asObjectMap(value)),
    );
  }

}
