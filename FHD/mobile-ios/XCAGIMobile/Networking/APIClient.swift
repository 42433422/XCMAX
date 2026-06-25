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

    /// 企业账号自助注册(对标 Android `RegisterScreen` → FHD `api/auth/register`)。
    @discardableResult
    func register(username: String, password: String, email: String) async throws -> Bool {
        let body: [String: Any] = [
            "username": username.trimmingCharacters(in: .whitespaces),
            "password": password,
            "email": email.trimmingCharacters(in: .whitespaces),
        ]
        let resp = try await raw(APIEndpoints.authRegister, method: .post, body: body, of: SimpleResult.self)
        if resp.success == false { throw APIError.business(resp.message ?? "注册失败") }
        return true
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

    /// 专属客服资料(对标 Android cs/info → CsInfoDto:cs_name/cs_online/cs_avatar/cs_available)。
    func csInfo() async throws -> CsInfo {
        try await envelope(APIEndpoints.csInfo, of: CsInfo.self)
            ?? CsInfo(csAvailable: true, csName: "专属客服", csOnline: true)
    }

    /// 客服历史消息(对标 Android cs/messages GET;映射 sender/body → role/text)。
    /// `since` 可选(增量拉取)。
    func csMessages(since: String? = nil) async throws -> [CsMessageDto] {
        var path = APIEndpoints.csMessages
        if let since, !since.isEmpty {
            path += "?since=\(since.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? since)"
        }
        let data = try await envelope(path, of: CsMessagesListData.self)
        return (data?.messages ?? []).map { item in
            let role = (item.sender == "user") ? "user" : "assistant"
            return CsMessageDto(role: role, text: item.body)
        }
    }

    /// 发送客服消息(对标 Android cs/messages POST,body={"body": text})。
    /// 返回 reply 文本,套用 ChatResponseData 以兼容现有 UI 的 `bestReply`。
    func csSend(message: String) async throws -> ChatResponseData {
        let body: [String: Any] = ["body": message]
        let resp = try await envelope(APIEndpoints.csMessages, method: .post, body: body, of: CsMessageResponseData.self)
        return ChatResponseData(success: true, reply: resp?.reply, message: nil, data: nil)
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

    /// 交流圈发帖(对标 Android createAiCirclePost,POST circle/posts,body={"body": text})。
    func createPost(body: String) async throws {
        let text = body.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { throw APIError.business("内容不能为空") }
        _ = try await envelope(APIEndpoints.circlePosts, method: .post, body: ["body": text], of: EmptyData.self)
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

    /// 建群并一次性带入成员(对标 Android 建群多选:先 createAiGroup 再逐个 addAiGroupMember)。
    /// 后端无原子建群带成员接口,故串行 N+1 调用,返回最终 group。
    @discardableResult
    func createGroupWithMembers(name: String, members: [AiGroupMemberDraft]) async throws -> AiGroup {
        var group = try await createAiGroup(name: name)
        guard let gid = group.id, !gid.isEmpty else { return group }
        for m in members {
            if let updated = try? await addAiGroupMember(
                groupId: gid, employeeId: m.employeeId, modId: m.modId,
                name: m.name, avatar: m.avatar, summary: m.summary
            ) {
                group = updated
            }
        }
        return group
    }

    /// 群增成员(POST ai-groups/{id}/members)。
    @discardableResult
    func addAiGroupMember(groupId: String, employeeId: String, modId: String,
                          name: String, avatar: String, summary: String) async throws -> AiGroup {
        let body: [String: Any] = [
            "employee_id": employeeId, "mod_id": modId,
            "name": name, "avatar": avatar, "summary": summary,
        ]
        let data = try await envelope(APIEndpoints.path(APIEndpoints.aiGroupMembers, id: groupId),
                                      method: .post, body: body, of: AiGroupWrap.self)
        return data?.group ?? AiGroup()
    }

    /// 群删成员(DELETE ai-groups/{id}/members/{employeeId})。
    @discardableResult
    func removeAiGroupMember(groupId: String, employeeId: String) async throws -> AiGroup {
        let path = Self.aiGroupMember
            .replacingOccurrences(of: "{groupId}", with: groupId)
            .replacingOccurrences(of: "{employeeId}", with: employeeId)
        let data = try await envelope(path, method: .delete, of: AiGroupWrap.self)
        return data?.group ?? AiGroup()
    }

    /// 置顶切换(PUT ai-groups/{id}/pin)。
    @discardableResult
    func toggleAiGroupPin(groupId: String) async throws -> AiGroup {
        let data = try await envelope(APIEndpoints.path(Self.aiGroupPin, id: groupId), method: .put, of: AiGroupWrap.self)
        return data?.group ?? AiGroup()
    }

    /// 标记未读(POST ai-groups/{id}/mark-unread)。
    @discardableResult
    func markAiGroupUnread(groupId: String) async throws -> AiGroup {
        let data = try await envelope(APIEndpoints.path(APIEndpoints.aiGroupMarkUnread, id: groupId), method: .post, of: AiGroupWrap.self)
        return data?.group ?? AiGroup()
    }

    /// 关注切换(PUT ai-groups/{id}/followed)。
    @discardableResult
    func toggleAiGroupFollowed(groupId: String) async throws -> AiGroup {
        let data = try await envelope(APIEndpoints.path(Self.aiGroupFollowed, id: groupId), method: .put, of: AiGroupWrap.self)
        return data?.group ?? AiGroup()
    }

    /// 隐藏切换(PUT ai-groups/{id}/hidden)。
    @discardableResult
    func toggleAiGroupHidden(groupId: String) async throws -> AiGroup {
        let data = try await envelope(APIEndpoints.path(Self.aiGroupHidden, id: groupId), method: .put, of: AiGroupWrap.self)
        return data?.group ?? AiGroup()
    }

    /// 删除群(DELETE ai-groups/{id})。
    func deleteAiGroup(groupId: String) async throws {
        _ = try await envelope(APIEndpoints.path(Self.aiGroupDelete, id: groupId), method: .delete, of: EmptyData.self)
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

    /// 回复服务桥工单(对标 Android `BridgeScreen`)。PUT,status ∈ pending/processing/resolved/closed。
    func serviceBridgeRespond(id: Int, response: String, status: String = "resolved") async throws {
        let body: [String: Any] = ["response": response, "responded_by": "ios", "status": status]
        _ = try await envelope(APIEndpoints.path(APIEndpoints.serviceBridgeRespond, id: String(id)),
                               method: .put, body: body, of: EmptyData.self)
    }

    func walletBalance() async throws -> WalletBalanceData {
        try await envelope(APIEndpoints.walletBalance, of: WalletBalanceData.self) ?? WalletBalanceData()
    }

    /// 企业库存(对标 Android inventoryItems,GET api/inventory/items;非信封,兼容 {data:[]}/{items:[]})。
    func inventoryItems() async throws -> [InventoryItem] {
        try await raw(Self.inventoryItems, of: InventoryItemsData.self).resolved
    }

    // MARK: - IM 即时通讯(顶层非信封,用 raw 解码)

    func imConversations() async throws -> [ImConversation] {
        try await raw(APIEndpoints.imConversations, of: ImConversationsResponse.self).conversations ?? []
    }

    func imCreateDirect(peerUserId: Int) async throws -> ImConversation? {
        try await raw(APIEndpoints.imDirect, method: .post, body: ["peer_user_id": peerUserId], of: ImDirectResponse.self).conversation
    }

    func imMessages(conversationId: Int, limit: Int = 50) async throws -> [ImMessageDto] {
        try await raw("\(APIEndpoints.path(APIEndpoints.imMessages, id: String(conversationId)))?limit=\(limit)",
                      of: ImMessagesResponse.self).messages ?? []
    }

    @discardableResult
    func imSend(conversationId: Int, body: String) async throws -> ImMessageDto? {
        try await raw(APIEndpoints.path(APIEndpoints.imMessages, id: String(conversationId)),
                      method: .post, body: ["body": body], of: ImSendResponse.self).message
    }

    func imMarkRead(conversationId: Int, lastMessageId: Int) async throws {
        _ = try await raw(APIEndpoints.path(APIEndpoints.imRead, id: String(conversationId)),
                          method: .post, body: ["last_message_id": lastMessageId], of: EmptyData.self)
    }

    // MARK: - 账号注销 / 手机号验证码登录(对标 Android ModstoreApi + 手机登录)

    /// 注销账号(App Store 硬要求;对标 Android deleteAccount,POST api/auth/account/delete)。
    /// 走 MODstore 端点;调用方负责注销成功后清本地会话。
    func deleteAccount(password: String) async throws {
        let body: [String: Any] = ["password": password]
        _ = try await raw(Self.accountDelete, method: .post, body: body, of: SimpleResult.self, baseOverride: AppConfig.modstoreBaseURL)
    }

    /// 发送手机验证码(对标 Android sendPhoneCode,POST api/auth/send-phone-code)。
    func sendCode(phone: String) async throws {
        let p = phone.trimmingCharacters(in: .whitespaces)
        _ = try await raw(Self.sendPhoneCode, method: .post, body: ["phone": p], of: SimpleResult.self, baseOverride: AppConfig.modstoreBaseURL)
    }

    /// 手机号 + 验证码登录(对标 Android mobileLoginWithPhone,走 FHD v1 端点)。
    func loginPhone(phone: String, code: String, accountKind: String = "enterprise") async throws -> MobileLoginData {
        let body: [String: Any] = [
            "phone": phone.trimmingCharacters(in: .whitespaces),
            "code": code.trimmingCharacters(in: .whitespaces),
            "account_kind": accountKind.isEmpty ? "enterprise" : accountKind,
        ]
        return try await envelope(APIEndpoints.authLoginWithPhoneCode, method: .post, body: body, of: MobileLoginData.self) ?? MobileLoginData()
    }

    // MARK: - 桌面工具动态菜单 / 市场 MOD Web URL(item ⑨)

    /// 侧栏工具菜单(对标 Android fetchNavMenu,GET api/mobile/v1/nav-menu;配对后与桌面端侧栏对齐)。
    func loadNavMenu() async throws -> NavMenuData {
        try await envelope(Self.navMenu, of: NavMenuData.self) ?? NavMenuData()
    }

    /// 解析市场 MOD 的 WebView 地址(对标 Android modWebUrl 的 online/offline 分支)。
    /// - `online`: 已连电脑(局域网/中继)→ `{fhdBase}mod/{id}/`
    /// - `offline`: 纯云端 → MODstore workbench `/workbench/mod/{id}?client=ios`
    /// `online` 由调用方(SessionManager/页面)按健康检查结果传入。
    func modWebUrl(modId: String, online: Bool) -> String {
        if online {
            return "\(baseURL)mod/\(modId)/"
        }
        let base = AppConfig.modstoreBaseURL.hasSuffix("/") ? String(AppConfig.modstoreBaseURL.dropLast()) : AppConfig.modstoreBaseURL
        return "\(base)/workbench/mod/\(modId)?client=ios"
    }

    // MARK: - 超级员工开发(派工 + 轮询 + git 操作;对标 Android XcagiRepository)

    /// 提交一条超级员工消息(codex / claude),返回派工回包(含 request_id / task_id / 即时直答)。
    /// `tool` ∈ "codex" | "claude"。context 与桌面端一致(source/client_surface/mode)。
    func postSuperEmployeeMessage(tool: String, message: String) async throws -> SuperEmployeeDispatchData {
        let path = (tool == "claude") ? Self.claudeSuperEmployeeMessages : Self.codexSuperEmployeeMessages
        let body: [String: Any] = [
            "body": message,
            "message": message,
            "context": ["source": "mobile_chat", "client_surface": "mobile", "mode": "code"],
        ]
        return try await envelope(path, method: .post, body: body, of: SuperEmployeeDispatchData.self) ?? SuperEmployeeDispatchData()
    }

    /// 拉取超级员工历史消息(codex / claude)。
    func superEmployeeMessages(tool: String, limit: Int = 80) async throws -> [SuperEmployeeMessage] {
        let path = (tool == "claude") ? Self.claudeSuperEmployeeMessages : Self.codexSuperEmployeeMessages
        let data = try await envelope("\(path)?limit=\(limit)", of: SuperEmployeeMessagesData.self)
        return data?.messages ?? []
    }

    /// 创建中继任务(对标 Android relayCreateTask)。kind 形如 codex.invoke / claude.invoke / git.merge。
    @discardableResult
    func relayCreateTask(relayId: String, kind: String, payload: [String: Any]) async throws -> RelayTask {
        let body: [String: Any] = ["relay_id": relayId, "kind": kind, "payload": payload]
        let data = try await envelope(APIEndpoints.relayTasks, method: .post, body: body, of: RelayTaskData.self)
        return data?.task ?? RelayTask()
    }

    /// 查询中继任务状态(对标 Android relayTaskStatus)。
    func relayTaskStatus(taskId: String) async throws -> RelayTask {
        let data = try await envelope(APIEndpoints.path(APIEndpoints.relayTaskDetail, id: taskId), of: RelayTaskData.self)
        return data?.task ?? RelayTask()
    }

    /// git 操作经中继到电脑执行端(对标 Android streamRelayGitOp)。
    /// `op` ∈ "git.merge" | "git.diff" | "git.discard"。返回执行端回写文本;轮询直到终态。
    func relayGitOp(relayId: String, branch: String, op: String) async throws -> String {
        let task = try await relayCreateTask(
            relayId: relayId, kind: op,
            payload: ["branch": branch, "context": ["source": "mobile_chat", "client_surface": "mobile"]]
        )
        guard let taskId = task.taskId, !taskId.isEmpty else { throw APIError.business("操作缺少 task_id") }
        // 轮询(2s 间隔,最多 150 次,与 Android pollRelayTask 一致)。
        for _ in 0..<150 {
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            let cur = try await relayTaskStatus(taskId: taskId)
            switch cur.status {
            case "done", "completed":
                return cur.result?.reply ?? "电脑执行端已完成任务。"
            case "failed", "blocked", "cancelled":
                throw APIError.business(cur.result?.error ?? cur.result?.reply ?? "电脑执行端执行失败")
            default:
                continue
            }
        }
        throw APIError.business("电脑执行端暂未回写结果,任务仍在后台运行。")
    }

    /// 便捷:git 合并 / 差异 / 丢弃(item ⑧)。
    func gitMerge(relayId: String, branch: String) async throws -> String { try await relayGitOp(relayId: relayId, branch: branch, op: "git.merge") }
    func gitDiff(relayId: String, branch: String) async throws -> String { try await relayGitOp(relayId: relayId, branch: branch, op: "git.diff") }
    func gitDiscard(relayId: String, branch: String) async throws -> String { try await relayGitOp(relayId: relayId, branch: branch, op: "git.discard") }

    // MARK: - SSE 流式对话(补全请求体 + 单次重试;item ①)

    /// SSE 事件帧(token / done / error)。
    enum ChatStreamChunk {
        case token(String)
        case done(String)
    }

    /// 流式对话(对标 Android SseChatClient.streamChat):
    /// 请求体补 source / mode / user_id / context.recent_messages / industry;
    /// 连接建立失败(HTTP 5xx 或网络异常)时单次重试(一旦开始收 token 即不重试)。
    /// 以 `AsyncThrowingStream` 顺序产出,消费方按序更新 UI。
    func streamChat(message: String,
                    userId: Int = 0,
                    source: String = "pro",
                    mode: String = "professional",
                    recentMessages: [ChatContextMessage] = [],
                    industry: String? = nil) -> AsyncThrowingStream<ChatStreamChunk, Error> {
        // 组装请求体(与桌面端 useChatRequest.ts 对齐)。
        var bodyMap: [String: Any] = ["message": message, "source": source, "mode": mode]
        if userId > 0 { bodyMap["user_id"] = String(userId) }
        var contextMap: [String: Any] = [:]
        if !recentMessages.isEmpty { contextMap["recent_messages"] = recentMessages.map { $0.asDict } }
        if let industry, !industry.isEmpty { contextMap["industry"] = industry }
        if !contextMap.isEmpty { bodyMap["context"] = contextMap }

        let token = accessToken.trimmingCharacters(in: .whitespaces)
        let uid = userId
        let url = resolve(APIEndpoints.aiChatStream)
        let streamSession = session

        return AsyncThrowingStream { continuation in
            let work = Task {
                let maxAttempts = 2   // 首发 + 单次重试
                var lastError: Error = APIError.transport("连接失败")
                for attempt in 1...maxAttempts {
                    var streamingStarted = false
                    do {
                        guard let reqURL = URL(string: url),
                              let httpBody = try? JSONSerialization.data(withJSONObject: bodyMap) else {
                            continuation.finish(throwing: APIError.invalidURL); return
                        }
                        var req = URLRequest(url: reqURL)
                        req.httpMethod = HTTPMethod.post.rawValue
                        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
                        req.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                        req.setValue("ios", forHTTPHeaderField: "X-XCAGI-Client")
                        if !token.isEmpty { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
                        if uid > 0 { req.setValue(String(uid), forHTTPHeaderField: "X-User-ID") }
                        req.httpBody = httpBody

                        let (bytes, response) = try await streamSession.bytes(for: req)
                        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
                        if status >= 400 {
                            lastError = APIError.http(status: status, message: "")
                            // 5xx 瞬时故障可重试;4xx 不重试。
                            if (500...599).contains(status) && attempt < maxAttempts {
                                try? await Task.sleep(nanoseconds: UInt64(800_000_000 * attempt))
                                continue
                            }
                            continuation.finish(throwing: lastError); return
                        }
                        var buf = ""
                        for try await line in bytes.lines {
                            if Task.isCancelled { continuation.finish(); return }
                            let trimmed = line.trimmingCharacters(in: .whitespaces)
                            guard trimmed.hasPrefix("data:") else { continue }
                            let payload = String(trimmed.dropFirst(5)).trimmingCharacters(in: .whitespaces)
                            if payload.isEmpty || payload == "[DONE]" { continue }
                            guard let event = Self.decodeSSE(payload) else { continue }
                            switch event.type ?? "" {
                            case "token":
                                streamingStarted = true
                                let t = event.text ?? ""
                                if !t.isEmpty { buf += t; continuation.yield(.token(t)) }
                            case "done":
                                let final = Self.extractSSEReply(event.result)
                                continuation.yield(.done(final.isEmpty ? buf : final))
                                continuation.finish(); return
                            case "error":
                                let msg = event.message ?? "流式对话失败"
                                if !streamingStarted && attempt < maxAttempts && Self.isRetryableUpstream(msg) {
                                    lastError = APIError.business(msg)
                                    try? await Task.sleep(nanoseconds: UInt64(800_000_000 * attempt))
                                    streamingStarted = false
                                    break   // 跳出 for-line 循环 → 进入下一 attempt
                                }
                                continuation.finish(throwing: APIError.business(msg)); return
                            default:
                                continue
                            }
                        }
                        if streamingStarted {
                            continuation.yield(.done(buf))
                            continuation.finish(); return
                        }
                        // 未收到任何 token 且循环自然结束:若可重试则重试,否则结束。
                        if attempt < maxAttempts { continue }
                        continuation.yield(.done(buf))
                        continuation.finish(); return
                    } catch {
                        lastError = APIError.transport(error.localizedDescription)
                        if attempt < maxAttempts {
                            try? await Task.sleep(nanoseconds: UInt64(800_000_000 * attempt))
                            continue
                        }
                        continuation.finish(throwing: lastError); return
                    }
                }
                continuation.finish(throwing: lastError)
            }
            continuation.onTermination = { _ in work.cancel() }
        }
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

    /// 非信封请求:直接解码为 T(用于 ai/chat、inventory 等)。
    /// `baseOverride` 非空时改用指定基址(如 MODstore 注销 / 验证码端点)。
    private func raw<T: Decodable>(_ path: String,
                                   method: HTTPMethod = .get,
                                   body: [String: Any]? = nil,
                                   of type: T.Type,
                                   baseOverride: String? = nil) async throws -> T {
        let resolved = baseOverride.map { Self.resolve($0, path: path) } ?? resolve(path)
        guard let url = URL(string: resolved) else { throw APIError.invalidURL }

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

    /// 用指定基址拼接路径(供 baseOverride 走 MODstore 等非默认基址)。
    private static func resolve(_ base: String, path: String) -> String {
        let normalizedBase = normalize(base)
        let cleaned = path.hasPrefix("/") ? String(path.dropFirst()) : path
        return normalizedBase + cleaned
    }

    // MARK: - 本文件私有端点常量(APIEndpoints 未覆盖的;不改共享端点表)

    // AI 群聊扩展(用 {id} 占位,配合 APIEndpoints.path)
    static let aiGroupPin = "\(APIEndpoints.base)/ai-groups/{id}/pin"
    static let aiGroupFollowed = "\(APIEndpoints.base)/ai-groups/{id}/followed"
    static let aiGroupHidden = "\(APIEndpoints.base)/ai-groups/{id}/hidden"
    static let aiGroupDelete = "\(APIEndpoints.base)/ai-groups/{id}"
    // 删成员需双占位 {groupId}/{employeeId}(由调用处自行替换)
    static let aiGroupMember = "\(APIEndpoints.base)/ai-groups/{groupId}/members/{employeeId}"
    // 桌面工具菜单
    static let navMenu = "\(APIEndpoints.base)/nav-menu"
    // 超级员工开发(管理端 codex / claude)
    static let codexSuperEmployeeMessages = "\(APIEndpoints.base)/admin/codex-super-employee/messages"
    static let claudeSuperEmployeeMessages = "\(APIEndpoints.base)/admin/claude-super-employee/messages"
    // 企业库存(非 v1)
    static let inventoryItems = "api/inventory/items"
    // MODstore 账号(注销 / 验证码,走 modstoreBaseURL)
    static let accountDelete = "api/auth/account/delete"
    static let sendPhoneCode = "api/auth/send-phone-code"

    // MARK: - SSE 帧解析(供 streamChat 使用,对标 SSEChatClient)

    private struct SSEEvent: Decodable {
        var type: String?
        var text: String?
        var message: String?
        var result: SSEResult?
    }
    private struct SSEResult: Decodable {
        var response: String?
        var reply: String?
        var message: String?
        var data: SSEResultData?
    }
    private struct SSEResultData: Decodable {
        var reply: String?
        var content: String?
        var message: String?
    }

    private static func decodeSSE(_ json: String) -> SSEEvent? {
        guard let data = json.data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode(SSEEvent.self, from: data)
    }

    private static func extractSSEReply(_ result: SSEResult?) -> String {
        guard let result else { return "" }
        if let r = result.reply, !r.isEmpty { return r }
        if let r = result.response, !r.isEmpty { return r }
        if let r = result.data?.reply, !r.isEmpty { return r }
        if let r = result.data?.content, !r.isEmpty { return r }
        if let r = result.message, !r.isEmpty { return r }
        return ""
    }

    /// 判断后端 LLM 上游错误是否值得重试(对标 Android isRetryableUpstreamError)。
    private static func isRetryableUpstream(_ msg: String) -> Bool {
        let lower = msg.lowercased()
        return lower.contains("_ssl.c") || lower.contains("handshake") ||
            lower.contains("timeout") || lower.contains("timed out") ||
            lower.contains("upstream") || lower.contains("502") ||
            lower.contains("504") || lower.contains("上游")
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
