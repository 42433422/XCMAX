import SwiftUI

// ════════════════════════════════════════════════════════════════
// 聊天/会话共享组件(对标 Android ChatScreen / ConversationListScreen 的可复用片段)
// ════════════════════════════════════════════════════════════════

/// 会话方头像语义(对标 Android `AppAvatarFallback` + `chatAvatarFallback`)。
/// 用于把会话的 kind/route 解析成真实头像或品牌占位首字。
enum ChatPeerKind: Hashable {
    case assistant            // 小C助理
    case customerService      // 专属客服
    case codex                // 超级员工-Codex
    case claude               // 超级员工-Claude
    case employee             // 普通 AI 员工
    case user                 // 当前用户

    /// 占位首字(无 url 时显示)。
    var fallbackInitial: String {
        switch self {
        case .assistant: return "C"
        case .customerService: return "客"
        case .codex: return "X"
        case .claude: return "C"
        case .employee: return "员"
        case .user: return "我"
        }
    }

    /// 由固定联系人/会话 id + kind 解析方头像语义(对标 Android isCodex/isClaude 判定)。
    static func resolve(id: String, kind: String) -> ChatPeerKind {
        let i = id.lowercased()
        let k = kind.lowercased()
        if i.contains("codex") || k.contains("codex") { return .codex }
        if i.contains("claude") || k.contains("claude") { return .claude }
        if k == "assistant" || i == "assistant" { return .assistant }
        if k.contains("cs") || k.contains("service") || i == "dedicated_cs" { return .customerService }
        return .employee
    }
}

/// 单条聊天气泡(对标 Android `ImBubble`):左白右绿、流式光标、真实方头像、按角色显示头像。
struct ChatBubble: View {
    let message: ChatMessage
    var isStreaming: Bool = false
    var showAvatar: Bool = true
    /// 方头像语义(AI 一侧);用户消息固定用 user 头像。
    var peerKind: ChatPeerKind = .assistant
    /// AI 真实头像 url(员工头像);空则回退占位。
    var aiAvatarURL: String? = nil
    /// 当前用户真实头像 url。
    var userAvatarURL: String? = nil
    /// AI 一侧占位名(用于首字颜色/字)。
    var aiName: String = "AI"

    private var isUser: Bool { message.role == .user }

    private var bubbleText: String {
        var t = message.text
        if isStreaming { t += "\u{200B}▌" }   // 流式光标
        return t.isEmpty && !isStreaming ? "…" : t
    }

    var body: some View {
        HStack(alignment: .top, spacing: Theme.Space.sm) {
            if isUser { Spacer(minLength: 40) }

            if !isUser {
                if showAvatar {
                    AvatarView(text: aiName.isEmpty ? peerKind.fallbackInitial : aiName,
                               url: aiAvatarURL, size: 36)
                } else {
                    Color.clear.frame(width: 36, height: 1)   // 同组占位对齐
                }
            }

            Text(bubbleText)
                .textSelection(.enabled)
                .font(.system(size: 15))
                .padding(.horizontal, Theme.Space.md)
                .padding(.vertical, Theme.Space.sm)
                .foregroundColor(isUser ? .white : .primary)
                .background(isUser ? Theme.brand : Theme.cardBackground)
                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.md, style: .continuous))
                .frame(maxWidth: 280, alignment: isUser ? .trailing : .leading)

            if isUser {
                if showAvatar {
                    AvatarView(text: "我", url: userAvatarURL, size: 36)
                } else {
                    Color.clear.frame(width: 36, height: 1)
                }
            }

            if !isUser { Spacer(minLength: 40) }
        }
        .id(message.id)
    }
}

/// 可自动滚到底的消息列表(流式逐字时跟随)。
struct ChatMessagesView: View {
    let messages: [ChatMessage]
    var isStreaming: Bool = false
    var peerKind: ChatPeerKind = .assistant
    var aiAvatarURL: String? = nil
    var userAvatarURL: String? = nil
    var aiName: String = "AI"

    /// 仅每组第一条对方消息显示头像;用户消息每条都显示(对标 Android isUserOrFirstInGroup)。
    private func showAvatar(at index: Int) -> Bool {
        let role = messages[index].role
        if role == .user { return true }
        if index == 0 { return true }
        return messages[index - 1].role != role
    }

    private func lastAssistantIndex() -> Int? {
        messages.lastIndex { $0.role == .assistant }
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 2) {
                    ForEach(Array(messages.enumerated()), id: \.element.id) { index, msg in
                        ChatBubble(
                            message: msg,
                            isStreaming: isStreaming && index == lastAssistantIndex() && msg.role == .assistant,
                            showAvatar: showAvatar(at: index),
                            peerKind: peerKind,
                            aiAvatarURL: aiAvatarURL,
                            userAvatarURL: userAvatarURL,
                            aiName: aiName
                        )
                    }
                }
                .padding(.horizontal, 14)
                .padding(.vertical, Theme.Space.sm)
            }
            .onChange(of: messages.last?.text) { _ in scrollToBottom(proxy) }
            .onChange(of: messages.count) { _ in scrollToBottom(proxy) }
        }
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy) {
        guard let last = messages.last else { return }
        withAnimation(.easeOut(duration: 0.15)) { proxy.scrollTo(last.id, anchor: .bottom) }
    }
}

/// 底部输入条(对标 Android `ImInputBar`):常驻发送、流式态切「停止」、可选超级员工开发工具条。
struct ChatInputBar: View {
    @Binding var text: String
    var isBusy: Bool
    var onSend: () -> Void
    /// 流式中点击发送键 → 停止;非流式 → 发送。停止与发送共用主按钮(对标 Android)。
    var onStop: (() -> Void)? = nil

    /// 超级员工开发工具条(仅 codex/claude 会话传入)。
    var devTools: GitActionBar.Config? = nil

    private var canSend: Bool {
        !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        VStack(spacing: 0) {
            if let devTools {
                Divider()
                GitActionBar(config: devTools)
            }
            Divider()
            HStack(spacing: Theme.Space.sm) {
                TextField("发消息…", text: $text, axis: .vertical)
                    .lineLimit(1...4)
                    .padding(.horizontal, Theme.Space.md)
                    .padding(.vertical, Theme.Space.sm)
                    .background(Theme.cardBackground)
                    .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.lg, style: .continuous))

                Button {
                    if isBusy { onStop?() } else { onSend() }
                } label: {
                    Image(systemName: isBusy ? "stop.circle.fill" : "arrow.up.circle.fill")
                        .font(.system(size: 30))
                        .foregroundColor(isBusy ? .red : (canSend ? Theme.brand : .secondary))
                }
                .disabled(!isBusy && !canSend)
            }
            .padding(Theme.Space.sm)
            .background(.bar)
        }
    }
}

/// 情境功能键条(对标 Android `GitActionBar`):超级员工开发任务分支的 查看 diff / 合并 / 丢弃。
/// 有分支时点亮可操作;无分支置灰,点了提示先发开发任务。
struct GitActionBar: View {
    struct Config {
        var branch: String?           // nil = 无可处置分支(置灰)
        var busy: Bool                // git 操作进行中
        var onDiff: () -> Void
        var onMerge: () -> Void
        var onDiscard: () -> Void
        var onEmptyHint: () -> Void
    }

    let config: Config

    private var active: Bool { (config.branch?.isEmpty == false) && !config.busy }

    private var branchTail: String {
        guard let b = config.branch, let tail = b.split(separator: "/").last else { return "" }
        return String(tail)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 4) {
                if config.busy {
                    ProgressView().scaleEffect(0.7)
                } else {
                    Image(systemName: "arrow.triangle.merge").font(.caption2)
                }
                Text(active ? "开发任务分支 · \(branchTail)"
                            : (config.busy ? "电脑执行端处理中…" : "开发工具 · 发任务后可合并 / 查看 / 丢弃分支"))
                    .font(.caption2)
                    .foregroundColor(.secondary)
                    .lineLimit(1)
            }
            HStack(spacing: Theme.Space.sm) {
                chip("查看 diff", "doc.text.magnifyingglass", .primary, filled: false) {
                    active ? config.onDiff() : config.onEmptyHint()
                }
                chip("合并到主干", "arrow.triangle.merge", Theme.brand, filled: active) {
                    active ? config.onMerge() : config.onEmptyHint()
                }
                chip("丢弃", "trash", .red, filled: false) {
                    active ? config.onDiscard() : config.onEmptyHint()
                }
            }
        }
        .padding(.horizontal, Theme.Space.md)
        .padding(.vertical, Theme.Space.sm)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func chip(_ label: String, _ icon: String, _ tint: Color, filled: Bool, action: @escaping () -> Void) -> some View {
        let dimmed = !active
        let effTint = dimmed ? tint.opacity(0.45) : tint
        return Button(action: action) {
            HStack(spacing: 4) {
                Image(systemName: icon).font(.caption2)
                Text(label).font(.caption)
            }
            .foregroundColor(effTint)
            .padding(.horizontal, 11)
            .padding(.vertical, 6)
            .background(filled ? tint.opacity(0.12) : Color.secondary.opacity(dimmed ? 0.06 : 0.10))
            .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.sm, style: .continuous))
        }
        .buttonStyle(.plain)
        .disabled(config.busy)
    }
}

/// 空状态:AI 头像 + 问候 + 建议气泡(对标 Android `ChatEmptyState`)。
struct ChatEmptyState: View {
    let title: String
    var peerKind: ChatPeerKind = .assistant
    var aiAvatarURL: String? = nil
    var suggestions: [ChatSuggestion] = []
    var onSuggestion: (String) -> Void = { _ in }

    var body: some View {
        VStack(spacing: Theme.Space.sm) {
            AvatarView(text: title, url: aiAvatarURL, size: 64)
                .padding(.top, 48)
            Text("你好,我是 \(title)")
                .font(.headline)
            Text("有什么我可以帮你的?")
                .font(.subheadline).foregroundColor(.secondary)
            if !suggestions.isEmpty {
                FlowSuggestions(suggestions: suggestions, onSuggestion: onSuggestion)
                    .padding(.top, Theme.Space.md)
                    .padding(.horizontal, Theme.Space.xl)
            }
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// 建议气泡流式布局(对标 Android `FlowRow` of `ChatSuggestionChip`)。
struct FlowSuggestions: View {
    let suggestions: [ChatSuggestion]
    var onSuggestion: (String) -> Void

    var body: some View {
        // 简单两列流式;SwiftUI 无原生 FlowRow,用 chunk 折行近似。
        VStack(spacing: Theme.Space.sm) {
            ForEach(rows.indices, id: \.self) { r in
                HStack(spacing: Theme.Space.sm) {
                    ForEach(rows[r]) { s in
                        Button { onSuggestion(s.prompt) } label: {
                            Text(s.label)
                                .font(.caption)
                                .padding(.horizontal, 14).padding(.vertical, 8)
                                .background(Theme.brand.opacity(0.10))
                                .foregroundColor(Theme.brand)
                                .clipShape(Capsule())
                        }
                        .buttonStyle(.plain)
                    }
                    Spacer(minLength: 0)
                }
            }
        }
    }

    /// 每行最多 2 个建议(标签较短时贴近 Android FlowRow 视觉)。
    private var rows: [[ChatSuggestion]] {
        stride(from: 0, to: suggestions.count, by: 2).map {
            Array(suggestions[$0..<min($0 + 2, suggestions.count)])
        }
    }
}

/// 一条建议(对标 Android `ChatSuggestion`)。
struct ChatSuggestion: Identifiable, Hashable {
    let id = UUID()
    var label: String
    var prompt: String
}

// ════════════════════════════════════════════════════════════════
// 会话列表辅助:未读角标 / 状态徽标 / 时间戳格式化(对标 Android)
// ════════════════════════════════════════════════════════════════

/// 头像右上角未读角标(红点 + 计数,对标 Android ConversationCell 的 badge)。
struct UnreadBadge: View {
    let count: Int

    var body: some View {
        if count > 0 {
            Text(count > 99 ? "99+" : "\(count)")
                .font(.system(size: 11, weight: .bold))
                .foregroundColor(.white)
                .padding(.horizontal, count > 99 ? 5 : 0)
                .frame(minWidth: 18, minHeight: 18)
                .background(Circle().fill(Color.red))
        }
    }
}

/// 二级状态徽标(在线/置顶等小标,对标 Android `StatusBadge`)。
/// 命名加 `Conversation` 前缀,避免与审批页 `StatusBadge`(状态字符串语义)冲突。
struct ConversationTagBadge: View {
    let text: String
    var color: Color = .green

    var body: some View {
        Text(text)
            .font(.system(size: 11, weight: .medium))
            .foregroundColor(color)
            .padding(.horizontal, Theme.Space.sm).padding(.vertical, 2)
            .background(color.opacity(0.12))
            .overlay(Capsule().stroke(color.opacity(0.3), lineWidth: 0.5))
            .clipShape(Capsule())
    }
}

/// 会话时间戳格式化(对标 Android `formatTimestamp`:刚刚/分钟前/小时前/昨天/M月d日)。
/// 入参为毫秒时间戳;<=0 返回空串。
func formatConversationTimestamp(_ ms: Double) -> String {
    guard ms > 0 else { return "" }
    let nowMs = Date().timeIntervalSince1970 * 1000
    let diff = nowMs - ms
    switch diff {
    case ..<60_000: return "刚刚"
    case ..<3_600_000: return "\(Int(diff / 60_000))分钟前"
    case ..<86_400_000: return "\(Int(diff / 3_600_000))小时前"
    case ..<172_800_000: return "昨天"
    default:
        let date = Date(timeIntervalSince1970: ms / 1000)
        let cal = Calendar.current
        let fmt = DateFormatter()
        fmt.locale = Locale(identifier: "zh_CN")
        fmt.dateFormat = cal.isDate(date, equalTo: Date(), toGranularity: .year) ? "M/d" : "yy/M/d"
        return fmt.string(from: date)
    }
}
