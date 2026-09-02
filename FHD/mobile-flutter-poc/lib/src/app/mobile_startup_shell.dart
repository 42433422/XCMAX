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

part 'mobile_startup_shell_state.part.dart';
part 'mobile_startup_shell_screens.part.dart';

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

class _MobileStartupAppState extends _MobileStartupStateBase {
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
}
