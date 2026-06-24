import Foundation

/// API 端点常量表(对标 mobile-harmony `ApiEndpoints.ets` 与 Android `ApiEndpoints.kt`)。
///
/// 所有 `api/mobile/v1/*` 路径集中于此;端点变更时只改本文件,保持三端同步。
enum APIEndpoints {
    static let base = "api/mobile/v1"

    // 健康检查
    static let health = "\(base)/health"

    // 认证
    static let authLogin = "\(base)/auth/login"
    static let authRegister = "api/auth/register"   // 非 v1:企业账号自助注册(FHD)
    static let authLoginWithPhoneCode = "\(base)/auth/login-with-phone-code"
    static let authQrConfirm = "\(base)/auth/qr/confirm"
    static let authOidcExchange = "\(base)/auth/oidc/exchange"
    static let authRefresh = "\(base)/auth/refresh"

    // 主机发现
    static let hostDiscoverHint = "\(base)/host/discover-hint"

    // 用户信息
    static let me = "\(base)/me"

    // 审批
    static let approvalRequests = "\(base)/approval/requests"
    static let approvalDetail = "api/approval/requests/{id}"
    static let approvalApprove = "api/approval/requests/{id}/approve"
    static let approvalReject = "api/approval/requests/{id}/reject"

    // 企业模块
    static let customers = "\(base)/customers"
    static let shipments = "\(base)/shipments"
    static let serviceBridgeRequests = "\(base)/service-bridge/requests"
    static let serviceBridgeRespond = "\(base)/service-bridge/requests/{id}/respond"

    // MOD / 平台壳
    static let mods = "\(base)/mods"
    static let platformShell = "\(base)/platform-shell"

    // 首页
    static let home = "\(base)/home"
    static let adminHome = "\(base)/admin/home"

    // 同步
    static let syncStatus = "\(base)/sync/status"
    static let syncPull = "\(base)/sync/pull"
    static let syncPush = "\(base)/sync/push"
    static let syncConflicts = "\(base)/sync/conflicts"

    // 设备 / 推送
    static let devicesRegister = "\(base)/devices/register"

    // 配对
    static let pairingExchange = "\(base)/pairing/exchange"
    static let pairingIssue = "\(base)/pairing/issue"

    // 中继
    static let relayMobileConfirm = "\(base)/relay/mobile/confirm"
    static let relayMobileConfirmCode = "\(base)/relay/mobile/confirm-code"
    static let relayMobileDesktops = "\(base)/relay/mobile/desktops"
    static let relayTasks = "\(base)/relay/tasks"
    static let relayTaskDetail = "\(base)/relay/tasks/{taskId}"

    // 客服
    static let csInfo = "\(base)/cs/info"
    static let csMessages = "\(base)/cs/messages"

    // 联系人固定区(按端 SSOT 派生)
    static let contactsFixed = "\(base)/contacts/fixed"

    // AI 圈子(朋友圈)
    static let circlePosts = "\(base)/circle/posts"
    static let circlePostLike = "\(base)/circle/posts/{id}/like"
    static let circlePostComments = "\(base)/circle/posts/{id}/comments"

    // AI 群聊
    static let aiGroups = "\(base)/ai-groups"
    static let aiGroupMessages = "\(base)/ai-groups/{id}/messages"
    static let aiGroupMembers = "\(base)/ai-groups/{id}/members"
    static let aiGroupMarkRead = "\(base)/ai-groups/{id}/mark-read"
    static let aiGroupMarkUnread = "\(base)/ai-groups/{id}/mark-unread"

    // 钱包
    static let walletBalance = "\(base)/wallet/balance"
    static let walletOverview = "\(base)/wallet/overview"

    // 非 v1:普通对话 / 客服对话 / SSE 流式
    static let aiChat = "api/ai/chat"
    static let csChat = "api/cs/chat"
    static let aiChatStream = "api/ai/chat/stream"

    // IM 即时通讯(非 v1,顶层非信封;app/fastapi_routes/im_routes.py)
    static let imConversations = "api/im/conversations"
    static let imContacts = "api/im/contacts"
    static let imDirect = "api/im/conversations/direct"
    static let imMessages = "api/im/conversations/{id}/messages"
    static let imRead = "api/im/conversations/{id}/read"

    /// 把 `{id}` / `{taskId}` 占位替换为实际值。
    static func path(_ template: String, id: String) -> String {
        template
            .replacingOccurrences(of: "{id}", with: id)
            .replacingOccurrences(of: "{taskId}", with: id)
    }
}
