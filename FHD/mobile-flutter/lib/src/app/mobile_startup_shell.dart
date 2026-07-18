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
import '../features/contacts/employee_questions_screen.dart';
import '../features/contacts/fixed_partner_profile_screen.dart';
import '../features/cs/admin_cs_console_screen.dart';
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
import '../platform/background_work_scheduler.dart';
import '../policy/mobile_error_policy.dart';
import '../platform/deep_link_bridge.dart';
import '../platform/biometric_gate.dart';
import '../policy/mobile_runtime_policy.dart';
import '../policy/pinned_ids.dart';
import '../theme/app_assets.dart';
import '../theme/app_theme.dart';
import '../widgets/we_ui.dart';

enum MobileStartupRoute { legal, authAutoLogin, auth, onboarding, home }

@visibleForTesting
MobileStartupRoute resolveMobileStartupRoute({
  required MobileSessionData session,
  required MobileAppConfigData? appConfig,
}) {
  final legalVersion = appConfig?.legalVersion.trim();
  if (legalVersion != null &&
      legalVersion.isNotEmpty &&
      session.legalAcceptedVersion.trim() != legalVersion) {
    return MobileStartupRoute.legal;
  }

  final loggedIn = session.hasAuth;
  final canAutoLogin = session.canAutoLogin;
  if (!loggedIn && canAutoLogin) return MobileStartupRoute.authAutoLogin;
  if (!loggedIn) return MobileStartupRoute.auth;

  final adminMode = MobileConversationRuntimePolicy.isAdminAccountKind(
    session.accountKind,
  );
  final setupComplete =
      adminMode || session.setupComplete || session.fhdHost.trim().isNotEmpty;
  return setupComplete
      ? MobileStartupRoute.home
      : MobileStartupRoute.onboarding;
}

@visibleForTesting
ThemeMode mobileThemeModeFromSession(String rawMode) {
  switch (rawMode.trim().toLowerCase()) {
    case 'light':
      return ThemeMode.light;
    case 'dark':
      return ThemeMode.dark;
    default:
      return ThemeMode.system;
  }
}

class MobileStartupApp extends StatefulWidget {
  const MobileStartupApp({
    super.key,
    required this.repository,
    this.biometricGate = const PlatformBiometricGate(),
    this.deepLinkBridge = const MobileDeepLinkBridge(),
    this.backgroundWorkScheduler = const PlatformBackgroundWorkScheduler(),
    this.enableBiometricGate = true,
  });

  final MobileRepository repository;
  final PlatformBiometricGate biometricGate;
  final MobileDeepLinkBridge deepLinkBridge;
  final PlatformBackgroundWorkScheduler backgroundWorkScheduler;
  final bool enableBiometricGate;

  @override
  State<MobileStartupApp> createState() => _MobileStartupAppState();
}

class _MobileStartupAppState extends State<MobileStartupApp> {
  MobileSessionData _session = MobileSessionData.empty;
  MobileAppConfigData? _appConfig;
  MobileStartupRoute? _route;
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
    return MobileRepositoryScope(
      repository: widget.repository,
      child: MaterialApp(
        debugShowCheckedModeBanner: false,
        title: 'XCAGI',
        navigatorKey: _navigatorKey,
        scaffoldMessengerKey: _scaffoldMessengerKey,
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: mobileThemeModeFromSession(_session.themeMode),
        home: _buildHome(),
      ),
    );
  }

  Widget _buildHome() {
    if (_route == null) return const _StartupLoadingScreen();
    if (_checkingBiometric) return const _BiometricLockScreen();

    switch (_route!) {
      case MobileStartupRoute.legal:
        return LegalConsentScreen(
          api: _client,
          legalVersion: _appConfig?.legalVersion ?? '1',
          onAccepted: _acceptLegalAndRefresh,
        );
      case MobileStartupRoute.authAutoLogin:
      case MobileStartupRoute.auth:
        return AuthScreen(
          repository: widget.repository,
          onDone: _refreshRouteFromSession,
        );
      case MobileStartupRoute.onboarding:
        return MobileOnboardingScreen(
          repository: widget.repository,
          onFinish: _finishOnboarding,
        );
      case MobileStartupRoute.home:
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
      _route = resolveMobileStartupRoute(session: session, appConfig: config);
    });
    await _runBiometricGateIfNeeded(session);
    unawaited(_reconcileBackgroundWork(session));
    _startAutoLoginIfNeeded();
    _tryHandlePendingDeepLink();
  }

  void _handleSessionChanged(MobileSessionData session) {
    if (!mounted || _handlingDeepLink) return;
    final nextRoute = resolveMobileStartupRoute(
      session: session,
      appConfig: _appConfig,
    );
    setState(() {
      _session = session;
      if (_route != nextRoute) {
        _route = nextRoute;
        _autoLoginStarted = false;
      }
    });
    unawaited(_reconcileBackgroundWork(session));
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
      _route = resolveMobileStartupRoute(
        session: session,
        appConfig: _appConfig,
      );
      _autoLoginStarted = false;
    });
    unawaited(_reconcileBackgroundWork(session));
    _startAutoLoginIfNeeded();
    _tryHandlePendingDeepLink();
  }

  void _startAutoLoginIfNeeded() {
    if (_route != MobileStartupRoute.authAutoLogin || _autoLoginStarted) {
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
        _autoLoginStarted = false;
        _route = MobileStartupRoute.auth;
      });
      _showMobileSnack('自动登录失败，请手动登录');
    }
  }

  Future<void> _loadInitialDeepLinkRoute() async {
    final route = await widget.deepLinkBridge.initialRoute();
    if (route == null || !mounted) return;
    _queueDeepLink(route);
  }

  Future<void> _reconcileBackgroundWork(
    MobileSessionData session,
  ) async {
    await widget.backgroundWorkScheduler.reconcile(session).catchError((_) {});
  }

  void _queueDeepLink(String route) {
    final normalized = route.trim();
    if (normalized.isEmpty || !mounted) return;
    _pendingDeepLinkRoute = normalized;
    _tryHandlePendingDeepLink();
  }

  bool _canHandleStartupPairingDeepLink() {
    return switch (_route) {
      MobileStartupRoute.auth || MobileStartupRoute.onboarding => true,
      _ => false,
    };
  }

  void _tryHandlePendingDeepLink() {
    if (_handlingDeepLink || _pendingDeepLinkRoute == null || !mounted) {
      return;
    }
    final route = _pendingDeepLinkRoute!;
    final pairingPayload = pairingPayloadFromDeepLinkRoute(route);
    if (pairingPayload != null &&
        !_session.setupComplete &&
        _canHandleStartupPairingDeepLink()) {
      _handlingDeepLink = true;
      _pendingDeepLinkRoute = null;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) {
          _handlingDeepLink = false;
          _pendingDeepLinkRoute = route;
          return;
        }
        unawaited(_completePairingDeepLink(pairingPayload));
      });
      return;
    }
    if (!_session.hasAuth || _route != MobileStartupRoute.home) {
      return;
    }
    _pendingDeepLinkRoute = null;
    _handlingDeepLink = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) {
        _handlingDeepLink = false;
        return;
      }
      final handled = _openMobileDeepLink(route);
      if (!handled) _pendingDeepLinkRoute = route;
      _handlingDeepLink = false;
      _tryHandlePendingDeepLink();
    });
  }

  Future<void> _completePairingDeepLink(String payload) async {
    try {
      await widget.repository.exchangePairingCode(payload);
      if (!mounted) return;
      await _refreshRouteFromSession();
      if (!mounted) return;
      _showMobileSnackAfterFrame('设备绑定成功');
    } catch (error) {
      if (!mounted) return;
      _showMobileSnackAfterFrame(
        mobileProductErrorMessage(
          error is MobileRepositoryException ? error.message : '$error',
          '设备配对失败，请刷新二维码或输入设备码',
        ),
      );
    } finally {
      _handlingDeepLink = false;
      _tryHandlePendingDeepLink();
    }
  }

  void _showMobileSnackAfterFrame(String message) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _showMobileSnack(message);
    });
  }

  bool _openMobileDeepLink(String route) {
    final navigator = _navigatorKey.currentState;
    if (navigator == null) return false;
    final destination = resolveMobileDeepLinkDestination(route);
    switch (destination.target) {
      case MobileDeepLinkTarget.chat:
        _homeController.selectTab(0);
        navigator.popUntil((route) => route.isFirst);
        return true;
      case MobileDeepLinkTarget.work:
        _homeController.selectTab(1);
        navigator.popUntil((route) => route.isFirst);
        return true;
      case MobileDeepLinkTarget.discover:
        _homeController.selectTab(2);
        navigator.popUntil((route) => route.isFirst);
        return true;
      case MobileDeepLinkTarget.profile:
        _homeController.selectTab(3);
        navigator.popUntil((route) => route.isFirst);
        return true;
      case MobileDeepLinkTarget.aiChat:
        final conversation = _conversationForMobileRoute(PinnedIds.assistant);
        if (conversation == null) {
          _homeController.selectTab(0);
          navigator.popUntil((route) => route.isFirst);
          return true;
        }
        _pushMobileDeepLinkPage(
          navigator,
          ChatScreen(
            conversation: conversation,
            initialMessages: const [],
            repository: widget.repository,
          ),
        );
        return true;
      case MobileDeepLinkTarget.conversationChat:
        final conversation = _conversationForMobileRoute(
          destination.conversationId ?? '',
        );
        if (conversation == null) {
          _homeController.selectTab(0);
          navigator.popUntil((route) => route.isFirst);
          return true;
        }
        if (conversation.id == PinnedIds.cs) {
          _pushMobileDeepLinkPage(
            navigator,
            CsChatScreen(repository: widget.repository),
          );
          return true;
        }
        _pushMobileDeepLinkPage(
          navigator,
          ChatScreen(
            conversation: conversation,
            initialMessages: const [],
            repository: widget.repository,
          ),
        );
        return true;
      case MobileDeepLinkTarget.csChat:
        _pushMobileDeepLinkPage(
          navigator,
          CsChatScreen(repository: widget.repository),
        );
        return true;
      case MobileDeepLinkTarget.adminCsConsole:
        _pushMobileDeepLinkPage(
          navigator,
          AdminCsConsoleScreen(repository: widget.repository),
        );
        return true;
      case MobileDeepLinkTarget.fixedPartnerProfile:
        _pushMobileDeepLinkPage(
          navigator,
          FixedPartnerProfileScreen(
            kind: _fixedPartnerKindFromMobileRoute(destination.partnerKind),
            repository: widget.repository,
          ),
        );
        return true;
      case MobileDeepLinkTarget.market:
        unawaited(_refreshWalletForMobilePaymentReturn());
        _showMobileSnack('已返回应用，正在刷新支付状态');
        _pushMobileDeepLinkPage(
          navigator,
          MarketListScreen(repository: widget.repository),
        );
        return true;
      case MobileDeepLinkTarget.mods:
        _pushMobileDeepLinkPage(
          navigator,
          MarketListScreen(repository: widget.repository),
        );
        return true;
      case MobileDeepLinkTarget.modWeb:
        _pushMobileDeepLinkPage(
          navigator,
          ModWebViewScreen(
            modId: destination.modId ?? '',
            api: widget.repository.client,
          ),
        );
        return true;
      case MobileDeepLinkTarget.desktopWebView:
        _pushMobileDeepLinkPage(
          navigator,
          DesktopToolWebViewScreen(
            title: destination.title ?? '桌面工具',
            path: destination.path ?? '/',
            api: widget.repository.client,
          ),
        );
        return true;
      case MobileDeepLinkTarget.aiEmployees:
        _pushMobileDeepLinkPage(
          navigator,
          AiEmployeesScreen(repository: widget.repository),
        );
        return true;
      case MobileDeepLinkTarget.aiCircle:
        _pushMobileDeepLinkPage(
          navigator,
          AiCircleScreen(repository: widget.repository),
        );
        return true;
      case MobileDeepLinkTarget.aiGroups:
        _pushMobileDeepLinkPage(
          navigator,
          AiGroupListScreen(
            repository: widget.repository,
            initialGroups: const [],
          ),
        );
        return true;
      case MobileDeepLinkTarget.aiGroupCreate:
        _pushMobileDeepLinkPage(
          navigator,
          AiGroupCreateScreen(repository: widget.repository),
        );
        return true;
      case MobileDeepLinkTarget.scanQr:
        _pushMobileDeepLinkPage(
          navigator,
          ScanQrScreen(repository: widget.repository),
        );
        return true;
      case MobileDeepLinkTarget.approvalList:
        _pushMobileDeepLinkPage(
          navigator,
          ApprovalListScreen(repository: widget.repository),
        );
        return true;
      case MobileDeepLinkTarget.approvalDetail:
        _pushMobileDeepLinkPage(
          navigator,
          ApprovalDetailScreen(
            id: destination.approvalId ?? 0,
            repository: widget.repository,
          ),
        );
        return true;
      case MobileDeepLinkTarget.aiEmployeeProfile:
        _pushMobileDeepLinkPage(
          navigator,
          _DeepLinkedAiEmployeeProfileScreen(
            repository: widget.repository,
            modId: destination.modId ?? '',
            employeeId: destination.employeeId ?? '',
          ),
        );
        return true;
      case MobileDeepLinkTarget.employeeQuestions:
        _pushMobileDeepLinkPage(
          navigator,
          EmployeeQuestionsScreen(
            repository: widget.repository,
            employeeId: destination.employeeId,
          ),
        );
        return true;
      case MobileDeepLinkTarget.settings:
        _pushMobileDeepLinkPage(
          navigator,
          SettingsScreen(api: widget.repository.client),
        );
        return true;
      case MobileDeepLinkTarget.about:
        _pushMobileDeepLinkPage(
          navigator,
          AboutScreen(api: widget.repository.client),
        );
        return true;
      case MobileDeepLinkTarget.notifications:
        _pushMobileDeepLinkPage(
          navigator,
          NotificationListScreen(repository: widget.repository),
        );
        return true;
      case MobileDeepLinkTarget.ocr:
        _pushMobileDeepLinkPage(navigator, const OcrScreen());
        return true;
      case MobileDeepLinkTarget.bridge:
        _pushMobileDeepLinkPage(
          navigator,
          BridgeScreen(repository: widget.repository),
        );
        return true;
      case MobileDeepLinkTarget.erp:
        _pushMobileDeepLinkPage(
          navigator,
          ErpScreen(repository: widget.repository),
        );
        return true;
      case MobileDeepLinkTarget.erpTab:
        _pushMobileDeepLinkPage(
          navigator,
          BusinessListScreen(
            kind: _businessListKindForMobileTab(destination.tabIndex ?? 0),
            repository: widget.repository,
          ),
        );
        return true;
      case MobileDeepLinkTarget.im:
        _pushMobileDeepLinkPage(
          navigator,
          ImMessengerScreen(repository: widget.repository),
        );
        return true;
      case MobileDeepLinkTarget.connect:
        _pushMobileDeepLinkPage(
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
      case MobileDeepLinkTarget.connectPc:
        _pushMobileDeepLinkPage(
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
      case MobileDeepLinkTarget.onboarding:
        _pushMobileDeepLinkPage(
          navigator,
          MobileOnboardingScreen(
            repository: widget.repository,
            onFinish: () => navigator.maybePop(),
          ),
        );
        return true;
      case MobileDeepLinkTarget.register:
        _pushMobileDeepLinkPage(
          navigator,
          RegisterScreen(onLogin: () => navigator.maybePop()),
        );
        return true;
      case MobileDeepLinkTarget.smartAnalysis:
        _pushMobileDeepLinkPage(
          navigator,
          EnterpriseModuleScreen.smartAnalysis(
            onAction: () {
              navigator.maybePop();
              _homeController.selectTab(0);
            },
          ),
        );
        return true;
      case MobileDeepLinkTarget.aiOpen:
        _pushMobileDeepLinkPage(
          navigator,
          EnterpriseModuleScreen.aiOpen(onAction: () => navigator.maybePop()),
        );
        return true;
      case MobileDeepLinkTarget.brain:
        _pushMobileDeepLinkPage(
          navigator,
          EnterpriseModuleScreen.brain(
            onAction: () {
              navigator.maybePop();
              _pushMobileDeepLinkPage(
                navigator,
                MarketListScreen(repository: widget.repository),
              );
            },
          ),
        );
        return true;
      case MobileDeepLinkTarget.modStore:
        _pushMobileDeepLinkPage(
          navigator,
          EnterpriseModuleScreen.modStore(
            onAction: () {
              navigator.maybePop();
              _pushMobileDeepLinkPage(
                navigator,
                MarketListScreen(repository: widget.repository),
              );
            },
          ),
        );
        return true;
      case MobileDeepLinkTarget.longtail:
        _pushMobileDeepLinkPage(
          navigator,
          LongTailScreen(repository: widget.repository),
        );
        return true;
    }
  }

  void _pushMobileDeepLinkPage(NavigatorState navigator, Widget page) {
    navigator.push(MaterialPageRoute(builder: (_) => page));
  }

  ConversationItem? _conversationForMobileRoute(String? conversationId) {
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

  FixedPartnerKind _fixedPartnerKindFromMobileRoute(String? raw) {
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
      case 'trae':
        return FixedPartnerKind.trae;
      case 'assistant':
      default:
        return FixedPartnerKind.assistant;
    }
  }

  BusinessListKind _businessListKindForMobileTab(int tabIndex) {
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

  void _showMobileSnack(String message) {
    final messenger = _scaffoldMessengerKey.currentState;
    messenger
      ?..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _refreshWalletForMobilePaymentReturn() async {
    try {
      await _client.walletBalance();
    } catch (_) {
      // Keep payment-return navigation moving if wallet refresh fails.
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
