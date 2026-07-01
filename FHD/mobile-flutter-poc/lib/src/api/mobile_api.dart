import 'dart:async';
import 'dart:convert';
import 'dart:io';

import '../platform/credential_cipher.dart';
import '../policy/android_runtime_policy.dart';
import 'mobile_models.dart';
import 'mobile_session_store.dart';

class XcagiMobileEndpoints {
  static const rootHealth = 'api/health';
  static const base = 'api/mobile/v1';
  static const health = '$base/health';
  static const authLogin = '$base/auth/login';
  static const authRegister = '$base/auth/register';
  static const authSessionValidate = '$base/auth/session/validate';
  static const authLoginWithPhoneCode = '$base/auth/login-with-phone-code';
  static const authOidcExchange = '$base/auth/oidc/exchange';
  static const authRefresh = '$base/auth/refresh';
  static const legacyAuthRegister = 'api/auth/register';
  static const lanAccessRequests = 'api/lan/access-requests';
  static const lanStatus = 'api/lan/status';
  static const hostDiscoverHint = '$base/host/discover-hint';
  static const me = '$base/me';
  static const adminHome = '$base/admin/home';
  static const home = '$base/home';
  static const gitBranches = '$base/git/branches';
  static const aiGroups = '$base/ai-groups';
  static const aiGroupCandidates = '$base/ai-groups/candidates';
  static const circlePosts = '$base/circle/posts';
  static const navMenu = '$base/nav-menu';
  static const platformShell = '$base/platform-shell';
  static const syncStatus = '$base/sync/status';
  static const syncPull = '$base/sync/pull';
  static const syncPush = '$base/sync/push';
  static const syncConflicts = '$base/sync/conflicts';
  static const devicesRegister = '$base/devices/register';
  static const notificationsPending = '$base/notifications/pending';
  static const authQrConfirm = '$base/auth/qr/confirm';
  static const pairingExchange = '$base/pairing/exchange';
  static const pairingIssue = '$base/pairing/issue';
  static const relayMobileConfirm = '$base/relay/mobile/confirm';
  static const relayMobileConfirmCode = '$base/relay/mobile/confirm-code';
  static const relayMobileBindAccount = '$base/relay/mobile/bind-account';
  static const relayMobileDesktops = '$base/relay/mobile/desktops';
  static const relayTasks = '$base/relay/tasks';
  static const walletBalance = '$base/wallet/balance';
  static const onboardingIndustries = '$base/onboarding/industries';
  static const onboardingIndustryBaseline =
      '$base/onboarding/industry-baseline';
  static const onboardingSelectIndustry = '$base/onboarding/select-industry';
  static const installHostFoundation =
      '$base/mod-store/install-host-foundation';
  static const installMod = '$base/mod-store/install';
  static const installIndustrySeed = '$base/mod-store/install-industry-seed';
  static const installCustomerDeliverySeed =
      '$base/mod-store/install-customer-delivery-seed';
  static const approvalRequests = '$base/approval/requests';
  static const customers = '$base/customers';
  static const shipments = '$base/shipments';
  static const serviceBridgeRequests = '$base/service-bridge/requests';
  static const serviceBridgeRequestsRespond =
      '$base/service-bridge/requests/{id}/respond';
  static const csInfo = '$base/cs/info';
  static const csMessages = '$base/cs/messages';
  static const mods = '$base/mods';
  static const paymentPlans = '$base/payment/plans';
  static const paymentCheckout = '$base/payment/checkout';
  static const imDirect = 'api/im/conversations/direct';
  static const financeSummary = 'api/finance/summary';
  static const aiChat = 'api/ai/chat';
  static const aiChatStream = 'api/ai/chat/stream';
  static const approvalDetailTemplate = 'api/approval/requests/{id}';
  static const approvalApproveTemplate = 'api/approval/requests/{id}/approve';
  static const approvalRejectTemplate = 'api/approval/requests/{id}/reject';
  static const marketAccountSync = 'api/market/account-sync';
  static const marketSessionHandoff = 'api/market/session-handoff';
  static const marketSendPhoneCode = 'api/market/send-phone-code';
  static const appConfig = 'api/app/config';
  static const appFeedback = 'api/app/feedback';
  static const accountDelete = 'api/auth/account/delete';
  static const accountExport = 'api/auth/export';
  static const codexSuperEmployeeMessages =
      '$base/admin/codex-super-employee/messages';
  static const claudeSuperEmployeeMessages =
      '$base/admin/claude-super-employee/messages';
  static const cursorSuperEmployeeMessages =
      '$base/admin/cursor-super-employee/messages';
  static const traeSuperEmployeeMessages =
      '$base/admin/trae-super-employee/messages';
  static const circleLikeTemplate = '$base/circle/posts/{postId}/like';
  static const circleCommentsTemplate = '$base/circle/posts/{postId}/comments';
  static const relayTasksDetail = '$base/relay/tasks/{taskId}';
  static const aiGroupMessagesTemplate = '$base/ai-groups/{groupId}/messages';
  static const aiGroupMembersTemplate = '$base/ai-groups/{groupId}/members';
  static const aiGroupMemberTemplate =
      '$base/ai-groups/{groupId}/members/{employeeId}';
  static const aiGroupPinTemplate = '$base/ai-groups/{groupId}/pin';
  static const aiGroupMarkUnreadTemplate =
      '$base/ai-groups/{groupId}/mark-unread';
  static const aiGroupMarkReadTemplate = '$base/ai-groups/{groupId}/mark-read';
  static const aiGroupFollowedTemplate = '$base/ai-groups/{groupId}/followed';
  static const aiGroupHiddenTemplate = '$base/ai-groups/{groupId}/hidden';
  static const aiGroupDeleteTemplate = '$base/ai-groups/{groupId}';
  static const conversationPinTemplate =
      '$base/conversations/{conversationId}/pin';
  static const conversationMarkUnreadTemplate =
      '$base/conversations/{conversationId}/mark-unread';
  static const conversationMarkReadTemplate =
      '$base/conversations/{conversationId}/mark-read';
  static const conversationFollowedTemplate =
      '$base/conversations/{conversationId}/followed';
  static const conversationHiddenTemplate =
      '$base/conversations/{conversationId}/hidden';
  static const conversationDeleteTemplate =
      '$base/conversations/{conversationId}';
  static const paymentQueryTemplate = '$base/payment/query/{outTradeNo}';
  static const legacyServiceBridgeRequests = 'api/service-bridge/requests';
  static const legacyServiceBridgeRequestsRespondTemplate =
      'api/service-bridge/requests/{id}/respond';
  static const inventoryItems = 'api/inventory/items';
  static const legacyModsList = 'api/mods/';
  static const imMessagesTemplate = 'api/im/conversations/{id}/messages';

  static String superEmployeeMessages(String tool) {
    switch (tool.trim().toLowerCase()) {
      case 'claude':
        return claudeSuperEmployeeMessages;
      case 'cursor':
        return cursorSuperEmployeeMessages;
      case 'trae':
        return traeSuperEmployeeMessages;
      case 'codex':
      default:
        return codexSuperEmployeeMessages;
    }
  }

  static String circleLike(int postId) {
    return circleLikeTemplate.replaceFirst('{postId}', '$postId');
  }

  static String circleComments(int postId) {
    return circleCommentsTemplate.replaceFirst('{postId}', '$postId');
  }

  static String relayTaskStatus(String taskId) {
    return relayTasksDetail.replaceFirst(
      '{taskId}',
      Uri.encodeComponent(taskId),
    );
  }

  static String approvalDetail(int id) {
    return approvalDetailTemplate.replaceFirst('{id}', '$id');
  }

  static String approvalApprove(int id) {
    return approvalApproveTemplate.replaceFirst('{id}', '$id');
  }

  static String approvalReject(int id) {
    return approvalRejectTemplate.replaceFirst('{id}', '$id');
  }

  static String serviceBridgeRespond(int id) {
    return serviceBridgeRequestsRespond.replaceFirst('{id}', '$id');
  }

  static String aiGroupMessages(String groupId) {
    return aiGroupMessagesTemplate.replaceFirst(
      '{groupId}',
      Uri.encodeComponent(groupId),
    );
  }

  static String aiGroupMembers(String groupId) {
    return aiGroupMembersTemplate.replaceFirst(
      '{groupId}',
      Uri.encodeComponent(groupId),
    );
  }

  static String aiGroupMember({
    required String groupId,
    required String employeeId,
  }) {
    return aiGroupMemberTemplate
        .replaceFirst('{groupId}', Uri.encodeComponent(groupId))
        .replaceFirst('{employeeId}', Uri.encodeComponent(employeeId));
  }

  static String aiGroupPin(String groupId) {
    return aiGroupPinTemplate.replaceFirst(
      '{groupId}',
      Uri.encodeComponent(groupId),
    );
  }

  static String aiGroupMarkUnread(String groupId) {
    return aiGroupMarkUnreadTemplate.replaceFirst(
      '{groupId}',
      Uri.encodeComponent(groupId),
    );
  }

  static String aiGroupMarkRead(String groupId) {
    return aiGroupMarkReadTemplate.replaceFirst(
      '{groupId}',
      Uri.encodeComponent(groupId),
    );
  }

  static String aiGroupFollowed(String groupId) {
    return aiGroupFollowedTemplate.replaceFirst(
      '{groupId}',
      Uri.encodeComponent(groupId),
    );
  }

  static String aiGroupHidden(String groupId) {
    return aiGroupHiddenTemplate.replaceFirst(
      '{groupId}',
      Uri.encodeComponent(groupId),
    );
  }

  static String aiGroupDelete(String groupId) {
    return aiGroupDeleteTemplate.replaceFirst(
      '{groupId}',
      Uri.encodeComponent(groupId),
    );
  }

  static String conversationPin(String conversationId) {
    return conversationPinTemplate.replaceFirst(
      '{conversationId}',
      Uri.encodeComponent(conversationId),
    );
  }

  static String conversationMarkUnread(String conversationId) {
    return conversationMarkUnreadTemplate.replaceFirst(
      '{conversationId}',
      Uri.encodeComponent(conversationId),
    );
  }

  static String conversationMarkRead(String conversationId) {
    return conversationMarkReadTemplate.replaceFirst(
      '{conversationId}',
      Uri.encodeComponent(conversationId),
    );
  }

  static String conversationFollowed(String conversationId) {
    return conversationFollowedTemplate.replaceFirst(
      '{conversationId}',
      Uri.encodeComponent(conversationId),
    );
  }

  static String conversationHidden(String conversationId) {
    return conversationHiddenTemplate.replaceFirst(
      '{conversationId}',
      Uri.encodeComponent(conversationId),
    );
  }

  static String conversationDelete(String conversationId) {
    return conversationDeleteTemplate.replaceFirst(
      '{conversationId}',
      Uri.encodeComponent(conversationId),
    );
  }

  static String legacyServiceBridgeRespond(int id) {
    return legacyServiceBridgeRequestsRespondTemplate.replaceFirst(
      '{id}',
      '$id',
    );
  }

  static String paymentQuery(String outTradeNo) {
    return paymentQueryTemplate.replaceFirst(
      '{outTradeNo}',
      Uri.encodeComponent(outTradeNo),
    );
  }

  static String imMessages(int conversationId) {
    return imMessagesTemplate.replaceFirst('{id}', '$conversationId');
  }
}

class XcagiMobileTopology {
  static const productionHost = 'xiu-ci.com';
  static const productionScheme = 'https';
  static const siteRootUrl = 'https://xiu-ci.com';
  static const fhdApiBaseUrl = 'https://xiu-ci.com/fhd-api';
  static const marketBaseUrl = 'https://xiu-ci.com/market';
  static const llmV1BaseUrl = 'https://xiu-ci.com/v1';
  static const marketCatalogUrl = 'https://xiu-ci.com/api/market/catalog';
  static const imWsUrl = 'wss://xiu-ci.com/ws/im';
  static const desktopFhdListenPort = 17500;
  static const fhdApiListenPort = 5000;
  static const fhdApiUpstreamPort = 5100;
  static const modstoreListenPort = 8765;
  static const mustRunProcesses = ['web', 'modstore-scheduler'];
}

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

enum AndroidServerMode {
  lan,
  cloud,
}

class AndroidServerRouter {
  const AndroidServerRouter({
    this.fhdHost = '127.0.0.1',
    this.mode = AndroidServerMode.cloud,
    this.isEnterprise = true,
    this.fhdDefaultPort = MobileAndroidBuild.fhdDefaultPort,
    this.enterpriseFhdBaseUrlRaw = MobileAndroidBuild.enterpriseFhdBaseUrl,
    this.modstoreBaseUrlRaw = MobileAndroidBuild.modstoreBaseUrl,
  });

  final String fhdHost;
  final AndroidServerMode mode;
  final bool isEnterprise;
  final int fhdDefaultPort;
  final String enterpriseFhdBaseUrlRaw;
  final String modstoreBaseUrlRaw;

  String fhdBaseUrl() {
    if (mode == AndroidServerMode.cloud && isEnterprise) {
      return enterpriseFhdBaseUrl();
    }
    return lanFhdBaseUrl();
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
    final base =
        enterpriseFhdBaseUrlRaw.trim().replaceFirst(RegExp(r'/+$'), '');
    return '$base/';
  }

  String modstoreBaseUrl() {
    final base = modstoreBaseUrlRaw.trim().replaceFirst(RegExp(r'/+$'), '');
    return '$base/';
  }

  String activeWriteBaseUrl() {
    switch (mode) {
      case AndroidServerMode.lan:
        return fhdBaseUrl();
      case AndroidServerMode.cloud:
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

class AndroidAuthHeaderPolicy {
  const AndroidAuthHeaderPolicy._();

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
    final rawPath =
        (parsed?.path ?? urlOrPath).replaceFirst(RegExp(r'/+$'), '');
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
      '/${XcagiMobileEndpoints.relayMobileConfirm}',
      '/${XcagiMobileEndpoints.relayMobileConfirmCode}',
    };
    return publicPaths.any(path.endsWith);
  }
}

class MobileAndroidBuild {
  static const productSku = 'enterprise';
  static const fhdDefaultPort = 17500;
  static const modstoreBaseUrl = 'https://xiu-ci.com';
  static const enterpriseFhdBaseUrl = 'https://xiu-ci.com/fhd-api';
  static const versionCode = 10;
  static const versionName = '10.0.0';
  static const displayVersion = 'v$versionName';
  static const profileVersionText = '版本 10.0.0 (10)';
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

  String get androidPromptMessage => '最新版本 $versionName，将下载完整安装包并交给系统安装器安装。';

  Map<String, Object?> get apkDelta {
    final value = raw['apk_delta'];
    if (value is! Map) return const {};
    return value.map((key, value) => MapEntry(key.toString(), value));
  }
}

class MobileApiClient {
  MobileApiClient({
    MobileApiConfig config = const MobileApiConfig(),
    MobileSessionStore? sessionStore,
    HttpClient? httpClient,
    AndroidCredentialCipher? credentialCipher,
  })  : _config = config,
        _sessionStore = sessionStore ?? FileMobileSessionStore(),
        _httpClient = httpClient ?? HttpClient(),
        _credentialCipher = credentialCipher ?? const AndroidCredentialCipher();

  final MobileApiConfig _config;
  final MobileSessionStore _sessionStore;
  final HttpClient _httpClient;
  final AndroidCredentialCipher _credentialCipher;
  final StreamController<MobileSessionData> _sessionChanges =
      StreamController<MobileSessionData>.broadcast();
  MobileSessionData _lastSession = MobileSessionData.empty;

  String get configuredRelayId => _config.relayId.trim();
  String get localAvatarSource => _config.localAvatarSource.trim();
  MobileSessionStore get sessionStore => _sessionStore;
  Stream<MobileSessionData> get sessionChanges async* {
    yield _lastSession;
    yield* _sessionChanges.stream;
  }

  Future<MobileSessionData> loadSession() async {
    final stored = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    final decodedStored = await _decodeSavedCredential(stored);
    final session = decodedStored.mergePreferNonBlank(_configSession());
    _rememberSession(session);
    return session;
  }

  Future<void> _saveSession(
    MobileSessionData session, {
    MobileSessionData? notifyAs,
  }) async {
    await _sessionStore.save(session);
    _rememberSession(notifyAs ?? await _decodeSavedCredential(session));
  }

  Future<MobileSessionData> _decodeSavedCredential(
    MobileSessionData session,
  ) async {
    final stored = session.savedPassword;
    if (stored.isEmpty) return session;
    if (!stored.startsWith('enc:v1:')) return session;
    final decoded = await _credentialCipher.decrypt(stored).catchError(
          (_) => '',
        );
    if (decoded == stored) return session;
    return session.copyWith(savedPassword: decoded);
  }

  Future<String> _encodeSavedCredential(String password) async {
    if (password.isEmpty) return '';
    return _credentialCipher.encrypt(password).catchError((_) => password);
  }

  void _rememberSession(MobileSessionData session) {
    _lastSession = session;
    if (!_sessionChanges.isClosed) {
      _sessionChanges.add(session);
    }
  }

  Future<String> resolvedLocalAvatarSource() async =>
      (await loadSession()).localAvatarSource.trim();

  Future<void> saveLocalProfile({
    required String displayName,
    required String avatarSource,
  }) async {
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    final cleanName = displayName.trim();
    await _saveSession(
      current.copyWith(
        username: cleanName.isEmpty ? current.username : cleanName,
        localAvatarSource: avatarSource.trim(),
      ),
    );
  }

  Future<void> saveLoginPreferences({
    required String username,
    required String password,
    required bool rememberPassword,
    required bool autoLogin,
  }) async {
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    final storedPassword =
        rememberPassword ? await _encodeSavedCredential(password) : '';
    final notifySession = current.copyWith(
      savedUsername: rememberPassword ? username.trim() : '',
      savedPassword: rememberPassword ? password : '',
      rememberPassword: rememberPassword,
      autoLogin: autoLogin,
    );
    await _saveSession(
      current.copyWith(
        savedUsername: rememberPassword ? username.trim() : '',
        savedPassword: storedPassword,
        rememberPassword: rememberPassword,
        autoLogin: autoLogin,
      ),
      notifyAs: notifySession,
    );
  }

  Future<void> saveLocalSettings({
    String? themeMode,
    bool? biometricEnabled,
  }) async {
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    var next = current;
    final rawTheme = themeMode;
    if (rawTheme != null) {
      next = next.copyWith(
        themeMode: rawTheme.trim().isEmpty ? 'system' : rawTheme.trim(),
      );
    }
    if (biometricEnabled != null) {
      next = next.copyWith(biometricEnabled: biometricEnabled);
    }
    await _saveSession(next);
  }

  Future<void> saveLegalAcceptedVersion(String version) async {
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    await _saveSession(
      current.copyWith(legalAcceptedVersion: version.trim()),
    );
  }

  Future<void> saveSetupComplete(bool complete) async {
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    await _saveSession(current.copyWith(setupComplete: complete));
  }

  Future<void> saveFcmToken(String token) async {
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    await _saveSession(current.copyWith(fcmToken: token.trim()));
  }

  Future<void> saveAutoLanProbe(bool enabled) async {
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    await _saveSession(current.copyWith(autoLanProbe: enabled));
  }

  Future<void> saveSyncState({
    int? syncCursor,
    String? lastSyncAt,
    bool? autoSync,
  }) async {
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    var next = current;
    if (syncCursor != null) {
      next = next.copyWith(syncCursor: syncCursor < 0 ? 0 : syncCursor);
    }
    if (lastSyncAt != null) {
      next = next.copyWith(lastSyncAt: lastSyncAt.trim());
    }
    if (autoSync != null) {
      next = next.copyWith(autoSync: autoSync);
    }
    await _saveSession(next);
  }

  Future<void> saveWalletBalanceJson(String json) async {
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    await _saveSession(current.copyWith(walletBalanceJson: json.trim()));
  }

  Future<void> clearActiveAuth() async {
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    await _saveSession(
      current.copyWith(
        accessToken: '',
        refreshToken: '',
        sessionId: '',
        username: '',
        accountKind: '',
        userId: 0,
        marketAccessToken: '',
        marketRefreshToken: '',
        relayDesktopId: '',
        relayBaseUrl: '',
        localBaseUrl: '',
        relaySessionToken: '',
        relayAccountId: '',
        relayTenantId: '',
        relayPairedAt: '',
        inflightRelayTasks: const <String, String>{},
        walletBalanceJson: '',
        setupComplete: false,
        autoLogin: false,
        cachedChatMessages: const <String, List<Map<String, Object?>>>{},
        conversationListStates: const <String, Map<String, Object?>>{},
      ),
    );
  }

  Future<void> persistLoginSession(
    Map<String, Object?>? data, {
    required String fallbackUsername,
    required String fallbackAccountKind,
  }) async {
    if (data == null || data.isEmpty) return;
    final user = _asObjectMap(data['user']);
    final accessToken = _readString(data, const ['access_token']);
    final marketToken = _readString(data, const ['market_access_token']);
    if (accessToken.isEmpty && marketToken.isEmpty) return;

    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    final next = current.mergePreferNonBlank(
      MobileSessionData(
        accessToken: accessToken,
        refreshToken: _readString(data, const ['refresh_token']),
        sessionId: _readString(data, const ['session_id']),
        username: _readString(user, const ['username', 'name'])
            .ifEmpty(fallbackUsername),
        accountKind: _readString(data, const ['account_kind'])
            .ifEmpty(fallbackAccountKind),
        userId: _readInt(user, const ['id'], 0),
        marketAccessToken: marketToken,
        marketRefreshToken: _readString(data, const ['market_refresh_token']),
      ),
    );
    await _saveSession(
      next.copyWith(
        setupComplete: false,
        serverMode: _preferredServerModeAfterLogin(next),
      ),
    );
  }

  Future<void> persistRelayBindingMeta(
    String relayId,
    Map<String, Object?>? data,
  ) async {
    final cleanRelayId = relayId.trim().ifEmpty(_relayIdFromBindingData(data));
    if (cleanRelayId.isEmpty) return;
    final payload = data ?? const <String, Object?>{};
    final desktop = _asObjectMap(payload['desktop']);
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );
    await _saveSession(
      current.copyWith(
        relayDesktopId: cleanRelayId,
        relayBaseUrl: _firstNonBlank([
          _readString(payload, const ['relay_base_url']),
          _readString(desktop, const ['relay_base_url']),
          current.relayBaseUrl,
        ]),
        localBaseUrl: _firstNonBlank([
          _readString(payload, const ['local_base_url']),
          _readString(desktop, const ['local_base_url']),
          current.localBaseUrl,
        ]),
        relaySessionToken: _firstNonBlank([
          _readString(payload, const ['session_token']),
          current.relaySessionToken,
        ]),
        relayAccountId: _firstNonBlank([
          _readString(payload, const ['account_id']),
          current.relayAccountId,
        ]),
        relayTenantId: _firstNonBlank([
          _readString(payload, const ['tenant_id']),
          current.relayTenantId,
        ]),
        relayPairedAt: _firstNonBlank([
          _readString(payload, const ['paired_at']),
          _readString(desktop, const ['paired_at']),
          current.relayPairedAt,
        ]),
      ),
    );
  }

  Future<void> persistPairingSession(
    Map<String, Object?>? data, {
    String hostWithPort = '',
    bool clearRelayDesktop = false,
    bool setupComplete = false,
  }) async {
    final payload = data ?? const <String, Object?>{};
    final resolvedHost = hostWithPort.trim().ifEmpty(
          _hostPortFromPairingData(payload),
        );
    final current = await _sessionStore.load().catchError(
          (_) => MobileSessionData.empty,
        );

    var next = current;
    final access = _readString(payload, const ['access_token']);
    if (access.isNotEmpty) {
      final user = _asObjectMap(payload['user']);
      next = next.copyWith(
        accessToken: access,
        refreshToken: _firstNonBlank([
          _readString(payload, const ['refresh_token']),
          current.refreshToken,
        ]),
        sessionId: _firstNonBlank([
          _readString(payload, const ['session_id', 'session_token']),
          current.sessionId,
        ]),
        username: _firstNonBlank([
          _readString(user, const ['username', 'display_name']),
          current.username,
          'mobile',
        ]),
        accountKind: _firstNonBlank([
          _readString(payload, const ['account_kind']),
          current.accountKind,
          'enterprise',
        ]),
        userId: _readInt(user, const ['id'], current.userId),
        relayBaseUrl: _firstNonBlank([
          _readString(payload, const ['relay_base_url']),
          current.relayBaseUrl,
        ]),
        localBaseUrl: _firstNonBlank([
          _readString(payload, const ['local_base_url']),
          current.localBaseUrl,
        ]),
        relaySessionToken: _firstNonBlank([
          _readString(payload, const ['session_token']),
          _readString(payload, const ['session_id']),
          current.relaySessionToken,
        ]),
        relayAccountId: _firstNonBlank([
          _readString(payload, const ['account_id']),
          current.relayAccountId,
        ]),
        relayTenantId: _firstNonBlank([
          _readString(payload, const ['tenant_id']),
          current.relayTenantId,
        ]),
        relayPairedAt: _firstNonBlank([
          _readString(payload, const ['paired_at']),
          current.relayPairedAt,
        ]),
      );
    }

    if (resolvedHost.isNotEmpty) {
      next = next.copyWith(
        fhdHost: resolvedHost,
        serverMode: 'lan',
        inflightRelayTasks: const <String, String>{},
      );
    }
    if (clearRelayDesktop) {
      next = next.copyWith(
        relayDesktopId: '',
        inflightRelayTasks: const <String, String>{},
      );
    }
    if (setupComplete) {
      next = next.copyWith(setupComplete: true);
    }
    await _saveSession(next);
  }

  Future<MobileEnvelope<Map<String, Object?>>> mobileHealth() async {
    final json = await getJson(XcagiMobileEndpoints.health);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<Map<String, Object?>> rootHealth() {
    return getJson(XcagiMobileEndpoints.rootHealth);
  }

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

  Future<MobileEnvelope<Map<String, Object?>>> aiGroups() async {
    final json = await getJson(XcagiMobileEndpoints.aiGroups);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> aiGroupCandidates() async {
    final json = await getJson(XcagiMobileEndpoints.aiGroupCandidates);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> createAiGroup(
    String name,
  ) async {
    final json = await postJson(XcagiMobileEndpoints.aiGroups, {
      'name': name.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> aiGroupMessages(
    String groupId, {
    int limit = 100,
  }) async {
    final json = await getJson(
      XcagiMobileEndpoints.aiGroupMessages(groupId),
      query: {'limit': '$limit'},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> postAiGroupMessage({
    required String groupId,
    required String message,
    List<String> mentions = const [],
    bool dispatch = false,
    String branchContext = '',
    Map<String, String> context = const {},
  }) async {
    final branch = branchContext.trim();
    final json = await postJson(XcagiMobileEndpoints.aiGroupMessages(groupId), {
      'message': message.trim(),
      'sender_name': '我',
      'mentions': mentions,
      'dispatch': dispatch,
      'branch_context': branch,
      'branch': branch,
      'context': context,
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> addAiGroupMember({
    required String groupId,
    required String employeeId,
    required String modId,
    required String name,
    required String avatar,
    required String summary,
  }) async {
    final json = await postJson(XcagiMobileEndpoints.aiGroupMembers(groupId), {
      'employee_id': employeeId.trim(),
      'mod_id': modId.trim(),
      'name': name.trim(),
      'avatar': avatar.trim(),
      'summary': summary.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> removeAiGroupMember({
    required String groupId,
    required String employeeId,
  }) async {
    final json = await deleteJson(
      XcagiMobileEndpoints.aiGroupMember(
        groupId: groupId,
        employeeId: employeeId,
      ),
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> toggleAiGroupPin(
    String groupId,
  ) async {
    final json = await putJson(XcagiMobileEndpoints.aiGroupPin(groupId), {});
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> markAiGroupUnread(
    String groupId,
  ) async {
    final json =
        await postJson(XcagiMobileEndpoints.aiGroupMarkUnread(groupId), {});
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> markAiGroupRead(
    String groupId,
  ) async {
    final json =
        await postJson(XcagiMobileEndpoints.aiGroupMarkRead(groupId), {});
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> toggleAiGroupFollowed(
    String groupId,
  ) async {
    final json =
        await putJson(XcagiMobileEndpoints.aiGroupFollowed(groupId), {});
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> toggleAiGroupHidden(
    String groupId,
  ) async {
    final json = await putJson(XcagiMobileEndpoints.aiGroupHidden(groupId), {});
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> deleteAiGroup(
    String groupId,
  ) async {
    final json = await deleteJson(XcagiMobileEndpoints.aiGroupDelete(groupId));
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> toggleConversationPin(
    String conversationId,
  ) async {
    final json =
        await putJson(XcagiMobileEndpoints.conversationPin(conversationId), {});
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> markConversationUnread(
    String conversationId,
  ) async {
    final json = await postJson(
      XcagiMobileEndpoints.conversationMarkUnread(conversationId),
      {},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> markConversationRead(
    String conversationId,
  ) async {
    final json = await postJson(
      XcagiMobileEndpoints.conversationMarkRead(conversationId),
      {},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> toggleConversationFollowed(
    String conversationId,
  ) async {
    final json = await putJson(
      XcagiMobileEndpoints.conversationFollowed(conversationId),
      {},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> toggleConversationHidden(
    String conversationId,
  ) async {
    final json = await putJson(
      XcagiMobileEndpoints.conversationHidden(conversationId),
      {},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> deleteConversation(
    String conversationId,
  ) async {
    final json = await deleteJson(
        XcagiMobileEndpoints.conversationDelete(conversationId));
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> csInfo() async {
    final json = await getJson(XcagiMobileEndpoints.csInfo);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> csMessages({
    String? since,
  }) async {
    final query = since == null || since.trim().isEmpty
        ? const <String, String>{}
        : {'since': since.trim()};
    final json = await getJson(XcagiMobileEndpoints.csMessages, query: query);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> postCsMessage(
    String body,
  ) async {
    final json = await postJson(XcagiMobileEndpoints.csMessages, {
      'body': body.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> login({
    required String username,
    required String password,
    required String accountKind,
  }) async {
    final json = await postJson(XcagiMobileEndpoints.authLogin, {
      'username': username.trim(),
      'password': password,
      'account_kind': accountKind.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> validateSession() async {
    final json = await getJson(XcagiMobileEndpoints.authSessionValidate);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> oidcExchange({
    required String code,
    required String state,
  }) async {
    final json = await postJson(XcagiMobileEndpoints.authOidcExchange, {
      'code': code.trim(),
      'state': state.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> refreshSession(
    String refreshToken,
  ) async {
    final json = await postJson(XcagiMobileEndpoints.authRefresh, {
      'refresh_token': refreshToken.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> discoverHint() async {
    final json = await getJson(XcagiMobileEndpoints.hostDiscoverHint);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> me() async {
    final json = _withLocalAvatar(
      await getJson(XcagiMobileEndpoints.me),
      await resolvedLocalAvatarSource(),
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> register({
    required String username,
    required String password,
    required String email,
    required String industryId,
    required String budgetRange,
    required String accountKind,
  }) async {
    final json = await postJson(XcagiMobileEndpoints.authRegister, {
      'username': username.trim(),
      'password': password,
      'email': email.trim(),
      'industry_id': industryId.trim().isEmpty ? '通用' : industryId.trim(),
      'budget_range': budgetRange.trim(),
      'account_kind': accountKind.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<Map<String, Object?>> legacyRegister({
    required String username,
    required String password,
    String email = '',
    String verificationCode = '',
    String industryId = '',
    String budgetRange = '',
    String accountKind = 'enterprise',
  }) {
    return postJson(XcagiMobileEndpoints.legacyAuthRegister, {
      'username': username.trim(),
      'password': password,
      'email': email.trim(),
      'verification_code': verificationCode.trim(),
      'industry_id': industryId.trim(),
      'budget_range': budgetRange.trim(),
      'account_kind':
          accountKind.trim().isEmpty ? 'enterprise' : accountKind.trim(),
    });
  }

  Future<Map<String, Object?>> lanAccessRequest({
    required String deviceLabel,
    String note = '',
  }) {
    return postJson(XcagiMobileEndpoints.lanAccessRequests, {
      'device_label': deviceLabel.trim(),
      'note': note.trim(),
    });
  }

  Future<Map<String, Object?>> lanStatus() {
    return getJson(XcagiMobileEndpoints.lanStatus);
  }

  Future<MobileEnvelope<Map<String, Object?>>> sendPhoneCode(
    String phone,
  ) async {
    final json = await postJson(XcagiMobileEndpoints.marketSendPhoneCode, {
      'phone': phone.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> loginWithPhoneCode({
    required String phone,
    required String code,
    required String accountKind,
  }) async {
    final json = await postJson(XcagiMobileEndpoints.authLoginWithPhoneCode, {
      'phone': phone.trim(),
      'code': code.trim(),
      'account_kind': accountKind.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> deleteAccount(
    String password,
  ) async {
    final json = await postModstoreJson(XcagiMobileEndpoints.accountDelete, {
      'password': password,
    });
    final envelope = MobileEnvelope.fromJson(json, _asObjectMap);
    if (envelope.success) {
      await clearActiveAuth();
    }
    return envelope;
  }

  Future<MobileEnvelope<Map<String, Object?>>> exportAccountData() async {
    final json = await getModstoreJson(XcagiMobileEndpoints.accountExport);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileAppConfigData> appConfig({
    int currentVersionCode = MobileAndroidBuild.versionCode,
    String sku = MobileAndroidBuild.productSku,
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
    AndroidProductSkuConfig.setRemoteSku(data.sku);
    return data;
  }

  Future<MobileUpdateCheckResult> checkForUpdate({
    int currentVersionCode = MobileAndroidBuild.versionCode,
    String sku = MobileAndroidBuild.productSku,
  }) async {
    final json = await getModstoreJson(
      XcagiMobileEndpoints.appConfig,
      query: {
        'platform': 'android',
        'sku': sku,
        'current_version_code': currentVersionCode.toString(),
      },
    );
    AndroidProductSkuConfig.setRemoteSku(_readString(json, const ['sku']));
    final latestVersionCode = _readInt(
      json,
      const ['latest_android_version'],
      0,
    );
    final minVersionCode = _readInt(json, const ['min_android_version'], 0);
    final forceUpdate = _readBool(json, const ['force_update']);
    final forceRequired = currentVersionCode < minVersionCode ||
        (forceUpdate && currentVersionCode < latestVersionCode);
    final available = forceRequired || currentVersionCode < latestVersionCode;
    final latestVersionName = _readString(
      json,
      const ['latest_android_version_name'],
    ).ifEmpty(latestVersionCode.toString());

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
      'app_version': MobileAndroidBuild.versionName,
      'sku': MobileAndroidBuild.productSku,
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

  Future<MobileEnvelope<Map<String, Object?>>> exchangePairing({
    String nonce = '',
    String code = '',
    String baseUrl = '',
  }) async {
    final json = await postJson(
      XcagiMobileEndpoints.pairingExchange,
      {
        'nonce': nonce.trim(),
        'code': code.trim(),
      },
      baseUrl: baseUrl.trim().isEmpty ? null : baseUrl.trim(),
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> issuePairing() async {
    final json = await postJson(XcagiMobileEndpoints.pairingIssue, const {});
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> confirmAuthQr({
    required String qrId,
    required String username,
    required String password,
    required String accountKind,
  }) async {
    final json = await postJson(XcagiMobileEndpoints.authQrConfirm, {
      'qr_id': qrId.trim(),
      'username': username.trim(),
      'password': password,
      'account_kind': accountKind.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> syncStatus() async {
    final json = await getJson(XcagiMobileEndpoints.syncStatus);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> syncPull({
    int sinceCursor = 0,
  }) async {
    final json = await postJson(XcagiMobileEndpoints.syncPull, {
      'since_cursor': sinceCursor,
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> syncPush(
    List<Map<String, Object?>> items,
  ) async {
    final json = await postJson(XcagiMobileEndpoints.syncPush, {
      'items': items,
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> syncConflicts() async {
    final json = await getJson(XcagiMobileEndpoints.syncConflicts);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> registerDevice(
    Map<String, Object?> body,
  ) async {
    final json = await postJson(XcagiMobileEndpoints.devicesRegister, body);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> relayConfirm({
    required String relayId,
    required String code,
  }) async {
    final json = await postJson(XcagiMobileEndpoints.relayMobileConfirm, {
      'relay_id': relayId.trim(),
      'code': code.trim(),
    });
    final envelope = MobileEnvelope.fromJson(json, _asObjectMap);
    if (envelope.success) {
      await persistRelayBindingMeta(relayId.trim(), envelope.data);
    }
    return envelope;
  }

  Future<MobileEnvelope<Map<String, Object?>>> relayConfirmCode(
    String code,
  ) async {
    final json = await postJson(XcagiMobileEndpoints.relayMobileConfirmCode, {
      'code': code.trim(),
    });
    final envelope = MobileEnvelope.fromJson(json, _asObjectMap);
    if (envelope.success) {
      final relayId = _relayIdFromBindingData(envelope.data);
      if (relayId.isNotEmpty) {
        await persistRelayBindingMeta(relayId, envelope.data);
      }
    }
    return envelope;
  }

  Future<MobileEnvelope<Map<String, Object?>>> relayBindAccount(
    String relayId,
  ) async {
    final json = await postJson(XcagiMobileEndpoints.relayMobileBindAccount, {
      'relay_id': relayId.trim(),
    });
    final envelope = MobileEnvelope.fromJson(json, _asObjectMap);
    if (envelope.success) {
      await persistRelayBindingMeta(relayId.trim(), envelope.data);
    }
    return envelope;
  }

  Future<MobileEnvelope<Map<String, Object?>>> relayDesktops() async {
    final json = await getJson(XcagiMobileEndpoints.relayMobileDesktops);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> relayCreateTask({
    required String relayId,
    required String kind,
    required Map<String, Object?> payload,
  }) async {
    final json = await postJson(XcagiMobileEndpoints.relayTasks, {
      'relay_id': relayId.trim(),
      'kind': kind.trim(),
      'payload': payload,
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> relayTaskStatus(
    String taskId,
  ) async {
    final json = await getJson(XcagiMobileEndpoints.relayTaskStatus(taskId));
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> onboardingIndustries() async {
    final json = await getJson(XcagiMobileEndpoints.onboardingIndustries);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> industryBaseline(
    String industryId,
  ) async {
    final json = await getJson(
      XcagiMobileEndpoints.onboardingIndustryBaseline,
      query: {'industry_id': industryId.trim().isEmpty ? '通用' : industryId},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> selectOnboardingIndustry(
    String industryId,
  ) async {
    final json = await postJson(
      XcagiMobileEndpoints.onboardingSelectIndustry,
      {'industry_id': industryId.trim().isEmpty ? '通用' : industryId.trim()},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> installHostFoundation({
    String edition = 'generic',
  }) async {
    final json = await postJson(
      XcagiMobileEndpoints.installHostFoundation,
      const {},
      query: {'edition': edition},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> installIndustrySeed(
    String industryId,
  ) async {
    final json = await postJson(XcagiMobileEndpoints.installIndustrySeed, {
      'industry_id': industryId.trim().isEmpty ? '通用' : industryId.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> installMod({
    required String modId,
    required String industryId,
  }) async {
    final json = await postJson(XcagiMobileEndpoints.installMod, {
      'mod_id': modId.trim(),
      'industry_id': industryId.trim().isEmpty ? '通用' : industryId.trim(),
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> installCustomerDeliverySeed({
    required String modId,
    required String industryId,
  }) async {
    final json = await postJson(
      XcagiMobileEndpoints.installCustomerDeliverySeed,
      {
        'mod_id': modId.trim(),
        'industry_id': industryId.trim().isEmpty ? '通用' : industryId.trim(),
      },
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> approvals({
    int page = 1,
    int pageSize = 50,
  }) async {
    final json = await getJson(
      XcagiMobileEndpoints.approvalRequests,
      query: {'page': '$page', 'page_size': '$pageSize'},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<Map<String, Object?>> approvalDetail(int id) {
    return getJson(XcagiMobileEndpoints.approvalDetail(id));
  }

  Future<Map<String, Object?>> approveApproval({
    required int id,
    required int approverId,
    required String opinion,
  }) {
    return postJson(XcagiMobileEndpoints.approvalApprove(id), {
      'approver_id': approverId,
      'opinion': opinion.trim(),
    });
  }

  Future<Map<String, Object?>> rejectApproval({
    required int id,
    required int approverId,
    required String reason,
  }) {
    return postJson(XcagiMobileEndpoints.approvalReject(id), {
      'approver_id': approverId,
      'reason': reason.trim(),
    });
  }

  Future<MobileEnvelope<Map<String, Object?>>> customers({
    int page = 1,
    int perPage = 20,
  }) async {
    final json = await getJson(
      XcagiMobileEndpoints.customers,
      query: {'page': '$page', 'per_page': '$perPage'},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> shipments({
    int page = 1,
    int perPage = 20,
  }) async {
    final json = await getJson(
      XcagiMobileEndpoints.shipments,
      query: {'page': '$page', 'per_page': '$perPage'},
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> bridgeRequests({
    int page = 1,
    int perPage = 20,
    String? status,
    String? requestType,
  }) async {
    final query = <String, String>{
      'page': '$page',
      'per_page': '$perPage',
    };
    final cleanStatus = status?.trim();
    if (cleanStatus != null && cleanStatus.isNotEmpty) {
      query['status'] = cleanStatus;
    }
    final cleanRequestType = requestType?.trim();
    if (cleanRequestType != null && cleanRequestType.isNotEmpty) {
      query['request_type'] = cleanRequestType;
    }
    final json = await getJson(
      XcagiMobileEndpoints.serviceBridgeRequests,
      query: query,
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<Map<String, Object?>> legacyBridgeRequests({
    int page = 1,
    int perPage = 20,
    String? status,
    String? requestType,
  }) {
    final query = <String, String>{
      'page': '$page',
      'per_page': '$perPage',
    };
    final cleanStatus = status?.trim();
    if (cleanStatus != null && cleanStatus.isNotEmpty) {
      query['status'] = cleanStatus;
    }
    final cleanRequestType = requestType?.trim();
    if (cleanRequestType != null && cleanRequestType.isNotEmpty) {
      query['request_type'] = cleanRequestType;
    }
    return getJson(
      XcagiMobileEndpoints.legacyServiceBridgeRequests,
      query: query,
    );
  }

  Future<MobileEnvelope<Map<String, Object?>>> bridgeRespond({
    required int id,
    required String response,
    String respondedBy = 'android',
  }) async {
    final json = await putJson(XcagiMobileEndpoints.serviceBridgeRespond(id), {
      'response': response.trim(),
      'responded_by':
          respondedBy.trim().isEmpty ? 'android' : respondedBy.trim(),
      'status': 'resolved',
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<Map<String, Object?>> legacyBridgeRespond({
    required int id,
    required String response,
    String respondedBy = 'android',
  }) {
    return putJson(XcagiMobileEndpoints.legacyServiceBridgeRespond(id), {
      'response': response.trim(),
      'responded_by':
          respondedBy.trim().isEmpty ? 'android' : respondedBy.trim(),
      'status': 'resolved',
    });
  }

  Future<Map<String, Object?>> inventoryItems() {
    return getJson(XcagiMobileEndpoints.inventoryItems);
  }

  Future<Map<String, Object?>> modsList() {
    return getJson(XcagiMobileEndpoints.legacyModsList);
  }

  Future<Map<String, Object?>> financeSummary() {
    return getJson(XcagiMobileEndpoints.financeSummary);
  }

  Future<Map<String, Object?>> marketAccountSync(
    Map<String, String> body,
  ) {
    return postJson(XcagiMobileEndpoints.marketAccountSync, body);
  }

  Future<Map<String, Object?>> marketSessionHandoff() {
    return getJson(XcagiMobileEndpoints.marketSessionHandoff);
  }

  Future<MobileEnvelope<Map<String, Object?>>> mobileMods() async {
    final json = await getJson(XcagiMobileEndpoints.mods);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> paymentPlans() async {
    final json = await getJson(XcagiMobileEndpoints.paymentPlans);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> paymentCheckout(
    Map<String, Object?> body,
  ) async {
    final json = await postJson(XcagiMobileEndpoints.paymentCheckout, body);
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<Map<String, Object?>>> paymentQuery(
    String outTradeNo,
  ) async {
    final json = await getJson(XcagiMobileEndpoints.paymentQuery(outTradeNo));
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<MobileEnvelope<AiCircleListData>> circlePosts({
    int limit = 50,
  }) async {
    final json = await getJson(
      XcagiMobileEndpoints.circlePosts,
      query: {'limit': '$limit'},
    );
    return MobileEnvelope.fromJson(
      json,
      (value) => AiCircleListData.fromJson(_asObjectMap(value)),
    );
  }

  Future<MobileEnvelope<Map<String, Object?>>> toggleCircleLike(
    int postId,
  ) async {
    final json = await postJson(XcagiMobileEndpoints.circleLike(postId), {});
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<Map<String, Object?>> imCreateDirect(int peerUserId) {
    return postJson(XcagiMobileEndpoints.imDirect, {
      'peer_user_id': peerUserId,
    });
  }

  Future<Map<String, Object?>> imListMessages(
    int conversationId, {
    int limit = 50,
  }) {
    return getJson(
      XcagiMobileEndpoints.imMessages(conversationId),
      query: {'limit': '$limit'},
    );
  }

  Future<Map<String, Object?>> imSendMessage({
    required int conversationId,
    required String body,
  }) {
    return postJson(XcagiMobileEndpoints.imMessages(conversationId), {
      'body': body.trim(),
    });
  }

  Future<MobileEnvelope<Map<String, Object?>>> addCircleComment(
    int postId,
    String body,
  ) async {
    final text = body.trim();
    final json = await postJson(XcagiMobileEndpoints.circleComments(postId), {
      'body': text,
    });
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<Map<String, Object?>> chat(
    String message, {
    String? sessionId,
    Map<String, Object?> context = const {},
  }) {
    final cleanContext = Map<String, Object?>.of(context)
      ..removeWhere((key, value) => key.trim().isEmpty || value == null);
    return postJson(XcagiMobileEndpoints.aiChat, {
      'message': message,
      'body': message,
      'source': 'pro',
      'mode': 'professional',
      if (sessionId != null && sessionId.trim().isNotEmpty)
        'session_id': sessionId.trim(),
      if (cleanContext.isNotEmpty) 'context': cleanContext,
    });
  }

  Future<String> streamChat(
    String message, {
    String? sessionId,
    int userId = 0,
    List<Map<String, String>> recentMessages = const [],
    void Function(String token)? onToken,
  }) async {
    final context = <String, Object?>{};
    if (recentMessages.isNotEmpty) {
      context['recent_messages'] = recentMessages;
    }
    final body = <String, Object?>{
      'message': message,
      'source': 'pro',
      'mode': 'professional',
      if (userId > 0) 'user_id': '$userId',
      if (context.isNotEmpty) 'context': context,
    };

    final request = await _open('POST', XcagiMobileEndpoints.aiChatStream);
    request.headers.set(HttpHeaders.acceptHeader, 'text/event-stream');
    if (userId > 0) {
      request.headers.set('X-User-ID', '$userId');
    }
    final bytes = utf8.encode(jsonEncode(body));
    request.contentLength = bytes.length;
    request.add(bytes);

    final response = await request.close().timeout(_config.timeout);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final text = await utf8.decodeStream(response).timeout(_config.timeout);
      final body = _asObjectMap(text.trim().isEmpty ? null : jsonDecode(text));
      throw MobileApiException(
        statusCode: response.statusCode,
        message: body['message']?.toString() ??
            body['error']?.toString() ??
            'HTTP ${response.statusCode}',
        body: body,
      );
    }

    final buffer = StringBuffer();
    await for (final line
        in response.transform(utf8.decoder).transform(const LineSplitter())) {
      final trimmed = line.trim();
      if (!trimmed.startsWith('data:')) continue;
      final payload = trimmed.substring('data:'.length).trim();
      if (payload.isEmpty || payload == '[DONE]') continue;

      final json = _asObjectMap(jsonDecode(payload));
      final eventType = json['type']?.toString() ?? '';
      if (eventType.isNotEmpty) {
        switch (eventType) {
          case 'token':
            final token = json['text']?.toString() ?? '';
            if (token.isNotEmpty) {
              buffer.write(token);
              onToken?.call(token);
            }
            break;
          case 'done':
            final result = json['result'];
            final finalText =
                _chatResultText(result).ifEmpty(buffer.toString());
            return finalText.ifEmpty('（无回复）');
          case 'error':
            throw MobileApiException(
              statusCode: response.statusCode,
              message: json['message']?.toString() ?? 'stream error',
              body: json,
            );
        }
      } else {
        final error = json['error']?.toString() ?? '';
        if (error.isNotEmpty) {
          throw MobileApiException(
            statusCode: response.statusCode,
            message: error,
            body: json,
          );
        }
        final token = json['text']?.toString() ?? '';
        if (token.isNotEmpty) {
          buffer.write(token);
          onToken?.call(token);
        }
        if (json['done'] == true) {
          return buffer.toString().ifEmpty('（无回复）');
        }
      }
    }
    return buffer.toString().ifEmpty('（无回复）');
  }

  Future<MobileEnvelope<List<SuperEmployeeMessage>>> superEmployeeMessages(
    String tool, {
    int limit = 80,
  }) async {
    final json = await getJson(
      XcagiMobileEndpoints.superEmployeeMessages(tool),
      query: {'limit': '$limit'},
    );
    return MobileEnvelope.fromJson(json, parseSuperEmployeeMessages);
  }

  Future<MobileEnvelope<Map<String, Object?>>> postSuperEmployeeMessage(
    String tool,
    String body,
  ) async {
    final json = await postJson(
      XcagiMobileEndpoints.superEmployeeMessages(tool),
      {
        'body': body,
        'message': body,
        'context': const {'source': 'mobile', 'client_surface': 'mobile'},
      },
    );
    return MobileEnvelope.fromJson(json, _asObjectMap);
  }

  Future<Map<String, Object?>> getJson(
    String path, {
    Map<String, String> query = const {},
  }) async {
    final request = await _open('GET', path, query: query);
    return _readJsonResponse(request);
  }

  Future<Map<String, Object?>> postJson(
    String path,
    Map<String, Object?> body, {
    Map<String, String> query = const {},
    String? baseUrl,
  }) async {
    final request = await _open('POST', path, query: query, baseUrl: baseUrl);
    final bytes = utf8.encode(jsonEncode(body));
    request.contentLength = bytes.length;
    request.add(bytes);
    return _readJsonResponse(request);
  }

  Future<Map<String, Object?>> postModstoreJson(
    String path,
    Map<String, Object?> body, {
    Map<String, String> query = const {},
  }) async {
    final request = await _open(
      'POST',
      path,
      query: query,
      baseUrl: _config.modstoreBaseUrl,
      authToken: _config.marketAccessToken,
    );
    final bytes = utf8.encode(jsonEncode(body));
    request.contentLength = bytes.length;
    request.add(bytes);
    return _readJsonResponse(request);
  }

  Future<Map<String, Object?>> getModstoreJson(
    String path, {
    Map<String, String> query = const {},
  }) async {
    final request = await _open(
      'GET',
      path,
      query: query,
      baseUrl: _config.modstoreBaseUrl,
      authToken: _config.marketAccessToken,
    );
    return _readJsonResponse(request);
  }

  Future<Map<String, Object?>> putJson(
    String path,
    Map<String, Object?> body, {
    Map<String, String> query = const {},
  }) async {
    final request = await _open('PUT', path, query: query);
    final bytes = utf8.encode(jsonEncode(body));
    request.contentLength = bytes.length;
    request.add(bytes);
    return _readJsonResponse(request);
  }

  Future<Map<String, Object?>> deleteJson(
    String path, {
    Map<String, String> query = const {},
  }) async {
    final request = await _open('DELETE', path, query: query);
    return _readJsonResponse(request);
  }

  Future<HttpClientRequest> _open(
    String method,
    String path, {
    Map<String, String> query = const {},
    String? baseUrl,
    String? authToken,
  }) async {
    final uri = _buildUri(path, query, baseUrl: baseUrl);
    final request =
        await _httpClient.openUrl(method, uri).timeout(_config.timeout);
    request.headers.set(HttpHeaders.acceptHeader, 'application/json');
    request.headers.set(HttpHeaders.contentTypeHeader, 'application/json');
    request.headers.set('X-XCAGI-Client', 'android');
    request.headers.set('X-XCAGI-SKU', MobileAndroidBuild.productSku);

    final session = await loadSession();
    final explicitAuthorization = authToken?.trim() ?? '';
    if (explicitAuthorization.isNotEmpty) {
      request.headers.set(
        HttpHeaders.authorizationHeader,
        'Bearer $explicitAuthorization',
      );
    } else {
      final selectedBearer = _requestToken(session: session, url: uri);
      if (AndroidAuthHeaderPolicy.shouldAttachSelectedBearer(
        isPublicAuthWriteRequest:
            AndroidAuthHeaderPolicy.isPublicAuthWriteRequest(uri.toString()),
        callerAuthorization:
            request.headers.value(HttpHeaders.authorizationHeader) ?? '',
        selectedBearer: selectedBearer,
      )) {
        request.headers.set(
          HttpHeaders.authorizationHeader,
          'Bearer $selectedBearer',
        );
      }
    }
    final sessionId = _firstNonBlank([
      _config.sessionId,
      session.sessionId,
    ]);
    if (sessionId.isNotEmpty) {
      request.headers.set('X-Session-ID', sessionId);
      request.headers.set(HttpHeaders.cookieHeader, 'session_id=$sessionId');
    }
    return request;
  }

  Uri _buildUri(
    String path,
    Map<String, String> query, {
    String? baseUrl,
  }) {
    final normalizedPath = path.startsWith('/') ? path.substring(1) : path;
    final rawBase = baseUrl ?? _config.baseUrl;
    final base = Uri.parse(
      rawBase.endsWith('/') ? rawBase : '$rawBase/',
    );
    final uri = base.resolve(normalizedPath);
    if (query.isEmpty) return uri;
    return uri.replace(queryParameters: {...uri.queryParameters, ...query});
  }

  Map<String, Object?> _withLocalAvatar(
    Map<String, Object?> json,
    String avatarSource,
  ) {
    final avatar = avatarSource.trim();
    if (avatar.isEmpty) return json;

    final data = _asObjectMap(json['data']);
    if (data.isEmpty) return json;
    final user = _asObjectMap(data['user']);
    if (user.isEmpty) return json;
    final existing =
        (user['avatar_url'] ?? user['avatar'] ?? '').toString().trim();
    if (existing.isNotEmpty) return json;

    return {
      ...json,
      'data': {
        ...data,
        'user': {
          ...user,
          'avatar_url': avatar,
        },
      },
    };
  }

  MobileSessionData _configSession() {
    return MobileSessionData(
      accessToken: _config.accessToken,
      sessionId: _config.sessionId,
      marketAccessToken: _config.marketAccessToken,
      marketRefreshToken: _config.marketRefreshToken,
      localAvatarSource: _config.localAvatarSource,
      relayDesktopId: _config.relayId,
    );
  }

  String _requestToken({
    required MobileSessionData session,
    required Uri url,
  }) {
    return AndroidAuthHeaderPolicy.selectBearer(
      url: url.toString(),
      fhdToken: _firstNonBlank([
        _config.accessToken,
        session.accessToken,
      ]),
      marketToken: _firstNonBlank([
        _config.marketAccessToken,
        session.marketAccessToken,
      ]),
      modstoreBaseUrl: _config.modstoreBaseUrl,
      enterpriseFhdBaseUrl: XcagiMobileTopology.fhdApiBaseUrl,
    );
  }

  Future<Map<String, Object?>> _readJsonResponse(
    HttpClientRequest request,
  ) async {
    final response = await request.close().timeout(_config.timeout);
    final text = await utf8.decodeStream(response).timeout(_config.timeout);
    final status = response.statusCode;
    Object? decoded;

    if (text.trim().isNotEmpty) {
      decoded = jsonDecode(text);
    }
    final body = _asObjectMap(decoded);
    if (status < 200 || status >= 300) {
      throw MobileApiException(
        statusCode: status,
        message: body['message']?.toString() ??
            body['error']?.toString() ??
            'HTTP $status',
        body: body,
      );
    }
    return body;
  }
}

class MobileApiException implements Exception {
  const MobileApiException({
    required this.statusCode,
    required this.message,
    required this.body,
  });

  final int statusCode;
  final String message;
  final Map<String, Object?> body;

  @override
  String toString() => 'MobileApiException($statusCode): $message';
}

Map<String, Object?> _asObjectMap(Object? value) {
  if (value is Map<String, Object?>) return value;
  if (value is Map) {
    return value.map((key, value) => MapEntry(key.toString(), value));
  }
  return const <String, Object?>{};
}

String _chatResultText(Object? result) {
  if (result == null) return '';
  if (result is String) return result.trim();
  final map = _asObjectMap(result);
  for (final key in const ['response', 'reply', 'message', 'content', 'text']) {
    final value = map[key]?.toString().trim() ?? '';
    if (value.isNotEmpty) return value;
  }
  return '';
}

String _readString(Map<String, Object?> json, List<String> keys) {
  for (final key in keys) {
    final value = json[key];
    if (value == null) continue;
    final text = value.toString().trim();
    if (text.isNotEmpty) return text;
  }
  return '';
}

int _readInt(Map<String, Object?> json, List<String> keys, int fallback) {
  for (final key in keys) {
    final value = json[key];
    if (value is int) return value;
    if (value is num) return value.toInt();
    if (value is String) {
      final parsed = int.tryParse(value.trim());
      if (parsed != null) return parsed;
    }
  }
  return fallback;
}

String _relayIdFromBindingData(Map<String, Object?>? data) {
  final payload = data ?? const <String, Object?>{};
  return _firstNonBlank([
    _readString(payload, const ['relay_id']),
    _readString(_asObjectMap(payload['relay']), const ['relay_id']),
    _readString(_asObjectMap(payload['desktop']), const ['relay_id']),
  ]);
}

String _hostPortFromPairingData(Map<String, Object?> data) {
  final baseUrl = _firstNonBlank([
    _readString(data, const ['api_base_url']),
    _readString(data, const ['base_url']),
  ]);
  final fromBase = _hostPortFromApiBase(baseUrl);
  final host = _firstNonBlank([
    _readString(data, const ['host']),
    fromBase.$1,
  ]);
  if (host.isEmpty) return '';
  final port = _readInt(data, const ['port'], fromBase.$2);
  return _compactHostPort(host, port);
}

(String, int) _hostPortFromApiBase(String raw) {
  if (raw.trim().isEmpty) return ('', 0);
  final normalized = raw.contains('://') ? raw.trim() : 'http://${raw.trim()}';
  final uri = Uri.tryParse(normalized);
  if (uri == null) return ('', 0);
  final host = uri.host.trim();
  if (host.isEmpty) return ('', 0);
  final port = uri.hasPort
      ? uri.port
      : switch (uri.scheme.toLowerCase()) {
          'https' => 443,
          'http' => 80,
          _ => 0,
        };
  return (host, port);
}

String _compactHostPort(String host, int port) {
  final bare = host
      .trim()
      .replaceFirst(RegExp(r'^https?://'), '')
      .split('/')
      .first
      .split(':')
      .first
      .trim();
  if (bare.isEmpty) return '';
  if (port <= 0 || port > 65535) return bare;
  return '$bare:$port';
}

String _preferredServerModeAfterLogin(MobileSessionData session) {
  return AndroidAuthRoutingPolicy.preferredServerModeAfterLogin(
    isEnterprise: AndroidProductSkuConfig.isEnterprise(
      buildSku: MobileAndroidBuild.productSku,
    ),
    configuredHost: session.fhdHost,
    currentMode: session.serverMode,
  );
}

String _firstNonBlank(List<String> values) {
  for (final value in values) {
    final clean = value.trim();
    if (clean.isNotEmpty) return clean;
  }
  return '';
}

bool _readBool(Map<String, Object?> json, List<String> keys) {
  for (final key in keys) {
    final value = json[key];
    if (value is bool) return value;
    if (value is num) return value != 0;
    if (value is String) {
      final normalized = value.trim().toLowerCase();
      if (['1', 'true', 'yes', 'on'].contains(normalized)) return true;
      if (['0', 'false', 'no', 'off'].contains(normalized)) return false;
    }
  }
  return false;
}
