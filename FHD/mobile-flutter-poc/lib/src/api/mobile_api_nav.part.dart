part of 'mobile_api.dart';

abstract class _ApiNavBase extends _ApiSessionPersistBase {
  _ApiNavBase({
    super.config,
    super.sessionStore,
    super.httpClient,
    super.credentialCipher,
  });

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
    int? currentVersionCode,
    String sku = MobileBuildConfig.productSku,
  }) async {
    final isIos = defaultTargetPlatform == TargetPlatform.iOS;
    final package = isIos || currentVersionCode == null
        ? await PackageInfo.fromPlatform()
        : null;
    final installedCode =
        currentVersionCode ?? int.tryParse(package!.buildNumber) ?? 0;
    final json = await getModstoreJson(
      XcagiMobileEndpoints.appConfig,
      query: {
        'platform': isIos ? 'ios' : 'android',
        'sku': sku,
        'current_version_code': installedCode.toString(),
      },
    );
    MobileProductSkuConfig.setRemoteSku(_readString(json, const ['sku']));
    if (isIos) {
      final storeUrl = _readString(json, const ['app_store_url']);
      final latestVersion = _readString(json, const ['latest_ios_version_name']);
      final configured = storeUrl.isNotEmpty && latestVersion.isNotEmpty;
      return MobileUpdateCheckResult(
        available: configured &&
            Version.parse(latestVersion) > Version.parse(package!.version),
        force: false,
        versionName: latestVersion,
        downloadUrl: storeUrl,
        raw: json,
        channelAvailable: configured,
        isAppStore: true,
      );
    }
    if (installedCode <= 0) {
      throw StateError('无法读取当前 Android 版本号');
    }
    final latestVersionCode = _readInt(
        json,
        const [
          'latest_android_version',
        ],
        0);
    final minVersionCode = _readInt(json, const ['min_android_version'], 0);
    final forceUpdate = _readBool(json, const ['force_update']);
    final forceRequired = installedCode < minVersionCode ||
        (forceUpdate && installedCode < latestVersionCode);
    final available = forceRequired || installedCode < latestVersionCode;
    final latestVersionName = _readString(json, const [
      'latest_android_version_name',
    ]).ifEmpty(latestVersionCode.toString());

    return MobileUpdateCheckResult(
      available: available,
      force: forceRequired,
      versionName: latestVersionName,
      downloadUrl: _readString(json, const ['apk_download_url']),
      raw: json,
      targetVersionCode: latestVersionCode,
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

  Future<MobileEnvelope<PendingNotificationsData>> notificationInbox({
    int limit = 50,
    int? beforeId,
  }) async {
    final json = await getJson(XcagiMobileEndpoints.notificationsInbox, query: {
      'limit': '$limit',
      if (beforeId != null) 'before_id': '$beforeId',
    });
    return MobileEnvelope.fromJson(json, (value) => PendingNotificationsData.fromJson(_asObjectMap(value)));
  }

  Future<MobileEnvelope<PendingNotification>> markNotificationRead(int id) async {
    final json = await postJson(XcagiMobileEndpoints.notificationRead(id), {});
    return MobileEnvelope.fromJson(json, (value) => PendingNotification.fromJson(_asObjectMap(value)));
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
