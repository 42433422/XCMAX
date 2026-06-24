import SwiftUI

@MainActor
final class AiGroupListViewModel: ObservableObject {
    @Published var groups: [AiGroup] = []
    @Published var phase: LoadPhase = .idle
    @Published var newName = ""
    @Published var creating = false

    func load(_ api: APIClient) async {
        phase = .loading
        do {
            groups = try await api.aiGroups()
            phase = groups.isEmpty ? .empty : .loaded
        } catch {
            phase = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
        }
    }

    func create(_ api: APIClient) async {
        let name = newName.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty, !creating else { return }
        creating = true
        defer { creating = false }
        _ = try? await api.createAiGroup(name: name)
        newName = ""
        await load(api)
    }
}

/// AI 群聊列表(对标 Android `AiGroupScreens`)。
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
                EmptyStateView(icon: "person.3", title: "还没有群聊", subtitle: "点右上角「+」建一个")
            case .loaded:
                List(vm.groups) { group in
                    NavigationLink(value: group) {
                        HStack(spacing: Theme.Space.md) {
                            AvatarView(text: group.name ?? "群", size: 42)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(group.name ?? "群聊").fontWeight(.medium)
                                Text(group.lastMessagePreview ?? "成员 \(group.memberCount ?? 0)")
                                    .font(.footnote).foregroundColor(.secondary).lineLimit(1)
                            }
                            Spacer()
                            if let n = group.unreadCount, n > 0 {
                                Text("\(n)").font(.caption2).bold().foregroundColor(.white)
                                    .padding(6).background(Circle().fill(Color.red))
                            }
                        }
                    }
                }
                .listStyle(.insetGrouped)
                .refreshable { await vm.load(session.api) }
            }
        }
        .navigationTitle("AI 群聊")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                Button { showCreate = true } label: { Image(systemName: "plus") }
            }
        }
        .navigationDestination(for: AiGroup.self) { g in
            AiGroupChatView(group: g)
        }
        .alert("新建群聊", isPresented: $showCreate) {
            TextField("群名称", text: $vm.newName)
            Button("创建") { Task { await vm.create(session.api) } }
            Button("取消", role: .cancel) {}
        }
        .task { if vm.phase == .idle { await vm.load(session.api) } }
    }
}

@MainActor
final class AiGroupChatViewModel: ObservableObject {
    @Published var messages: [AiGroupMessage] = []
    @Published var input = ""
    @Published var sending = false
    @Published var phase: LoadPhase = .idle

    let groupId: String
    init(groupId: String) { self.groupId = groupId }

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

    func send(_ api: APIClient, senderName: String) async {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !sending else { return }
        input = ""
        sending = true
        defer { sending = false }
        do {
            let result = try await api.sendAiGroupMessage(groupId: groupId, message: text, senderName: senderName, mentions: [])
            // 本地先追加自己的消息,再并入服务端返回的成员回复
            messages.append(AiGroupMessage(id: UUID().uuidString, groupId: groupId, role: "user", senderName: senderName, body: text))
            messages.append(contentsOf: result.messages ?? [])
        } catch {
            messages.append(AiGroupMessage(id: UUID().uuidString, groupId: groupId, role: "system", senderName: "系统",
                                           body: "⚠️ " + ((error as? LocalizedError)?.errorDescription ?? "发送失败")))
        }
    }
}

/// AI 群聊会话页。
struct AiGroupChatView: View {
    let group: AiGroup
    @EnvironmentObject private var session: SessionManager
    @StateObject private var vm: AiGroupChatViewModel

    init(group: AiGroup) {
        self.group = group
        _vm = StateObject(wrappedValue: AiGroupChatViewModel(groupId: group.idValue))
    }

    var body: some View {
        VStack(spacing: 0) {
            switch vm.phase {
            case .idle, .loading: LoadingView()
            case .failed(let m): ErrorStateView(message: m) { Task { await vm.load(session.api) } }
            default:
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: Theme.Space.md) {
                            ForEach(vm.messages) { GroupMessageRow(message: $0) }
                        }
                        .padding(Theme.Space.md)
                    }
                    .onChange(of: vm.messages.count) { _ in
                        if let last = vm.messages.last { proxy.scrollTo(last.idValue, anchor: .bottom) }
                    }
                }
            }
            ChatInputBar(text: $vm.input, isBusy: vm.sending) {
                Task { await vm.send(session.api, senderName: session.session.displayName) }
            }
        }
        .navigationTitle(group.name ?? "群聊")
        .navigationBarTitleDisplayMode(.inline)
        .task { if vm.phase == .idle { await vm.load(session.api) } }
    }
}

private struct GroupMessageRow: View {
    let message: AiGroupMessage
    private var isMine: Bool { message.role == "user" }

    var body: some View {
        HStack(alignment: .top, spacing: Theme.Space.sm) {
            if isMine { Spacer(minLength: 32) }
            if !isMine { AvatarView(text: message.senderName ?? "AI", size: 30) }
            VStack(alignment: isMine ? .trailing : .leading, spacing: 2) {
                Text(message.senderName ?? (isMine ? "我" : "AI")).font(.caption2).foregroundColor(.secondary)
                Text(message.body ?? "")
                    .padding(.horizontal, Theme.Space.md).padding(.vertical, Theme.Space.sm)
                    .foregroundColor(isMine ? .white : .primary)
                    .background(isMine ? Theme.brand : Theme.cardBackground)
                    .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.md, style: .continuous))
            }
            if isMine { AvatarView(text: message.senderName ?? "我", size: 30) }
            if !isMine { Spacer(minLength: 32) }
        }
        .id(message.idValue)
    }
}
