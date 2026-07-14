import SwiftUI

/// IM 即时通讯视图模型(全量对标 Android `ImMessengerScreen` + `ImRepository` + `ImWebSocketClient`)。
///
/// 关键对齐点:
/// - 本地持久化(LocalCache):每会话消息按 `im:<cid>` 持久化,冷启动秒出(对标 Android Room `ImMessageCacheEntity`)。
/// - 实时收发:REST 历史 + 发送 + WebSocket 实时接收(`type=message`),去重落库后投影。
/// - 已读上报时机:打开会话载入历史后上报一次;此后每当有新「对方」消息到达且视图处于活跃态时再次上报
///   (对标 Android「活跃会话有新消息即标已读」)。
/// - 已读回执处理:维护对端已读水位 `peerLastReadMessageId`,用于在「我」发出的消息上展示已读/已送达
///   (对标 Android `ImWsEvent.Read` → `ImReadStateEntity`;本端 WS 客户端仅转发 message 帧,
///   故对端已读水位以本地可观测信号推进,见 `updatePeerRead`)。
@MainActor
final class ImMessengerViewModel: ObservableObject {
    @Published var peerId = ""
    @Published var conversationId: Int?
    @Published var messages: [ImMessageDto] = []
    @Published var draft = ""
    @Published var status: IMWebSocketClient.Status = .idle
    @Published var error: String?
    @Published var opening = false
    /// 对端已读到的消息 id(用于「我」的消息已读态展示)。
    @Published var peerLastReadMessageId: Int = 0

    private var ws: IMWebSocketClient?
    private var myUserId: Int?
    private var localSeq = -1   // 本地回显消息的稳定(负数)id,不与服务端正数冲突
    /// 视图是否在前台(决定新消息到达时是否即时上报已读)。
    private var active = false

    var statusLabel: String {
        switch status {
        case .open: return "实时已连接"
        case .connecting: return "连接中…"
        case .reconnecting: return "重连中…"
        case .closed: return "已断开"
        case .idle: return "未连接"
        }
    }

    /// 本会话的本地缓存键(对标 Android 以 conversation_id 分桶)。
    private func cacheKey(_ cid: Int) -> String { "im:\(cid)" }

    // MARK: - 打开会话

    func open(session: SessionManager) async {
        guard let peer = Int(peerId.trimmingCharacters(in: .whitespaces)), peer > 0 else {
            error = "请输入有效的对方用户 ID"; return
        }
        error = nil
        opening = true
        defer { opening = false }
        // 我方 user id 优先取会话态,回退 me()(对标 Android sender_user_id<=0 判定本端)。
        if myUserId == nil {
            myUserId = session.userId > 0 ? session.userId : (try? await session.api.me())?.user?.id
        }
        do {
            guard let conv = try await session.api.imCreateDirect(peerUserId: peer), conv.idValue > 0 else {
                error = "无法创建会话"; return
            }
            let cid = conv.idValue
            conversationId = cid
            active = true

            // 冷启动:先用本地缓存铺底(对标 Android observeImMessages 立即吐缓存)。
            let cached = loadCache(session: session, cid: cid)
            if !cached.isEmpty { messages = cached }

            // 网络历史(seed)→ 与缓存合并去重 → 落库。
            if let history = try? await session.api.imMessages(conversationId: cid) {
                mergeSeed(history, session: session, cid: cid)
            }
            // 载入历史后上报一次已读(正确时机一:进入会话)。
            await markRead(session)
            connectWS(session, cid: cid)
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    // MARK: - 发送

    func send(session: SessionManager) async {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, let cid = conversationId else { return }
        draft = ""
        if let sent = try? await session.api.imSend(conversationId: cid, body: text) {
            appendUnique(sent, session: session, cid: cid)
        } else {
            // 乐观本地回显(server 失败时仍展示;对标 Android cacheSentMessage 缺省回显)。
            appendUnique(ImMessageDto(id: nil, conversationId: cid, senderId: myUserId, body: text, content: text),
                         session: session, cid: cid)
        }
    }

    // MARK: - 生命周期

    /// 视图出现:标记活跃,补一次已读上报(对标 Android 进入活跃态)。
    func onAppear(session: SessionManager) {
        active = true
        Task { await markRead(session) }
    }

    /// 视图消失:暂停活跃态但不断开会话(WS 仍维持)。
    func onDisappear() {
        active = false
    }

    func close() {
        ws?.disconnect()
        ws = nil
        status = .idle
        active = false
        conversationId = nil
        messages = []
        draft = ""
        peerLastReadMessageId = 0
        myUserId = nil
        localSeq = -1
    }

    func isMine(_ m: ImMessageDto) -> Bool {
        if let id = m.id, id < 0 { return true }   // 本地回显消息
        guard let mine = myUserId, let sid = m.senderId else { return false }
        return sid == mine
    }

    /// 「我」发出的消息是否已被对端读到(已读回执投影)。
    func isReadByPeer(_ m: ImMessageDto) -> Bool {
        guard isMine(m), let id = m.id, id > 0 else { return false }
        return id <= peerLastReadMessageId
    }

    // MARK: - 已读上报(正确时机)

    /// 上报本端已读至当前最大消息 id(对标 Android imMarkRead)。
    /// 时机:进入会话载入历史后、以及活跃态下每次新「对方」消息到达后。
    private func markRead(_ session: SessionManager) async {
        guard let cid = conversationId,
              let last = messages.compactMap(\.id).filter({ $0 > 0 }).max() else { return }
        try? await session.api.imMarkRead(conversationId: cid, lastMessageId: last)
    }

    // MARK: - WebSocket

    private func connectWS(_ session: SessionManager, cid: Int) {
        ws?.disconnect()
        let client = session.makeIMClient()
        ws = client
        client.connect(
            onMessage: { [weak self] inbound in
                Task { @MainActor in self?.onInbound(inbound, session: session, cid: cid) }
            },
            onStatus: { [weak self] s in
                Task { @MainActor in self?.status = s }
            }
        )
    }

    private func onInbound(_ inbound: IMWebSocketClient.Inbound, session: SessionManager, cid: Int) {
        guard let m = inbound.message else { return }
        let convId = inbound.conversationId ?? m.conversationId ?? cid
        guard convId == cid else { return }
        let dto = ImMessageDto(id: m.id, conversationId: convId, senderId: m.senderId,
                               body: m.body, content: m.content, createdAt: m.createdAt)
        let before = messages.count
        appendUnique(dto, session: session, cid: cid)
        let added = messages.count > before
        // 已读回执推进:对端发来的新消息表明对端已读到我此前发出的全部消息(对标 Android Read 水位上移)。
        if added && !isMine(dto) {
            updatePeerRead()
            // 正确时机二:活跃态收到对方新消息 → 即时上报已读。
            if active { Task { await markRead(session) } }
        }
    }

    /// 推进对端已读水位:取当前我方已发出的最大消息 id 作为对端已读到的位置。
    private func updatePeerRead() {
        let myMax = messages
            .filter { isMine($0) }
            .compactMap { $0.id }
            .filter { $0 > 0 }
            .max() ?? 0
        if myMax > peerLastReadMessageId { peerLastReadMessageId = myMax }
    }

    // MARK: - 去重 + 本地持久化

    private func appendUnique(_ dto: ImMessageDto, session: SessionManager, cid: Int) {
        var d = dto
        if let id = d.id {
            if messages.contains(where: { $0.id == id }) { return }
        } else {
            d.id = localSeq
            localSeq -= 1
        }
        messages.append(d)
        persist(d, session: session, cid: cid)
    }

    /// 网络历史合并:逐条按 id 去重落库(对标 Android seedMessagesFromNetwork + upsert)。
    private func mergeSeed(_ history: [ImMessageDto], session: SessionManager, cid: Int) {
        for dto in history {
            guard let id = dto.id else { continue }
            if !messages.contains(where: { $0.id == id }) {
                messages.append(dto)
            }
        }
        // 按 id 升序(服务端历史 + 实时增量统一顺序)。
        messages.sort { ($0.id ?? Int.max) < ($1.id ?? Int.max) }
        persistAll(session: session, cid: cid)
    }

    /// 单条落库(增量追加 + 刷新会话预览)。
    private func persist(_ dto: ImMessageDto, session: SessionManager, cid: Int) {
        let role = isMine(dto) ? "user" : "peer"
        let cached = LocalCache.CachedMessage(id: cacheId(dto), role: role, text: dto.textValue)
        session.cache.appendMessage(cached, sessionId: cacheKey(cid))
    }

    /// 全量覆盖落库(seed 合并后调用)。
    private func persistAll(session: SessionManager, cid: Int) {
        let cached = messages.map {
            LocalCache.CachedMessage(id: cacheId($0), role: isMine($0) ? "user" : "peer", text: $0.textValue)
        }
        session.cache.setMessages(cached, sessionId: cacheKey(cid))
        if let last = messages.last {
            session.cache.markConversationActivity(
                conversationId: cacheKey(cid),
                preview: LocalCache.formatPreview(role: isMine(last) ? "user" : "peer", text: last.textValue)
            )
        }
    }

    /// 从本地缓存读出会话消息(冷启动)。role=user→我方,据此回填 senderId 以保留气泡归属。
    private func loadCache(session: SessionManager, cid: Int) -> [ImMessageDto] {
        session.cache.messages(sessionId: cacheKey(cid)).compactMap { cm in
            let mid = Int(cm.id)
            // role=user 的缓存条目代表本端消息;无服务端 id(本地回显)的不强制恢复 senderId。
            let sender = cm.role == "user" ? myUserId : nil
            return ImMessageDto(id: mid, conversationId: cid, senderId: sender,
                                body: cm.text, content: cm.text)
        }
    }

    /// 缓存条目稳定 id:用服务端消息 id(字符串化)以便去重对齐。
    private func cacheId(_ dto: ImMessageDto) -> String {
        if let id = dto.id { return String(id) }
        return UUID().uuidString
    }
}

/// IM 即时通讯页(全量对标 Android `ImMessengerScreen` / 鸿蒙 `ImMessengerPage`)。
/// 本地持久化冷启动 + REST 历史 + 发送 + WebSocket 实时接收 + 已读上报/回执。
struct ImMessengerView: View {
    @EnvironmentObject private var session: SessionManager
    @StateObject private var vm = ImMessengerViewModel()

    var body: some View {
        Group {
            if vm.conversationId == nil {
                newConversation
            } else {
                conversation
            }
        }
        .navigationTitle("即时通讯")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear { if vm.conversationId != nil { vm.onAppear(session: session) } }
        .onDisappear { vm.onDisappear() }
    }

    private var newConversation: some View {
        VStack(spacing: Theme.Space.lg) {
            Image(systemName: "bubble.left.and.text.bubble.right.fill")
                .font(.system(size: 48)).foregroundColor(Theme.brand).padding(.top, Theme.Space.xl)
            Text("发起直聊").font(.headline)
            Text("输入企业用户 ID 发起即时会话(WebSocket 实时收发)。")
                .font(.footnote).foregroundColor(.secondary).multilineTextAlignment(.center)
            TextField("对方用户 ID", text: $vm.peerId)
                .keyboardType(.numberPad)
                .multilineTextAlignment(.center)
                .padding().background(Theme.cardBackground).cornerRadius(Theme.Radius.md)
            if let e = vm.error { Text(e).font(.footnote).foregroundColor(.red) }
            Button {
                Task {
                    await vm.open(session: session)
                    if vm.conversationId != nil { vm.onAppear(session: session) }
                }
            } label: {
                Text(vm.opening ? "打开中…" : "打开会话").frame(maxWidth: .infinity).padding(.vertical, Theme.Space.sm)
            }
            .buttonStyle(.borderedProminent)
            .disabled(vm.peerId.trimmingCharacters(in: .whitespaces).isEmpty || vm.opening)
            Spacer()
        }
        .padding(Theme.Space.xl)
    }

    private var conversation: some View {
        VStack(spacing: 0) {
            HStack {
                Text(vm.statusLabel)
                    .font(.caption).foregroundColor(vm.status == .open ? .green : .secondary)
                Spacer()
                Button("关闭") { vm.close() }.font(.caption)
            }
            .padding(.horizontal, Theme.Space.lg).padding(.vertical, Theme.Space.sm)
            .background(Theme.cardBackground)

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(spacing: Theme.Space.sm) {
                        if vm.messages.isEmpty {
                            emptyConversationHint
                        }
                        ForEach(vm.messages) { m in
                            ImBubble(text: m.textValue,
                                     mine: vm.isMine(m),
                                     readByPeer: vm.isReadByPeer(m))
                                .id(m.idValue)
                        }
                    }
                    .padding(Theme.Space.md)
                }
                .onChange(of: vm.messages.count) { _ in
                    if let last = vm.messages.last { proxy.scrollTo(last.idValue, anchor: .bottom) }
                }
            }
            ChatInputBar(text: $vm.draft, isBusy: false) {
                Task { await vm.send(session: session) }
            }
        }
    }

    private var emptyConversationHint: some View {
        VStack(spacing: Theme.Space.sm) {
            Image(systemName: "bubble.left")
                .font(.system(size: 36))
                .foregroundColor(Color.secondary.opacity(0.5))
                .padding(.top, 48)
            Text("暂无消息").font(.subheadline).foregroundColor(.secondary)
            Text("发出第一条消息后会显示在这里")
                .font(.caption).foregroundColor(Color.secondary.opacity(0.6))
        }
        .frame(maxWidth: .infinity)
        .padding(.bottom, 24)
    }
}

private struct ImBubble: View {
    let text: String
    let mine: Bool
    var readByPeer: Bool = false
    var body: some View {
        HStack(alignment: .bottom, spacing: Theme.Space.xs) {
            if mine {
                Spacer(minLength: 40)
                if readByPeer {
                    Text("已读").font(.caption2).foregroundColor(.secondary)
                }
            }
            Text(text)
                .padding(.horizontal, Theme.Space.md).padding(.vertical, Theme.Space.sm)
                .foregroundColor(mine ? .white : .primary)
                .background(mine ? Theme.brand : Theme.cardBackground)
                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.md, style: .continuous))
            if !mine { Spacer(minLength: 40) }
        }
    }
}
