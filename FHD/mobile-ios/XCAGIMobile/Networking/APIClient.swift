import Foundation

/// 客服消息 DTO(后端 cs/messages 返回 {role,text})。
struct CsMessageDto: Decodable {
    var role: String?
    var text: String?
}

/// REST 客户端(对标 mobile-harmony `MobileApiClient.ets` / Android `XcagiApi`)。
///
/// 统一信封解包、Bearer 鉴权、snake_case 解码、超时与错误归一。
/// 线程安全:`baseURL` / `accessToken` 仅由 `SessionManager`(@MainActor)写入。
final class APIClient: @unchecked Sendable {
    private(set) var baseURL: String
    private var accessToken: String

    private let session: URLSession
    private let decoder: JSONDecoder

    init(baseURL: String, accessToken: String = "") {
        self.baseURL = APIClient.normalize(baseURL)
        self.accessToken = accessToken

        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 60
        config.waitsForConnectivity = true
        self.session = URLSession(configuration: config)

        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        self.decoder = d
    }

    func setBaseURL(_ url: String) { baseURL = APIClient.normalize(url) }
    func setAccessToken(_ token: String) { accessToken = token }

    // MARK: - 认证 / 用户 / 首页

    func login(username: String, password: String, accountKind: String = "admin") async throws -> MobileLoginData {
        let kind = accountKind.trimmingCharacters(in: .whitespaces)
        let body: [String: Any] = [
            "username": username.trimmingCharacters(in: .whitespaces),
            "password": password,
            "account_kind": kind.isEmpty ? "admin" : kind,
        ]
        return try await envelope(APIEndpoints.authLogin, method: .post, body: body, of: MobileLoginData.self) ?? MobileLoginData()
    }

    func me() async throws -> MobileMeData {
        try await envelope(APIEndpoints.me, of: MobileMeData.self) ?? MobileMeData()
    }

    func home() async throws -> MobileHomeData {
        try await envelope(APIEndpoints.home, of: MobileHomeData.self) ?? MobileHomeData()
    }

    func mods() async throws -> MobileModsData {
        try await envelope(APIEndpoints.mods, of: MobileModsData.self) ?? MobileModsData()
    }

    func pairingExchange(code: String) async throws -> PairingExchangeData {
        let body: [String: Any] = ["code": code.trimmingCharacters(in: .whitespaces)]
        return try await envelope(APIEndpoints.pairingExchange, method: .post, body: body, of: PairingExchangeData.self) ?? PairingExchangeData()
    }

    // MARK: - 普通对话(非流式回退)/ 客服

    func chat(message: String, sessionId: String) async throws -> ChatResponseData {
        let body: [String: Any] = ["message": message, "session_id": sessionId]
        return try await raw(APIEndpoints.aiChat, method: .post, body: body, of: ChatResponseData.self)
    }

    func csInfo() async throws -> CsInfo {
        try await envelope(APIEndpoints.csInfo, of: CsInfo.self)
            ?? CsInfo(title: "专属客服", subtitle: "在线", online: true)
    }

    func csMessages() async throws -> [CsMessageDto] {
        try await envelope(APIEndpoints.csMessages, of: [CsMessageDto].self) ?? []
    }

    func csSend(message: String) async throws -> ChatResponseData {
        let body: [String: Any] = ["message": message, "session_id": "cs"]
        return try await raw(APIEndpoints.csChat, method: .post, body: body, of: ChatResponseData.self)
    }

    func contactsFixed() async throws -> MobileFixedContactsData {
        try await envelope(APIEndpoints.contactsFixed, of: MobileFixedContactsData.self) ?? MobileFixedContactsData()
    }

    // MARK: - 审批流

    func approvals() async throws -> [ApprovalItem] {
        try await envelope(APIEndpoints.approvalRequests, of: [ApprovalItem].self) ?? []
    }

    func approvalDetail(id: String) async throws -> ApprovalDetail {
        try await envelope(APIEndpoints.path(APIEndpoints.approvalDetail, id: id), of: ApprovalDetail.self) ?? ApprovalDetail()
    }

    func approve(id: String, opinion: String) async throws {
        _ = try await envelope(APIEndpoints.path(APIEndpoints.approvalApprove, id: id),
                               method: .post, body: ["opinion": opinion], of: EmptyData.self)
    }

    func reject(id: String, reason: String) async throws {
        _ = try await envelope(APIEndpoints.path(APIEndpoints.approvalReject, id: id),
                               method: .post, body: ["opinion": reason], of: EmptyData.self)
    }

    // MARK: - AI 圈子(朋友圈)

    func circlePosts() async throws -> [CirclePost] {
        let data = try await envelope(APIEndpoints.circlePosts, of: CirclePostsData.self)
        return data?.items ?? []
    }

    func circleToggleLike(postId: Int) async throws {
        _ = try await envelope(APIEndpoints.path(APIEndpoints.circlePostLike, id: String(postId)),
                               method: .post, of: EmptyData.self)
    }

    func circleAddComment(postId: Int, body: String) async throws {
        _ = try await envelope(APIEndpoints.path(APIEndpoints.circlePostComments, id: String(postId)),
                               method: .post, body: ["body": body], of: EmptyData.self)
    }

    // MARK: - AI 群聊

    func aiGroups() async throws -> [AiGroup] {
        let data = try await envelope(APIEndpoints.aiGroups, of: AiGroupsData.self)
        return data?.groups ?? []
    }

    func createAiGroup(name: String) async throws -> AiGroup {
        let data = try await envelope(APIEndpoints.aiGroups, method: .post,
                                      body: ["name": name.trimmingCharacters(in: .whitespaces)],
                                      of: AiGroupCreateData.self)
        return data?.group ?? AiGroup()
    }

    func aiGroupMessages(groupId: String) async throws -> [AiGroupMessage] {
        let data = try await envelope(APIEndpoints.path(APIEndpoints.aiGroupMessages, id: groupId), of: AiGroupMessagesData.self)
        return data?.messages ?? []
    }

    func sendAiGroupMessage(groupId: String, message: String, senderName: String, mentions: [String]) async throws -> AiGroupPostResult {
        let body: [String: Any] = [
            "message": message,
            "sender_name": senderName.isEmpty ? "我" : senderName,
            "mentions": mentions,
        ]
        return try await envelope(APIEndpoints.path(APIEndpoints.aiGroupMessages, id: groupId), method: .post, body: body, of: AiGroupPostResult.self) ?? AiGroupPostResult()
    }

    func markAiGroupRead(groupId: String) async throws {
        _ = try await envelope(APIEndpoints.path(APIEndpoints.aiGroupMarkRead, id: groupId), method: .post, of: EmptyData.self)
    }

    // MARK: - 企业模块

    func customers(page: Int = 1) async throws -> CustomersData {
        try await envelope("\(APIEndpoints.customers)?page=\(page)&per_page=20", of: CustomersData.self) ?? CustomersData()
    }

    func shipments(page: Int = 1) async throws -> ShipmentsData {
        try await envelope("\(APIEndpoints.shipments)?page=\(page)&per_page=20", of: ShipmentsData.self) ?? ShipmentsData()
    }

    func serviceBridgeRequests() async throws -> ServiceBridgeData {
        try await envelope("\(APIEndpoints.serviceBridgeRequests)?page=1&per_page=20", of: ServiceBridgeData.self) ?? ServiceBridgeData()
    }

    func walletBalance() async throws -> WalletBalanceData {
        try await envelope(APIEndpoints.walletBalance, of: WalletBalanceData.self) ?? WalletBalanceData()
    }

    // MARK: - 设备 / 推送注册

    func registerDevice(pushToken: String, platform: String = AppConfig.platform) async throws {
        let body: [String: Any] = [
            "fcm_token": pushToken,
            "push_provider": "apns",
            "push_token": pushToken,
            "product_sku": AppConfig.sku.rawValue,
            "device_label": "iOS",
            "platform": platform,
        ]
        _ = try await envelope(APIEndpoints.devicesRegister, method: .post, body: body, of: EmptyData.self)
    }

    // MARK: - 底层请求

    /// 解包 `MobileEnvelope<T>`,success==false 时抛 `.business`。
    private func envelope<T: Decodable>(_ path: String,
                                        method: HTTPMethod = .get,
                                        body: [String: Any]? = nil,
                                        of type: T.Type) async throws -> T? {
        let env = try await raw(path, method: method, body: body, of: MobileEnvelope<T>.self)
        if env.success == false {
            throw APIError.business(env.message ?? "请求失败")
        }
        return env.data
    }

    /// 非信封请求:直接解码为 T(用于 ai/chat、cs/chat 等)。
    private func raw<T: Decodable>(_ path: String,
                                   method: HTTPMethod = .get,
                                   body: [String: Any]? = nil,
                                   of type: T.Type) async throws -> T {
        guard let url = URL(string: resolve(path)) else { throw APIError.invalidURL }

        var req = URLRequest(url: url)
        req.httpMethod = method.rawValue
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        if !accessToken.trimmingCharacters(in: .whitespaces).isEmpty {
            req.setValue("Bearer \(accessToken.trimmingCharacters(in: .whitespaces))", forHTTPHeaderField: "Authorization")
        }
        if let body {
            req.httpBody = try JSONSerialization.data(withJSONObject: body, options: [])
        }

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: req)
        } catch {
            throw APIError.transport(error.localizedDescription)
        }

        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        if status >= 400 {
            throw APIError.http(status: status, message: APIClient.errorMessage(from: data))
        }
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw APIError.decoding(error.localizedDescription)
        }
    }

    private func resolve(_ path: String) -> String {
        let cleaned = path.hasPrefix("/") ? String(path.dropFirst()) : path
        return baseURL + cleaned
    }

    static func normalize(_ value: String) -> String {
        var url = value.trimmingCharacters(in: .whitespaces)
        if url.isEmpty { url = "http://127.0.0.1:5000/" }
        if !url.hasPrefix("http://") && !url.hasPrefix("https://") { url = "http://" + url }
        return url.hasSuffix("/") ? url : url + "/"
    }

    private static func errorMessage(from data: Data) -> String {
        guard
            let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let msg = obj["message"] as? String, !msg.isEmpty
        else { return "" }
        return msg
    }
}

/// 占位解码类型(用于无 data 返回体的接口)。
struct EmptyData: Decodable {}
