import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/policy/mobile_runtime_policy.dart';

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
      'PAIRING_LOOKUP': XcagiMobileEndpoints.pairingLookup,
      'PAIRING_ISSUE': XcagiMobileEndpoints.pairingIssue,
      'RELAY_MOBILE_BIND_ACCOUNT': XcagiMobileEndpoints.relayMobileBindAccount,
      'RELAY_MOBILE_DESKTOPS': XcagiMobileEndpoints.relayMobileDesktops,
      'RELAY_TASKS': XcagiMobileEndpoints.relayTasks,
      'RELAY_TASKS_DETAIL': XcagiMobileEndpoints.relayTasksDetail,
      'CS_INFO': XcagiMobileEndpoints.csInfo,
      'CS_MESSAGES': XcagiMobileEndpoints.csMessages,
      'ADMIN_CS_INBOX': XcagiMobileEndpoints.adminCsInbox,
      'ADMIN_CS_INBOX_MESSAGES':
          XcagiMobileEndpoints.adminCsInboxMessagesTemplate,
      'ADMIN_CS_INBOX_REPLY': XcagiMobileEndpoints.adminCsInboxReplyTemplate,
      'ADMIN_EMPLOYEE_PENDING_QUESTIONS':
          XcagiMobileEndpoints.adminEmployeePendingQuestions,
      'ADMIN_EMPLOYEE_PENDING_QUESTION_ANSWER':
          XcagiMobileEndpoints.adminEmployeePendingQuestionAnswerTemplate,
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
      'POST ${XcagiMobileEndpoints.relayMobileBindAccount}',
      'GET ${XcagiMobileEndpoints.relayMobileDesktops}',
      'POST ${XcagiMobileEndpoints.relayTasks}',
      'GET ${XcagiMobileEndpoints.relayTasksDetail}',
      'POST ${XcagiMobileEndpoints.marketAccountSync}',
      'GET ${XcagiMobileEndpoints.marketSessionHandoff}',
      'GET ${XcagiMobileEndpoints.financeSummary}',
      'GET ${XcagiMobileEndpoints.imConversations}',
      'POST ${XcagiMobileEndpoints.imReadTemplate}',
      'POST ${XcagiMobileEndpoints.imDirect}',
      'GET ${XcagiMobileEndpoints.imMessagesTemplate}',
      'POST ${XcagiMobileEndpoints.imMessagesTemplate}',
      'GET ${XcagiMobileEndpoints.csInfo}',
      'POST ${XcagiMobileEndpoints.csMessages}',
      'GET ${XcagiMobileEndpoints.csMessages}',
      'GET ${XcagiMobileEndpoints.adminCsInbox}',
      'GET ${XcagiMobileEndpoints.adminCsInboxMessagesTemplate}',
      'POST ${XcagiMobileEndpoints.adminCsInboxReplyTemplate}',
      'GET ${XcagiMobileEndpoints.adminEmployeePendingQuestions}',
      'POST ${XcagiMobileEndpoints.adminEmployeePendingQuestionAnswerTemplate}',
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
  setUp(MobileProductSkuConfig.resetRemoteSku);

  test('mobile endpoints are complete Flutter contract entries', () {
    final flutterEndpoints = _flutterMobileEndpointTemplates();
    expect(flutterEndpoints, hasLength(77));
    expect(flutterEndpoints.values, everyElement(isNotEmpty));
    expect(flutterEndpoints['BASE'], 'api/mobile/v1');
    expect(flutterEndpoints['AUTH_LOGIN'], 'api/mobile/v1/auth/login');
  });

  test('HTTP surface keeps the published Flutter API coverage', () {
    final flutterEndpointPairs = _flutterFhdApiEndpointPairs();
    expect(flutterEndpointPairs.length, 103);
    expect(flutterEndpointPairs, contains('GET api/mobile/v1/admin/home'));
    expect(flutterEndpointPairs, contains('POST api/mobile/v1/ai-groups'));
  });

  test('mobile topology comes from the generated Flutter SSOT', () {
    final topology =
        jsonDecode(File('../config/topology.generated.json').readAsStringSync())
            as Map<String, dynamic>;
    final urls = topology['urls'] as Map<String, dynamic>;
    expect(XcagiMobileTopology.productionHost, topology['host']);
    expect(XcagiMobileTopology.productionScheme, topology['scheme']);
    expect(XcagiMobileTopology.siteRootUrl, urls['SITE_ROOT_URL']);
    expect(XcagiMobileTopology.fhdApiBaseUrl, urls['FHD_API_BASE_URL']);
    expect(XcagiMobileTopology.mobileLanProxyListenPort, 5011);
    expect(
      XcagiMobileTopology.mustRunProcesses,
      topology['must_run_processes'],
    );
    expect(const MobileApiConfig().baseUrl, XcagiMobileTopology.fhdApiBaseUrl);
    expect(
      const MobileApiConfig().modstoreBaseUrl,
      XcagiMobileTopology.siteRootUrl,
    );
  });

  test('mobile build network defaults stay explicit and cross-platform', () {
    expect(MobileBuildConfig.productSku, 'enterprise');
    expect(MobileBuildConfig.fhdDefaultPort, 17500);
    expect(MobileBuildConfig.modstoreBaseUrl, 'https://xiu-ci.com');
    expect(
      MobileBuildConfig.enterpriseFhdBaseUrl,
      'https://xiu-ci.com/fhd-api',
    );
  });

  test('ServerRouter applies mobile base URL and websocket routing', () {
    expect(
      const MobileServerRouter().fhdBaseUrl(),
      'https://xiu-ci.com/fhd-api/',
    );
    expect(
      const MobileServerRouter(
        mode: MobileServerMode.cloud,
        isEnterprise: false,
      ).fhdBaseUrl(),
      'http://127.0.0.1:17500/',
    );
    expect(
      const MobileServerRouter(
        fhdHost: ' https://192.168.1.9:5112/ ',
        mode: MobileServerMode.lan,
      ).fhdBaseUrl(),
      'http://192.168.1.9:5112/',
    );
    expect(
      const MobileServerRouter(
        fhdHost: '192.168.1.9',
        mode: MobileServerMode.lan,
      ).fhdBaseUrl(),
      'http://192.168.1.9:17500/',
    );
    expect(
      const MobileServerRouter(mode: MobileServerMode.lan).activeWriteBaseUrl(),
      'http://127.0.0.1:17500/',
    );
    expect(
      const MobileServerRouter().activeWriteBaseUrl(),
      'https://xiu-ci.com/',
    );
    expect(
      const MobileServerRouter(
        fhdHost: '192.168.1.9:5112',
        mode: MobileServerMode.lan,
      ).fhdImWebSocketUrl('session 1'),
      'ws://192.168.1.9:5112/ws/im?session_id=session+1',
    );
    expect(
      const MobileServerRouter().fhdImWebSocketUrl('session/1'),
      'wss://xiu-ci.com/fhd-api/ws/im?session_id=session%2F1',
    );
  });

  test(
    'AuthHeaderPolicy applies the public-auth and token-selection branches',
    () {
      for (final path in {
        '/api/auth/login',
        '/api/auth/register',
        '/api/auth/login-with-phone-code',
        '/api/mobile/v1/auth/login',
        '/api/mobile/v1/auth/register',
        '/api/mobile/v1/auth/login-with-phone-code',
        '/api/mobile/v1/auth/refresh',
        '/api/mobile/v1/auth/oidc/exchange',
        '/api/mobile/v1/auth/qr/confirm',
        '/api/mobile/v1/pairing/issue',
        '/api/mobile/v1/pairing/exchange',
      }) {
        expect(
          MobileAuthHeaderPolicy.isPublicAuthWriteRequest(path),
          isTrue,
          reason: 'Flutter public auth policy missed $path',
        );
      }
      expect(
        MobileAuthHeaderPolicy.isPublicAuthWriteRequest('/api/mobile/v1/me'),
        isFalse,
      );
      expect(
        MobileAuthHeaderPolicy.selectBearer(
          url: 'https://xiu-ci.com/fhd-api/api/mobile/v1/me',
          fhdToken: 'fhd',
          marketToken: 'market',
          modstoreBaseUrl: 'https://xiu-ci.com',
          enterpriseFhdBaseUrl: 'https://xiu-ci.com/fhd-api',
        ),
        'fhd',
      );
      expect(
        MobileAuthHeaderPolicy.selectBearer(
          url: 'https://xiu-ci.com/api/app/config',
          fhdToken: 'fhd',
          marketToken: 'market',
          modstoreBaseUrl: 'https://xiu-ci.com',
          enterpriseFhdBaseUrl: 'https://xiu-ci.com/fhd-api',
        ),
        'market',
      );
      expect(
        MobileAuthHeaderPolicy.selectBearer(
          url: 'http://192.168.1.9:17500/api/mobile/v1/me',
          fhdToken: '',
          marketToken: 'market',
          modstoreBaseUrl: 'https://xiu-ci.com',
          enterpriseFhdBaseUrl: 'https://xiu-ci.com/fhd-api',
        ),
        'market',
      );
      expect(
        MobileAuthHeaderPolicy.shouldAttachSelectedBearer(
          isPublicAuthWriteRequest: true,
          callerAuthorization: '',
          selectedBearer: 'fhd',
        ),
        isFalse,
      );
      expect(
        MobileAuthHeaderPolicy.shouldAttachSelectedBearer(
          isPublicAuthWriteRequest: false,
          callerAuthorization: 'Bearer caller',
          selectedBearer: 'fhd',
        ),
        isFalse,
      );
      expect(
        MobileAuthHeaderPolicy.shouldAttachSelectedBearer(
          isPublicAuthWriteRequest: false,
          callerAuthorization: '',
          selectedBearer: 'fhd',
        ),
        isTrue,
      );
    },
  );

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
      XcagiMobileEndpoints.employeeChatStream('emp 1'),
      'api/mobile/v1/employees/emp%201/chat/stream',
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
          captured['authAuthorization'] = request.headers.value(
            HttpHeaders.authorizationHeader,
          );
        } else if (requestCount == 2) {
          captured['protectedPath'] = request.uri.path;
          captured['protectedAuthorization'] = request.headers.value(
            HttpHeaders.authorizationHeader,
          );
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
    },
  );

  test(
    'app config request matches the mobile ModstoreApi root base and headers',
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
        capturedAuthorization = request.headers.value(
          HttpHeaders.authorizationHeader,
        );
        request.response.statusCode = HttpStatus.ok;
        request.response.headers.contentType = ContentType.json;
        request.response.write(
          jsonEncode({
            'ok': true,
            'sku': 'personal',
            'profile_page': {
              'enabled': true,
              'revision': 'profile-hot-v2',
              'subtitle': '账号、员工体系、工作台与执行端状态统一管理',
              'status_ready': '资料、头像和工作台状态已同步',
            },
          }),
        );
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
      expect(MobileProductSkuConfig.remoteSku, 'personal');
      expect(
        MobileProductSkuConfig.isPersonal(
          buildSku: MobileBuildConfig.productSku,
        ),
        isTrue,
      );
      expect(config.profilePage.enabled, isTrue);
      expect(config.profilePage.subtitle, '账号、员工体系、工作台与执行端状态统一管理');
      expect(config.profilePage.statusReady, '资料、头像和工作台状态已同步');
    },
  );

  test('AI chat request matches the mobile client envelope', () async {
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
      // Keep session in cloud so preferCloudIfLanUnreachable skips file I/O.
      sessionStore: MemoryMobileSessionStore(
        const MobileSessionData(serverMode: 'cloud'),
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

  test('AI chat stream matches the mobile SSE envelope', () async {
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
      request.response.headers.contentType = ContentType.parse(
        'text/event-stream; charset=utf-8',
      );
      request.response.write('data: {"type":"token","text":"你"}\n\n');
      request.response.write('data: {"type":"token","text":"好"}\n\n');
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

  test('employee chat stream matches the mobile SSE envelope', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final httpClient = HttpClient();
    addTearDown(() => httpClient.close(force: true));
    addTearDown(() => server.close(force: true));

    Map<String, Object?>? capturedBody;
    String? capturedClient;
    String? capturedAccept;
    String? capturedUserId;
    String? capturedPath;
    String? capturedAuthorization;
    final requestDone = server.first.then((request) async {
      capturedPath = request.uri.path;
      capturedClient = request.headers.value('X-XCAGI-Client');
      capturedAccept = request.headers.value(HttpHeaders.acceptHeader);
      capturedUserId = request.headers.value('X-User-ID');
      capturedAuthorization = request.headers.value(
        HttpHeaders.authorizationHeader,
      );
      capturedBody =
          jsonDecode(await utf8.decodeStream(request)) as Map<String, Object?>;
      request.response.statusCode = HttpStatus.ok;
      request.response.headers.contentType = ContentType.parse(
        'text/event-stream; charset=utf-8',
      );
      request.response.write('data: {"type":"token","text":"已连接"}\n\n');
      request.response.write('data: {"type":"token","text":"员工回复"}\n\n');
      request.response.write(
        'data: {"type":"done","result":{"response":"员工回复"}}\n\n',
      );
      await request.response.close();
    });

    final api = MobileApiClient(
      config: MobileApiConfig(
        baseUrl: 'http://${server.address.address}:${server.port}/',
      ),
      sessionStore: MemoryMobileSessionStore(
        const MobileSessionData(
          accessToken: 'fhd-access',
          sessionId: 'session-1',
        ),
      ),
      httpClient: httpClient,
    );

    final tokens = <String>[];
    final result = await api.streamEmployeeChat(
      message: '继续',
      employeeId: 'site-content-editor',
      modId: 'admin-duty-employees',
      conversationId: 'employee:admin-duty-employees:site-content-editor',
      userId: 7,
      onToken: tokens.add,
    );
    await requestDone;

    expect(result, '员工回复');
    expect(tokens, ['已连接', '员工回复']);
    expect(
      capturedPath,
      '/api/mobile/v1/employees/site-content-editor/chat/stream',
    );
    expect(capturedClient, 'android');
    expect(capturedAccept, 'text/event-stream');
    expect(capturedUserId, '7');
    expect(capturedAuthorization, 'Bearer fhd-access');
    expect(capturedBody, {
      'message': '继续',
      'conversation_id': 'employee:admin-duty-employees:site-content-editor',
      'mod_id': 'admin-duty-employees',
      'employee_id': 'site-content-editor',
    });
  });
}
