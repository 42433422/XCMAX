import SwiftUI

/// 专属客服会话视图模型(全量对标 Android `CsRepository` + `CsChatScreen`)。
///
/// 关键对齐点:
/// - 专用端点:`cs/info`(在线/离线态、客服名)+ `cs/messages`(历史/发送),不走通用对话 SSE。
/// - 冷启动秒出:消息先从 `LocalCache`(key=`cs`)读出,网络历史回来再覆盖并回写缓存。
/// - 流式打字:发送期间 `isSending=true` 驱动最后一条客服气泡的闪烁光标(对标 Android `streaming` 标志)。
/// - 空回复回退:POST 回包 `reply` 为空时,重新拉取历史(对标 Android `loadMessages()` 回退)。
@MainActor
final class CsChatViewModel: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var input = ""
    @Published var info: CsInfo?
    @Published var isSending = false

    /// 本地缓存会话键(对标 Android PinnedIds.CS)。
    private let sessionId = "cs"
    private var loaded = false

    /// 是否处于流式打字态(最后一条为客服气泡且正在发送)。
    var streaming: Bool { isSending }

    // MARK: - 加载

    func load(_ session: SessionManager) async {
        // 冷启动:先用本地缓存填充,避免白屏(对标 Android Room 冷读)。
        if !loaded {
            loaded = true
            let cached = session.cache.messages(sessionId: sessionId)
            if !cached.isEmpty {
                messages = cached.map { ChatMessage(role: role(for: $0.role), text: $0.text) }
            }
        }
        // 并行拉取客服资料 + 历史(对标 Android LaunchedEffect 双 launch)。
        async let infoTask: CsInfo? = try? await session.api.csInfo()
        async let historyTask: [CsMessageDto]? = try? await session.api.csMessages()
        if let i = await infoTask { info = i }
        if let history = await historyTask {
            applyHistory(history, session: session)
        }
    }

    // MARK: - 发送

    func send(_ session: SessionManager) async {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isSending else { return }
        input = ""

        // 乐观回显 user 消息 + 写缓存(对标 Android sendMessage 先追加 local_user)。
        appendAndCache(role: .user, text: text, session: session)
        isSending = true
        defer { isSending = false }

        do {
            let resp = try await session.api.csSend(message: text)
            let reply = resp.bestReply
            if reply.isEmpty {
                // 空回复回退:重拉历史(对标 Android `else { loadMessages() }`)。
                if let history = try? await session.api.csMessages() {
                    applyHistory(history, session: session)
                }
            } else {
                appendAndCache(role: .assistant, text: reply, session: session)
            }
        } catch {
            let msg = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            // 失败提示进气泡(不缓存错误占位)。
            messages.append(ChatMessage(role: .assistant, text: "⚠️ " + msg))
        }
    }

    // MARK: - 展示衍生

    /// 标题:优先客服名(对标 Android csInfo.name / resolvedTitle)。
    var displayTitle: String { info?.resolvedTitle ?? "专属客服" }
    /// 在线态(对标 Android csInfo.online / resolvedOnline)。
    var isOnline: Bool { info?.resolvedOnline ?? false }
    /// 副标题文案:在线→客服名「在线」,离线→「离线」。
    var statusText: String {
        guard let info else { return "在线为您服务" }
        let name = (info.csName?.isEmpty == false) ? info.csName! : nil
        if info.resolvedOnline { return name ?? "客服在线" }
        return name ?? "客服离线"
    }

    // MARK: - 内部

    private func applyHistory(_ history: [CsMessageDto], session: SessionManager) {
        let mapped = history.map { ChatMessage(role: role(for: $0.role), text: $0.text ?? "") }
        messages = mapped
        // 覆盖式回写缓存 + 刷新会话列表预览(对标 Android persistCsConversationPreview)。
        let cached = mapped.map { LocalCache.CachedMessage(role: $0.role == .user ? "user" : "cs", text: $0.text) }
        session.cache.setMessages(cached, sessionId: sessionId)
        if let last = mapped.last {
            session.cache.markConversationActivity(
                conversationId: sessionId,
                preview: LocalCache.formatPreview(role: last.role == .user ? "user" : "cs", text: last.text)
            )
        }
    }

    private func appendAndCache(role: ChatMessage.Role, text: String, session: SessionManager) {
        messages.append(ChatMessage(role: role, text: text))
        session.cache.cache(role: role == .user ? "user" : "cs", text: text, sessionId: sessionId)
    }

    private func role(for raw: String?) -> ChatMessage.Role {
        raw == "user" ? .user : .assistant
    }
}

/// 专属客服聊天(全量对标 Android `CsChatScreen`)。
///
/// 标题区显示在线/离线态(在线带绿点),空态展示引导文案,发送时末条客服气泡闪烁打字光标。
struct CsChatView: View {
    var title: String = "专属客服"
    @EnvironmentObject private var session: SessionManager
    @StateObject private var vm = CsChatViewModel()

    var body: some View {
        VStack(spacing: 0) {
            if vm.messages.isEmpty {
                csEmptyState
            } else {
                CsMessagesView(messages: vm.messages,
                               streaming: vm.streaming,
                               avatarUrl: vm.info?.csAvatar)
            }
            ChatInputBar(text: $vm.input, isBusy: vm.isSending) {
                Task { await vm.send(session) }
            }
        }
        .navigationTitle(vm.displayTitle)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .principal) { titleBar }
        }
        .task { await vm.load(session) }
    }

    /// 顶栏标题 + 在线态(对标 Android TopAppBar 双行 title:名字 + 绿点/在线文案)。
    private var titleBar: some View {
        VStack(spacing: 2) {
            Text(vm.displayTitle).font(.headline)
            HStack(spacing: Theme.Space.xs) {
                if vm.isOnline {
                    Circle().fill(Color.green).frame(width: 7, height: 7)
                }
                Text(vm.statusText)
                    .font(.caption2)
                    .foregroundColor(vm.isOnline ? .green : .secondary)
            }
        }
    }

    private var csEmptyState: some View {
        VStack(spacing: Theme.Space.sm) {
            Image(systemName: "headphones")
                .font(.system(size: 44))
                .foregroundColor(Color.secondary.opacity(0.5))
            Text("向专属客服提问")
                .font(.subheadline).foregroundColor(.secondary)
            Text("客服上线后会尽快回复您")
                .font(.caption).foregroundColor(Color.secondary.opacity(0.6))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding()
    }
}

/// 客服消息列表:在末条客服气泡上叠加流式打字光标(对标 Android `CsMessageBubble(isStreaming:)`)。
private struct CsMessagesView: View {
    let messages: [ChatMessage]
    let streaming: Bool
    let avatarUrl: String?

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: Theme.Space.md) {
                    ForEach(Array(messages.enumerated()), id: \.element.id) { idx, msg in
                        CsBubble(
                            message: msg,
                            avatarUrl: avatarUrl,
                            isStreaming: streaming
                                && idx == messages.count - 1
                                && msg.role != .user
                        )
                        .id(msg.id)
                    }
                }
                .padding(Theme.Space.md)
            }
            .onChange(of: messages.count) { _ in
                if let last = messages.last { proxy.scrollTo(last.id, anchor: .bottom) }
            }
            .onChange(of: streaming) { _ in
                if let last = messages.last { proxy.scrollTo(last.id, anchor: .bottom) }
            }
        }
    }
}

/// 单条客服气泡(客服侧带头像 + 可选闪烁打字光标)。
private struct CsBubble: View {
    let message: ChatMessage
    let avatarUrl: String?
    let isStreaming: Bool

    private var isUser: Bool { message.role == .user }

    var body: some View {
        HStack(alignment: .top, spacing: Theme.Space.sm) {
            if isUser { Spacer(minLength: 40) }
            if !isUser {
                AvatarView(text: "客", url: avatarUrl, size: 32)
            }

            HStack(alignment: .bottom, spacing: 2) {
                Text(message.text.isEmpty ? "…" : message.text)
                    .textSelection(.enabled)
                if isStreaming { TypingCursor() }
            }
            .padding(.horizontal, Theme.Space.md)
            .padding(.vertical, Theme.Space.sm)
            .foregroundColor(isUser ? .white : .primary)
            .background(isUser ? Theme.brand : Theme.cardBackground)
            .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.md, style: .continuous))

            if !isUser { Spacer(minLength: 40) }
        }
    }
}

/// 流式打字闪烁光标(对标 Android `infiniteRepeatable` 的 ▌ 闪烁)。
private struct TypingCursor: View {
    @State private var visible = true
    var body: some View {
        Text("▌")
            .foregroundColor(Theme.brand)
            .opacity(visible ? 1 : 0.1)
            .onAppear {
                withAnimation(.easeInOut(duration: 0.53).repeatForever(autoreverses: true)) {
                    visible = false
                }
            }
    }
}
