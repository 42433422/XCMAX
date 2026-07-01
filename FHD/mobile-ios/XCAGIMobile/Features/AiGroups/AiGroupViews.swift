import SwiftUI

// ══════════════════════════════════════════
//  AI 员工档案(对标 Android AiEmployeeProfile / aiEmployeeProfiles)
//  由 ModInfo.workflowEmployees 派生,供「建群多选」和「群成员管理」选人。
// ══════════════════════════════════════════
struct AiEmployeeProfile: Identifiable, Hashable {
    let modId: String
    let modName: String
    let employeeId: String
    let name: String
    let summary: String
    let avatarUrl: String?

    /// 与 Android 一致:modId:employeeId 作为去重/选择键。
    var key: String { "\(modId):\(employeeId)" }
    var id: String { key }
}

extension Array where Element == ModInfo {
    /// 把 MOD 的工作流员工摊平成可选人的 AI 员工档案(对标 Android `List<ModInfo>.aiEmployeeProfiles()`)。
    func aiEmployeeProfiles() -> [AiEmployeeProfile] {
        flatMap { mod -> [AiEmployeeProfile] in
            let modId = mod.stableId
            let modName = (mod.name?.isEmpty == false ? mod.name : mod.id) ?? modId
            return (mod.workflowEmployees ?? []).compactMap { emp -> AiEmployeeProfile? in
                let employeeId = (emp.id ?? "").trimmingCharacters(in: .whitespaces)
                let name = (emp.label ?? emp.id ?? "").trimmingCharacters(in: .whitespaces)
                guard !employeeId.isEmpty, !name.isEmpty else { return nil }
                let summary = [emp.panelSummary, mod.description]
                    .compactMap { $0 }
                    .first(where: { !$0.isEmpty })
                    ?? "由当前账号生态的 \(modName ?? modId) 同步到手机端。"
                return AiEmployeeProfile(
                    modId: modId,
                    modName: modName ?? modId,
                    employeeId: employeeId,
                    name: name,
                    summary: summary,
                    avatarUrl: emp.resolvedAvatar
                )
            }
        }
    }
}

// ══════════════════════════════════════════
//  群列表 ViewModel(置顶/标未读/关注/隐藏/删除 + 建群多选)
// ══════════════════════════════════════════
@MainActor
final class AiGroupListViewModel: ObservableObject {
    @Published var groups: [AiGroup] = []
    @Published var phase: LoadPhase = .idle
    /// 可选 AI 员工(建群多选用),由 mods() 派生。
    @Published var employees: [AiEmployeeProfile] = []

    func load(_ api: APIClient) async {
        phase = .loading
        do {
            groups = try await api.aiGroups()
            phase = groups.isEmpty ? .empty : .loaded
        } catch {
            phase = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
        }
    }

    /// 刷新可选 AI 员工(对标 Android `vm.refreshModInfos()` + `aiEmployeeProfiles()`)。
    func loadEmployees(_ api: APIClient) async {
        if let data = try? await api.mods() {
            employees = (data.items ?? []).aiEmployeeProfiles()
        }
    }

    /// 单纯重载列表(操作后刷新)。
    private func reload(_ api: APIClient) async {
        if let fresh = try? await api.aiGroups() {
            groups = fresh
            phase = fresh.isEmpty ? .empty : .loaded
        }
    }

    func togglePin(_ api: APIClient, _ group: AiGroup) async {
        _ = try? await api.toggleAiGroupPin(groupId: group.idValue)
        await reload(api)
    }

    func markUnread(_ api: APIClient, _ group: AiGroup) async {
        _ = try? await api.markAiGroupUnread(groupId: group.idValue)
        await reload(api)
    }

    func toggleFollowed(_ api: APIClient, _ group: AiGroup) async {
        _ = try? await api.toggleAiGroupFollowed(groupId: group.idValue)
        await reload(api)
    }

    func toggleHidden(_ api: APIClient, _ group: AiGroup) async {
        _ = try? await api.toggleAiGroupHidden(groupId: group.idValue)
        await reload(api)
    }

    func delete(_ api: APIClient, _ group: AiGroup) async {
        try? await api.deleteAiGroup(groupId: group.idValue)
        await reload(api)
    }
}

/// AI 群聊列表(对标 Android `AiGroupListScreen`)。
struct AiGroupListView: View {
    @EnvironmentObject private var session: SessionManager
    @StateObject private var vm = AiGroupListViewModel()
    @State private var showCreate = false

    var body: some View {
        Group {
            switch vm.phase {
            case .idle, .loading: LoadingView()
            case .failed(let m): ErrorStateView(message: m) { Task { await vm.load(session.api) } }
            case .empty:
                EmptyStateView(icon: "person.3", title: "还没有群聊", subtitle: "点右上角「+」拉 AI 员工建群")
            case .loaded:
                List {
                    ForEach(vm.groups) { group in
                        ZStack {
                            NavigationLink(value: group) { EmptyView() }.opacity(0)
                            GroupConversationRow(group: group)
                        }
                        .listRowInsets(EdgeInsets(top: 0, leading: 0, bottom: 0, trailing: 0))
                        .listRowBackground(group.isPinned == true ? Theme.cardBackground : Color(uiColor: .systemBackground))
                        .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                            Button(role: .destructive) {
                                Task { await vm.delete(session.api, group) }
                            } label: { Label("删除", systemImage: "trash") }
                            Button {
                                Task { await vm.toggleHidden(session.api, group) }
                            } label: {
                                Label(group.isHidden == true ? "显示" : "隐藏", systemImage: "eye.slash")
                            }.tint(.gray)
                        }
                        .swipeActions(edge: .leading, allowsFullSwipe: false) {
                            Button {
                                Task { await vm.togglePin(session.api, group) }
                            } label: {
                                Label(group.isPinned == true ? "取消置顶" : "置顶", systemImage: "pin")
                            }.tint(Theme.brand)
                            Button {
                                Task { await vm.markUnread(session.api, group) }
                            } label: { Label("标未读", systemImage: "circle.badge") }.tint(.orange)
                        }
                        // 长按菜单:与 Android 长按弹窗一一对应。
                        .contextMenu {
                            Button { Task { await vm.markUnread(session.api, group) } } label: {
                                Label("标为未读", systemImage: "circle.badge")
                            }
                            Button { Task { await vm.togglePin(session.api, group) } } label: {
                                Label(group.isPinned == true ? "取消置顶" : "置顶聊天", systemImage: "pin")
                            }
                            Button { Task { await vm.toggleFollowed(session.api, group) } } label: {
                                Label(group.isFollowed == false ? "恢复关注" : "不再关注", systemImage: "bell.slash")
                            }
                            Button { Task { await vm.toggleHidden(session.api, group) } } label: {
                                Label(group.isHidden == true ? "显示该聊天" : "不显示该聊天", systemImage: "eye.slash")
                            }
                            Button(role: .destructive) { Task { await vm.delete(session.api, group) } } label: {
                                Label("删除该聊天", systemImage: "trash")
                            }
                        }
                    }
                }
                .listStyle(.plain)
                .refreshable { await vm.load(session.api) }
            }
        }
        .navigationTitle("群聊")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                Button { showCreate = true } label: { Image(systemName: "plus") }
            }
        }
        .navigationDestination(for: AiGroup.self) { g in
            AiGroupChatView(group: g)
        }
        .sheet(isPresented: $showCreate) {
            NavigationStack {
                AiGroupCreateView(employees: vm.employees) {
                    showCreate = false
                    Task { await vm.load(session.api) }
                }
            }
        }
        .task {
            if vm.phase == .idle { await vm.load(session.api) }
            await vm.loadEmployees(session.api)
        }
    }
}

// ══════════════════════════════════════════
//  微信式九宫格群头像(最多 9 个,空群占位图标)
// ══════════════════════════════════════════
struct GroupGridAvatar: View {
    let members: [AiGroupMember]
    var size: CGFloat = 52

    private var shown: [AiGroupMember] { Array(members.prefix(9)) }

    var body: some View {
        let n = shown.count
        let cols = n <= 1 ? 1 : (n <= 4 ? 2 : 3)
        let gap: CGFloat = 1.5
        let cell = (size - gap * CGFloat(cols + 1)) / CGFloat(cols)
        RoundedRectangle(cornerRadius: 10, style: .continuous)
            .fill(Color(uiColor: .tertiarySystemFill))
            .frame(width: size, height: size)
            .overlay {
                if n == 0 {
                    Image(systemName: "person.3.fill")
                        .font(.system(size: size * 0.42))
                        .foregroundColor(.secondary)
                } else {
                    let rows = Int(ceil(Double(n) / Double(cols)))
                    VStack(spacing: gap) {
                        ForEach(0..<rows, id: \.self) { r in
                            HStack(spacing: gap) {
                                ForEach(0..<cols, id: \.self) { c in
                                    let idx = r * cols + c
                                    if idx < n {
                                        AvatarView(
                                            text: shown[idx].name ?? "AI",
                                            url: shown[idx].avatar,
                                            fallback: aiGroupAvatarFallback(
                                                employeeId: shown[idx].employeeId,
                                                name: shown[idx].name ?? "",
                                                avatarKey: shown[idx].avatarKey ?? ""
                                            ),
                                            size: cell,
                                            cornerRadius: 8
                                        )
                                    } else {
                                        Color.clear.frame(width: cell, height: cell)
                                    }
                                }
                            }
                        }
                    }
                    .padding(gap)
                }
            }
    }
}

/// 群聊在列表里的一行(九宫格头像 + 名字(成员数) + 预览 + 未读/时间 + 置顶/隐藏视觉态)。
private struct GroupConversationRow: View {
    let group: AiGroup

    private var dimmed: Bool { group.isHidden == true || group.isFollowed == false }

    private var preview: String {
        if let p = group.lastMessagePreview, !p.isEmpty { return p }
        let count = group.memberCount ?? 0
        return count == 0 ? "还没有成员,进群把 AI 拉进来" : "\(count) 个 AI 成员在群里"
    }

    var body: some View {
        HStack(spacing: Theme.Space.md) {
            GroupGridAvatar(members: group.members ?? [], size: 52)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 4) {
                    if group.isPinned == true {
                        Image(systemName: "pin.fill")
                            .font(.system(size: 11))
                            .foregroundColor(Theme.brand)
                    }
                    Text(group.name ?? "群聊")
                        .font(.system(size: 16, weight: .medium))
                        .foregroundColor(dimmed ? .secondary : .primary)
                        .lineLimit(1)
                    if let c = group.memberCount, c > 0 {
                        Text("(\(c))").font(.caption).foregroundColor(.secondary)
                    }
                }
                Text(preview)
                    .font(.footnote).foregroundColor(.secondary).lineLimit(1)
            }
            Spacer(minLength: Theme.Space.sm)
            VStack(alignment: .trailing, spacing: 4) {
                if let n = group.unreadCount, n > 0 {
                    Text(n > 99 ? "99+" : "\(n)")
                        .font(.system(size: 10)).bold().foregroundColor(.white)
                        .padding(.horizontal, 6).padding(.vertical, 1)
                        .background(Capsule().fill(Color.red))
                } else if let at = group.lastMessageAt, !at.isEmpty {
                    Text(at).font(.caption2).foregroundColor(Color.secondary.opacity(0.7))
                }
                if group.isFollowed == false && (group.unreadCount ?? 0) == 0 {
                    Text("不再关注")
                        .font(.system(size: 10)).foregroundColor(Color.secondary.opacity(0.6))
                }
            }
        }
        .padding(.horizontal, Theme.Space.lg)
        .padding(.vertical, 11)
        .contentShape(Rectangle())
    }
}

// ══════════════════════════════════════════
//  建群:多选 AI 员工 → 一次建群(对标 Android AiGroupCreateScreen)
// ══════════════════════════════════════════
struct AiGroupCreateView: View {
    let employees: [AiEmployeeProfile]
    var onCreated: () -> Void

    @EnvironmentObject private var session: SessionManager
    @Environment(\.dismiss) private var dismiss
    @State private var selectedKeys: Set<String> = []
    @State private var name = ""
    @State private var creating = false

    private var picked: [AiEmployeeProfile] { employees.filter { selectedKeys.contains($0.key) } }
    private var autoName: String { String(picked.map { $0.name }.joined(separator: "、").prefix(40)) }

    var body: some View {
        VStack(spacing: 0) {
            TextField(autoName.isEmpty ? "群名称(可留空,自动命名)" : autoName, text: $name)
                .textFieldStyle(.roundedBorder)
                .padding(.horizontal, Theme.Space.md)
                .padding(.vertical, Theme.Space.sm)
            Divider()
            if employees.isEmpty {
                EmptyStateView(icon: "person.crop.circle.badge.questionmark",
                               title: "暂无可选 AI 员工",
                               subtitle: "先在「AI员工」里同步")
            } else {
                List {
                    ForEach(employees) { e in
                        let checked = selectedKeys.contains(e.key)
                        Button {
                            if checked { selectedKeys.remove(e.key) } else { selectedKeys.insert(e.key) }
                        } label: {
                            HStack(spacing: Theme.Space.md) {
                                Image(systemName: checked ? "checkmark.circle.fill" : "circle")
                                    .foregroundColor(checked ? Theme.brand : .secondary)
                                AvatarView(
                                    text: e.name,
                                    url: e.avatarUrl,
                                    fallback: aiGroupAvatarFallback(employeeId: e.employeeId, name: e.name),
                                    size: MessageAvatarLayout.bubbleAvatarSize,
                                    cornerRadius: MessageAvatarLayout.bubbleAvatarCornerRadius
                                )
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(e.name).fontWeight(.medium).foregroundColor(.primary).lineLimit(1)
                                    Text(e.summary).font(.caption).foregroundColor(.secondary).lineLimit(1)
                                }
                                Spacer()
                            }
                        }
                    }
                }
                .listStyle(.plain)
            }
        }
        .navigationTitle("发起群聊")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .navigationBarLeading) {
                Button("取消") { dismiss() }
            }
            ToolbarItem(placement: .navigationBarTrailing) {
                Button(selectedKeys.isEmpty ? "完成" : "完成(\(selectedKeys.count))") {
                    Task { await create() }
                }
                .disabled(selectedKeys.isEmpty || creating)
            }
        }
    }

    private func create() async {
        guard !creating else { return }
        creating = true
        defer { creating = false }
        let drafts = picked.map {
            AiGroupMemberDraft(employeeId: $0.employeeId, modId: $0.modId,
                               name: $0.name, avatar: $0.avatarUrl ?? "", summary: $0.summary)
        }
        let trimmed = name.trimmingCharacters(in: .whitespaces)
        let finalName = !trimmed.isEmpty ? trimmed : (autoName.isEmpty ? "新建群聊" : autoName)
        _ = try? await session.api.createGroupWithMembers(name: finalName, members: drafts)
        dismiss()
        onCreated()
    }
}

// ══════════════════════════════════════════
//  群聊会话 ViewModel(@成员 + 群成员增删 + 正在回复)
// ══════════════════════════════════════════
@MainActor
final class AiGroupChatViewModel: ObservableObject {
    @Published var group: AiGroup
    @Published var messages: [AiGroupMessage] = []
    @Published var input = ""
    @Published var sending = false
    @Published var phase: LoadPhase = .idle
    /// 可添加的 AI 员工(群成员管理用)。
    @Published var employees: [AiEmployeeProfile] = []

    var groupId: String { group.idValue }
    init(group: AiGroup) { self.group = group }

    func load(_ api: APIClient) async {
        phase = .loading
        do {
            messages = try await api.aiGroupMessages(groupId: groupId)
            phase = .loaded
            try? await api.markAiGroupRead(groupId: groupId)
        } catch {
            phase = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
        }
    }

    func loadEmployees(_ api: APIClient) async {
        if let data = try? await api.mods() {
            employees = (data.items ?? []).aiEmployeeProfiles()
        }
    }

    /// @某成员:把「@名字 」拼到输入框开头(对标 Android「@成员 可单独点名」)。
    func mention(_ member: AiGroupMember) {
        let tag = "@\(member.name ?? "成员") "
        if !input.hasPrefix(tag) { input = tag + input }
    }

    func send(_ api: APIClient, senderName: String) async {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !sending else { return }
        // 解析 @提及:命中群成员名字的 @标记转成 employeeId 列表传给后端。
        let mentions = (group.members ?? []).compactMap { m -> String? in
            guard let name = m.name, !name.isEmpty, text.contains("@\(name)") else { return nil }
            return m.employeeId
        }
        input = ""
        sending = true
        defer { sending = false }
        // 本地先回显自己的消息。
        messages.append(AiGroupMessage(id: UUID().uuidString, groupId: groupId,
                                       role: "user", senderName: senderName, body: text))
        do {
            let result = try await api.sendAiGroupMessage(groupId: groupId, message: text,
                                                          senderName: senderName, mentions: mentions)
            messages.append(contentsOf: result.messages ?? [])
        } catch {
            messages.append(AiGroupMessage(id: UUID().uuidString, groupId: groupId, role: "system",
                                           senderName: "系统",
                                           body: "⚠️ " + ((error as? LocalizedError)?.errorDescription ?? "发送失败")))
        }
    }

    func addMember(_ api: APIClient, _ emp: AiEmployeeProfile) async {
        if let updated = try? await api.addAiGroupMember(
            groupId: groupId, employeeId: emp.employeeId, modId: emp.modId,
            name: emp.name, avatar: emp.avatarUrl ?? "", summary: emp.summary
        ), updated.id != nil {
            group = updated
        }
    }

    func removeMember(_ api: APIClient, _ employeeId: String) async {
        if let updated = try? await api.removeAiGroupMember(groupId: groupId, employeeId: employeeId),
           updated.id != nil {
            group = updated
        }
    }
}

/// AI 群聊会话页(对标 Android `AiGroupChatScreen`)。
struct AiGroupChatView: View {
    @EnvironmentObject private var session: SessionManager
    @StateObject private var vm: AiGroupChatViewModel
    @State private var showMembers = false

    init(group: AiGroup) {
        _vm = StateObject(wrappedValue: AiGroupChatViewModel(group: group))
    }

    var body: some View {
        VStack(spacing: 0) {
            switch vm.phase {
            case .idle, .loading: LoadingView()
            case .failed(let m): ErrorStateView(message: m) { Task { await vm.load(session.api) } }
            default:
                if vm.messages.isEmpty {
                    groupEmptyState
                } else {
                    messageList
                }
            }
            inputBar
        }
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .principal) {
                HStack(spacing: Theme.Space.sm) {
                    GroupGridAvatar(members: vm.group.members ?? [], size: 30)
                    VStack(alignment: .leading, spacing: 0) {
                        Text(vm.group.name ?? "群聊")
                            .font(.system(size: 16, weight: .medium)).lineLimit(1)
                        if let c = vm.group.memberCount, c > 0 {
                            Text("\(c) 个 AI 成员").font(.caption2).foregroundColor(.secondary)
                        }
                    }
                }
            }
            ToolbarItem(placement: .navigationBarTrailing) {
                Button { showMembers = true } label: { Image(systemName: "person.2.badge.plus") }
            }
        }
        .sheet(isPresented: $showMembers) {
            GroupMembersSheet(
                group: vm.group,
                employees: vm.employees,
                onAdd: { emp in await vm.addMember(session.api, emp) },
                onRemove: { id in await vm.removeMember(session.api, id) }
            )
        }
        .task {
            if vm.phase == .idle { await vm.load(session.api) }
            await vm.loadEmployees(session.api)
        }
    }

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 2) {
                    ForEach(vm.messages) { msg in
                        GroupBubble(message: msg, userName: session.session.displayName) {
                            // 点头像 @TA(仅 AI 成员)
                            if msg.role != "user",
                               let member = (vm.group.members ?? []).first(where: {
                                   ($0.employeeId != nil && $0.employeeId == msg.senderId) || $0.name == msg.senderName
                               }) {
                                vm.mention(member)
                            }
                        }
                    }
                    if vm.sending { GroupTypingRow() }
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 6)
            }
            .onChange(of: vm.messages.count) { _ in
                if let last = vm.messages.last { withAnimation { proxy.scrollTo(last.idValue, anchor: .bottom) } }
            }
            .onChange(of: vm.sending) { busy in
                if busy { withAnimation { proxy.scrollTo("typing", anchor: .bottom) } }
            }
        }
    }

    private var groupEmptyState: some View {
        VStack(spacing: Theme.Space.md) {
            GroupGridAvatar(members: vm.group.members ?? [], size: 64)
            Text((vm.group.memberCount ?? 0) == 0 ? "群里还没有 AI 成员" : "群里安静得很")
                .font(.body).fontWeight(.medium)
            Text((vm.group.memberCount ?? 0) == 0 ? "点右上角把 AI 员工拉进群,然后开聊" : "发条消息,群成员会各自回复你")
                .font(.footnote).foregroundColor(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding(.horizontal, 40)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var inputBar: some View {
        HStack(spacing: Theme.Space.sm) {
            TextField("发群消息(@成员 可单独点名)", text: $vm.input, axis: .vertical)
                .lineLimit(1...4)
                .padding(.horizontal, Theme.Space.md)
                .padding(.vertical, Theme.Space.sm)
                .background(Theme.cardBackground)
                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.lg, style: .continuous))
            Button {
                Task { await vm.send(session.api, senderName: session.session.displayName) }
            } label: {
                Image(systemName: vm.sending ? "ellipsis" : "arrow.up.circle.fill")
                    .font(.system(size: 30))
                    .foregroundColor(canSend ? Theme.brand : .secondary)
            }
            .disabled(!canSend)
        }
        .padding(Theme.Space.sm)
        .background(.bar)
    }

    private var canSend: Bool {
        !vm.input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !vm.sending
    }
}

// ══════════════════════════════════════════
//  群消息气泡(微信群风格:每条显示发送者名 + 头像)
// ══════════════════════════════════════════
private struct GroupBubble: View {
    let message: AiGroupMessage
    let userName: String
    var onTapAvatar: () -> Void = {}

    private var isUser: Bool { message.role == "user" }
    private var isSystem: Bool { message.role == "system" }

    var body: some View {
        if isSystem {
            HStack {
                Spacer()
                Text(message.body ?? "")
                    .font(.caption).foregroundColor(.secondary)
                    .padding(.horizontal, Theme.Space.md).padding(.vertical, Theme.Space.xs)
                    .background(Theme.cardBackground)
                    .clipShape(Capsule())
                Spacer()
            }
            .padding(.vertical, 4)
            .id(message.idValue)
        } else {
            HStack(alignment: .top, spacing: Theme.Space.sm) {
                if isUser { Spacer(minLength: 40) }
                if !isUser {
                    AvatarView(
                        text: message.senderName ?? "AI",
                        url: message.senderAvatar,
                        fallback: aiGroupAvatarFallback(employeeId: message.senderId, name: message.senderName ?? ""),
                        size: MessageAvatarLayout.bubbleAvatarSize,
                        cornerRadius: MessageAvatarLayout.bubbleAvatarCornerRadius
                    )
                        .onTapGesture { onTapAvatar() }
                }
                VStack(alignment: isUser ? .trailing : .leading, spacing: 2) {
                    Text(isUser ? (userName.isEmpty ? "我" : userName) : (message.senderName ?? "AI"))
                        .font(.caption2).foregroundColor(.secondary)
                    Text(message.body ?? "")
                        .font(.system(size: 15))
                        .padding(.horizontal, Theme.Space.md).padding(.vertical, 10)
                        .foregroundColor(isUser ? .white : .primary)
                        .background(isUser ? Theme.brand : Theme.cardBackground)
                        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.md, style: .continuous))
                        .frame(maxWidth: 260, alignment: isUser ? .trailing : .leading)
                }
                if !isUser { Spacer(minLength: 40) }
                if isUser {
                    AvatarView(
                        text: userName.isEmpty ? "我" : userName,
                        fallback: .user,
                        size: MessageAvatarLayout.bubbleAvatarSize,
                        cornerRadius: MessageAvatarLayout.bubbleAvatarCornerRadius
                    )
                }
            }
            .padding(.top, 8).padding(.bottom, 2)
            .id(message.idValue)
        }
    }
}

/// 正在回复指示(对标 Android GroupTypingRow)。
private struct GroupTypingRow: View {
    var body: some View {
        HStack(alignment: .top, spacing: Theme.Space.sm) {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(Color(uiColor: .tertiarySystemFill))
                .frame(width: 40, height: 40)
                .overlay { Image(systemName: "person.3.fill").foregroundColor(.secondary) }
            HStack(spacing: Theme.Space.sm) {
                ProgressView().scaleEffect(0.7)
                Text("AI 成员正在回复…").font(.subheadline).foregroundColor(.secondary)
            }
            .padding(.horizontal, Theme.Space.md).padding(.vertical, 11)
            .background(Theme.cardBackground)
            .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.md, style: .continuous))
            Spacer(minLength: 40)
        }
        .padding(.top, 8).padding(.bottom, 2)
        .id("typing")
    }
}

// ══════════════════════════════════════════
//  群成员管理 Sheet(查看 / 移除 / 添加 AI)
// ══════════════════════════════════════════
private struct GroupMembersSheet: View {
    let group: AiGroup
    let employees: [AiEmployeeProfile]
    var onAdd: (AiEmployeeProfile) async -> Void
    var onRemove: (String) async -> Void

    @Environment(\.dismiss) private var dismiss

    private var memberIds: Set<String> {
        Set((group.members ?? []).compactMap { $0.employeeId })
    }
    private var addable: [AiEmployeeProfile] {
        employees.filter { !memberIds.contains($0.employeeId) }
    }

    var body: some View {
        NavigationStack {
            List {
                Section("群成员(\(group.memberCount ?? (group.members?.count ?? 0)))") {
                    ForEach(group.members ?? [], id: \.self) { m in
                        HStack(spacing: Theme.Space.md) {
                            AvatarView(
                                text: m.name ?? "AI",
                                url: m.avatar,
                                fallback: aiGroupAvatarFallback(
                                    employeeId: m.employeeId,
                                    name: m.name ?? "",
                                    avatarKey: m.avatarKey ?? ""
                                ),
                                size: 38,
                                cornerRadius: 8
                            )
                            Text(m.name ?? "AI 成员").foregroundColor(.primary)
                            Spacer()
                            if let id = m.employeeId {
                                Button(role: .destructive) {
                                    Task { await onRemove(id) }
                                } label: {
                                    Image(systemName: "person.badge.minus").foregroundColor(.red)
                                }
                                .buttonStyle(.borderless)
                            }
                        }
                    }
                }

                Section("添加 AI 成员") {
                    if addable.isEmpty {
                        Text(employees.isEmpty ? "暂无可用 AI 员工,先在「AI员工」里同步" : "已把所有 AI 员工都拉进群了")
                            .font(.footnote).foregroundColor(.secondary)
                    } else {
                        ForEach(addable) { emp in
                            Button {
                                Task { await onAdd(emp) }
                            } label: {
                                HStack(spacing: Theme.Space.md) {
                                    AvatarView(
                                        text: emp.name,
                                        url: emp.avatarUrl,
                                        fallback: aiGroupAvatarFallback(employeeId: emp.employeeId, name: emp.name),
                                        size: 38,
                                        cornerRadius: 8
                                    )
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(emp.name).foregroundColor(.primary).lineLimit(1)
                                        Text(emp.summary).font(.caption).foregroundColor(.secondary).lineLimit(1)
                                    }
                                    Spacer()
                                    Image(systemName: "plus.circle.fill").foregroundColor(Theme.brand)
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("群成员")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("完成") { dismiss() }
                }
            }
        }
    }
}
