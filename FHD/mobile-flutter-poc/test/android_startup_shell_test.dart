import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/app/android_startup_shell.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/approval/approval_screens.dart';
import 'package:xcagi_flutter_poc/src/features/shell/home_shell.dart';
import 'package:xcagi_flutter_poc/src/models/conversation.dart';
import 'package:xcagi_flutter_poc/src/platform/android_background_work_scheduler.dart';
import 'package:xcagi_flutter_poc/src/platform/android_deep_link_bridge.dart';
import 'package:xcagi_flutter_poc/src/platform/biometric_gate.dart';

void main() {
  test('startup route mirrors Android AppViewModel priority', () {
    final config = _appConfig('legal-2');

    expect(
      resolveAndroidStartupRoute(
        session: const MobileSessionData(),
        appConfig: config,
      ),
      AndroidStartupRoute.legal,
    );
    expect(
      resolveAndroidStartupRoute(
        session: const MobileSessionData(
          legalAcceptedVersion: 'legal-2',
          autoLogin: true,
          savedUsername: 'admin',
          savedPassword: 'secret',
        ),
        appConfig: config,
      ),
      AndroidStartupRoute.authAutoLogin,
    );
    expect(
      resolveAndroidStartupRoute(
        session: const MobileSessionData(legalAcceptedVersion: 'legal-2'),
        appConfig: config,
      ),
      AndroidStartupRoute.auth,
    );
    expect(
      resolveAndroidStartupRoute(
        session: const MobileSessionData(
          legalAcceptedVersion: 'legal-2',
          accessToken: 'access',
        ),
        appConfig: config,
      ),
      AndroidStartupRoute.onboarding,
    );
    expect(
      resolveAndroidStartupRoute(
        session: const MobileSessionData(
          legalAcceptedVersion: 'legal-2',
          accessToken: 'access',
          setupComplete: true,
        ),
        appConfig: config,
      ),
      AndroidStartupRoute.home,
    );
  });

  test('theme mode follows Android system light dark values', () {
    expect(androidThemeModeFromSession(''), ThemeMode.system);
    expect(androidThemeModeFromSession('system'), ThemeMode.system);
    expect(androidThemeModeFromSession('light'), ThemeMode.light);
    expect(androidThemeModeFromSession('dark'), ThemeMode.dark);
  });

  test('deep link route parsing mirrors Android MainActivity mapping', () {
    expect(
      resolveAndroidDeepLinkRoute(extraRoute: 'approval/9'),
      'approval/9',
    );
    expect(
      resolveAndroidDeepLinkRoute(uri: Uri.parse('xcagi://payment/complete')),
      'payment/complete',
    );
    expect(
      resolveAndroidDeepLinkRoute(
        uri: Uri.parse('https://xiu-ci.com/app/approval/12'),
      ),
      '/app/approval/12',
    );

    expect(
      resolveAndroidDeepLinkDestination('payment/complete').target,
      AndroidDeepLinkTarget.market,
    );
    expect(
      resolveAndroidDeepLinkDestination('work').target,
      AndroidDeepLinkTarget.work,
    );
    expect(
      resolveAndroidDeepLinkDestination('/app/approval/12').approvalId,
      12,
    );
    expect(
      resolveAndroidDeepLinkDestination('discover').target,
      AndroidDeepLinkTarget.discover,
    );
    expect(
      resolveAndroidDeepLinkDestination('unknown').target,
      AndroidDeepLinkTarget.chat,
    );
  });

  test('deep link destinations cover Android Routes table', () {
    final routes = <String, AndroidDeepLinkTarget>{
      'chat': AndroidDeepLinkTarget.chat,
      'home_hub': AndroidDeepLinkTarget.chat,
      'work': AndroidDeepLinkTarget.work,
      'discover': AndroidDeepLinkTarget.discover,
      'profile': AndroidDeepLinkTarget.profile,
      'ai_chat': AndroidDeepLinkTarget.aiChat,
      'cs_chat': AndroidDeepLinkTarget.csChat,
      'ai_employees': AndroidDeepLinkTarget.aiEmployees,
      'ai_circle': AndroidDeepLinkTarget.aiCircle,
      'ai_groups': AndroidDeepLinkTarget.aiGroups,
      'ai_group_chat': AndroidDeepLinkTarget.aiGroups,
      'ai_group_create': AndroidDeepLinkTarget.aiGroupCreate,
      'scan_qr': AndroidDeepLinkTarget.scanQr,
      'approval': AndroidDeepLinkTarget.approvalList,
      'erp': AndroidDeepLinkTarget.erp,
      'erp_overview': AndroidDeepLinkTarget.erp,
      'ocr': AndroidDeepLinkTarget.ocr,
      'bridge': AndroidDeepLinkTarget.bridge,
      'market': AndroidDeepLinkTarget.market,
      'mods': AndroidDeepLinkTarget.mods,
      'longtail': AndroidDeepLinkTarget.longtail,
      'settings': AndroidDeepLinkTarget.settings,
      'about': AndroidDeepLinkTarget.about,
      'notifications': AndroidDeepLinkTarget.notifications,
      'im': AndroidDeepLinkTarget.im,
      'connect': AndroidDeepLinkTarget.connect,
      'connect_pc': AndroidDeepLinkTarget.connectPc,
      'onboarding': AndroidDeepLinkTarget.onboarding,
      'register': AndroidDeepLinkTarget.register,
      'smart_analysis': AndroidDeepLinkTarget.smartAnalysis,
      'ai_open': AndroidDeepLinkTarget.aiOpen,
      'brain': AndroidDeepLinkTarget.brain,
      'mod_store': AndroidDeepLinkTarget.modStore,
    };

    for (final entry in routes.entries) {
      expect(
        resolveAndroidDeepLinkDestination(entry.key).target,
        entry.value,
        reason: '${entry.key} should mirror Android Routes.kt',
      );
    }

    expect(
      resolveAndroidDeepLinkDestination('conversation_chat/pinned:codex')
          .conversationId,
      'pinned:codex',
    );
    expect(
      resolveAndroidDeepLinkDestination('fixed_partner/codex').partnerKind,
      'codex',
    );
    expect(resolveAndroidDeepLinkDestination('erp_tab/2').tabIndex, 2);
    expect(resolveAndroidDeepLinkDestination('approval/42').approvalId, 42);
    expect(resolveAndroidDeepLinkDestination('mod/example').modId, 'example');
    final web = resolveAndroidDeepLinkDestination(
      'web_view?url=/market/workbench/home&title=工作台',
    );
    expect(web.target, AndroidDeepLinkTarget.desktopWebView);
    expect(web.path, '/market/workbench/home');
    expect(web.title, '工作台');
  });

  test('deep link coverage tracks Android Routes.kt constants', () {
    final androidRoutes = _androidRouteValues();
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
      'notifications',
    };
    final templateExamples = <String, String>{
      'fixed_partner/{partnerKind}': 'fixed_partner/codex',
      'approval/{id}': 'approval/42',
      'erp_tab/{tabIndex}': 'erp_tab/2',
      'mod/{modId}': 'mod/example',
      'ai_employee/{modId}/{employeeId}':
          'ai_employee/example/example-employee',
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

    expect(
      androidRoutes.difference(coveredRouteValues),
      isEmpty,
      reason: 'New Android Routes.kt values must be mapped in Flutter.',
    );
    final chatEquivalentRoutes = <String>{
      'chat',
      'home',
      'home_hub',
      'conversation_chat',
    };
    for (final route
        in directlyCoveredRoutes.difference(chatEquivalentRoutes)) {
      expect(
        resolveAndroidDeepLinkDestination(route).target,
        isNot(AndroidDeepLinkTarget.chat),
        reason: '$route should not silently fall back to chat',
      );
    }
    for (final example in templateExamples.values) {
      expect(
        resolveAndroidDeepLinkDestination(example).target,
        isNot(AndroidDeepLinkTarget.chat),
        reason: '$example should not silently fall back to chat',
      );
    }
  });

  testWidgets('legal version gates the Flutter root before auth',
      (tester) async {
    final api = _FakeStartupApi(
      session: const MobileSessionData(),
      config: _appConfig('legal-2'),
    );

    await tester.pumpWidget(
      AndroidStartupApp(
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
    expect(find.text('XCAGI 手机控制端'), findsOneWidget);
  });

  testWidgets('biometric root gate runs before Android home shell', (
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
    final gate =
        _FakeBiometricGate(canAuthenticateValue: true, promptValue: true);

    await tester.pumpWidget(
      AndroidStartupApp(
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

  testWidgets('startup consumes Android initial deep link after home is ready',
      (
    tester,
  ) async {
    final api = _FakeStartupApi(
      session: const MobileSessionData(
        legalAcceptedVersion: 'legal-2',
        accessToken: 'access',
        setupComplete: true,
      ),
      config: _appConfig('legal-2'),
    );

    await tester.pumpWidget(
      AndroidStartupApp(
        repository: _StartupRepository(api),
        deepLinkBridge: _FakeDeepLinkBridge(initialRouteValue: 'approval/12'),
        enableBiometricGate: false,
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byType(ApprovalDetailScreen), findsOneWidget);
    expect(find.text('Android 深链审批'), findsOneWidget);
  });

  testWidgets('startup reconciles Android WorkManager switches from session', (
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
      AndroidStartupApp(
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

Set<String> _androidRouteValues() {
  final source = File(
    '../mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/Routes.kt',
  ).readAsStringSync();
  return RegExp(r'const val\s+[A-Z0-9_]+\s*=\s*"([^"]*)"')
      .allMatches(source)
      .map((match) => match.group(1)!)
      .toSet();
}

class _FakeStartupApi extends MobileApiClient {
  _FakeStartupApi({
    required this.session,
    required this.config,
  });

  final MobileAppConfigData config;
  final _changes = StreamController<MobileSessionData>.broadcast();
  MobileSessionData session;

  @override
  Stream<MobileSessionData> get sessionChanges => _changes.stream;

  @override
  Future<MobileSessionData> loadSession() async => session;

  @override
  Future<MobileAppConfigData> appConfig({
    int currentVersionCode = MobileAndroidBuild.versionCode,
    String sku = MobileAndroidBuild.productSku,
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
  _StartupRepository(this.api) : super(client: api);

  final _FakeStartupApi api;
  final List<Map<String, Object?>> logins = [];

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
    api.session = api.session.copyWith(
      accessToken: 'access',
      username: username.trim(),
      accountKind: adminMode ? 'admin' : 'enterprise',
      setupComplete: false,
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
      title: 'Android 深链审批',
      status: '待审批',
      applicantName: 'admin',
      flowName: '移动端巡检',
      currentNodeName: '负责人',
      submittedAt: '刚刚',
      description: '从 Android deep_link_route 打开',
    );
  }
}

class _FakeDeepLinkBridge extends AndroidDeepLinkBridge {
  _FakeDeepLinkBridge({this.initialRouteValue});

  final String? initialRouteValue;
  final _routes = StreamController<String>.broadcast();

  @override
  Future<String?> initialRoute() async => initialRouteValue;

  @override
  Stream<String> get routes => _routes.stream;
}

class _FakeBackgroundWorkScheduler extends AndroidBackgroundWorkScheduler {
  final sessions = <MobileSessionData>[];

  @override
  Future<void> reconcile(MobileSessionData session) async {
    sessions.add(session);
  }
}

class _FakeBiometricGate extends AndroidBiometricGate {
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
