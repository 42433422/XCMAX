import SwiftUI

@MainActor
final class ContactsViewModel: ObservableObject {
    @Published var mods: [ModInfo] = []
    @Published var phase: LoadPhase = .idle

    func load(_ api: APIClient) async {
        phase = .loading
        do {
            let data = try await api.mods()
            mods = (data.items ?? []).filter { ($0.workflowEmployees ?? []).isEmpty == false }
            phase = mods.isEmpty ? .empty : .loaded
        } catch {
            phase = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
        }
    }
}

/// 通讯录(对标 Android 通讯录 / 鸿蒙 `ContactsPage`):MOD → 工作流员工 → 进对话。
struct ContactsView: View {
    @EnvironmentObject private var session: SessionManager
    @StateObject private var vm = ContactsViewModel()

    var body: some View {
        NavigationStack {
            Group {
                switch vm.phase {
                case .idle, .loading: LoadingView()
                case .failed(let m): ErrorStateView(message: m) { Task { await vm.load(session.api) } }
                case .empty: EmptyStateView(icon: "person.2", title: "暂无员工")
                case .loaded: list
                }
            }
            .navigationTitle("通讯录")
            .navigationDestination(for: EmployeeRoute.self) { route in
                ChatView(title: route.name, sessionId: route.id)
            }
        }
        .task { if vm.phase == .idle { await vm.load(session.api) } }
    }

    private var list: some View {
        List {
            ForEach(vm.mods, id: \.stableId) { mod in
                Section(mod.name ?? mod.stableId) {
                    ForEach(mod.workflowEmployees ?? [], id: \.self) { emp in
                        NavigationLink(value: EmployeeRoute(emp)) {
                            HStack(spacing: Theme.Space.md) {
                                AvatarView(text: emp.label ?? "员工", size: 40)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(emp.label ?? emp.id ?? "员工").fontWeight(.medium)
                                    if let s = emp.panelSummary, !s.isEmpty {
                                        Text(s).font(.footnote).foregroundColor(.secondary).lineLimit(1)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
        .refreshable { await vm.load(session.api) }
    }
}

/// 员工对话路由(可哈希)。
struct EmployeeRoute: Hashable {
    let id: String
    let name: String
    init(_ emp: WorkflowEmployeeInfo) {
        self.id = emp.id ?? "assistant"
        self.name = emp.label ?? emp.id ?? "员工"
    }
}
