import SwiftUI

@MainActor
final class ChatViewModel: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var input = ""
    @Published var isStreaming = false
    @Published var gitBusy = false
    /// 当前会话的活动开发分支(由助手消息正则解析;对标 Android gitBranch 派生)。
    @Published var gitBranch: String?

    let sessionId: String
    let peerKind: ChatPeerKind
    /// 超级员工工具("codex" | "cursor" | "claude" | "trae");普通会话为 nil。
    let superTool: String?

    private var streamTask: Task<Void, Never>?

    init(sessionId: String, peerKind: ChatPeerKind) {
        self.sessionId = sessionId
        self.peerKind = peerKind
        superTool = peerKind.superTool
    }

    /// 冷启动:从本地缓存秒出历史(对标 Android loadChatCache)。
    func loadCache(_ cache: LocalCache) {
        messages = cache.messages(sessionId: sessionId).map {
            ChatMessage(role: roleFromCache($0.role), text: $0.text)
        }
        recomputeGitBranch()
    }

    private func roleFromCache(_ raw: String) -> ChatMessage.Role {
        switch raw.lowercased() {
        case "user": return .user
        case "system": return .system
        default: return .assistant
        }
    }

    // MARK: - 发送 / 停止

    func send(using session: SessionManager) {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isStreaming, !gitBusy else { return }
        input = ""
        if let tool = superTool {
            dispatchSuperEmployee(text: text, tool: tool, session: session)
        } else {
            streamNormal(text: text, session: session)
        }
    }

    /// 停止流式(对标 Android stopChat):取消进行中的流任务,保留已收到的部分文本。
    func stop() {
        streamTask?.cancel()
        streamTask = nil
        isStreaming = false
    }

    /// 普通 AI 对话:经 SessionManager.streamChat(内建 LocalCache 缓存 + 最近 6 条上下文 + 单次重试)。
    private func streamNormal(text: String, session: SessionManager) {
        messages.append(ChatMessage(role: .user, text: text))
        messages.append(ChatMessage(role: .assistant, text: ""))
        let idx = messages.count - 1
        isStreaming = true
        streamTask = Task { [weak self] in
            await session.streamChat(
                message: text,
                sessionId: self?.sessionId ?? "default",
                onToken: { token in
                    Task { @MainActor in
                        guard let self, self.messages.indices.contains(idx) else { return }
                        self.messages[idx].text += token
                    }
                },
                onDone: { full in
                    Task { @MainActor in
                        guard let self else { return }
                        if self.messages.indices.contains(idx), !full.isEmpty {
                            self.messages[idx].text = full
                        }
                        if self.messages.indices.contains(idx), self.messages[idx].text.isEmpty {
                            self.messages[idx].text = "(无回复)"
                        }
                        self.isStreaming = false
                        self.streamTask = nil
                    }
                },
                onError: { msg in
                    Task { @MainActor in
                        guard let self, self.messages.indices.contains(idx) else { return }
                        if self.messages[idx].text.isEmpty {
                            self.messages[idx].text = "⚠️ " + msg
                        }
                        self.isStreaming = false
                        self.streamTask = nil
                    }
                }
            )
        }
    }

    /// 超级员工派工(codex/cursor/claude/trae):提交一条消息,展示即时直答 / 派工回执,拉取最新历史。
    private func dispatchSuperEmployee(text: String, tool: String, session: SessionManager) {
        cache(session, role: "user", text: text)
        messages.append(ChatMessage(role: .user, text: text))
        messages.append(ChatMessage(role: .assistant, text: "正在派工…"))
        let idx = messages.count - 1   // 助手占位行索引
        isStreaming = true
        streamTask = Task { [weak self] in
            defer { Task { @MainActor in self?.isStreaming = false; self?.streamTask = nil } }
            do {
                let resp = try await session.api.postSuperEmployeeMessage(tool: tool, message: text)
                let immediate = resp.assistantMessage?.body ?? ""
                await MainActor.run {
                    guard let self, self.messages.indices.contains(idx) else { return }
                    self.messages[idx].text = immediate.isEmpty
                        ? "已派工(任务号 \(resp.dispatch?.taskId ?? resp.taskId ?? "—")),完成后回写结果。"
                        : immediate
                    self.cache(session, role: "assistant", text: self.messages[idx].text)
                }
                // 拉一次最新历史,带回派工产生的结果消息(分支/diff 等)。
                await self?.refreshSuperEmployeeHistory(tool: tool, session: session)
            } catch {
                let msg = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
                await MainActor.run {
                    guard let self, self.messages.indices.contains(idx) else { return }
                    self.messages[idx].text = "⚠️ " + msg
                }
            }
        }
    }

    /// 拉取超级员工历史并合并(去重保留更完整文本),刷新分支态。
    func refreshSuperEmployeeHistory(tool: String, session: SessionManager) async {
        guard let history = try? await session.api.superEmployeeMessages(tool: tool) else { return }
        let mapped = history.compactMap { m -> ChatMessage? in
            let body = m.body ?? ""
            guard !body.isEmpty else { return nil }
            let role: ChatMessage.Role = (m.role == "user") ? .user : (m.role == "system" ? .system : .assistant)
            return ChatMessage(role: role, text: body)
        }
        guard !mapped.isEmpty else { return }
        await MainActor.run {
            self.messages = mapped
            // 同步进本地缓存,保证冷启动一致。
            session.cache.setMessages(mapped.map {
                LocalCache.CachedMessage(role: $0.role.rawValue, text: $0.text)
            }, sessionId: self.sessionId)
            self.recomputeGitBranch()
        }
    }

    private func cache(_ session: SessionManager, role: String, text: String) {
        session.cache.cache(role: role, text: text, sessionId: sessionId)
    }

    // MARK: - 新建 / 清空

    func clear(_ session: SessionManager) {
        stop()
        messages = []
        gitBranch = nil
        session.cache.clearMessages(sessionId: sessionId)
    }

    // MARK: - 超级员工开发工具(合并 / diff / 丢弃,经中继 git 操作)

    /// 解析最近一个未处置的开发分支(对标 Android gitBranch 单遍扫描)。
    /// push/diff 带 super-employee/ 分支名 → 候选;遇「✅ 已合并 / 已丢弃分支」→ 清空。
    private func recomputeGitBranch() {
        guard superTool != nil, !isStreaming else { gitBranch = nil; return }
        var candidate: String?
        for m in messages where m.role == .assistant {
            if let range = m.text.range(of: #"super-employee/[\w./-]+"#, options: .regularExpression) {
                candidate = String(m.text[range])
            }
            if m.text.contains("✅ 已合并") || m.text.contains("已丢弃分支") {
                candidate = nil
            }
        }
        gitBranch = candidate
    }

    func gitOp(_ op: GitOp, session: SessionManager) {
        guard let branch = gitBranch, !gitBusy else { return }
        let relayId = session.relayDesktopId
        guard !relayId.isEmpty else {
            messages.append(ChatMessage(role: .system, text: "⚠️ 未绑定电脑执行端,请先在「设置」里扫码绑定中继设备。"))
            return
        }
        gitBusy = true
        Task { [weak self] in
            defer { Task { @MainActor in self?.gitBusy = false } }
            do {
                let reply: String
                switch op {
                case .merge:   reply = try await session.api.gitMerge(relayId: relayId, branch: branch)
                case .diff:    reply = try await session.api.gitDiff(relayId: relayId, branch: branch)
                case .discard: reply = try await session.api.gitDiscard(relayId: relayId, branch: branch)
                }
                await MainActor.run {
                    self?.messages.append(ChatMessage(role: .assistant, text: reply.isEmpty ? op.doneText : reply))
                    self?.cache(session, role: "assistant", text: reply.isEmpty ? op.doneText : reply)
                    self?.recomputeGitBranch()
                }
            } catch {
                let msg = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
                await MainActor.run {
                    self?.messages.append(ChatMessage(role: .system, text: "⚠️ " + msg))
                }
            }
        }
    }

    enum GitOp {
        case merge, diff, discard
        var doneText: String {
            switch self {
            case .merge: return "✅ 已合并到主干。"
            case .diff: return "已返回 diff。"
            case .discard: return "已丢弃分支。"
            }
        }
    }
}

/// SSE 流式对话页(对标 Android `ChatScreen` / 鸿蒙 SSE 对话)。
/// 普通会话走 SessionManager.streamChat(带缓存/上下文/重试);
/// codex/claude 超级员工会话走派工 + git 开发工具条。
struct ChatView: View {
    let title: String
    let sessionId: String
    /// 方头像语义(由会话来源解析;默认助理)。
    var peerKind: ChatPeerKind
    /// AI 员工真实头像(普通员工会话传入)。
    var aiAvatarURL: String?

    @EnvironmentObject private var session: SessionManager
    @StateObject private var vm: ChatViewModel
    @State private var loaded = false

    init(title: String, sessionId: String, peerKind: ChatPeerKind = .assistant, aiAvatarURL: String? = nil) {
        self.title = title
        self.sessionId = sessionId
        self.peerKind = peerKind
        self.aiAvatarURL = aiAvatarURL
        _vm = StateObject(wrappedValue: ChatViewModel(sessionId: sessionId, peerKind: peerKind))
    }

    /// 普通会话的建议气泡(对标 Android rebuildChatSuggestions 的基础项)。
    private var suggestions: [ChatSuggestion] {
        guard vm.superTool == nil else { return [] }
        return [
            ChatSuggestion(label: "企业同步", prompt: "同步企业端已安装的智能伙伴和能力"),
            ChatSuggestion(label: "今日待办", prompt: "总结我今天的待办和审批"),
            ChatSuggestion(label: "同步状态", prompt: "我的手机和电脑数据同步了吗?"),
        ]
    }

    private var devTools: GitActionBar.Config? {
        guard vm.superTool != nil else { return nil }
        return GitActionBar.Config(
            branch: vm.gitBranch,
            busy: vm.gitBusy,
            onDiff: { vm.gitOp(.diff, session: session) },
            onMerge: { vm.gitOp(.merge, session: session) },
            onDiscard: { vm.gitOp(.discard, session: session) },
            onEmptyHint: {}
        )
    }

    var body: some View {
        VStack(spacing: 0) {
            if vm.messages.isEmpty {
                ChatEmptyState(
                    title: title,
                    peerKind: peerKind,
                    aiAvatarURL: aiAvatarURL,
                    suggestions: suggestions,
                    onSuggestion: { prompt in
                        vm.input = prompt
                        vm.send(using: session)
                    }
                )
            } else {
                ChatMessagesView(
                    messages: vm.messages,
                    isStreaming: vm.isStreaming,
                    peerKind: peerKind,
                    aiAvatarURL: aiAvatarURL,
                    userAvatarURL: nil,
                    aiName: title
                )
            }
            ChatInputBar(
                text: $vm.input,
                isBusy: vm.isStreaming,
                onSend: { vm.send(using: session) },
                onStop: { vm.stop() },
                devTools: devTools
            )
        }
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                Menu {
                    Button { vm.clear(session) } label: {
                        Label("新建对话", systemImage: "square.and.pencil")
                    }
                    Button(role: .destructive) { vm.clear(session) } label: {
                        Label("清空当前对话", systemImage: "trash")
                    }
                } label: {
                    Image(systemName: "ellipsis")
                }
            }
        }
        .task {
            guard !loaded else { return }
            loaded = true
            vm.loadCache(session.cache)
            // 超级员工会话:进入即拉一次云端历史,补齐跨设备产生的派工结果。
            if let tool = vm.superTool {
                await vm.refreshSuperEmployeeHistory(tool: tool, session: session)
            }
        }
    }
}
