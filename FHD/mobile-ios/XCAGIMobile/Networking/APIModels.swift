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
    // 头像(对标 Android AppAvatar 加载 market_avatar / avatar_url)
    var avatar: String?
    var avatarUrl: String?
    var marketAvatar: String?

    /// 解析出可用头像 URL(优先 avatarUrl → marketAvatar → avatar)。
    var resolvedAvatar: String? { avatarUrl ?? marketAvatar ?? avatar }
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

// MARK: - 客服(对标 Android cs/info + cs/messages,字段 cs_name/cs_online/cs_avatar/cs_available)

struct CsInfo: Decodable {
    // 旧版 cs/info 字段(向后兼容)
    var title: String?
    var subtitle: String?
    var online: Bool?
    // Android 对齐字段(cs_* → camelCase 自动映射)
    var csAvailable: Bool?
    var csName: String?
    var csAvatar: String?
    var csOnline: Bool?

    init(title: String? = nil, subtitle: String? = nil, online: Bool? = nil,
         csAvailable: Bool? = nil, csName: String? = nil, csAvatar: String? = nil, csOnline: Bool? = nil) {
        self.title = title; self.subtitle = subtitle; self.online = online
        self.csAvailable = csAvailable; self.csName = csName; self.csAvatar = csAvatar; self.csOnline = csOnline
    }

    /// 展示标题:优先 cs_name,回退旧 title。
    var resolvedTitle: String { csName?.isEmpty == false ? csName! : (title ?? "专属客服") }
    /// 在线状态:优先 cs_online,回退旧 online。
    var resolvedOnline: Bool { csOnline ?? online ?? false }
    var resolvedSubtitle: String { subtitle?.isEmpty == false ? subtitle! : (resolvedOnline ? "在线" : "离线") }
}

/// cs/messages GET 列表项(sender ∈ "cs"|"user", body 文本)。
struct CsMessageItemDto: Decodable {
    var messageId: String?
    var sender: String?
    var body: String?
    var timestamp: String?
    var msgType: String?
}

struct CsMessagesListData: Decodable { var messages: [CsMessageItemDto]? }

/// cs/messages POST 回包(reply 为客服回复文本)。
struct CsMessageResponseData: Decodable {
    var messageId: String?
    var requestId: Int?
    var reply: String?
    var backend: String?
    var timestamp: String?
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
    var avatarKey: String?
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
/// 增删成员 / 置顶 / 关注 / 隐藏 / 标读未读 等返回 {group}(对标 Android AiGroupWrap)。
struct AiGroupWrap: Decodable { var group: AiGroup? }
struct AiGroupMessagesData: Decodable { var messages: [AiGroupMessage]? }
struct AiGroupPostResult: Decodable {
    var groupId: String?
    var group: AiGroup?
    var messages: [AiGroupMessage]?
}

/// 建群多选成员草稿(对标 Android AiGroupMemberDraft;UI 选人后传给 createGroupWithMembers)。
struct AiGroupMemberDraft {
    var employeeId: String
    var modId: String
    var name: String
    var avatar: String
    var summary: String

    init(employeeId: String, modId: String = "", name: String, avatar: String = "", summary: String = "") {
        self.employeeId = employeeId; self.modId = modId; self.name = name
        self.avatar = avatar; self.summary = summary
    }
}

// MARK: - 侧栏菜单(桌面工具动态;对标 Android NavMenuData)

struct NavMenuItem: Decodable, Hashable, Identifiable {
    var key: String?
    var name: String?
    var icon: String?
    var path: String?
    var source: String?
    var modId: String?

    var id: String { key ?? path ?? UUID().uuidString }
}

struct NavMenuData: Decodable {
    var items: [NavMenuItem]?
    var accountKind: String?
}

// MARK: - 超级员工开发(派工回包;对标 Android codex/claude super-employee messages)

/// 派工消息列表项(role ∈ user/assistant/system;kind 区分调度/结果/直答)。
struct SuperEmployeeMessage: Decodable, Hashable, Identifiable {
    var id: String?
    var role: String?
    var body: String?
    var kind: String?
    var createdAt: String?
    var taskId: String?
    var dispatchRequestId: String?
    var requestId: String?

    var idValue: String { id ?? UUID().uuidString }
}

struct SuperEmployeeMessagesData: Decodable { var messages: [SuperEmployeeMessage]? }

/// 派工提交回包(dispatch 含 request_id/task_id;assistant_message 可能含即时直答)。
struct SuperEmployeeDispatchData: Decodable {
    var dispatch: SuperEmployeeDispatch?
    var assistantMessage: SuperEmployeeMessage?
    var taskId: String?
    var dispatchRequestId: String?
    var requestId: String?
}

struct SuperEmployeeDispatch: Decodable {
    var requestId: String?
    var taskId: String?
}

// MARK: - 中继任务(relay tasks;git 操作 / 多设备派工)

struct RelayTaskResult: Decodable {
    var error: String?
    var reply: String?
}

struct RelayTask: Decodable {
    var taskId: String?
    var status: String?
    var result: RelayTaskResult?
}

struct RelayTaskData: Decodable { var task: RelayTask? }

// MARK: - 企业库存(api/inventory/items)

struct InventoryItem: Decodable, Hashable, Identifiable {
    var id: Int?
    var name: String?
    var sku: String?
    var quantity: Int?
    var unit: String?
    var idValue: Int { id ?? 0 }
}

struct InventoryItemsData: Decodable {
    var items: [InventoryItem]?
    var data: [InventoryItem]?
    /// 兼容 {items:[]} 与 {data:[]} 两种回包。
    var resolved: [InventoryItem] { items ?? data ?? [] }
}

// MARK: - App 配置 / 反馈 / 注销(MODstore 端,对标 Android ModstoreApi)

struct AppConfigData: Decodable {
    var latestVersion: String?
    var minVersion: String?
    var downloadUrl: String?
    var updateUrl: String?
    var forceUpdate: Bool?
    var releaseNotes: String?
    var privacyUrl: String?
    var termsUrl: String?
}

/// 市场登录/注册回包(对标 Android MarketAuthResponse)。
struct MarketAuthData: Decodable {
    var success: Bool?
    var ok: Bool?
    var accountKind: String?
    var token: String?
    var accessToken: String?
    var refreshToken: String?
    var message: String?
    var marketIsAdmin: Bool?
    var isEnterprise: Bool?

    var isAuthenticated: Bool { success == true || ok == true }
    var resolvedToken: String? {
        if let t = accessToken, !t.isEmpty { return t }
        if let t = token, !t.isEmpty { return t }
        return nil
    }
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

// MARK: - 配对二维码解析(对标 Android PairingQrCodec;多格式:relay v3 / host:port / JSON / xcagi://)

/// 配对二维码载荷。version: 1=host:port:nonce 旧格式, 2=短码优先, 3=云中继绑定。
struct PairingQrPayload: Equatable {
    var host: String = ""
    var port: Int = 0
    var nonce: String = ""
    var token: String = ""          // v2:短码(6 位)或 nonce;v3:中继短码
    var apiBaseUrl: String = ""
    var relayId: String = ""
    var relayBaseUrl: String = ""
    var version: Int = 1
}

/// 配对二维码多格式解析器(对标 Android PairingQrCodec)。
/// 支持:纯 6 位短码 / `host:port` 直连 / JSON(v1/v2/v3)/ `xcagi://...` 深链。
enum PairingQrCodec {
    static func parse(_ raw: String) -> PairingQrPayload? {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty || text.lowercased().contains("auth-qr") { return nil }

        // 纯 6 位数字 → 配对短码
        if text.count == 6, text.allSatisfy({ $0.isNumber }) {
            return PairingQrPayload(token: text, version: 2)
        }
        if text.hasPrefix("{") { return parseJson(text) }
        if text.lowercased().hasPrefix("xcagi://") { return parseDeepLink(text) }
        // 纯文本 host:port 直连(Android repo 侧也接受;此处统一在 codec 内处理)
        if let hp = parsePlainHostPort(text) { return hp }
        return nil
    }

    private static func parsePlainHostPort(_ text: String) -> PairingQrPayload? {
        let cleaned = text
            .replacingOccurrences(of: "http://", with: "")
            .replacingOccurrences(of: "https://", with: "")
            .split(separator: "/").first.map(String.init) ?? text
        guard cleaned.contains(":") else { return nil }
        let parts = cleaned.split(separator: ":", maxSplits: 1).map(String.init)
        guard parts.count == 2 else { return nil }
        let host = parts[0].trimmingCharacters(in: .whitespaces)
        guard let port = Int(parts[1].trimmingCharacters(in: .whitespaces)), (1...65535).contains(port), !host.isEmpty else { return nil }
        return PairingQrPayload(host: host, port: port, version: 1)
    }

    private static func parseJson(_ text: String) -> PairingQrPayload? {
        guard let data = text.data(using: .utf8),
              let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return nil }
        let v = intValue(obj["v"]) ?? 1
        let kind = (obj["kind"] as? String ?? "").lowercased()
        let relayId = firstNonBlank(obj["relay_id"], obj["relayId"])
        let relayBaseUrl = firstNonBlank(obj["relay_base_url"], obj["relayBaseUrl"])

        // v3:云中继绑定
        if v >= 3 || kind.contains("relay") {
            let t = firstNonBlank(obj["t"], obj["code"], obj["shortCode"], obj["short_code"], obj["token"])
            if !relayId.isEmpty && !t.isEmpty {
                return PairingQrPayload(token: t, relayId: relayId, relayBaseUrl: relayBaseUrl, version: 3)
            }
        }

        let apiBaseUrl = firstNonBlank(obj["api_base_url"], obj["base_url"], obj["apiBaseUrl"])
        let fromBase = parseApiBase(apiBaseUrl)
        var host = normalizeHost(stringValue(obj["host"]))
        if host.isEmpty { host = fromBase.0 }
        let port = (parsePort(obj, host: host)).nonZeroOr(fromBase.1)
        let bareHost = host.split(separator: ":").first.map(String.init) ?? host
        let hasHostPort = !bareHost.isEmpty && (1...65535).contains(port)
        let nonce = stringValue(obj["nonce"])

        // v2:短码优先,兼容带 host/port/nonce 直连兜底
        if v >= 2 || kind.contains("pairing") {
            let t = firstNonBlank(obj["t"], obj["code"], obj["shortCode"], obj["short_code"], obj["token"])
            if !t.isEmpty {
                return PairingQrPayload(host: hasHostPort ? bareHost : "", port: hasHostPort ? port : 0,
                                        nonce: nonce, token: t, apiBaseUrl: apiBaseUrl, version: 2)
            }
            if !nonce.isEmpty {
                return PairingQrPayload(host: hasHostPort ? bareHost : "", port: hasHostPort ? port : 0,
                                        nonce: nonce, token: nonce, apiBaseUrl: apiBaseUrl, version: 2)
            }
            return nil
        }

        // v1:host:port:nonce
        if nonce.count >= 8 && hasHostPort {
            return PairingQrPayload(host: bareHost, port: port, nonce: nonce, version: 1)
        }
        return nil
    }

    private static func parseDeepLink(_ text: String) -> PairingQrPayload? {
        guard let comps = URLComponents(string: text) else { return nil }
        let route = "\(comps.host ?? "")/\(comps.path)"
        guard route.lowercased().contains("pair") else { return nil }
        var params: [String: String] = [:]
        for item in comps.queryItems ?? [] { params[item.name] = item.value?.removingPercentEncoding ?? item.value }

        let nonce = params["nonce"] ?? ""
        let code = firstNonBlank(params["code"], params["shortCode"], params["short_code"], params["token"])
        let apiBaseUrl = firstNonBlank(params["api_base_url"], params["api_base"], params["base_url"])
        let relayId = firstNonBlank(params["relay_id"], params["relayId"])
        let relayBaseUrl = firstNonBlank(params["relay_base_url"], params["relayBaseUrl"])

        if !relayId.isEmpty && !code.isEmpty {
            return PairingQrPayload(token: code, relayId: relayId, relayBaseUrl: relayBaseUrl, version: 3)
        }
        let fromBase = parseApiBase(apiBaseUrl)
        var host = normalizeHost(params["host"] ?? "")
        if host.isEmpty { host = fromBase.0 }
        let port = (Int(params["port"] ?? "") ?? 0).nonZeroOr(fromBase.1)
        let bareHost = host.split(separator: ":").first.map(String.init) ?? host
        if !code.isEmpty {
            return PairingQrPayload(host: bareHost, port: (1...65535).contains(port) ? port : 0,
                                    nonce: nonce, token: code, apiBaseUrl: apiBaseUrl, version: 2)
        }
        if nonce.count >= 8 && !bareHost.isEmpty && (1...65535).contains(port) {
            return PairingQrPayload(host: bareHost, port: port, nonce: nonce, apiBaseUrl: apiBaseUrl, version: 1)
        }
        return nil
    }

    static func formatHostPort(host: String, port: Int) -> String {
        let bare = host
            .replacingOccurrences(of: "http://", with: "")
            .replacingOccurrences(of: "https://", with: "")
            .split(separator: "/").first.map(String.init) ?? host
        let h = bare.split(separator: ":").first.map(String.init) ?? bare
        return "\(h.trimmingCharacters(in: .whitespaces)):\(port)"
    }

    // 内部工具
    private static func normalizeHost(_ host: String) -> String {
        host.replacingOccurrences(of: "http://", with: "")
            .replacingOccurrences(of: "https://", with: "")
            .trimmingCharacters(in: CharacterSet(charactersIn: "/ "))
    }

    private static func firstNonBlank(_ values: Any?...) -> String {
        for v in values {
            let s = stringValue(v)
            if !s.isEmpty { return s }
        }
        return ""
    }

    private static func stringValue(_ value: Any?) -> String {
        guard let value else { return "" }
        if let s = value as? String { return s.trimmingCharacters(in: .whitespaces) }
        if let n = value as? NSNumber { return n.stringValue }
        return ""
    }

    private static func intValue(_ value: Any?) -> Int? {
        if let n = value as? Int { return n }
        if let n = value as? NSNumber { return n.intValue }
        if let s = value as? String { return Int(s) }
        return nil
    }

    private static func parseApiBase(_ apiBaseUrl: String) -> (String, Int) {
        if apiBaseUrl.isEmpty { return ("", 0) }
        let normalized = apiBaseUrl.contains("://") ? apiBaseUrl : "http://\(apiBaseUrl)"
        guard let comps = URLComponents(string: normalized) else { return ("", 0) }
        let host = comps.host ?? ""
        let port: Int
        if let p = comps.port, (1...65535).contains(p) { port = p }
        else { port = (comps.scheme?.lowercased() == "https") ? 443 : (comps.scheme?.lowercased() == "http" ? 80 : 0) }
        return (host, port)
    }

    private static func parsePort(_ obj: [String: Any], host: String) -> Int {
        if let p = intValue(obj["port"]) { return p }
        if host.contains(":"), let last = host.split(separator: ":").last, let p = Int(last) { return p }
        return 0
    }
}

private extension Int {
    /// 自身非 0 时返回自身,否则返回 fallback。
    func nonZeroOr(_ fallback: Int) -> Int { self != 0 ? self : fallback }
}

/// SSE 对话上下文里的一条历史消息(对标桌面端 useChatRequest.ts 的 recent_messages 项)。
/// 编码为 {"role": ..., "content": ...},content 截断到 500 字与 Android 一致。
struct ChatContextMessage: Codable, Hashable {
    var role: String
    var content: String

    init(role: String, content: String) {
        self.role = role.isEmpty ? "user" : role
        self.content = String(content.prefix(500))
    }

    var asDict: [String: String] { ["role": role, "content": content] }
}
