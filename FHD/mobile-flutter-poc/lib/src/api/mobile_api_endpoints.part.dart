part of 'mobile_api.dart';

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
  static const pairingLookup = '$base/pairing/lookup';
  static const pairingIssue = '$base/pairing/issue';
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
  static const adminCsInbox = '$base/im/cs/inbox';
  static const adminCsInboxMessagesTemplate = '$base/im/cs/inbox/{id}/messages';
  static const adminCsInboxReplyTemplate = '$base/im/cs/inbox/{id}/reply';
  static const mods = '$base/mods';
  static const paymentPlans = '$base/payment/plans';
  static const paymentCheckout = '$base/payment/checkout';
  static const imConversations = '$base/im/conversations';
  static const imDirect = '$base/im/conversations/direct';
  static const imReadTemplate = '$base/im/conversations/{id}/read';
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
  static const codexSuperEmployeeStream =
      '$base/admin/codex-super-employee/messages/stream';
  static const claudeSuperEmployeeStream =
      '$base/admin/claude-super-employee/messages/stream';
  static const cursorSuperEmployeeStream =
      '$base/admin/cursor-super-employee/messages/stream';
  static const traeSuperEmployeeStream =
      '$base/admin/trae-super-employee/messages/stream';
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
  static const imMessagesTemplate = '$base/im/conversations/{id}/messages';
  static const adminEmployeePendingQuestions =
      '$base/admin/employee-pending-questions';
  static const adminEmployeePendingQuestionAnswerTemplate =
      '$base/admin/employee-pending-questions/{questionId}/answer';
  static const employeeChatStreamTemplate =
      '$base/employees/{employeeId}/chat/stream';

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

  static String superEmployeeStream(String tool) {
    switch (tool.trim().toLowerCase()) {
      case 'claude':
        return claudeSuperEmployeeStream;
      case 'cursor':
        return cursorSuperEmployeeStream;
      case 'trae':
        return traeSuperEmployeeStream;
      case 'codex':
      default:
        return codexSuperEmployeeStream;
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

  static String relayTaskCancel(String taskId) {
    return '${relayTasksDetail.replaceFirst('{taskId}', Uri.encodeComponent(taskId))}/cancel';
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

  static String adminCsInboxMessages(int id) {
    return adminCsInboxMessagesTemplate.replaceFirst('{id}', '$id');
  }

  static String adminCsInboxReply(int id) {
    return adminCsInboxReplyTemplate.replaceFirst('{id}', '$id');
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

  static String employeeChatStream(String employeeId) {
    return employeeChatStreamTemplate.replaceFirst(
      '{employeeId}',
      Uri.encodeComponent(employeeId),
    );
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

  static String imRead(int conversationId) {
    return imReadTemplate.replaceFirst('{id}', '$conversationId');
  }

  static String adminEmployeePendingQuestionAnswer(int questionId) {
    return adminEmployeePendingQuestionAnswerTemplate.replaceFirst(
      '{questionId}',
      '$questionId',
    );
  }
}
