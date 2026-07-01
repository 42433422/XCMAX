import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/policy/android_runtime_policy.dart';

Map<String, String> _androidApiEndpoints() {
  final source = File(
    '../mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/network/ApiEndpoints.kt',
  ).readAsStringSync();
  final values = <String, String>{};
  final declarations = RegExp(
    r'const val\s+([A-Z0-9_]+)\s*=\s*"([^"]*)"',
  ).allMatches(source);

  for (final declaration in declarations) {
    final name = declaration.group(1)!;
    final template = declaration.group(2)!.replaceAllMapped(
      RegExp(r'\$([A-Z0-9_]+)'),
      (match) {
        final refName = match.group(1)!;
        final refValue = values[refName];
        if (refValue == null) {
          throw StateError('Unresolved Android endpoint ref: $refName');
        }
        return refValue;
      },
    );
    values[name] = template;
  }
  return values;
}

Map<String, Object> _androidTopology() {
  final source = File(
    '../mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/network/Topology.kt',
  ).readAsStringSync();
  final values = <String, Object>{};
  for (final declaration in RegExp(
    r'const val\s+([A-Z0-9_]+)\s*=\s*("[^"]*"|\d+)',
  ).allMatches(source)) {
    final name = declaration.group(1)!;
    final rawValue = declaration.group(2)!;
    values[name] = rawValue.startsWith('"')
        ? rawValue.substring(1, rawValue.length - 1)
        : int.parse(rawValue);
  }

  final processes = RegExp(
    r'MUST_RUN_PROCESSES\s*=\s*listOf\(([^)]*)\)',
  ).firstMatch(source);
  if (processes == null) {
    throw StateError('Android Topology.kt MUST_RUN_PROCESSES not found');
  }
  values['MUST_RUN_PROCESSES'] = RegExp(
    r'"([^"]+)"',
  ).allMatches(processes.group(1)!).map((match) => match.group(1)!).toList();
  return values;
}

Map<String, Object> _androidBuildConfigDefaults() {
  final source =
      File('../mobile-android/app/build.gradle.kts').readAsStringSync();
  final values = <String, Object>{};
  for (final declaration in RegExp(
    r'buildConfigField\("([^"]+)",\s*"([^"]+)",\s*"((?:\\.|[^"])*)"\)',
  ).allMatches(source)) {
    final type = declaration.group(1)!;
    final name = declaration.group(2)!;
    final rawValue = declaration.group(3)!;
    if (name == 'PRODUCT_SKU' && !rawValue.contains('enterprise')) {
      continue;
    }
    if (type == 'int') {
      values[name] = int.parse(rawValue);
    } else {
      values[name] = rawValue.replaceAll(r'\"', '');
    }
  }
  return values;
}

Set<String> _androidPublicAuthWritePaths() {
  final source = File(
    '../mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/network/AuthInterceptor.kt',
  ).readAsStringSync();
  final endpoints = _androidApiEndpoints();
  final paths = <String>{};
  for (final match
      in RegExp(r'path\.endsWith\("([^"]+)"\)').allMatches(source)) {
    paths.add(match.group(1)!);
  }
  for (final match in RegExp(
    r'path\.endsWith\("/"\s*\+\s*ApiEndpoints\.([A-Z0-9_]+)\)',
  ).allMatches(source)) {
    final endpoint = endpoints[match.group(1)!];
    if (endpoint == null) {
      throw StateError('Unresolved public auth endpoint: ${match.group(1)}');
    }
    paths.add('/$endpoint');
  }
  if (paths.length < 10) {
    throw StateError('Android public auth path parser found too few paths');
  }
  return paths;
}

Set<String> _androidFhdApiEndpointPairs() {
  final source = File(
    '../mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/network/FhdApi.kt',
  ).readAsStringSync();
  final endpoints = _androidApiEndpoints();
  return RegExp(r'@(GET|POST|PUT|DELETE)\(([^)]*)\)')
      .allMatches(source)
      .map((match) {
    final method = match.group(1)!;
    final rawPath = match.group(2)!.trim();
    final path = rawPath.startsWith('ApiEndpoints.')
        ? endpoints[rawPath.substring('ApiEndpoints.'.length)]
        : RegExp(r'"([^"]*)"').firstMatch(rawPath)?.group(1);
    if (path == null) {
      throw StateError('Unresolved Android FhdApi endpoint: $rawPath');
    }
    return '$method $path';
  }).toSet();
}

Map<String, String> _flutterMobileEndpointTemplates() => {
      'BASE': XcagiMobileEndpoints.base,
      'HEALTH': XcagiMobileEndpoints.health,
      'AUTH_LOGIN': XcagiMobileEndpoints.authLogin,
      'AUTH_REGISTER': XcagiMobileEndpoints.authRegister,
      'AUTH_SESSION_VALIDATE': XcagiMobileEndpoints.authSessionValidate,
      'AUTH_LOGIN_WITH_PHONE_CODE': XcagiMobileEndpoints.authLoginWithPhoneCode,
      'AUTH_QR_CONFIRM': XcagiMobileEndpoints.authQrConfirm,
      'AUTH_OIDC_EXCHANGE': XcagiMobileEndpoints.authOidcExchange,
      'AUTH_REFRESH': XcagiMobileEndpoints.authRefresh,
      'HOST_DISCOVER_HINT': XcagiMobileEndpoints.hostDiscoverHint,
      'ME': XcagiMobileEndpoints.me,
      'APPROVAL_REQUESTS': XcagiMobileEndpoints.approvalRequests,
      'CUSTOMERS': XcagiMobileEndpoints.customers,
      'SHIPMENTS': XcagiMobileEndpoints.shipments,
      'SERVICE_BRIDGE_REQUESTS': XcagiMobileEndpoints.serviceBridgeRequests,
      'SERVICE_BRIDGE_REQUESTS_RESPOND':
          XcagiMobileEndpoints.serviceBridgeRequestsRespond,
      'MODS': XcagiMobileEndpoints.mods,
      'PLATFORM_SHELL': XcagiMobileEndpoints.platformShell,
      'ONBOARDING_INDUSTRIES': XcagiMobileEndpoints.onboardingIndustries,
      'ONBOARDING_INDUSTRY_BASELINE':
          XcagiMobileEndpoints.onboardingIndustryBaseline,
      'ONBOARDING_SELECT_INDUSTRY':
          XcagiMobileEndpoints.onboardingSelectIndustry,
      'INSTALL_HOST_FOUNDATION': XcagiMobileEndpoints.installHostFoundation,
      'INSTALL_MOD': XcagiMobileEndpoints.installMod,
      'INSTALL_INDUSTRY_SEED': XcagiMobileEndpoints.installIndustrySeed,
      'INSTALL_CUSTOMER_DELIVERY_SEED':
          XcagiMobileEndpoints.installCustomerDeliverySeed,
      'HOME': XcagiMobileEndpoints.home,
      'ADMIN_HOME': XcagiMobileEndpoints.adminHome,
      'NAV_MENU': XcagiMobileEndpoints.navMenu,
      'CIRCLE_POSTS': XcagiMobileEndpoints.circlePosts,
      'CIRCLE_LIKE': XcagiMobileEndpoints.circleLikeTemplate,
      'CIRCLE_COMMENTS': XcagiMobileEndpoints.circleCommentsTemplate,
      'SYNC_STATUS': XcagiMobileEndpoints.syncStatus,
      'SYNC_PULL': XcagiMobileEndpoints.syncPull,
      'SYNC_PUSH': XcagiMobileEndpoints.syncPush,
      'SYNC_CONFLICTS': XcagiMobileEndpoints.syncConflicts,
      'DEVICES_REGISTER': XcagiMobileEndpoints.devicesRegister,
      'NOTIFICATIONS_PENDING': XcagiMobileEndpoints.notificationsPending,
      'PAIRING_EXCHANGE': XcagiMobileEndpoints.pairingExchange,
      'PAIRING_ISSUE': XcagiMobileEndpoints.pairingIssue,
      'RELAY_MOBILE_CONFIRM': XcagiMobileEndpoints.relayMobileConfirm,
      'RELAY_MOBILE_CONFIRM_CODE': XcagiMobileEndpoints.relayMobileConfirmCode,
      'RELAY_MOBILE_BIND_ACCOUNT': XcagiMobileEndpoints.relayMobileBindAccount,
      'RELAY_MOBILE_DESKTOPS': XcagiMobileEndpoints.relayMobileDesktops,
      'RELAY_TASKS': XcagiMobileEndpoints.relayTasks,
      'RELAY_TASKS_DETAIL': XcagiMobileEndpoints.relayTasksDetail,
      'CS_INFO': XcagiMobileEndpoints.csInfo,
      'CS_MESSAGES': XcagiMobileEndpoints.csMessages,
      'ADMIN_CODEX_SUPER_EMPLOYEE_MESSAGES':
          XcagiMobileEndpoints.codexSuperEmployeeMessages,
      'ADMIN_CLAUDE_SUPER_EMPLOYEE_MESSAGES':
          XcagiMobileEndpoints.claudeSuperEmployeeMessages,
      'ADMIN_CURSOR_SUPER_EMPLOYEE_MESSAGES':
          XcagiMobileEndpoints.cursorSuperEmployeeMessages,
      'ADMIN_TRAE_SUPER_EMPLOYEE_MESSAGES':
          XcagiMobileEndpoints.traeSuperEmployeeMessages,
      'GIT_BRANCHES': XcagiMobileEndpoints.gitBranches,
      'AI_GROUPS': XcagiMobileEndpoints.aiGroups,
      'AI_GROUP_CANDIDATES': XcagiMobileEndpoints.aiGroupCandidates,
      'AI_GROUP_MESSAGES': XcagiMobileEndpoints.aiGroupMessagesTemplate,
      'AI_GROUP_MEMBERS': XcagiMobileEndpoints.aiGroupMembersTemplate,
      'AI_GROUP_MEMBER': XcagiMobileEndpoints.aiGroupMemberTemplate,
      'AI_GROUP_PIN': XcagiMobileEndpoints.aiGroupPinTemplate,
      'AI_GROUP_MARK_UNREAD': XcagiMobileEndpoints.aiGroupMarkUnreadTemplate,
      'AI_GROUP_MARK_READ': XcagiMobileEndpoints.aiGroupMarkReadTemplate,
      'AI_GROUP_FOLLOWED': XcagiMobileEndpoints.aiGroupFollowedTemplate,
      'AI_GROUP_HIDDEN': XcagiMobileEndpoints.aiGroupHiddenTemplate,
      'AI_GROUP_DELETE': XcagiMobileEndpoints.aiGroupDeleteTemplate,
      'CONVERSATION_PIN': XcagiMobileEndpoints.conversationPinTemplate,
      'CONVERSATION_MARK_UNREAD':
          XcagiMobileEndpoints.conversationMarkUnreadTemplate,
      'CONVERSATION_MARK_READ':
          XcagiMobileEndpoints.conversationMarkReadTemplate,
      'CONVERSATION_FOLLOWED':
          XcagiMobileEndpoints.conversationFollowedTemplate,
      'CONVERSATION_HIDDEN': XcagiMobileEndpoints.conversationHiddenTemplate,
      'CONVERSATION_DELETE': XcagiMobileEndpoints.conversationDeleteTemplate,
      'WALLET_BALANCE': XcagiMobileEndpoints.walletBalance,
      'PAYMENT_PLANS': XcagiMobileEndpoints.paymentPlans,
      'PAYMENT_CHECKOUT': XcagiMobileEndpoints.paymentCheckout,
      'PAYMENT_QUERY': XcagiMobileEndpoints.paymentQueryTemplate,
    };

Set<String> _flutterFhdApiEndpointPairs() => {
      'GET ${XcagiMobileEndpoints.rootHealth}',
      'GET ${XcagiMobileEndpoints.health}',
      'POST ${XcagiMobileEndpoints.authLogin}',
      'POST ${XcagiMobileEndpoints.authRegister}',
      'GET ${XcagiMobileEndpoints.authSessionValidate}',
      'POST ${XcagiMobileEndpoints.authLoginWithPhoneCode}',
      'POST ${XcagiMobileEndpoints.authQrConfirm}',
      'POST ${XcagiMobileEndpoints.authOidcExchange}',
      'POST ${XcagiMobileEndpoints.authRefresh}',
      'GET ${XcagiMobileEndpoints.hostDiscoverHint}',
      'GET ${XcagiMobileEndpoints.me}',
      'POST ${XcagiMobileEndpoints.legacyAuthRegister}',
      'POST ${XcagiMobileEndpoints.lanAccessRequests}',
      'GET ${XcagiMobileEndpoints.lanStatus}',
      'POST ${XcagiMobileEndpoints.aiChat}',
      'POST ${XcagiMobileEndpoints.aiChatStream}',
      'GET ${XcagiMobileEndpoints.approvalRequests}',
      'GET ${XcagiMobileEndpoints.approvalDetailTemplate}',
      'POST ${XcagiMobileEndpoints.approvalApproveTemplate}',
      'POST ${XcagiMobileEndpoints.approvalRejectTemplate}',
      'GET ${XcagiMobileEndpoints.customers}',
      'GET ${XcagiMobileEndpoints.shipments}',
      'GET ${XcagiMobileEndpoints.serviceBridgeRequests}',
      'PUT ${XcagiMobileEndpoints.serviceBridgeRequestsRespond}',
      'GET ${XcagiMobileEndpoints.legacyServiceBridgeRequests}',
      'PUT ${XcagiMobileEndpoints.legacyServiceBridgeRequestsRespondTemplate}',
      'GET ${XcagiMobileEndpoints.mods}',
      'GET ${XcagiMobileEndpoints.platformShell}',
      'GET ${XcagiMobileEndpoints.onboardingIndustries}',
      'GET ${XcagiMobileEndpoints.onboardingIndustryBaseline}',
      'POST ${XcagiMobileEndpoints.onboardingSelectIndustry}',
      'POST ${XcagiMobileEndpoints.installHostFoundation}',
      'POST ${XcagiMobileEndpoints.installIndustrySeed}',
      'POST ${XcagiMobileEndpoints.installMod}',
      'POST ${XcagiMobileEndpoints.installCustomerDeliverySeed}',
      'GET ${XcagiMobileEndpoints.home}',
      'GET ${XcagiMobileEndpoints.navMenu}',
      'GET ${XcagiMobileEndpoints.circlePosts}',
      'POST ${XcagiMobileEndpoints.circlePosts}',
      'POST ${XcagiMobileEndpoints.circleLikeTemplate}',
      'POST ${XcagiMobileEndpoints.circleCommentsTemplate}',
      'GET ${XcagiMobileEndpoints.adminHome}',
      'GET ${XcagiMobileEndpoints.syncStatus}',
      'POST ${XcagiMobileEndpoints.syncPull}',
      'POST ${XcagiMobileEndpoints.syncPush}',
      'GET ${XcagiMobileEndpoints.syncConflicts}',
      'GET ${XcagiMobileEndpoints.inventoryItems}',
      'GET ${XcagiMobileEndpoints.legacyModsList}',
      'POST ${XcagiMobileEndpoints.devicesRegister}',
      'GET ${XcagiMobileEndpoints.notificationsPending}',
      'POST ${XcagiMobileEndpoints.pairingExchange}',
      'POST ${XcagiMobileEndpoints.relayMobileConfirm}',
      'POST ${XcagiMobileEndpoints.relayMobileConfirmCode}',
      'POST ${XcagiMobileEndpoints.relayMobileBindAccount}',
      'GET ${XcagiMobileEndpoints.relayMobileDesktops}',
      'POST ${XcagiMobileEndpoints.relayTasks}',
      'GET ${XcagiMobileEndpoints.relayTasksDetail}',
      'POST ${XcagiMobileEndpoints.marketAccountSync}',
      'GET ${XcagiMobileEndpoints.marketSessionHandoff}',
      'GET ${XcagiMobileEndpoints.financeSummary}',
      'POST ${XcagiMobileEndpoints.imDirect}',
      'GET ${XcagiMobileEndpoints.imMessagesTemplate}',
      'POST ${XcagiMobileEndpoints.imMessagesTemplate}',
      'GET ${XcagiMobileEndpoints.csInfo}',
      'POST ${XcagiMobileEndpoints.csMessages}',
      'GET ${XcagiMobileEndpoints.csMessages}',
      'GET ${XcagiMobileEndpoints.codexSuperEmployeeMessages}',
      'POST ${XcagiMobileEndpoints.codexSuperEmployeeMessages}',
      'GET ${XcagiMobileEndpoints.claudeSuperEmployeeMessages}',
      'POST ${XcagiMobileEndpoints.claudeSuperEmployeeMessages}',
      'GET ${XcagiMobileEndpoints.cursorSuperEmployeeMessages}',
      'POST ${XcagiMobileEndpoints.cursorSuperEmployeeMessages}',
      'GET ${XcagiMobileEndpoints.traeSuperEmployeeMessages}',
      'POST ${XcagiMobileEndpoints.traeSuperEmployeeMessages}',
      'GET ${XcagiMobileEndpoints.gitBranches}',
      'GET ${XcagiMobileEndpoints.aiGroups}',
      'GET ${XcagiMobileEndpoints.aiGroupCandidates}',
      'POST ${XcagiMobileEndpoints.aiGroups}',
      'GET ${XcagiMobileEndpoints.aiGroupMessagesTemplate}',
      'POST ${XcagiMobileEndpoints.aiGroupMessagesTemplate}',
      'POST ${XcagiMobileEndpoints.aiGroupMembersTemplate}',
      'DELETE ${XcagiMobileEndpoints.aiGroupMemberTemplate}',
      'PUT ${XcagiMobileEndpoints.aiGroupPinTemplate}',
      'POST ${XcagiMobileEndpoints.aiGroupMarkUnreadTemplate}',
      'POST ${XcagiMobileEndpoints.aiGroupMarkReadTemplate}',
      'PUT ${XcagiMobileEndpoints.aiGroupFollowedTemplate}',
      'PUT ${XcagiMobileEndpoints.aiGroupHiddenTemplate}',
      'DELETE ${XcagiMobileEndpoints.aiGroupDeleteTemplate}',
      'PUT ${XcagiMobileEndpoints.conversationPinTemplate}',
      'POST ${XcagiMobileEndpoints.conversationMarkUnreadTemplate}',
      'POST ${XcagiMobileEndpoints.conversationMarkReadTemplate}',
      'PUT ${XcagiMobileEndpoints.conversationFollowedTemplate}',
      'PUT ${XcagiMobileEndpoints.conversationHiddenTemplate}',
      'DELETE ${XcagiMobileEndpoints.conversationDeleteTemplate}',
      'GET ${XcagiMobileEndpoints.walletBalance}',
      'GET ${XcagiMobileEndpoints.paymentPlans}',
      'POST ${XcagiMobileEndpoints.paymentCheckout}',
      'GET ${XcagiMobileEndpoints.paymentQueryTemplate}',
    };

void main() {
  setUp(AndroidProductSkuConfig.resetRemoteSku);

  test('mobile endpoints mirror Android ApiEndpoints source of truth', () {
    final androidEndpoints = _androidApiEndpoints();
    final flutterEndpoints = _flutterMobileEndpointTemplates();

    expect(flutterEndpoints.keys.toSet(), androidEndpoints.keys.toSet());
    for (final entry in androidEndpoints.entries) {
      expect(
        flutterEndpoints[entry.key],
        entry.value,
        reason: 'Endpoint ${entry.key} drifted from Android ApiEndpoints.kt',
      );
    }
  });

  test('HTTP surface mirrors every Android FhdApi Retrofit endpoint', () {
    final androidEndpointPairs = _androidFhdApiEndpointPairs();
    final flutterEndpointPairs = _flutterFhdApiEndpointPairs();

    expect(androidEndpointPairs.length, 98);
    expect(flutterEndpointPairs.length, androidEndpointPairs.length);
    expect(
      flutterEndpointPairs,
      androidEndpointPairs,
      reason: 'Flutter MobileApiClient endpoint surface drifted from FhdApi.kt',
    );
  });

  test('mobile topology mirrors Android Topology source of truth', () {
    expect(
      {
        'PRODUCTION_HOST': XcagiMobileTopology.productionHost,
        'PRODUCTION_SCHEME': XcagiMobileTopology.productionScheme,
        'SITE_ROOT_URL': XcagiMobileTopology.siteRootUrl,
        'FHD_API_BASE_URL': XcagiMobileTopology.fhdApiBaseUrl,
        'MARKET_BASE_URL': XcagiMobileTopology.marketBaseUrl,
        'LLM_V1_BASE_URL': XcagiMobileTopology.llmV1BaseUrl,
        'MARKET_CATALOG_URL': XcagiMobileTopology.marketCatalogUrl,
        'IM_WS_URL': XcagiMobileTopology.imWsUrl,
        'DESKTOP_FHD_LISTEN_PORT': XcagiMobileTopology.desktopFhdListenPort,
        'FHD_API_LISTEN_PORT': XcagiMobileTopology.fhdApiListenPort,
        'FHD_API_UPSTREAM_PORT': XcagiMobileTopology.fhdApiUpstreamPort,
        'MODSTORE_LISTEN_PORT': XcagiMobileTopology.modstoreListenPort,
        'MUST_RUN_PROCESSES': XcagiMobileTopology.mustRunProcesses,
      },
      _androidTopology(),
      reason: 'Flutter backend entrypoints must mirror Android Topology.kt.',
    );
    expect(
      const MobileApiConfig().baseUrl,
      XcagiMobileTopology.fhdApiBaseUrl,
    );
    expect(
      const MobileApiConfig().modstoreBaseUrl,
      XcagiMobileTopology.siteRootUrl,
    );
  });

  test('Android build network constants mirror Gradle BuildConfig defaults',
      () {
    final androidBuildConfig = _androidBuildConfigDefaults();
    expect(MobileAndroidBuild.productSku, androidBuildConfig['PRODUCT_SKU']);
    expect(
      MobileAndroidBuild.fhdDefaultPort,
      androidBuildConfig['FHD_DEFAULT_PORT'],
    );
    expect(
      MobileAndroidBuild.modstoreBaseUrl,
      androidBuildConfig['MODSTORE_BASE_URL'],
    );
    expect(
      MobileAndroidBuild.enterpriseFhdBaseUrl,
      androidBuildConfig['ENTERPRISE_FHD_BASE_URL'],
    );
  });

  test('ServerRouter mirrors Android base URL and websocket routing', () {
    expect(
      const AndroidServerRouter().fhdBaseUrl(),
      'https://xiu-ci.com/fhd-api/',
    );
    expect(
      const AndroidServerRouter(
        mode: AndroidServerMode.cloud,
        isEnterprise: false,
      ).fhdBaseUrl(),
      'http://127.0.0.1:17500/',
    );
    expect(
      const AndroidServerRouter(
        fhdHost: ' https://192.168.1.9:5112/ ',
        mode: AndroidServerMode.lan,
      ).fhdBaseUrl(),
      'http://192.168.1.9:5112/',
    );
    expect(
      const AndroidServerRouter(
        fhdHost: '192.168.1.9',
        mode: AndroidServerMode.lan,
      ).fhdBaseUrl(),
      'http://192.168.1.9:17500/',
    );
    expect(
      const AndroidServerRouter(mode: AndroidServerMode.lan)
          .activeWriteBaseUrl(),
      'http://127.0.0.1:17500/',
    );
    expect(
      const AndroidServerRouter().activeWriteBaseUrl(),
      'https://xiu-ci.com/',
    );
    expect(
      const AndroidServerRouter(
        fhdHost: '192.168.1.9:5112',
        mode: AndroidServerMode.lan,
      ).fhdImWebSocketUrl('session 1'),
      'ws://192.168.1.9:5112/ws/im?session_id=session+1',
    );
    expect(
      const AndroidServerRouter().fhdImWebSocketUrl('session/1'),
      'wss://xiu-ci.com/fhd-api/ws/im?session_id=session%2F1',
    );
  });

  test('AuthHeaderPolicy mirrors Android token selection branches', () {
    for (final path in _androidPublicAuthWritePaths()) {
      expect(
        AndroidAuthHeaderPolicy.isPublicAuthWriteRequest(path),
        isTrue,
        reason: 'Flutter public auth policy missed Android path $path',
      );
    }
    expect(
      AndroidAuthHeaderPolicy.isPublicAuthWriteRequest('/api/mobile/v1/me'),
      isFalse,
    );
    expect(
      AndroidAuthHeaderPolicy.selectBearer(
        url: 'https://xiu-ci.com/fhd-api/api/mobile/v1/me',
        fhdToken: 'fhd',
        marketToken: 'market',
        modstoreBaseUrl: 'https://xiu-ci.com',
        enterpriseFhdBaseUrl: 'https://xiu-ci.com/fhd-api',
      ),
      'fhd',
    );
    expect(
      AndroidAuthHeaderPolicy.selectBearer(
        url: 'https://xiu-ci.com/api/app/config',
        fhdToken: 'fhd',
        marketToken: 'market',
        modstoreBaseUrl: 'https://xiu-ci.com',
        enterpriseFhdBaseUrl: 'https://xiu-ci.com/fhd-api',
      ),
      'market',
    );
    expect(
      AndroidAuthHeaderPolicy.selectBearer(
        url: 'http://192.168.1.9:17500/api/mobile/v1/me',
        fhdToken: '',
        marketToken: 'market',
        modstoreBaseUrl: 'https://xiu-ci.com',
        enterpriseFhdBaseUrl: 'https://xiu-ci.com/fhd-api',
      ),
      'market',
    );
    expect(
      AndroidAuthHeaderPolicy.shouldAttachSelectedBearer(
        isPublicAuthWriteRequest: true,
        callerAuthorization: '',
        selectedBearer: 'fhd',
      ),
      isFalse,
    );
    expect(
      AndroidAuthHeaderPolicy.shouldAttachSelectedBearer(
        isPublicAuthWriteRequest: false,
        callerAuthorization: 'Bearer caller',
        selectedBearer: 'fhd',
      ),
      isFalse,
    );
    expect(
      AndroidAuthHeaderPolicy.shouldAttachSelectedBearer(
        isPublicAuthWriteRequest: false,
        callerAuthorization: '',
        selectedBearer: 'fhd',
      ),
      isTrue,
    );
  });

  test('mobile endpoint helpers encode runtime path params like Retrofit', () {
    expect(
      XcagiMobileEndpoints.circleLike(42),
      'api/mobile/v1/circle/posts/42/like',
    );
    expect(
      XcagiMobileEndpoints.circleComments(42),
      'api/mobile/v1/circle/posts/42/comments',
    );
    expect(
      XcagiMobileEndpoints.relayTaskStatus('task 1'),
      'api/mobile/v1/relay/tasks/task%201',
    );
    expect(
      XcagiMobileEndpoints.aiGroupMessages('group 1'),
      'api/mobile/v1/ai-groups/group%201/messages',
    );
    expect(
      XcagiMobileEndpoints.aiGroupMembers('group 1'),
      'api/mobile/v1/ai-groups/group%201/members',
    );
    expect(
      XcagiMobileEndpoints.aiGroupMember(
        groupId: 'group 1',
        employeeId: 'emp 1',
      ),
      'api/mobile/v1/ai-groups/group%201/members/emp%201',
    );
    expect(
      XcagiMobileEndpoints.aiGroupPin('group 1'),
      'api/mobile/v1/ai-groups/group%201/pin',
    );
    expect(
      XcagiMobileEndpoints.aiGroupMarkUnread('group 1'),
      'api/mobile/v1/ai-groups/group%201/mark-unread',
    );
    expect(
      XcagiMobileEndpoints.aiGroupMarkRead('group 1'),
      'api/mobile/v1/ai-groups/group%201/mark-read',
    );
    expect(
      XcagiMobileEndpoints.aiGroupFollowed('group 1'),
      'api/mobile/v1/ai-groups/group%201/followed',
    );
    expect(
      XcagiMobileEndpoints.aiGroupHidden('group 1'),
      'api/mobile/v1/ai-groups/group%201/hidden',
    );
    expect(
      XcagiMobileEndpoints.aiGroupDelete('group 1'),
      'api/mobile/v1/ai-groups/group%201',
    );
    expect(
      XcagiMobileEndpoints.conversationPin('conv 1'),
      'api/mobile/v1/conversations/conv%201/pin',
    );
    expect(
      XcagiMobileEndpoints.conversationMarkUnread('conv 1'),
      'api/mobile/v1/conversations/conv%201/mark-unread',
    );
    expect(
      XcagiMobileEndpoints.conversationMarkRead('conv 1'),
      'api/mobile/v1/conversations/conv%201/mark-read',
    );
    expect(
      XcagiMobileEndpoints.conversationFollowed('conv 1'),
      'api/mobile/v1/conversations/conv%201/followed',
    );
    expect(
      XcagiMobileEndpoints.conversationHidden('conv 1'),
      'api/mobile/v1/conversations/conv%201/hidden',
    );
    expect(
      XcagiMobileEndpoints.conversationDelete('conv 1'),
      'api/mobile/v1/conversations/conv%201',
    );
    expect(
      XcagiMobileEndpoints.paymentQuery('trade 1'),
      'api/mobile/v1/payment/query/trade%201',
    );
    expect(XcagiMobileEndpoints.marketAccountSync, 'api/market/account-sync');
    expect(
      XcagiMobileEndpoints.marketSessionHandoff,
      'api/market/session-handoff',
    );
    expect(XcagiMobileEndpoints.appConfig, 'api/app/config');
    expect(XcagiMobileEndpoints.accountDelete, 'api/auth/account/delete');
    expect(XcagiMobileEndpoints.accountExport, 'api/auth/export');
  });

  test(
      'public auth writes skip bearer while protected FHD requests attach FHD token',
      () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final httpClient = HttpClient();
    addTearDown(() => httpClient.close(force: true));
    addTearDown(() => server.close(force: true));

    final captured = <String, String?>{};
    final done = Completer<void>();
    var requestCount = 0;
    final subscription = server.listen((request) async {
      requestCount += 1;
      if (requestCount == 1) {
        captured['authPath'] = request.uri.path;
        captured['authAuthorization'] =
            request.headers.value(HttpHeaders.authorizationHeader);
      } else if (requestCount == 2) {
        captured['protectedPath'] = request.uri.path;
        captured['protectedAuthorization'] =
            request.headers.value(HttpHeaders.authorizationHeader);
        captured['protectedClient'] = request.headers.value('X-XCAGI-Client');
        captured['protectedSku'] = request.headers.value('X-XCAGI-SKU');
        captured['protectedSession'] = request.headers.value('X-Session-ID');
      }
      request.response.statusCode = HttpStatus.ok;
      request.response.headers.contentType = ContentType.json;
      request.response.write(jsonEncode({'success': true, 'data': {}}));
      await request.response.close();
      if (requestCount == 2 && !done.isCompleted) {
        done.complete();
      }
    }, onError: done.completeError);
    addTearDown(subscription.cancel);

    final api = MobileApiClient(
      config: MobileApiConfig(
        baseUrl: 'http://${server.address.address}:${server.port}/',
      ),
      sessionStore: MemoryMobileSessionStore(
        const MobileSessionData(
          accessToken: 'fhd-access',
          marketAccessToken: 'market-access',
          sessionId: 'session-1',
        ),
      ),
      httpClient: httpClient,
    );

    await api.postJson(XcagiMobileEndpoints.authLogin, {
      'username': 'admin',
      'password': 'secret',
      'account_kind': 'enterprise',
    });
    await api.getJson(XcagiMobileEndpoints.me);
    await done.future;

    expect(captured['authPath'], '/api/mobile/v1/auth/login');
    expect(captured['authAuthorization'], isNull);
    expect(captured['protectedPath'], '/api/mobile/v1/me');
    expect(captured['protectedAuthorization'], 'Bearer fhd-access');
    expect(captured['protectedClient'], 'android');
    expect(captured['protectedSku'], 'enterprise');
    expect(captured['protectedSession'], 'session-1');
  });

  test('app config request mirrors Android ModstoreApi root base and headers',
      () async {
    expect(const MobileApiConfig().modstoreBaseUrl, 'https://xiu-ci.com');

    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final httpClient = HttpClient();
    addTearDown(() => httpClient.close(force: true));
    addTearDown(() => server.close(force: true));

    String? capturedPath;
    String? capturedClient;
    String? capturedSku;
    String? capturedSession;
    String? capturedAuthorization;
    Map<String, String> capturedQuery = {};
    final requestDone = server.first.then((request) async {
      capturedPath = request.uri.path;
      capturedQuery = request.uri.queryParameters;
      capturedClient = request.headers.value('X-XCAGI-Client');
      capturedSku = request.headers.value('X-XCAGI-SKU');
      capturedSession = request.headers.value('X-Session-ID');
      capturedAuthorization =
          request.headers.value(HttpHeaders.authorizationHeader);
      request.response.statusCode = HttpStatus.ok;
      request.response.headers.contentType = ContentType.json;
      request.response.write(jsonEncode({
        'ok': true,
        'sku': 'personal',
        'profile_page': {
          'enabled': true,
          'revision': 'profile-hot-v2',
          'subtitle': '账号、员工体系、工作台与执行端状态统一管理',
          'status_ready': '资料、头像和工作台状态已同步',
        },
      }));
      await request.response.close();
    });

    final api = MobileApiClient(
      config: MobileApiConfig(
        modstoreBaseUrl: 'http://${server.address.address}:${server.port}',
      ),
      sessionStore: MemoryMobileSessionStore(
        const MobileSessionData(
          sessionId: 'session-1',
          accessToken: 'fhd-access',
          marketAccessToken: 'market-access',
        ),
      ),
      httpClient: httpClient,
    );

    final config = await api.appConfig();
    await requestDone;

    expect(capturedPath, '/api/app/config');
    expect(capturedQuery, {
      'platform': 'android',
      'sku': 'enterprise',
      'current_version_code': '10',
    });
    expect(capturedClient, 'android');
    expect(capturedSku, 'enterprise');
    expect(capturedSession, 'session-1');
    expect(capturedAuthorization, 'Bearer market-access');
    expect(config.sku, 'personal');
    expect(AndroidProductSkuConfig.remoteSku, 'personal');
    expect(
      AndroidProductSkuConfig.isPersonal(
        buildSku: MobileAndroidBuild.productSku,
      ),
      isTrue,
    );
    expect(config.profilePage.enabled, isTrue);
    expect(
      config.profilePage.subtitle,
      '账号、员工体系、工作台与执行端状态统一管理',
    );
    expect(config.profilePage.statusReady, '资料、头像和工作台状态已同步');
  });

  test('AI chat request mirrors Android client envelope', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final httpClient = HttpClient();
    addTearDown(() => httpClient.close(force: true));
    addTearDown(() => server.close(force: true));

    Map<String, Object?>? capturedBody;
    String? capturedClient;
    String? capturedPath;
    final requestDone = server.first.then((request) async {
      capturedPath = request.uri.path;
      capturedClient = request.headers.value('X-XCAGI-Client');
      capturedBody =
          jsonDecode(await utf8.decodeStream(request)) as Map<String, Object?>;
      request.response.statusCode = HttpStatus.ok;
      request.response.headers.contentType = ContentType.json;
      request.response.write(jsonEncode({'response': '收到'}));
      await request.response.close();
    });

    final api = MobileApiClient(
      config: MobileApiConfig(
        baseUrl: 'http://${server.address.address}:${server.port}/',
      ),
      httpClient: httpClient,
    );

    final response = await api.chat('继续', sessionId: 'employee:demo:worker');
    await requestDone;

    expect(response['response'], '收到');
    expect(capturedPath, '/api/ai/chat');
    expect(capturedClient, 'android');
    expect(capturedBody, {
      'message': '继续',
      'body': '继续',
      'source': 'pro',
      'mode': 'professional',
      'session_id': 'employee:demo:worker',
    });
  });

  test('AI chat stream mirrors Android SSE envelope', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final httpClient = HttpClient();
    addTearDown(() => httpClient.close(force: true));
    addTearDown(() => server.close(force: true));

    Map<String, Object?>? capturedBody;
    String? capturedClient;
    String? capturedAccept;
    String? capturedUserId;
    String? capturedPath;
    final requestDone = server.first.then((request) async {
      capturedPath = request.uri.path;
      capturedClient = request.headers.value('X-XCAGI-Client');
      capturedAccept = request.headers.value(HttpHeaders.acceptHeader);
      capturedUserId = request.headers.value('X-User-ID');
      capturedBody =
          jsonDecode(await utf8.decodeStream(request)) as Map<String, Object?>;
      request.response.statusCode = HttpStatus.ok;
      request.response.headers.contentType =
          ContentType.parse('text/event-stream; charset=utf-8');
      request.response.write(
        'data: {"type":"token","text":"你"}\n\n',
      );
      request.response.write(
        'data: {"type":"token","text":"好"}\n\n',
      );
      request.response.write(
        'data: {"type":"done","result":{"response":"你好"}}\n\n',
      );
      await request.response.close();
    });

    final api = MobileApiClient(
      config: MobileApiConfig(
        baseUrl: 'http://${server.address.address}:${server.port}/',
      ),
      httpClient: httpClient,
    );

    final tokens = <String>[];
    final result = await api.streamChat(
      '继续',
      userId: 7,
      recentMessages: const [
        {'role': 'assistant', 'content': '上一轮'},
        {'role': 'user', 'content': '继续'},
      ],
      onToken: tokens.add,
    );
    await requestDone;

    expect(result, '你好');
    expect(tokens, ['你', '好']);
    expect(capturedPath, '/api/ai/chat/stream');
    expect(capturedClient, 'android');
    expect(capturedAccept, 'text/event-stream');
    expect(capturedUserId, '7');
    expect(capturedBody, {
      'message': '继续',
      'source': 'pro',
      'mode': 'professional',
      'user_id': '7',
      'context': {
        'recent_messages': [
          {'role': 'assistant', 'content': '上一轮'},
          {'role': 'user', 'content': '继续'},
        ],
      },
    });
  });
}
