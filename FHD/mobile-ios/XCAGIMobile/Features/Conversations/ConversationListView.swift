import SwiftUI

@MainActor
final class ConversationListViewModel: ObservableObject {
    @Published var top: [FixedContactDto] = []
    @Published var bottom: [FixedContactDto] = []
    @Published var phase: LoadPhase = .idle

    func load(_ api: APIClient) async {
        phase = .loading
        do {
            let data = try await api.contactsFixed()
            top = data.top ?? []
            bottom = data.bottom ?? []
            phase = (top.isEmpty && bottom.isEmpty) ? .empty : .loaded
        } catch {
            phase = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
        }
    }
}

/// 消息列表(对标 Android `ConversationListScreen`):固定联系人 → 进入对话。
struct ConversationListView: View {
    @EnvironmentObject private var session: SessionManager
    @StateObject private var vm = ConversationListViewModel()
    @State private var profileContact: FixedContactDto?

    var body: some View {
        NavigationStack {
            Group {
                switch vm.phase {
                case .idle, .loading:
                    LoadingView()
                case .failed(let m):
                    ErrorStateView(message: m) { Task { await vm.load(session.api) } }
                case .empty:
                    EmptyStateView(icon: "bubble.left", title: "暂无会话")
                case .loaded:
                    list
                }
            }
            .navigationTitle("消息")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    NavigationLink {
                        AiGroupListView()
                    } label: { Image(systemName: "person.3.sequence.fill") }
                }
            }
            .navigationDestination(for: FixedContactDto.self) { contact in
                destination(for: contact)
            }
            .sheet(item: $profileContact) { c in
                NavigationStack { FixedPartnerProfileView(contact: c) }
            }
        }
        .task {
            if vm.phase == .idle { await vm.load(session.api) }
        }
    }

    private var list: some View {
        List {
            if !vm.top.isEmpty {
                Section {
                    ForEach(vm.top) { row($0) }
                }
            }
            if !vm.bottom.isEmpty {
                Section {
                    ForEach(vm.bottom) { row($0) }
                }
            }
        }
        .listStyle(.insetGrouped)
        .refreshable { await vm.load(session.api) }
    }

    private func row(_ c: FixedContactDto) -> some View {
        NavigationLink(value: c) {
            HStack(spacing: Theme.Space.md) {
                AvatarView(text: c.name)
                VStack(alignment: .leading, spacing: 2) {
                    Text(c.name).font(.body).fontWeight(.medium)
                    Text(c.summary.isEmpty ? "点击开始对话" : c.summary)
                        .font(.footnote).foregroundColor(.secondary)
                        .lineLimit(1)
                }
            }
            .padding(.vertical, 2)
        }
        .swipeActions(edge: .leading, allowsFullSwipe: false) {
            Button { profileContact = c } label: { Label("名片", systemImage: "person.crop.circle") }
                .tint(.blue)
        }
    }

    @ViewBuilder
    private func destination(for contact: FixedContactDto) -> some View {
        if contact.kind == "dedicated_cs" {
            CsChatView(title: contact.name)
        } else {
            ChatView(title: contact.name, sessionId: contact.id.isEmpty ? "assistant" : contact.id)
        }
    }
}
