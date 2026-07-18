import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/app/mobile_startup_shell.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/approval/approval_screens.dart';
import 'package:xcagi_flutter_poc/src/features/shell/home_shell.dart';
import 'package:xcagi_flutter_poc/src/models/conversation.dart';
import 'package:xcagi_flutter_poc/src/platform/background_work_scheduler.dart';
import 'package:xcagi_flutter_poc/src/platform/deep_link_bridge.dart';
import 'package:xcagi_flutter_poc/src/platform/biometric_gate.dart';

void main() {
  test('startup route matches the mobile AppViewModel priority', () {
    final config = _appConfig('legal-2');

    expect(
      resolveMobileStartupRoute(
        session: const MobileSessionData(),
        appConfig: config,
      ),
      MobileStartupRoute.legal,
    );
    expect(
      resolveMobileStartupRoute(
        session: const MobileSessionData(
          legalAcceptedVersion: 'legal-2',
          autoLogin: true,
          savedUsername: 'admin',
          savedPassword: 'secret',
        ),
        appConfig: config,
      ),
      MobileStartupRoute.authAutoLogin,
    );
    expect(
      resolveMobileStartupRoute(
        session: const MobileSessionData(legalAcceptedVersion: 'legal-2'),
        appConfig: config,
      ),
      MobileStartupRoute.auth,
    );
    expect(
      resolveMobileStartupRoute(
        session: const MobileSessionData(
          legalAcceptedVersion: 'legal-2',
          accessToken: 'access',
        ),
        appConfig: config,
      ),
      MobileStartupRoute.onboarding,
    );
    expect(
      resolveMobileStartupRoute(
        session: const MobileSessionData(
          legalAcceptedVersion: 'legal-2',
          accessToken: 'access',
          setupComplete: true,
        ),
        appConfig: config,
      ),
      MobileStartupRoute.home,
    );
    expect(
      resolveMobileStartupRoute(
        session: const MobileSessionData(
          legalAcceptedVersion: 'legal-2',
          accessToken: 'access',
          accountKind: 'admin',
          setupComplete: false,
        ),
        appConfig: config,
      ),
      MobileStartupRoute.home,
    );
    expect(
      resolveMobileStartupRoute(
        session: const MobileSessionData(
          legalAcceptedVersion: 'legal-2',
          accessToken: 'access',
          accountKind: 'admin_portal',
          setupComplete: false,
        ),
        appConfig: config,
      ),
      MobileStartupRoute.home,
    );
  });

  test('theme mode follows Flutter system light dark values', () {
    expect(mobileThemeModeFromSession(''), ThemeMode.system);
    expect(mobileThemeModeFromSession('system'), ThemeMode.system);
    expect(mobileThemeModeFromSession('light'), ThemeMode.light);
    expect(mobileThemeModeFromSession('dark'), ThemeMode.dark);
  });

  test('deep link route parsing matches the mobile MainActivity mapping', () {
    expect(resolveMobileDeepLinkRoute(extraRoute: 'approval/9'), 'approval/9');
    expect(
      resolveMobileDeepLinkRoute(uri: Uri.parse('xcagi://payment/complete')),
      'payment/complete',
    );
    expect(
      resolveMobileDeepLinkRoute(
        uri: Uri.parse(
          'xcagi://pairing?code=123456&host=192.168.10.2&port=17500',
        ),
      ),
      'pairing?code=123456&host=192.168.10.2&port=17500',
    );
    expect(pairingPayloadFromDeepLinkRoute('pairing?code=123456'), '123456');
    expect(pairingPayloadFromDeepLinkRoute('654321'), '654321');
    expect(
      resolveMobileDeepLinkRoute(
        uri: Uri.parse('https://xiu-ci.com/app/approval/12'),
      ),
      '/app/approval/12',
    );

    expect(
      resolveMobileDeepLinkDestination('payment/complete').target,
      MobileDeepLinkTarget.market,
    );
    expect(
      resolveMobileDeepLinkDestination('work').target,
      MobileDeepLinkTarget.work,
    );
    expect(resolveMobileDeepLinkDestination('/app/approval/12').approvalId, 12);
    expect(
      resolveMobileDeepLinkDestination('discover').target,
      MobileDeepLinkTarget.discover,
    );
    expect(
      resolveMobileDeepLinkDestination('unknown').target,
      MobileDeepLinkTarget.chat,
    );
  });

  test('deep link destinations cover Flutter Routes table', () {
    final routes = <String, MobileDeepLinkTarget>{
      'chat': MobileDeepLinkTarget.chat,
      'home_hub': MobileDeepLinkTarget.chat,
      'work': MobileDeepLinkTarget.work,
      'discover': MobileDeepLinkTarget.discover,
      'profile': MobileDeepLinkTarget.profile,
      'ai_chat': MobileDeepLinkTarget.aiChat,
      'cs_chat': MobileDeepLinkTarget.csChat,
      'admin_cs_console': MobileDeepLinkTarget.adminCsConsole,
      'ai_employees': MobileDeepLinkTarget.aiEmployees,
      'ai_circle': MobileDeepLinkTarget.aiCircle,
      'ai_groups': MobileDeepLinkTarget.aiGroups,
      'ai_group_chat': MobileDeepLinkTarget.aiGroups,
      'ai_group_create': MobileDeepLinkTarget.aiGroupCreate,
      'scan_qr': MobileDeepLinkTarget.scanQr,
      'approval': MobileDeepLinkTarget.approvalList,
      'erp': MobileDeepLinkTarget.erp,
      'erp_overview': MobileDeepLinkTarget.erp,
      'ocr': MobileDeepLinkTarget.ocr,
      'bridge': MobileDeepLinkTarget.bridge,
      'market': MobileDeepLinkTarget.market,
      'mods': MobileDeepLinkTarget.mods,
      'longtail': MobileDeepLinkTarget.longtail,
      'settings': MobileDeepLinkTarget.settings,
      'about': MobileDeepLinkTarget.about,
      'notifications': MobileDeepLinkTarget.notifications,
      'im': MobileDeepLinkTarget.im,
      'connect': MobileDeepLinkTarget.connect,
      'connect_pc': MobileDeepLinkTarget.connectPc,
      'onboarding': MobileDeepLinkTarget.onboarding,
      'register': MobileDeepLinkTarget.register,
      'smart_analysis': MobileDeepLinkTarget.smartAnalysis,
      'ai_open': MobileDeepLinkTarget.aiOpen,
      'brain': MobileDeepLinkTarget.brain,
      'mod_store': MobileDeepLinkTarget.modStore,
      'employee_questions_all': MobileDeepLinkTarget.employeeQuestions,
    };

    for (final entry in routes.entries) {
      expect(
        resolveMobileDeepLinkDestination(entry.key).target,
        entry.value,
        reason: '${entry.key} should match the mobile Routes.kt',
      );
    }

    expect(
      resolveMobileDeepLinkDestination(
        'conversation_chat/pinned:codex',
      ).conversationId,
      'pinned:codex',
    );
    expect(
      resolveMobileDeepLinkDestination('fixed_partner/codex').partnerKind,
      'codex',
    );
    expect(resolveMobileDeepLinkDestination('erp_tab/2').tabIndex, 2);
    expect(resolveMobileDeepLinkDestination('approval/42').approvalId, 42);
    expect(resolveMobileDeepLinkDestination('mod/example').modId, 'example');
    expect(
      resolveMobileDeepLinkDestination('employee_questions/example').employeeId,
      'example',
    );
    final web = resolveMobileDeepLinkDestination(
      'web_view?url=/market/workbench/home&title=工作台',
    );
    expect(web.target, MobileDeepLinkTarget.desktopWebView);
    expect(web.path, '/market/workbench/home');
    expect(web.title, '工作台');
  });

  test('deep link coverage tracks the published Flutter route contract', () {
    final directlyCoveredRoutes = <String>{
      'connect',
      'connect_pc',
      'register',
      'onboarding',
      'home_hub',
      'work',
      'discover',
      'profile',
      'home',
      'chat',
      'ai_chat',
      'conversation_chat',
      'cs_chat',
      'admin_cs_console',
      'im',
      'approval',
      'erp',
      'erp_overview',
      'bridge',
      'market',
      'mods',
      'ocr',
      'longtail',
      'settings',
      'about',
      'scan_qr',
      'ai_employees',
      'ai_circle',
      'ai_groups',
      'ai_group_chat',
      'ai_group_create',
      'smart_analysis',
      'ai_open',
      'brain',
      'mod_store',
      'employee_questions_all',
      'notifications',
    };
    final templateExamples = <String, String>{
      'fixed_partner/{partnerKind}': 'fixed_partner/codex',
      'approval/{id}': 'approval/42',
      'erp_tab/{tabIndex}': 'erp_tab/2',
      'mod/{modId}': 'mod/example',
      'ai_employee/{modId}/{employeeId}':
          'ai_employee/example/example-employee',
      'employee_questions/{employeeId}': 'employee_questions/example-employee',
      'web_view?url={url}&title={title}':
          'web_view?url=/market/workbench/home&title=工作台',
    };
    final startupOnlyRoutes = <String>{
      'legal',
      'splash',
      'auth',
      'auth_auto_login',
    };
    final coveredRouteValues = {
      ...directlyCoveredRoutes,
      ...templateExamples.keys,
      ...startupOnlyRoutes,
    };

    expect(coveredRouteValues, containsAll(directlyCoveredRoutes));
    final chatEquivalentRoutes = <String>{
      'chat',
      'home',
      'home_hub',
      'conversation_chat',
    };
    for (final route in directlyCoveredRoutes.difference(
      chatEquivalentRoutes,
    )) {
      expect(
        resolveMobileDeepLinkDestination(route).target,
        isNot(MobileDeepLinkTarget.chat),
        reason: '$route should not silently fall back to chat',
      );
    }
    for (final example in templateExamples.values) {
      expect(
        resolveMobileDeepLinkDestination(example).target,
        isNot(MobileDeepLinkTarget.chat),
        reason: '$example should not silently fall back to chat',
      );
    }
  });

  testWidgets('legal version gates the Flutter root before auth', (
    tester,
  ) async {
    final api = _FakeStartupApi(
      session: const MobileSessionData(),
      config: _appConfig('legal-2'),
    );

    await tester.pumpWidget(
      MobileStartupApp(
        repository: _StartupRepository(api),
        enableBiometricGate: false,
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('XCAGI'), findsOneWidget);
    expect(find.text('请先同意协议'), findsOneWidget);

    await tester.tap(find.textContaining('我已阅读并同意'));
    await tester.pump();
    await tester.tap(find.text('进入 XCAGI'));
    await tester.pumpAndSettle();

    expect(api.session.legalAcceptedVersion, 'legal-2');
    expect(find.text('密码登录'), findsOneWidget);
    expect(find.text('账号注册'), findsOneWidget);
  });

  testWidgets('auto-login route displays Flutter auth screen while retrying', (
    tester,
  ) async {
    final loginGate = Completer<void>();
    final api = _FakeStartupApi(
      session: const MobileSessionData(
        legalAcceptedVersion: 'legal-2',
        savedUsername: 'remembered-admin',
        savedPassword: 'secret',
        rememberPassword: true,
        autoLogin: true,
        accountKind: 'admin',
      ),
      config: _appConfig('legal-2'),
    );
    final repository = _StartupRepository(api, loginGate: loginGate);

    await tester.pumpWidget(
      MobileStartupApp(repository: repository, enableBiometricGate: false),
    );
    await tester.pump();
    await tester.pump();

    expect(find.text('密码登录'), findsOneWidget);
    expect(find.text('扫码绑定/登录'), findsOneWidget);
    expect(find.text('账号注册'), findsOneWidget);
    expect(find.text('正在自动登录'), findsNothing);
    expect(find.text('手动登录'), findsNothing);
    expect(repository.logins, hasLength(1));

    loginGate.complete();
    await tester.pumpAndSettle();

    expect(find.byType(HomeShell), findsOneWidget);
    expect(find.text('启动配置'), findsNothing);
  });

  testWidgets('auto-login failure stays on Flutter auth screen with snack', (
    tester,
  ) async {
    final api = _FakeStartupApi(
      session: const MobileSessionData(
        legalAcceptedVersion: 'legal-2',
        savedUsername: 'remembered-admin',
        savedPassword: 'secret',
        rememberPassword: true,
        autoLogin: true,
        accountKind: 'admin',
      ),
      config: _appConfig('legal-2'),
    );
    final repository = _StartupRepository(
      api,
      loginError: Exception('offline'),
    );

    await tester.pumpWidget(
      MobileStartupApp(repository: repository, enableBiometricGate: false),
    );
    await tester.pump();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));

    expect(repository.logins, hasLength(1));
    expect(find.text('密码登录'), findsOneWidget);
    expect(find.text('账号注册'), findsOneWidget);
    expect(find.text('自动登录失败，请手动登录'), findsOneWidget);
    expect(find.text('正在自动登录'), findsNothing);
  });

  testWidgets('biometric root gate runs before Flutter home shell', (
    tester,
  ) async {
    final api = _FakeStartupApi(
      session: const MobileSessionData(
        legalAcceptedVersion: 'legal-2',
        accessToken: 'access',
        setupComplete: true,
        themeMode: 'dark',
        biometricEnabled: true,
      ),
      config: _appConfig('legal-2'),
    );
    final gate = _FakeBiometricGate(
      canAuthenticateValue: true,
      promptValue: true,
    );

    await tester.pumpWidget(
      MobileStartupApp(
        repository: _StartupRepository(api),
        biometricGate: gate,
      ),
    );
    await tester.pumpAndSettle();

    expect(gate.canAuthenticateCalls, 1);
    expect(gate.promptCalls, 1);
    expect(find.byType(HomeShell), findsOneWidget);
    final context = tester.element(find.byType(HomeShell));
    expect(Theme.of(context).brightness, Brightness.dark);
  });

  testWidgets(
    'startup consumes Flutter initial deep link after home is ready',
    (tester) async {
      final api = _FakeStartupApi(
        session: const MobileSessionData(
          legalAcceptedVersion: 'legal-2',
          accessToken: 'access',
          setupComplete: true,
        ),
        config: _appConfig('legal-2'),
      );

      await tester.pumpWidget(
        MobileStartupApp(
          repository: _StartupRepository(api),
          deepLinkBridge: _FakeDeepLinkBridge(initialRouteValue: 'approval/12'),
          enableBiometricGate: false,
        ),
      );
      await tester.pumpAndSettle();

      expect(find.byType(ApprovalDetailScreen), findsOneWidget);
      expect(find.text('Flutter 深链审批'), findsOneWidget);
    },
  );

  testWidgets('pairing deep link waits for legal gate before exchange', (
    tester,
  ) async {
    final api = _FakeStartupApi(
      session: const MobileSessionData(),
      config: _appConfig('legal-2'),
    );
    final repository = _StartupRepository(
      api,
      pairingError: const MobileRepositoryException('未找到电脑'),
    );

    await tester.pumpWidget(
      MobileStartupApp(
        repository: repository,
        deepLinkBridge: _FakeDeepLinkBridge(
          initialRouteValue: 'pairing?code=123456',
        ),
        enableBiometricGate: false,
      ),
    );
    await tester.pump();
    await tester.pump();

    expect(repository.pairingAttempts, isEmpty);
    expect(find.text('请先同意协议'), findsOneWidget);

    await tester.tap(find.textContaining('我已阅读并同意'));
    await tester.pump();
    await tester.tap(find.text('进入 XCAGI'));
    await tester.pump();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(repository.pairingAttempts, ['123456']);
    expect(find.text('未找到电脑'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('startup reconciles Flutter WorkManager switches from session', (
    tester,
  ) async {
    final api = _FakeStartupApi(
      session: const MobileSessionData(
        legalAcceptedVersion: 'legal-2',
        accessToken: 'access',
        setupComplete: true,
        autoSync: false,
        autoLanProbe: true,
      ),
      config: _appConfig('legal-2'),
    );
    final scheduler = _FakeBackgroundWorkScheduler();

    await tester.pumpWidget(
      MobileStartupApp(
        repository: _StartupRepository(api),
        backgroundWorkScheduler: scheduler,
        enableBiometricGate: false,
      ),
    );
    await tester.pumpAndSettle();

    expect(scheduler.sessions, isNotEmpty);
    expect(scheduler.sessions.last.hasAuth, isTrue);
    expect(scheduler.sessions.last.autoSync, isFalse);
    expect(scheduler.sessions.last.autoLanProbe, isTrue);
  });
}

MobileAppConfigData _appConfig(String legalVersion) {
  return MobileAppConfigData(
    ok: true,
    legalVersion: legalVersion,
    profilePage: const MobileProfilePageConfig.disabled(),
    raw: {'ok': true, 'legal_version': legalVersion},
  );
}

class _FakeStartupApi extends MobileApiClient {
  _FakeStartupApi({required this.session, required this.config});

  final MobileAppConfigData config;
  final _changes = StreamController<MobileSessionData>.broadcast();
  MobileSessionData session;

  @override
  Stream<MobileSessionData> get sessionChanges => _changes.stream;

  @override
  Future<MobileSessionData> loadSession({bool forceReload = false}) async =>
      session;

  @override
  Future<MobileAppConfigData> appConfig({
    int currentVersionCode = MobileBuildConfig.versionCode,
    String sku = MobileBuildConfig.productSku,
  }) async {
    return config;
  }

  @override
  Future<void> saveLegalAcceptedVersion(String version) async {
    session = session.copyWith(legalAcceptedVersion: version.trim());
    _changes.add(session);
  }

  @override
  Future<void> saveSetupComplete(bool complete) async {
    session = session.copyWith(setupComplete: complete);
    _changes.add(session);
  }
}

class _StartupRepository extends MobileRepository {
  _StartupRepository(
    this.api, {
    this.loginGate,
    this.loginError,
    this.pairingError,
  }) : super(client: api);

  final _FakeStartupApi api;
  final Completer<void>? loginGate;
  final Object? loginError;
  final Object? pairingError;
  final List<Map<String, Object?>> logins = [];
  final List<String> pairingAttempts = [];

  @override
  Future<void> login({
    required String username,
    required String password,
    required bool adminMode,
    bool rememberPass = false,
    bool autoLogin = false,
  }) async {
    logins.add({
      'username': username.trim(),
      'password': password,
      'adminMode': adminMode,
      'rememberPass': rememberPass,
      'autoLogin': autoLogin,
    });
    final gate = loginGate;
    if (gate != null) await gate.future;
    final error = loginError;
    if (error != null) throw error;
    api.session = api.session.copyWith(
      accessToken: 'access',
      username: username.trim(),
      accountKind: adminMode ? 'admin' : 'enterprise',
      setupComplete: false,
    );
  }

  @override
  Future<void> exchangePairingCode(String raw) async {
    pairingAttempts.add(raw.trim());
    final error = pairingError;
    if (error != null) {
      if (error is MobileRepositoryException) throw error;
      throw MobileRepositoryException('$error');
    }
    api.session = api.session.copyWith(
      accessToken: 'access',
      setupComplete: true,
      fhdHost: '192.168.10.2:5011',
      accountKind: 'admin',
    );
  }

  @override
  Future<List<AiGroupConversation>> loadAiGroups() async => const [];

  @override
  Future<List<ConversationItem>> loadConversations({
    bool adminMode = true,
    bool enterpriseMode = true,
  }) async {
    return fallbackConversations();
  }

  @override
  Future<MobileMeData> loadMe() async => MobileMeData.adminFallback();

  @override
  Future<ApprovalDetail> loadApprovalDetail(int id) async {
    return ApprovalDetail(
      id: id,
      requestNo: '#$id',
      title: 'Flutter 深链审批',
      status: '待审批',
      applicantName: 'admin',
      flowName: '移动端巡检',
      currentNodeName: '负责人',
      submittedAt: '刚刚',
      description: '从 Flutter deep_link_route 打开',
    );
  }
}

class _FakeDeepLinkBridge extends MobileDeepLinkBridge {
  _FakeDeepLinkBridge({this.initialRouteValue});

  final String? initialRouteValue;
  final _routes = StreamController<String>.broadcast();

  @override
  Future<String?> initialRoute() async => initialRouteValue;

  @override
  Stream<String> get routes => _routes.stream;
}

class _FakeBackgroundWorkScheduler extends PlatformBackgroundWorkScheduler {
  final sessions = <MobileSessionData>[];

  @override
  Future<void> reconcile(MobileSessionData session) async {
    sessions.add(session);
  }
}

class _FakeBiometricGate extends PlatformBiometricGate {
  _FakeBiometricGate({
    required this.canAuthenticateValue,
    required this.promptValue,
  });

  final bool canAuthenticateValue;
  final bool promptValue;
  var canAuthenticateCalls = 0;
  var promptCalls = 0;
  var finishCalls = 0;

  @override
  Future<bool> canAuthenticate() async {
    canAuthenticateCalls += 1;
    return canAuthenticateValue;
  }

  @override
  Future<bool> prompt() async {
    promptCalls += 1;
    return promptValue;
  }

  @override
  Future<void> finishApp() async {
    finishCalls += 1;
  }
}
