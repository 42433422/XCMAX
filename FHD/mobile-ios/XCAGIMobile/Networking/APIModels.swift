import Foundation

// 数据模型(对标 mobile-harmony `MobileModels.ets` / Android `ApiModels.kt`)。
//
// 后端 JSON 为 snake_case;解码统一用 `.convertFromSnakeCase`(见 APIClient),
// 故此处用 camelCase 属性名,无需逐字段写 CodingKeys。所有字段可空,保持向后兼容。

// MARK: - 通用信封

struct MobileEnvelope<T: Decodable>: Decodable {
    var code: Int?
    var message: String?
    var success: Bool?
    var data: T?
}

struct UserDto: Decodable, Hashable {
    var id: Int?
    var username: String?
    var displayName: String?
    var email: String?
    var role: String?
    var isActive: Bool?
    var avatarUrl: String?
}

// MARK: - 认证 / 用户

struct MobileLoginData: Decodable {
    var user: UserDto?
    var sessionId: String?
    var accessToken: String?
    var refreshToken: String?
    var accountKind: String?
    var companyBrand: String?
    var marketIsAdmin: Bool?
    var marketIsEnterprise: Bool?
    var expiresIn: Int?
}

struct MobileMeData: Decodable {
    var user: UserDto?
    var permissions: [String]?
    var accountKind: String?
    var companyBrand: String?
    var mods: [ModSummary]?
}

struct ModSummary: Decodable { var id: String? }

// MARK: - MOD / 首页

struct ModIndustry: Decodable, Hashable { var id: String?; var name: String? }

struct ModMenuItem: Decodable, Hashable {
    var id: String?
    var label: String?
    var icon: String?
    var path: String?
}

struct WorkflowEmployeeInfo: Decodable, Hashable {
    var id: String?
    var label: String?
    var panelTitle: String?
    var panelSummary: String?
    var apiBasePath: String?
    var phoneChannel: String?
    var workflowPlaceholder: Bool?
    var yuangonArea: String?
    var isDutyEmployee: Bool?
    var isStoreEmployee: Bool?
    var status: String?
    var employeeSource: String?
    var employeeScope: String?
}

struct ModInfo: Decodable, Hashable, Identifiable {
    var id: String?
    var name: String?
    var version: String?
    var author: String?
    var description: String?
    var primary: Bool?
    var industry: ModIndustry?
    var frontendMenu: [ModMenuItem]?
    var menu: [ModMenuItem]?
    var workflowEmployees: [WorkflowEmployeeInfo]?

    // Identifiable 兜底(id 可空时用 name)
    var stableId: String { id ?? name ?? UUID().uuidString }
}

struct MobileModsData: Decodable { var items: [ModInfo]? }

struct SyncStatusData: Decodable {
    var status: String?
    var cursor: Int?
    var updatedAt: String?
    var error: String?
}

struct MobileHomeData: Decodable {
    var mods: [ModInfo]?
    var sync: SyncStatusData?
}

// MARK: - 配对 / 对话

struct PairingExchangeData: Decodable {
    var host: String?
    var port: Int?
    var apiBaseUrl: String?
    var baseUrl: String?
    var hint: String?
}

struct ChatPayload: Decodable {
    var reply: String?
    var content: String?
    var message: String?
}

struct ChatResponseData: Decodable {
    var success: Bool?
    var reply: String?
    var message: String?
    var data: ChatPayload?

    /// 从多种回包形态里取出最终回复文本。
    var bestReply: String {
        if let r = reply, !r.isEmpty { return r }
        if let r = data?.reply, !r.isEmpty { return r }
        if let r = data?.content, !r.isEmpty { return r }
        if let r = data?.message, !r.isEmpty { return r }
        if let r = message, !r.isEmpty { return r }
        return ""
    }
}

// MARK: - 联系人固定区

struct FixedContactDto: Decodable, Hashable, Identifiable {
    var id: String
    var kind: String
    var name: String
    var summary: String
    var avatar: String
    var route: String
    var backend: String
}

struct MobileFixedContactsData: Decodable {
    var side: String?
    var top: [FixedContactDto]?
    var bottom: [FixedContactDto]?
}

// MARK: - 客服

struct CsInfo: Decodable {
    var title: String?
    var subtitle: String?
    var online: Bool?
}

// MARK: - AI 圈子(朋友圈)

struct CircleComment: Decodable, Hashable {
    var id: Int?
    var authorName: String?
    var body: String?
    var createdAt: String?

    var idValue: String { id.map { String($0) } ?? UUID().uuidString }
}

struct CirclePost: Decodable, Hashable, Identifiable {
    var id: Int?
    var authorKind: String?
    var authorUserId: Int?
    var employeeId: String?
    var authorName: String?
    var authorAvatar: String?
    var body: String?
    var createdAt: String?
    var likeCount: Int?
    var likedByMe: Bool?
    var comments: [CircleComment]?

    var idValue: Int { id ?? 0 }
}

struct CirclePostsData: Decodable {
    var items: [CirclePost]?
    var count: Int?
}

// MARK: - AI 群聊

struct AiGroupMember: Decodable, Hashable {
    var employeeId: String?
    var modId: String?
    var name: String?
    var avatar: String?
    var summary: String?
}

struct AiGroup: Decodable, Hashable, Identifiable {
    var id: String?
    var name: String?
    var departmentKey: String?
    var memberCount: Int?
    var members: [AiGroupMember]?
    var isPinned: Bool?
    var isHidden: Bool?
    var isFollowed: Bool?
    var unreadCount: Int?
    var createdAt: String?
    var lastMessagePreview: String?
    var lastMessageAt: String?

    var idValue: String { id ?? UUID().uuidString }
}

struct AiGroupMessage: Decodable, Hashable, Identifiable {
    var id: String?
    var groupId: String?
    var role: String?
    var senderId: String?
    var senderName: String?
    var senderAvatar: String?
    var body: String?
    var createdAt: String?

    var idValue: String { id ?? UUID().uuidString }
}

struct AiGroupsData: Decodable { var groups: [AiGroup]? }
struct AiGroupCreateData: Decodable { var group: AiGroup? }
struct AiGroupMessagesData: Decodable { var messages: [AiGroupMessage]? }
struct AiGroupPostResult: Decodable {
    var groupId: String?
    var messages: [AiGroupMessage]?
}

// MARK: - 审批

struct ApprovalItem: Decodable, Hashable, Identifiable {
    var id: String
    var title: String?
    var subtitle: String?
    var status: String?
    var applicantName: String?
}

struct ApprovalDetail: Decodable {
    var id: String?
    var title: String?
    var requestNo: String?
    var applicantName: String?
    var flowName: String?
    var currentNodeName: String?
    var submittedAt: String?
    var description: String?
    var status: String?
}

// MARK: - 企业模块(客户 / 发货 / 服务桥 / 钱包)

struct PaginationInfo: Decodable {
    var total: Int?
    var page: Int?
    var perPage: Int?
    var totalPages: Int?
}

struct CustomerItem: Decodable, Hashable, Identifiable {
    var id: Int?
    var name: String?
    var phone: String?
    var idValue: Int { id ?? 0 }
}

struct CustomersData: Decodable {
    var items: [CustomerItem]?
    var pagination: PaginationInfo?
}

struct ShipmentItem: Decodable, Hashable, Identifiable {
    var id: Int?
    var orderNumber: String?
    var status: String?
    var idValue: Int { id ?? 0 }
}

struct ShipmentsData: Decodable {
    var items: [ShipmentItem]?
    var pagination: PaginationInfo?
}

struct ServiceBridgeRequest: Decodable, Hashable, Identifiable {
    var id: Int?
    var sourceInstanceId: String?
    var sourceInstanceName: String?
    var requestType: String?
    var title: String?
    var description: String?
    var priority: String?
    var status: String?
    var response: String?
    var respondedBy: String?
    var respondedAt: String?
    var createdAt: String?
    var updatedAt: String?
    var idValue: Int { id ?? 0 }
}

struct ServiceBridgeData: Decodable {
    var items: [ServiceBridgeRequest]?
    var pagination: PaginationInfo?
}

struct WalletBalanceData: Decodable {
    var balance: Double?
    var currency: String?
    var membershipLevel: String?
    var experience: Int?
    var byokConfigured: Bool?
    var byokCount: Int?
    var synced: Bool?
    var message: String?
    var marketBaseUrl: String?
}

/// 简单 {success, message} 返回(注册等非信封接口)。
struct SimpleResult: Decodable { var success: Bool?; var message: String? }

// MARK: - IM 即时通讯(对标 Android `ImMessengerScreen` / 后端 app/fastapi_routes/im_routes.py)
// 注意:IM 端点不在 api/mobile/v1 下,返回体也不是 MobileEnvelope —— 顶层即 {success, ...}。

struct ImConversation: Decodable, Hashable, Identifiable {
    var id: Int?
    var conversationId: Int?
    var title: String?
    var peerUserId: Int?
    var peerName: String?
    var unreadCount: Int?
    var lastMessagePreview: String?
    var idValue: Int { id ?? conversationId ?? 0 }
}

struct ImMessageDto: Decodable, Hashable, Identifiable {
    var id: Int?
    var conversationId: Int?
    var senderId: Int?
    var body: String?
    var content: String?
    var createdAt: String?
    var createdAtMs: Double?

    var idValue: String { id.map { String($0) } ?? UUID().uuidString }
    var textValue: String {
        if let b = body, !b.isEmpty { return b }
        if let c = content, !c.isEmpty { return c }
        return ""
    }
}

struct ImConversationsResponse: Decodable { var success: Bool?; var conversations: [ImConversation]? }
struct ImMessagesResponse: Decodable { var success: Bool?; var messages: [ImMessageDto]? }
struct ImDirectResponse: Decodable { var success: Bool?; var conversation: ImConversation? }
struct ImSendResponse: Decodable { var success: Bool?; var message: ImMessageDto? }

// MARK: - 客户端内部聊天消息(非解码,UI 用)

struct ChatMessage: Identifiable, Hashable {
    enum Role: String { case user, assistant, system }
    let id = UUID()
    var role: Role
    var text: String
}
