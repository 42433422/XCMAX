part of 'mobile_api.dart';

class MobileApiConfig {
  const MobileApiConfig({
    this.baseUrl = const String.fromEnvironment(
      'XCAGI_MOBILE_BASE_URL',
      defaultValue: XcagiMobileTopology.fhdApiBaseUrl,
    ),
    this.accessToken = const String.fromEnvironment(
      'XCAGI_MOBILE_ACCESS_TOKEN',
    ),
    this.sessionId = const String.fromEnvironment('XCAGI_MOBILE_SESSION_ID'),
    this.relayId = const String.fromEnvironment('XCAGI_MOBILE_RELAY_ID'),
    this.marketAccessToken = const String.fromEnvironment(
      'XCAGI_MARKET_ACCESS_TOKEN',
    ),
    this.marketRefreshToken = const String.fromEnvironment(
      'XCAGI_MARKET_REFRESH_TOKEN',
    ),
    this.localAvatarSource = const String.fromEnvironment(
      'XCAGI_MOBILE_AVATAR_SOURCE',
    ),
    this.modstoreBaseUrl = const String.fromEnvironment(
      'XCAGI_MODSTORE_BASE_URL',
      defaultValue: XcagiMobileTopology.siteRootUrl,
    ),
    this.timeout = const Duration(seconds: 8),
  });

  final String baseUrl;
  final String accessToken;
  final String sessionId;
  final String relayId;
  final String marketAccessToken;
  final String marketRefreshToken;
  final String localAvatarSource;
  final String modstoreBaseUrl;
  final Duration timeout;
}

enum MobileServerMode { lan, cloud }

class MobileServerRouter {
  const MobileServerRouter({
    this.fhdHost = '127.0.0.1',
    this.mode = MobileServerMode.cloud,
    this.isEnterprise = true,
    this.fhdDefaultPort = MobileBuildConfig.fhdDefaultPort,
    this.enterpriseFhdBaseUrlRaw = MobileBuildConfig.enterpriseFhdBaseUrl,
    this.modstoreBaseUrlRaw = MobileBuildConfig.modstoreBaseUrl,
  });

  final String fhdHost;
  final MobileServerMode mode;
  final bool isEnterprise;
  final int fhdDefaultPort;
  final String enterpriseFhdBaseUrlRaw;
  final String modstoreBaseUrlRaw;

  String fhdBaseUrl() {
    if (mode == MobileServerMode.cloud && isEnterprise) {
      return enterpriseFhdBaseUrl();
    }
    return lanFhdBaseUrl();
  }

  /// 手机端 LAN 直连专用：当后端 loopback 监听 17500 时，手机不可达，
  /// 需改用 vite proxy 端口 5011（监听 0.0.0.0）。
  String lanReachableBaseUrl() {
    final raw = lanFhdBaseUrl();
    final loopbackPort = ':$fhdDefaultPort/';
    if (raw.endsWith(loopbackPort)) {
      final prefix = raw.substring(0, raw.length - loopbackPort.length);
      return '$prefix:${XcagiMobileTopology.mobileLanProxyListenPort}/';
    }
    return raw;
  }

  String lanFhdBaseUrl() {
    var host = fhdHost.trim();
    if (host.startsWith('http://')) {
      host = host.substring('http://'.length);
    } else if (host.startsWith('https://')) {
      host = host.substring('https://'.length);
    }
    host = host.replaceFirst(RegExp(r'/+$'), '');
    final colon = host.indexOf(':');
    final bare = colon >= 0 ? host.substring(0, colon) : host;
    final port = colon >= 0
        ? host.substring(colon + 1).ifEmpty('$fhdDefaultPort')
        : '$fhdDefaultPort';
    return 'http://$bare:$port/';
  }

  String enterpriseFhdBaseUrl() {
    final base = enterpriseFhdBaseUrlRaw.trim().replaceFirst(
          RegExp(r'/+$'),
          '',
        );
    return '$base/';
  }

  String modstoreBaseUrl() {
    final base = modstoreBaseUrlRaw.trim().replaceFirst(RegExp(r'/+$'), '');
    return '$base/';
  }

  String activeWriteBaseUrl() {
    switch (mode) {
      case MobileServerMode.lan:
        return fhdBaseUrl();
      case MobileServerMode.cloud:
        return modstoreBaseUrl();
    }
  }

  String fhdImWebSocketUrl(String sessionId) {
    final http = fhdBaseUrl().replaceFirst(RegExp(r'/+$'), '');
    final ws = http.startsWith('https://')
        ? 'wss://${http.substring('https://'.length)}'
        : http.startsWith('http://')
            ? 'ws://${http.substring('http://'.length)}'
            : 'ws://$http';
    final encoded = Uri.encodeQueryComponent(sessionId);
    return '$ws/ws/im?session_id=$encoded';
  }
}

class MobileAuthHeaderPolicy {
  const MobileAuthHeaderPolicy._();

  static String normalizedBase(String base) =>
      base.trim().replaceFirst(RegExp(r'/+$'), '');

  static bool isEnterpriseFhdRequest({
    required String url,
    required String enterpriseFhdBaseUrl,
  }) {
    final base = normalizedBase(enterpriseFhdBaseUrl);
    if (base.isEmpty) return false;
    return url == base || url.startsWith('$base/');
  }

  static bool isModstoreRequest({
    required String url,
    required String modstoreBaseUrl,
    required String enterpriseFhdBaseUrl,
  }) {
    final base = normalizedBase(modstoreBaseUrl);
    if (base.isEmpty) return false;
    return (url == base || url.startsWith('$base/')) &&
        !isEnterpriseFhdRequest(
          url: url,
          enterpriseFhdBaseUrl: enterpriseFhdBaseUrl,
        );
  }

  static String selectBearer({
    required String url,
    required String fhdToken,
    required String marketToken,
    required String modstoreBaseUrl,
    required String enterpriseFhdBaseUrl,
  }) {
    final fhd = fhdToken.trim();
    final market = marketToken.trim();
    if (isEnterpriseFhdRequest(
      url: url,
      enterpriseFhdBaseUrl: enterpriseFhdBaseUrl,
    )) {
      return fhd;
    }
    if (isModstoreRequest(
      url: url,
      modstoreBaseUrl: modstoreBaseUrl,
      enterpriseFhdBaseUrl: enterpriseFhdBaseUrl,
    )) {
      return market;
    }
    return fhd.isNotEmpty ? fhd : market;
  }

  static bool shouldAttachSelectedBearer({
    required bool isPublicAuthWriteRequest,
    required String callerAuthorization,
    required String selectedBearer,
  }) {
    return !isPublicAuthWriteRequest &&
        callerAuthorization.trim().isEmpty &&
        selectedBearer.trim().isNotEmpty;
  }

  static bool isPublicAuthWriteRequest(String urlOrPath) {
    final parsed = Uri.tryParse(urlOrPath);
    final rawPath = (parsed?.path ?? urlOrPath).replaceFirst(
      RegExp(r'/+$'),
      '',
    );
    final path = rawPath.startsWith('/') ? rawPath : '/$rawPath';
    const publicPaths = {
      '/api/auth/login',
      '/api/auth/register',
      '/api/auth/login-with-phone-code',
      '/${XcagiMobileEndpoints.authLogin}',
      '/${XcagiMobileEndpoints.authRegister}',
      '/${XcagiMobileEndpoints.authLoginWithPhoneCode}',
      '/${XcagiMobileEndpoints.authRefresh}',
      '/${XcagiMobileEndpoints.authOidcExchange}',
      '/${XcagiMobileEndpoints.authQrConfirm}',
      '/${XcagiMobileEndpoints.pairingIssue}',
      '/${XcagiMobileEndpoints.pairingExchange}',
    };
    return publicPaths.any(path.endsWith);
  }
}

class MobileBuildConfig {
  static const productSku = 'enterprise';
  static const fhdDefaultPort = 17500;
  static const modstoreBaseUrl = 'https://xiu-ci.com';
  static const enterpriseFhdBaseUrl = 'https://xiu-ci.com/fhd-api';
  static const versionCode = 10;
  static const versionName = '1.0.0.1';
  static const displayVersion = 'v$versionName';
  static const profileVersionText = '版本 1.0.0.1 (10)';
}

class MobileUpdateCheckResult {
  const MobileUpdateCheckResult({
    required this.available,
    required this.force,
    required this.versionName,
    required this.downloadUrl,
    required this.raw,
  });

  final bool available;
  final bool force;
  final String versionName;
  final String downloadUrl;
  final Map<String, Object?> raw;

  String get title => force ? '需要更新' : '发现新版本';

  String get updatePromptMessage => '最新版本 $versionName，将下载完整安装包并交给系统安装器安装。';

  Map<String, Object?> get apkDelta {
    final value = raw['apk_delta'];
    if (value is! Map) return const {};
    return value.map((key, value) => MapEntry(key.toString(), value));
  }
}
