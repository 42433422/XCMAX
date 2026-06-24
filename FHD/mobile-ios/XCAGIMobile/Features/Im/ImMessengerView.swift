import SwiftUI

@MainActor
final class ImMessengerViewModel: ObservableObject {
    @Published var peerId = ""
    @Published var conversationId: Int?
    @Published var messages: [ImMessageDto] = []
    @Published var draft = ""
    @Published var status: IMWebSocketClient.Status = .idle
    @Published var error: String?
    @Published var opening = false

    private var ws: IMWebSocketClient?
    private var myUserId: Int?
    private var localSeq = -1   // 本地回显消息的稳定(负数)id,不与服务端正数冲突

    var statusLabel: String {
        switch status {
        case .open: return "实时已连接"
        case .connecting: return "连接中…"
        case .reconnecting: return "重连中…"
        case .closed: return "已断开"
        case .idle: return "未连接"
        }
    }

    func open(session: SessionManager) async {
        guard let peer = Int(peerId.trimmingCharacters(in: .whitespaces)), peer > 0 else {
            error = "请输入有效的对方用户 ID"; return
        }
        error = nil
        opening = true
        defer { opening = false }
        if myUserId == nil { myUserId = (try? await session.api.me())?.user?.id }
        do {
            guard let conv = try await session.api.imCreateDirect(peerUserId: peer), conv.idValue > 0 else {
                error = "无法创建会话"; return
            }
            let cid = conv.idValue
            conversationId = cid
            messages = (try? await session.api.imMessages(conversationId: cid)) ?? []
            await markRead(session)
            connectWS(session, cid: cid)
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    func send(session: SessionManager) async {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, let cid = conversationId else { return }
        draft = ""
        if let sent = try? await session.api.imSend(conversationId: cid, body: text) {
            appendUnique(sent)
        } else {
            // 乐观本地回显
            appendUnique(ImMessageDto(id: nil, conversationId: cid, senderId: myUserId, body: text, content: text))
        }
    }

    func close() {
        ws?.disconnect()
        ws = nil
        status = .idle
        conversationId = nil
        messages = []
        draft = ""
    }

    func isMine(_ m: ImMessageDto) -> Bool {
        if let id = m.id, id < 0 { return true }   // 本地回显消息
        guard let mine = myUserId, let sid = m.senderId else { return false }
        return sid == mine
    }

    private func markRead(_ session: SessionManager) async {
        guard let cid = conversationId, let last = messages.compactMap(\.id).max() else { return }
        try? await session.api.imMarkRead(conversationId: cid, lastMessageId: last)
    }

    private func connectWS(_ session: SessionManager, cid: Int) {
        ws?.disconnect()
        let client = session.makeIMClient()
        ws = client
        client.connect(
            onMessage: { [weak self] inbound in
                Task { @MainActor in self?.onInbound(inbound, cid: cid) }
            },
            onStatus: { [weak self] s in
                Task { @MainActor in self?.status = s }
            }
        )
    }

    private func onInbound(_ inbound: IMWebSocketClient.Inbound, cid: Int) {
        guard let m = inbound.message else { return }
        let convId = inbound.conversationId ?? m.conversationId ?? cid
        guard convId == cid else { return }
        let dto = ImMessageDto(id: m.id, conversationId: convId, senderId: m.senderId,
                               body: m.body, content: m.content, createdAt: m.createdAt)
        appendUnique(dto)
    }

    private func appendUnique(_ dto: ImMessageDto) {
        var d = dto
        if let id = d.id {
            if messages.contains(where: { $0.id == id }) { return }
        } else {
            d.id = localSeq
            localSeq -= 1
        }
        messages.append(d)
    }
}

/// IM 即时通讯页(对标 Android `ImMessengerScreen` / 鸿蒙 `ImMessengerPage`)。
/// 真实 REST 历史 + 发送 + WebSocket 实时接收。
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
        .onDisappear { vm.close() }
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
                Task { await vm.open(session: session) }
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
                        ForEach(vm.messages) { m in ImBubble(text: m.textValue, mine: vm.isMine(m)).id(m.idValue) }
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
}

private struct ImBubble: View {
    let text: String
    let mine: Bool
    var body: some View {
        HStack {
            if mine { Spacer(minLength: 40) }
            Text(text)
                .padding(.horizontal, Theme.Space.md).padding(.vertical, Theme.Space.sm)
                .foregroundColor(mine ? .white : .primary)
                .background(mine ? Theme.brand : Theme.cardBackground)
                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.md, style: .continuous))
            if !mine { Spacer(minLength: 40) }
        }
    }
}
