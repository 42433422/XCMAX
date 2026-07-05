import 'dart:async';

import 'package:flutter/material.dart';

import '../api/mobile_api.dart';
import '../api/mobile_models.dart';
import '../api/mobile_session_store.dart';
import '../data/mobile_repository.dart';
import '../data/mobile_repository_scope.dart';
import '../features/about/about_screen.dart';
import '../features/approval/approval_screens.dart';
import '../features/auth/auth_screen.dart';
import '../features/auth/register_screen.dart';
import '../features/bridge/bridge_screen.dart';
import '../features/business/business_screens.dart';
import '../features/chat/chat_screen.dart';
import '../features/circle/ai_circle_screen.dart';
import '../features/connect/connect_screen.dart';
import '../features/contacts/contacts_screen.dart';
import '../features/contacts/employee_profile_screen.dart';
import '../features/contacts/fixed_partner_profile_screen.dart';
import '../features/cs/cs_chat_screen.dart';
import '../features/enterprise/enterprise_module_screen.dart';
import '../features/finance/longtail_screen.dart';
import '../features/groups/ai_group_screens.dart';
import '../features/im/im_messenger_screen.dart';
import '../features/legal/legal_consent_screen.dart';
import '../features/market/market_list_screen.dart';
import '../features/notifications/notification_list_screen.dart';
import '../features/onboarding/mobile_onboarding_screen.dart';
import '../features/scan/scan_qr_screen.dart';
import '../features/settings/settings_screen.dart';
import '../features/shell/home_shell.dart';
import '../features/tools/ocr_screen.dart';
import '../features/webview/desktop_tool_webview_screen.dart';
import '../models/conversation.dart';
import '../platform/android_background_work_scheduler.dart';
import '../platform/android_deep_link_bridge.dart';
import '../platform/biometric_gate.dart';
import '../policy/pinned_ids.dart';
import '../theme/app_assets.dart';
import '../theme/app_theme.dart';
import '../widgets/we_ui.dart';

enum AndroidStartupRoute {
  legal,
  authAutoLogin,
  auth,
  onboarding,
  home,
}

@visibleForTesting
AndroidStartupRoute resolveAndroidStartupRoute({
  required MobileSessionData session,
  required MobileAppConfigData? appConfig,
}) {
  final legalVersion = appConfig?.legalVersion.trim();
  if (legalVersion != null &&
      legalVersion.isNotEmpty &&
      session.legalAcceptedVersion.trim() != legalVersion) {
    return AndroidStartupRoute.legal;
  }

  final loggedIn = session.hasAuth;
  final canAutoLogin = session.canAutoLoginForAndroid;
  if (!loggedIn && canAutoLogin) return AndroidStartupRoute.authAutoLogin;
  if (!loggedIn) return AndroidStartupRoute.auth;

  final setupComplete =
      session.setupComplete || session.fhdHost.trim().isNotEmpty;
  return setupComplete
      ? AndroidStartupRoute.home
      : AndroidStartupRoute.onboarding;
}

@visibleForTesting
ThemeMode androidThemeModeFromSession(String rawMode) {
  switch (rawMode.trim().toLowerCase()) {
    case 'light':
      return ThemeMode.light;
    case 'dark':
      return ThemeMode.dark;
    default:
      return ThemeMode.system;
  }
}

class AndroidStartupApp extends StatefulWidget {
  const AndroidStartupApp({
    super.key,
    required this.repository,
    this.biometricGate = const AndroidBiometricGate(),
    this.deepLinkBridge = const AndroidDeepLinkBridge(),
    this.backgroundWorkScheduler = const AndroidBackgroundWorkScheduler(),
    this.enableBiometricGate = true,
  });

  final MobileRepository repository;
  final AndroidBiometricGate biometricGate;
  final AndroidDeepLinkBridge deepLinkBridge;
  final AndroidBackgroundWorkScheduler backgroundWorkScheduler;
  final bool enableBiometricGate;

  @override
  State<AndroidStartupApp> createState() => _AndroidStartupAppState();
}

class _AndroidStartupAppState extends State<AndroidStartupApp> {
  MobileSessionData _session = MobileSessionData.empty;
  MobileAppConfigData? _appConfig;
  AndroidStartupRoute? _route;
  StreamSubscription<MobileSessionData>? _sessionSubscription;
  StreamSubscription<String>? _deepLinkSubscription;
  final _navigatorKey = GlobalKey<NavigatorState>();
  final _scaffoldMessengerKey = GlobalKey<ScaffoldMessengerState>();
  final _homeController = HomeShellController();
  var _unlocked = false;
  var _checkingBiometric = false;
  var _biometricPromptInFlight = false;
  var _autoLoginStarted = false;
  var _handlingDeepLink = false;
  String? _autoLoginError;
  String? _pendingDeepLinkRoute;

  MobileApiClient get _client => widget.repository.client;

  @override
  void initState() {
    super.initState();
    _sessionSubscription = _client.sessionChanges.listen(_handleSessionChanged);
    _deepLinkSubscription = widget.deepLinkBridge.routes.listen(_queueDeepLink);
    unawaited(_bootstrap());
    unawaited(_loadInitialDeepLinkRoute());
  }

  @override
  void dispose() {
    _sessionSubscription?.cancel();
    _deepLinkSubscription?.cancel();
    _homeController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'XCAGI',
      navigatorKey: _navigatorKey,
      scaffoldMessengerKey: _scaffoldMessengerKey,
      theme: AppTheme.light(),
      darkTheme: AppTheme.dark(),
      themeMode: androidThemeModeFromSession(_session.themeMode),
      builder: (context, child) => MobileRepositoryScope(
        repository: widget.repository,
        child: child ?? const SizedBox.shrink(),
      ),
      home: _buildHome(),
    );
  }

  Widget _buildHome() {
    if (_route == null) return const _StartupLoadingScreen();
    if (_checkingBiometric) return const _BiometricLockScreen();

    switch (_route!) {
      case AndroidStartupRoute.legal:
        return LegalConsentScreen(
          api: _client,
          legalVersion: _appConfig?.legalVersion ?? '1',
          onAccepted: _acceptLegalAndRefresh,
        );
      case AndroidStartupRoute.authAutoLogin:
        return _AutoLoginScreen(
          error: _autoLoginError,
          onRetry: _startAutoLogin,
          onManualLogin: () => _setRoute(AndroidStartupRoute.auth),
        );
      case AndroidStartupRoute.auth:
        return AuthScreen(
          repository: widget.repository,
          onDone: _refreshRouteFromSession,
        );
      case AndroidStartupRoute.onboarding:
        return MobileOnboardingScreen(
          repository: widget.repository,
          onFinish: _finishOnboarding,
        );
      case AndroidStartupRoute.home:
        return HomeShell(
          repository: widget.repository,
          controller: _homeController,
        );
    }
  }

  Future<void> _bootstrap() async {
    final session = await _client.loadSession();
    MobileAppConfigData? config;
    try {
      config = await _client.appConfig();
    } catch (_) {
      config = null;
    }
    if (!mounted) return;
    setState(() {
      _session = session;
      _appConfig = config;
      _route = resolveAndroidStartupRoute(
        session: session,
        appConfig: config,
      );
    });
    await _runBiometricGateIfNeeded(session);
    unawaited(_reconcileAndroidBackgroundWork(session));
    _startAutoLoginIfNeeded();
    _tryHandlePendingDeepLink();
  }

  void _handleSessionChanged(MobileSessionData session) {
    if (!mounted) return;
    setState(() => _session = session);
    unawaited(_reconcileAndroidBackgroundWork(session));
    unawaited(_runBiometricGateIfNeeded(session));
    _tryHandlePendingDeepLink();
  }

  Future<void> _runBiometricGateIfNeeded(MobileSessionData session) async {
    if (!widget.enableBiometricGate ||
        _unlocked ||
        _biometricPromptInFlight ||
        !session.biometricEnabled) {
      return;
    }
    _biometricPromptInFlight = true;
    final canAuthenticate =
        await widget.biometricGate.canAuthenticate().catchError((_) => false);
    if (!canAuthenticate) {
      _biometricPromptInFlight = false;
      return;
    }
    if (mounted) setState(() => _checkingBiometric = true);
    final ok = await widget.biometricGate.prompt().catchError((_) => false);
    if (!mounted) return;
    if (ok) {
      setState(() {
        _unlocked = true;
        _checkingBiometric = false;
      });
    } else {
      setState(() => _checkingBiometric = false);
      unawaited(widget.biometricGate.finishApp().catchError((_) {}));
    }
    _biometricPromptInFlight = false;
  }

  Future<void> _acceptLegalAndRefresh() async {
    final version = _appConfig?.legalVersion ?? '1';
    await _client.saveLegalAcceptedVersion(version);
    await _refreshRouteFromSession();
  }

  Future<void> _finishOnboarding() async {
    await _client.saveSetupComplete(true);
    await _refreshRouteFromSession();
  }

  Future<void> _refreshRouteFromSession() async {
    final session = await _client.loadSession();
    if (!mounted) return;
    setState(() {
      _session = session;
      _route = resolveAndroidStartupRoute(
        session: session,
        appConfig: _appConfig,
      );
      _autoLoginError = null;
      _autoLoginStarted = false;
    });
    unawaited(_reconcileAndroidBackgroundWork(session));
    _startAutoLoginIfNeeded();
    _tryHandlePendingDeepLink();
  }

  void _setRoute(AndroidStartupRoute route) {
    setState(() {
      _route = route;
      _autoLoginError = null;
    });
  }

  void _startAutoLoginIfNeeded() {
    if (_route != AndroidStartupRoute.authAutoLogin || _autoLoginStarted) {
      return;
    }
    _startAutoLogin();
  }

  void _startAutoLogin() {
    if (_autoLoginStarted) return;
    _autoLoginStarted = true;
    unawaited(_tryAutoLogin());
  }

  Future<void> _tryAutoLogin() async {
    try {
      await widget.repository.login(
        username: _session.savedUsername,
        password: _session.savedPassword,
        adminMode: _session.accountKind.trim().toLowerCase() == 'admin' ||
            _session.accountKind.trim().toLowerCase() == 'admin_portal',
        rememberPass: true,
        autoLogin: true,
      );
      await _refreshRouteFromSession();
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _autoLoginError = '自动登录失败，请手动登录';
        _autoLoginStarted = false;
        _route = AndroidStartupRoute.auth;
      });
    }
  }

  Future<void> _loadInitialDeepLinkRoute() async {
    final route = await widget.deepLinkBridge.initialRoute();
    if (route == null || !mounted) return;
    _queueDeepLink(route);
  }

  Future<void> _reconcileAndroidBackgroundWork(
      MobileSessionData session) async {
    await widget.backgroundWorkScheduler.reconcile(session).catchError((_) {});
  }

  void _queueDeepLink(String route) {
    final normalized = route.trim();
    if (normalized.isEmpty || !mounted) return;
    _pendingDeepLinkRoute = normalized;
    _tryHandlePendingDeepLink();
  }

  void _tryHandlePendingDeepLink() {
    if (_handlingDeepLink ||
        _pendingDeepLinkRoute == null ||
        !_session.hasAuth ||
        _route != AndroidStartupRoute.home) {
      return;
    }
    final route = _pendingDeepLinkRoute!;
    _pendingDeepLinkRoute = null;
    _handlingDeepLink = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) {
        _handlingDeepLink = false;
        return;
      }
      final handled = _openAndroidDeepLink(route);
      if (!handled) _pendingDeepLinkRoute = route;
      _handlingDeepLink = false;
      _tryHandlePendingDeepLink();
    });
  }

  bool _openAndroidDeepLink(String route) {
    final navigator = _navigatorKey.currentState;
    if (navigator == null) return false;
    final destination = resolveAndroidDeepLinkDestination(route);
    switch (destination.target) {
      case AndroidDeepLinkTarget.chat:
        _homeController.selectTab(0);
        navigator.popUntil((route) => route.isFirst);
        return true;
      case AndroidDeepLinkTarget.work:
        _homeController.selectTab(1);
        navigator.popUntil((route) => route.isFirst);
        return true;
      case AndroidDeepLinkTarget.discover:
        _homeController.selectTab(2);
        navigator.popUntil((route) => route.isFirst);
        return true;
      case AndroidDeepLinkTarget.profile:
        _homeController.selectTab(3);
        navigator.popUntil((route) => route.isFirst);
        return true;
      case AndroidDeepLinkTarget.aiChat:
        final conversation = _conversationForAndroidRoute(PinnedIds.assistant);
        if (conversation == null) {
          _homeController.selectTab(0);
          navigator.popUntil((route) => route.isFirst);
          return true;
        }
        _pushAndroidDeepLinkPage(
          navigator,
          ChatScreen(
            conversation: conversation,
            initialMessages: const [],
            repository: widget.repository,
          ),
        );
        return true;
      case AndroidDeepLinkTarget.conversationChat:
        final conversation = _conversationForAndroidRoute(
          destination.conversationId ?? '',
        );
        if (conversation == null) {
          _homeController.selectTab(0);
          navigator.popUntil((route) => route.isFirst);
          return true;
        }
        if (conversation.id == PinnedIds.cs) {
          _pushAndroidDeepLinkPage(
            navigator,
            CsChatScreen(repository: widget.repository),
          );
          return true;
        }
        _pushAndroidDeepLinkPage(
          navigator,
          ChatScreen(
            conversation: conversation,
            initialMessages: const [],
            repository: widget.repository,
          ),
        );
        return true;
      case AndroidDeepLinkTarget.csChat:
        _pushAndroidDeepLinkPage(
          navigator,
          CsChatScreen(repository: widget.repository),
        );
        return true;
      case AndroidDeepLinkTarget.fixedPartnerProfile:
        _pushAndroidDeepLinkPage(
          navigator,
          FixedPartnerProfileScreen(
            kind: _fixedPartnerKindFromAndroidRoute(destination.partnerKind),
            repository: widget.repository,
          ),
        );
        return true;
      case AndroidDeepLinkTarget.market:
        unawaited(_refreshWalletForAndroidPaymentReturn());
        _showAndroidDeepLinkSnack('已返回应用，正在刷新支付状态');
        _pushAndroidDeepLinkPage(
          navigator,
          MarketListScreen(repository: widget.repository),
        );
        return true;
      case AndroidDeepLinkTarget.mods:
        _pushAndroidDeepLinkPage(
          navigator,
          MarketListScreen(repository: widget.repository),
        );
        return true;
      case AndroidDeepLinkTarget.modWeb:
        _pushAndroidDeepLinkPage(
          navigator,
          ModWebViewScreen(
            modId: destination.modId ?? '',
            api: widget.repository.client,
          ),
        );
        return true;
      case AndroidDeepLinkTarget.desktopWebView:
        _pushAndroidDeepLinkPage(
          navigator,
          DesktopToolWebViewScreen(
            title: destination.title ?? '桌面工具',
            path: destination.path ?? '/',
            api: widget.repository.client,
          ),
        );
        return true;
      case AndroidDeepLinkTarget.aiEmployees:
        _pushAndroidDeepLinkPage(
          navigator,
          AiEmployeesScreen(repository: widget.repository),
        );
        return true;
      case AndroidDeepLinkTarget.aiCircle:
        _pushAndroidDeepLinkPage(
          navigator,
          AiCircleScreen(repository: widget.repository),
        );
        return true;
      case AndroidDeepLinkTarget.aiGroups:
        _pushAndroidDeepLinkPage(
          navigator,
          AiGroupListScreen(
            repository: widget.repository,
            initialGroups: const [],
          ),
        );
        return true;
      case AndroidDeepLinkTarget.aiGroupCreate:
        _pushAndroidDeepLinkPage(
          navigator,
          AiGroupCreateScreen(repository: widget.repository),
        );
        return true;
      case AndroidDeepLinkTarget.scanQr:
        _pushAndroidDeepLinkPage(
          navigator,
          ScanQrScreen(repository: widget.repository),
        );
        return true;
      case AndroidDeepLinkTarget.approvalList:
        _pushAndroidDeepLinkPage(
          navigator,
          ApprovalListScreen(repository: widget.repository),
        );
        return true;
      case AndroidDeepLinkTarget.approvalDetail:
        _pushAndroidDeepLinkPage(
          navigator,
          ApprovalDetailScreen(
            id: destination.approvalId ?? 0,
            repository: widget.repository,
          ),
        );
        return true;
      case AndroidDeepLinkTarget.aiEmployeeProfile:
        _pushAndroidDeepLinkPage(
          navigator,
          _DeepLinkedAiEmployeeProfileScreen(
            repository: widget.repository,
            modId: destination.modId ?? '',
            employeeId: destination.employeeId ?? '',
          ),
        );
        return true;
      case AndroidDeepLinkTarget.settings:
        _pushAndroidDeepLinkPage(
          navigator,
          SettingsScreen(api: widget.repository.client),
        );
        return true;
      case AndroidDeepLinkTarget.about:
        _pushAndroidDeepLinkPage(
          navigator,
          AboutScreen(api: widget.repository.client),
        );
        return true;
      case AndroidDeepLinkTarget.notifications:
        _pushAndroidDeepLinkPage(
          navigator,
          NotificationListScreen(repository: widget.repository),
        );
        return true;
      case AndroidDeepLinkTarget.ocr:
        _pushAndroidDeepLinkPage(
          navigator,
          const OcrScreen(),
        );
        return true;
      case AndroidDeepLinkTarget.bridge:
        _pushAndroidDeepLinkPage(
          navigator,
          BridgeScreen(repository: widget.repository),
        );
        return true;
      case AndroidDeepLinkTarget.erp:
        _pushAndroidDeepLinkPage(
          navigator,
          ErpScreen(repository: widget.repository),
        );
        return true;
      case AndroidDeepLinkTarget.erpTab:
        _pushAndroidDeepLinkPage(
          navigator,
          BusinessListScreen(
            kind: _businessListKindForAndroidTab(destination.tabIndex ?? 0),
            repository: widget.repository,
          ),
        );
        return true;
      case AndroidDeepLinkTarget.im:
        _pushAndroidDeepLinkPage(
          navigator,
          ImMessengerScreen(repository: widget.repository),
        );
        return true;
      case AndroidDeepLinkTarget.connect:
        _pushAndroidDeepLinkPage(
          navigator,
          ConnectScreen(
            onScan: () => navigator.push(
              MaterialPageRoute(
                builder: (_) => ScanQrScreen(repository: widget.repository),
              ),
            ),
          ),
        );
        return true;
      case AndroidDeepLinkTarget.connectPc:
        _pushAndroidDeepLinkPage(
          navigator,
          ConnectScreen(
            fromProfile: true,
            onBack: () => navigator.maybePop(),
            onSkipCloud: () => navigator.maybePop(),
            onNext: () => navigator.maybePop(),
            onScan: () => navigator.push(
              MaterialPageRoute(
                builder: (_) => ScanQrScreen(repository: widget.repository),
              ),
            ),
          ),
        );
        return true;
      case AndroidDeepLinkTarget.onboarding:
        _pushAndroidDeepLinkPage(
          navigator,
          MobileOnboardingScreen(
            repository: widget.repository,
            onFinish: () => navigator.maybePop(),
          ),
        );
        return true;
      case AndroidDeepLinkTarget.register:
        _pushAndroidDeepLinkPage(
          navigator,
          RegisterScreen(onLogin: () => navigator.maybePop()),
        );
        return true;
      case AndroidDeepLinkTarget.smartAnalysis:
        _pushAndroidDeepLinkPage(
          navigator,
          EnterpriseModuleScreen.smartAnalysis(
            onAction: () {
              navigator.maybePop();
              _homeController.selectTab(0);
            },
          ),
        );
        return true;
      case AndroidDeepLinkTarget.aiOpen:
        _pushAndroidDeepLinkPage(
          navigator,
          EnterpriseModuleScreen.aiOpen(onAction: () => navigator.maybePop()),
        );
        return true;
      case AndroidDeepLinkTarget.brain:
        _pushAndroidDeepLinkPage(
          navigator,
          EnterpriseModuleScreen.brain(
            onAction: () {
              navigator.maybePop();
              _pushAndroidDeepLinkPage(
                navigator,
                MarketListScreen(repository: widget.repository),
              );
            },
          ),
        );
        return true;
      case AndroidDeepLinkTarget.modStore:
        _pushAndroidDeepLinkPage(
          navigator,
          EnterpriseModuleScreen.modStore(
            onAction: () {
              navigator.maybePop();
              _pushAndroidDeepLinkPage(
                navigator,
                MarketListScreen(repository: widget.repository),
              );
            },
          ),
        );
        return true;
      case AndroidDeepLinkTarget.longtail:
        _pushAndroidDeepLinkPage(
          navigator,
          LongTailScreen(repository: widget.repository),
        );
        return true;
    }
  }

  void _pushAndroidDeepLinkPage(NavigatorState navigator, Widget page) {
    navigator.push(MaterialPageRoute(builder: (_) => page));
  }

  ConversationItem? _conversationForAndroidRoute(String? conversationId) {
    final cleanId = conversationId?.trim() ?? '';
    final conversations = widget.repository.fallbackConversations();
    if (cleanId.isEmpty) {
      return conversations.firstWhere(
        (item) => item.id == PinnedIds.assistant,
        orElse: () => conversations.first,
      );
    }
    for (final conversation in conversations) {
      if (conversation.id == cleanId) return conversation;
    }
    return null;
  }

  FixedPartnerKind _fixedPartnerKindFromAndroidRoute(String? raw) {
    switch ((raw ?? '').trim().toLowerCase()) {
      case 'customer_service':
      case 'customer-service':
      case 'cs':
        return FixedPartnerKind.customerService;
      case 'codex':
        return FixedPartnerKind.codex;
      case 'cursor':
        return FixedPartnerKind.cursor;
      case 'claude':
        return FixedPartnerKind.claude;
      case 'assistant':
      default:
        return FixedPartnerKind.assistant;
    }
  }

  BusinessListKind _businessListKindForAndroidTab(int tabIndex) {
    switch (tabIndex) {
      case 1:
        return BusinessListKind.shipments;
      case 2:
        return BusinessListKind.inventory;
      case 0:
      default:
        return BusinessListKind.customers;
    }
  }

  void _showAndroidDeepLinkSnack(String message) {
    final messenger = _scaffoldMessengerKey.currentState;
    messenger
      ?..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _refreshWalletForAndroidPaymentReturn() async {
    try {
      await _client.walletBalance();
    } catch (_) {
      // Android keeps payment-return navigation moving if wallet refresh fails.
    }
  }
}

class _DeepLinkedAiEmployeeProfileScreen extends StatelessWidget {
  const _DeepLinkedAiEmployeeProfileScreen({
    required this.repository,
    required this.modId,
    required this.employeeId,
  });

  final MobileRepository repository;
  final String modId;
  final String employeeId;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return FutureBuilder(
      future: repository.loadAiEmployees(),
      builder: (context, snapshot) {
        final employees = snapshot.data ?? const [];
        final normalizedModId = modId.trim();
        final normalizedEmployeeId = employeeId.trim();
        final matches = employees.where((employee) {
          final employeeMatches =
              employee.employeeId.trim() == normalizedEmployeeId;
          final modMatches = normalizedModId.isEmpty ||
              employee.modId.trim() == normalizedModId;
          return employeeMatches && modMatches;
        });
        final employee = matches.isEmpty ? null : matches.first;
        if (employee != null) {
          return AiEmployeeProfileScreen(
            employee: employee,
            repository: repository,
          );
        }
        return Scaffold(
          backgroundColor: colors.page,
          body: SafeArea(
            bottom: false,
            child: Column(
              children: [
                WeTopBar(
                  title: 'AI员工',
                  showBack: true,
                  onBack: () => Navigator.of(context).maybePop(),
                ),
                Expanded(
                  child: Center(
                    child: Text(
                      snapshot.connectionState == ConnectionState.waiting
                          ? '正在同步员工资料'
                          : '未找到该 AI 员工',
                      style: TextStyle(
                        color: colors.textSecondary,
                        fontSize: 16,
                        height: 1.38,
                        letterSpacing: 0,
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

class _StartupLoadingScreen extends StatelessWidget {
  const _StartupLoadingScreen();

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.surface,
      body: const Center(
        child: SizedBox(
          width: 28,
          height: 28,
          child: CircularProgressIndicator(strokeWidth: 2.4),
        ),
      ),
    );
  }
}

class _BiometricLockScreen extends StatelessWidget {
  const _BiometricLockScreen();

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.surface,
      body: SafeArea(
        child: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(16),
                child: Image.asset(
                  appLauncherIconAsset,
                  width: 64,
                  height: 64,
                  fit: BoxFit.contain,
                ),
              ),
              const SizedBox(height: 16),
              Text(
                '正在验证身份',
                style: TextStyle(
                  color: colors.textPrimary,
                  fontSize: 17,
                  height: 1.29,
                  fontWeight: FontWeight.w600,
                  letterSpacing: 0,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _AutoLoginScreen extends StatelessWidget {
  const _AutoLoginScreen({
    required this.error,
    required this.onRetry,
    required this.onManualLogin,
  });

  final String? error;
  final VoidCallback onRetry;
  final VoidCallback onManualLogin;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.surface,
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 32),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                ClipRRect(
                  borderRadius: BorderRadius.circular(16),
                  child: Image.asset(
                    appLauncherIconAsset,
                    width: 64,
                    height: 64,
                    fit: BoxFit.contain,
                  ),
                ),
                const SizedBox(height: 16),
                Text(
                  error ?? '正在自动登录',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: colors.textPrimary,
                    fontSize: 17,
                    height: 1.29,
                    fontWeight: FontWeight.w600,
                    letterSpacing: 0,
                  ),
                ),
                const SizedBox(height: 18),
                if (error == null)
                  const SizedBox(
                    width: 28,
                    height: 28,
                    child: CircularProgressIndicator(strokeWidth: 2.4),
                  )
                else ...[
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                      onPressed: onRetry,
                      child: const Text('重试'),
                    ),
                  ),
                  const SizedBox(height: 8),
                  SizedBox(
                    width: double.infinity,
                    child: OutlinedButton(
                      onPressed: onManualLogin,
                      child: const Text('手动登录'),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
