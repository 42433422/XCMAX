// part 文件：启动壳状态基类（字段与深链路由方法）。

part of 'mobile_startup_shell.dart';

abstract class _MobileStartupStateBase extends State<MobileStartupApp> {
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
