import SwiftUI

// ════════════════════════════════════════════════════════════════
// 会话列表(微信风格,对标 Android `ConversationListScreen`)
// 固定联系人(小C/客服/Codex/Claude)+ AI 部门群内联行,
// 未读角标 / 时间戳 / 置顶·关注·隐藏·已读 / 搜索 / ALL·PINNED·UNREAD 筛选 / 长按菜单。
// ════════════════════════════════════════════════════════════════

/// 会话筛选(对标 Android `ConversationFilter`)。
enum ConversationFilter: String, CaseIterable {
    case all, pinned, unread
    var label: String {
        switch self {
        case .all: return "全部"
        case .pinned: return "置顶"
        case .unread: return "未读"
        }
    }
}

/// 固定联系人的本地状态(置顶/关注/隐藏/未读)。
/// 固定条目无后端 toggle 端点,与 Android 一样在本地持久化(UserDefaults)。
struct LocalConversationState: Codable, Equatable {
    var pinned = false
    var hidden = false
    var followed = true
    var unread = 0
}

/// 列表里统一渲染的一行(固定联系人 或 AI 群)。
struct ConversationRow: Identifiable, Hashable {
    enum Kind: Equatable { case fixed(FixedContactDto), group(AiGroup) }
    let id: String
    let kind: Kind
    var title: String
    var subtitle: String
    var avatarURL: String?
    var type: ConversationType
    var avatarFallback: AppAvatarFallback
    var peerKind: ChatPeerKind
    var timestamp: Double      // 毫秒
    var unread: Int
    var pinned: Bool
    var hidden: Bool
    var followed: Bool
    var online: Bool

    static func == (l: ConversationRow, r: ConversationRow) -> Bool {
        l.id == r.id && l.title == r.title && l.subtitle == r.subtitle &&
        l.avatarURL == r.avatarURL && l.type == r.type && l.avatarFallback == r.avatarFallback &&
        l.timestamp == r.timestamp && l.unread == r.unread &&
        l.pinned == r.pinned && l.hidden == r.hidden && l.followed == r.followed && l.online == r.online
    }

    func hash(into hasher: inout Hasher) { hasher.combine(id) }
}

@MainActor
final class ConversationListViewModel: ObservableObject {
    @Published var fixedContacts: [FixedContactDto] = []
    @Published var groups: [AiGroup] = []
    @Published var phase: LoadPhase = .idle
    @Published var localStates: [String: LocalConversationState] = [:]

    private let defaults = UserDefaults.standard
    private let localStateKey = "conversation_local_states"

    init() { loadLocalStates() }

    var isEnterprise: Bool { true }   // 手机端仅企业版(对标 product SSOT)

    // MARK: - 加载

    func load(_ session: SessionManager) async {
        if fixedContacts.isEmpty && groups.isEmpty { phase = .loading }
        async let contactsTask = session.api.contactsFixed()
        async let groupsTask: [AiGroup] = (try? await session.api.aiGroups()) ?? []
        do {
            let data = try await contactsTask
            let allFixed = (data.top ?? []) + (data.bottom ?? [])
            fixedContacts = allFixed
            groups = await groupsTask
            phase = (allFixed.isEmpty && groups.isEmpty) ? .empty : .loaded
        } catch {
            // 联系人失败但群可能成功:仍尽量展示
            groups = await groupsTask
            if groups.isEmpty {
                phase = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
            } else {
                phase = .loaded
            }
        }
    }

    // MARK: - 行投影(合并 LocalCache 预览/时间戳 + 本地状态)

    func rows(cache: LocalCache, search: String, filter: ConversationFilter) -> [ConversationRow] {
        let states = cache.conversationStates()
        var out: [ConversationRow] = []

        // AI 部门群(内联,置于顶部,对标 Android filteredGroups)
        for g in groups {
            let id = "group:" + g.idValue
            let preview = g.lastMessagePreview ?? "成员 \(g.memberCount ?? 0)"
            out.append(ConversationRow(
                id: id,
                kind: .group(g),
                title: g.name ?? "群聊",
                subtitle: preview,
                avatarURL: nil,
                type: .aiTask,
                avatarFallback: .aiEmployee,
                peerKind: .employee,
                timestamp: parseISO(g.lastMessageAt) ?? states[id]?.lastMessageAt ?? 0,
                unread: g.unreadCount ?? 0,
                pinned: g.isPinned ?? false,
                hidden: g.isHidden ?? false,
                followed: g.isFollowed ?? true,
                online: false
            ))
        }

        // 固定联系人(小C / 客服 / Codex / Cursor / Claude / Trae)
        for c in fixedContacts {
            let local = localStates[c.id] ?? LocalConversationState()
            let sessionId = c.id.isEmpty ? "assistant" : c.id
            let cached = states[sessionId]
            let preview = cached?.lastMessagePreview.isEmpty == false ? cached!.lastMessagePreview : (c.summary.isEmpty ? "点击开始对话" : c.summary)
            let peer = ChatPeerKind.resolve(id: c.id, kind: c.kind, title: c.name)
            out.append(ConversationRow(
                id: c.id,
                kind: .fixed(c),
                title: c.name,
                subtitle: preview,
                avatarURL: fixedAvatarURL(contact: c, peer: peer),
                type: peer.conversationType,
                avatarFallback: peer.conversationType.avatarFallback,
                peerKind: peer,
                timestamp: cached?.lastMessageAt ?? 0,
                unread: local.unread,
                pinned: local.pinned,
                hidden: local.hidden,
                followed: local.followed,
                online: peer.conversationType.defaultOnline
            ))
        }

        // 搜索过滤
        let q = search.trimmingCharacters(in: .whitespaces)
        var filtered = out.filter { row in
            q.isEmpty || row.title.localizedCaseInsensitiveContains(q) || row.subtitle.localizedCaseInsensitiveContains(q)
        }
        // 筛选维度
        switch filter {
        case .all: break
        case .pinned: filtered = filtered.filter { $0.pinned }
        case .unread: filtered = filtered.filter { $0.unread > 0 }
        }
        // 排序:置顶优先,其次按时间倒序(0 时间的固定条目落在最后但稳定)。
        return filtered.sorted { a, b in
            if a.pinned != b.pinned { return a.pinned }
            return a.timestamp > b.timestamp
        }
    }

    var unreadTotal: Int {
        let fixedUnread = fixedContacts.reduce(0) { $0 + (localStates[$1.id]?.unread ?? 0) }
        let groupUnread = groups.reduce(0) { $0 + ($1.unreadCount ?? 0) }
        return fixedUnread + groupUnread
    }

    // MARK: - 长按操作(固定联系人:本地;群:走后端)

    func toggleFixedRead(_ id: String) {
        var s = localStates[id] ?? LocalConversationState()
        s.unread = s.unread > 0 ? 0 : 1
        localStates[id] = s; persistLocalStates()
    }
    func toggleFixedPin(_ id: String) {
        var s = localStates[id] ?? LocalConversationState(); s.pinned.toggle()
        localStates[id] = s; persistLocalStates()
    }
    func toggleFixedFollow(_ id: String) {
        var s = localStates[id] ?? LocalConversationState(); s.followed.toggle()
        localStates[id] = s; persistLocalStates()
    }
    func toggleFixedHide(_ id: String) {
        var s = localStates[id] ?? LocalConversationState(); s.hidden.toggle()
        localStates[id] = s; persistLocalStates()
    }

    func markFixedReadOnOpen(_ id: String) {
        guard let s = localStates[id], s.unread > 0 else { return }
        var ns = s; ns.unread = 0
        localStates[id] = ns; persistLocalStates()
    }

    func groupAction(_ action: GroupAction, group: AiGroup, session: SessionManager) {
        let gid = group.idValue
        Task {
            switch action {
            case .toggleRead:
                if (group.unreadCount ?? 0) > 0 { try? await session.api.markAiGroupRead(groupId: gid) }
                else { _ = try? await session.api.markAiGroupUnread(groupId: gid) }
            case .togglePin: _ = try? await session.api.toggleAiGroupPin(groupId: gid)
            case .toggleFollow: _ = try? await session.api.toggleAiGroupFollowed(groupId: gid)
            case .toggleHide: _ = try? await session.api.toggleAiGroupHidden(groupId: gid)
            case .delete: try? await session.api.deleteAiGroup(groupId: gid)
            }
            await load(session)
        }
    }

    enum GroupAction { case toggleRead, togglePin, toggleFollow, toggleHide, delete }

    // MARK: - 本地状态持久化

    private func loadLocalStates() {
        guard let data = defaults.data(forKey: localStateKey),
              let map = try? JSONDecoder().decode([String: LocalConversationState].self, from: data) else { return }
        localStates = map
    }
    private func persistLocalStates() {
        if let data = try? JSONEncoder().encode(localStates) {
            defaults.set(data, forKey: localStateKey)
        }
    }

    private func parseISO(_ s: String?) -> Double? {
        guard let s, !s.isEmpty else { return nil }
        let fmt = ISO8601DateFormatter()
        fmt.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = fmt.date(from: s) { return d.timeIntervalSince1970 * 1000 }
        fmt.formatOptions = [.withInternetDateTime]
        if let d = fmt.date(from: s) { return d.timeIntervalSince1970 * 1000 }
        return nil
    }

    private func fixedAvatarURL(contact: FixedContactDto, peer: ChatPeerKind) -> String? {
        guard peer == .employee, contact.avatar.hasPrefix("http") else { return nil }
        return contact.avatar
    }
}

/// 消息列表(对标 Android `ConversationListScreen`):固定联系人 + AI 部门群 → 进入对话。
struct ConversationListView: View {
    @EnvironmentObject private var session: SessionManager
    @StateObject private var vm = ConversationListViewModel()
    @State private var search = ""
    @State private var filter: ConversationFilter = .all
    @State private var profileContact: FixedContactDto?
    @State private var actionRow: ConversationRow?

    var body: some View {
        NavigationStack {
            Group {
                switch vm.phase {
                case .idle, .loading:
                    LoadingView()
                case .failed(let m):
                    ErrorStateView(message: m) { Task { await vm.load(session) } }
                case .empty:
                    EmptyStateView(icon: "bubble.left", title: "暂无会话", subtitle: "下拉刷新或和小C助理聊聊吧")
                case .loaded:
                    list
                }
            }
            .navigationTitle("消息")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Menu {
                        NavigationLink { AiGroupListView() } label: { Label("我的群聊", systemImage: "person.3") }
                        NavigationLink { ContactsView() } label: { Label("通讯录", systemImage: "person.2") }
                        NavigationLink { AiCircleView() } label: { Label("交流圈", systemImage: "photo.on.rectangle.angled") }
                    } label: { Image(systemName: "plus") }
                }
            }
            .navigationDestination(for: ConversationRow.self) { row in
                destination(for: row)
            }
            .sheet(item: $profileContact) { c in
                NavigationStack { FixedPartnerProfileView(contact: c) }
            }
            .confirmationDialog(actionRow?.title ?? "会话操作", isPresented: actionPresented, titleVisibility: .visible) {
                actionMenu
            }
        }
        .task {
            if vm.phase == .idle { await vm.load(session) }
        }
    }

    private var actionPresented: Binding<Bool> {
        Binding(get: { actionRow != nil }, set: { if !$0 { actionRow = nil } })
    }

    private var rows: [ConversationRow] {
        vm.rows(cache: session.cache, search: search, filter: filter)
    }

    private var list: some View {
        VStack(spacing: 0) {
            searchAndFilterHeader
            List {
                ForEach(rows) { row in
                    NavigationLink(value: row) { rowContent(row) }
                        .simultaneousGesture(TapGesture().onEnded { markReadOnOpen(row) })
                        .listRowInsets(EdgeInsets(
                            top: MessageAvatarLayout.conversationRowVerticalPadding,
                            leading: MessageAvatarLayout.conversationRowHorizontalPadding,
                            bottom: MessageAvatarLayout.conversationRowVerticalPadding,
                            trailing: MessageAvatarLayout.conversationRowHorizontalPadding
                        ))
                        .contextMenu { contextMenu(for: row) }
                        .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                            swipeActions(for: row)
                        }
                }
                bottomTabSpacer
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .background(Theme.screenBackground)
            .refreshable { await vm.load(session) }
        }
        .background(Theme.screenBackground)
    }

    private var searchAndFilterHeader: some View {
        VStack(spacing: 0) {
            searchBar
                .padding(.horizontal, Theme.Space.lg)
                .padding(.top, Theme.Space.sm)
                .padding(.bottom, Theme.Space.xs)
            filterBar
        }
        .background(Theme.screenBackground)
    }

    private var searchBar: some View {
        HStack(spacing: Theme.Space.sm) {
            Image(systemName: "magnifyingglass")
                .font(.subheadline.weight(.semibold))
                .foregroundColor(.secondary)
            TextField("查找会话或伙伴", text: $search)
                .textInputAutocapitalization(.never)
                .disableAutocorrection(true)
                .submitLabel(.search)
            if !search.isEmpty {
                Button {
                    search = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.subheadline)
                        .foregroundColor(.secondary)
                }
                .buttonStyle(.plain)
            }
        }
        .font(.subheadline)
        .frame(height: 42)
        .padding(.horizontal, Theme.Space.md)
        .background(Color(uiColor: .secondarySystemGroupedBackground))
        .clipShape(Capsule())
    }

    private var filterBar: some View {
        HStack(spacing: Theme.Space.sm) {
            ForEach(ConversationFilter.allCases, id: \.self) { f in
                let selected = filter == f
                Button {
                    filter = f
                } label: {
                    Text(f == .unread && vm.unreadTotal > 0 ? "未读 \(vm.unreadTotal > 99 ? "99+" : "\(vm.unreadTotal)")" : f.label)
                        .font(.subheadline.weight(selected ? .semibold : .regular))
                        .foregroundColor(selected ? .primary : .secondary)
                        .padding(.horizontal, Theme.Space.md).padding(.vertical, 6)
                        .background(selected ? Theme.cardBackground : Color.clear)
                        .clipShape(Capsule())
                }
                .buttonStyle(.plain)
            }
            Spacer()
        }
        .padding(.horizontal, Theme.Space.lg)
        .padding(.vertical, Theme.Space.sm)
        .background(Theme.screenBackground)
    }

    private var bottomTabSpacer: some View {
        Color.clear
            .frame(height: 96)
            .listRowInsets(EdgeInsets())
            .listRowSeparator(.hidden)
            .listRowBackground(Color.clear)
    }

    // MARK: - 行内容

    private func rowContent(_ row: ConversationRow) -> some View {
        HStack(spacing: MessageAvatarLayout.conversationAvatarTextGap) {
            ZStack {
                AvatarView(
                    text: row.title,
                    url: row.avatarURL,
                    fallback: row.avatarFallback,
                    size: MessageAvatarLayout.conversationAvatarSize,
                    cornerRadius: MessageAvatarLayout.conversationAvatarCornerRadius
                )
                UnreadBadge(count: row.unread)
                    .frame(
                        width: MessageAvatarLayout.conversationAvatarSize,
                        height: MessageAvatarLayout.conversationAvatarSize,
                        alignment: .topTrailing
                    )
                    .offset(x: MessageAvatarLayout.unreadBadgeOffsetX, y: MessageAvatarLayout.unreadBadgeOffsetY)
                if row.online && row.type == .pinnedCS {
                    Circle()
                        .fill(Color.green)
                        .frame(width: MessageAvatarLayout.onlineIndicatorSize, height: MessageAvatarLayout.onlineIndicatorSize)
                        .overlay(Circle().stroke(Theme.screenBackground, lineWidth: 2))
                        .frame(
                            width: MessageAvatarLayout.conversationAvatarSize,
                            height: MessageAvatarLayout.conversationAvatarSize,
                            alignment: .bottomTrailing
                        )
                        .offset(x: 0, y: MessageAvatarLayout.onlineIndicatorOffsetY)
                }
            }
            .frame(width: MessageAvatarLayout.conversationAvatarSize, height: MessageAvatarLayout.conversationAvatarSize)
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(row.title)
                        .font(.body)
                        .fontWeight(row.unread > 0 ? .bold : .semibold)
                        .foregroundColor(row.hidden || !row.followed ? .secondary : .primary)
                        .lineLimit(1)
                    Spacer(minLength: Theme.Space.xs)
                    Text(formatConversationTimestamp(row.timestamp))
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }
                HStack {
                    Text(row.subtitle)
                        .font(.footnote)
                        .foregroundColor(.secondary)
                        .lineLimit(1)
                    Spacer(minLength: Theme.Space.xs)
                    if case .group = row.kind {
                        ConversationTagBadge(text: "群", color: Theme.brand)
                    } else if !row.followed {
                        ConversationTagBadge(text: "免打扰", color: .secondary)
                    } else if row.pinned {
                        ConversationTagBadge(text: "置顶", color: .orange)
                    }
                }
            }
        }
        .opacity(row.hidden ? 0.55 : 1)
        .contentShape(Rectangle())
    }

    // MARK: - 长按 / 滑动菜单

    @ViewBuilder
    private func contextMenu(for row: ConversationRow) -> some View {
        Button { toggleRead(row) } label: {
            Label(row.unread > 0 ? "标为已读" : "标为未读", systemImage: row.unread > 0 ? "envelope.open" : "envelope.badge")
        }
        Button { togglePin(row) } label: {
            Label(row.pinned ? "取消置顶" : "置顶聊天", systemImage: row.pinned ? "pin.slash" : "pin")
        }
        Button { toggleFollow(row) } label: {
            Label(row.followed ? "不再关注" : "恢复关注", systemImage: row.followed ? "bell.slash" : "bell")
        }
        Button { toggleHide(row) } label: {
            Label(row.hidden ? "显示该聊天" : "不显示该聊天", systemImage: row.hidden ? "eye" : "eye.slash")
        }
        if case .group = row.kind {
            Button(role: .destructive) { deleteRow(row) } label: { Label("删除该聊天", systemImage: "trash") }
        }
    }

    @ViewBuilder
    private func swipeActions(for row: ConversationRow) -> some View {
        Button { actionRow = row } label: { Label("更多", systemImage: "ellipsis") }.tint(.gray)
        Button { togglePin(row) } label: {
            Label(row.pinned ? "取消置顶" : "置顶", systemImage: "pin")
        }.tint(.orange)
        Button { toggleRead(row) } label: {
            Label(row.unread > 0 ? "已读" : "未读", systemImage: "envelope")
        }.tint(.blue)
    }

    @ViewBuilder
    private var actionMenu: some View {
        if let row = actionRow {
            Button(row.unread > 0 ? "标为已读" : "标为未读") { toggleRead(row); actionRow = nil }
            Button(row.pinned ? "取消置顶" : "置顶聊天") { togglePin(row); actionRow = nil }
            Button(row.followed ? "不再关注" : "恢复关注") { toggleFollow(row); actionRow = nil }
            Button(row.hidden ? "显示该聊天" : "不显示该聊天") { toggleHide(row); actionRow = nil }
            if case .fixed(let c) = row.kind {
                Button("查看名片") { actionRow = nil; profileContact = c }
            }
            if case .group = row.kind {
                Button("删除该聊天", role: .destructive) { deleteRow(row); actionRow = nil }
            }
            Button("取消", role: .cancel) { actionRow = nil }
        }
    }

    // MARK: - 操作分发(固定本地 / 群走后端)

    private func toggleRead(_ row: ConversationRow) {
        switch row.kind {
        case .fixed(let c): vm.toggleFixedRead(c.id)
        case .group(let g): vm.groupAction(.toggleRead, group: g, session: session)
        }
    }
    private func togglePin(_ row: ConversationRow) {
        switch row.kind {
        case .fixed(let c): vm.toggleFixedPin(c.id)
        case .group(let g): vm.groupAction(.togglePin, group: g, session: session)
        }
    }
    private func toggleFollow(_ row: ConversationRow) {
        switch row.kind {
        case .fixed(let c): vm.toggleFixedFollow(c.id)
        case .group(let g): vm.groupAction(.toggleFollow, group: g, session: session)
        }
    }
    private func toggleHide(_ row: ConversationRow) {
        switch row.kind {
        case .fixed(let c): vm.toggleFixedHide(c.id)
        case .group(let g): vm.groupAction(.toggleHide, group: g, session: session)
        }
    }
    private func deleteRow(_ row: ConversationRow) {
        if case .group(let g) = row.kind { vm.groupAction(.delete, group: g, session: session) }
    }

    // MARK: - 打开会话 / 路由

    private func markReadOnOpen(_ row: ConversationRow) {
        if case .fixed(let c) = row.kind { vm.markFixedReadOnOpen(c.id) }
    }

    @ViewBuilder
    private func destination(for row: ConversationRow) -> some View {
        switch row.kind {
        case .group(let g):
            AiGroupChatView(group: g)
        case .fixed(let c):
            if c.kind == "dedicated_cs" || row.peerKind == .customerService {
                CsChatView(title: c.name)
            } else {
                ChatView(
                    title: c.name,
                    sessionId: c.id.isEmpty ? "assistant" : c.id,
                    peerKind: row.peerKind,
                    aiAvatarURL: row.avatarURL
                )
            }
        }
    }
}
