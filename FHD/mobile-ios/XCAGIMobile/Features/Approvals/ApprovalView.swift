import SwiftUI

@MainActor
final class ApprovalListViewModel: ObservableObject {
    @Published var items: [ApprovalItem] = []
    @Published var phase: LoadPhase = .idle

    func load(_ api: APIClient) async {
        phase = .loading
        do {
            items = try await api.approvals()
            phase = items.isEmpty ? .empty : .loaded
        } catch {
            phase = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
        }
    }
}

/// 审批列表(对标 Android `ApprovalScreens`)。
struct ApprovalListView: View {
    @EnvironmentObject private var session: SessionManager
    @StateObject private var vm = ApprovalListViewModel()

    var body: some View {
        Group {
            switch vm.phase {
            case .idle, .loading: LoadingView()
            case .failed(let m): ErrorStateView(message: m) { Task { await vm.load(session.api) } }
            case .empty: EmptyStateView(icon: "checkmark.seal", title: "暂无待办审批")
            case .loaded:
                List(vm.items) { item in
                    NavigationLink(value: item) {
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text(item.title ?? "审批").fontWeight(.medium)
                                Spacer()
                                StatusBadge(status: item.status ?? "")
                            }
                            if let sub = item.subtitle, !sub.isEmpty {
                                Text(sub).font(.footnote).foregroundColor(.secondary).lineLimit(2)
                            }
                            if let who = item.applicantName, !who.isEmpty {
                                Text("申请人:\(who)").font(.caption).foregroundColor(.secondary)
                            }
                        }
                        .padding(.vertical, 2)
                    }
                }
                .listStyle(.insetGrouped)
                .refreshable { await vm.load(session.api) }
            }
        }
        .navigationTitle("审批")
        .navigationDestination(for: ApprovalItem.self) { item in
            ApprovalDetailView(id: item.id, onActed: { Task { await vm.load(session.api) } })
        }
        .task { if vm.phase == .idle { await vm.load(session.api) } }
    }
}

@MainActor
final class ApprovalDetailViewModel: ObservableObject {
    @Published var detail: ApprovalDetail?
    @Published var phase: LoadPhase = .idle
    @Published var acting = false
    @Published var opinion = ""

    func load(_ api: APIClient, id: String) async {
        phase = .loading
        do { detail = try await api.approvalDetail(id: id); phase = .loaded }
        catch { phase = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription) }
    }

    func act(_ api: APIClient, id: String, approve: Bool) async -> Bool {
        acting = true
        defer { acting = false }
        do {
            if approve { try await api.approve(id: id, opinion: opinion.isEmpty ? "同意" : opinion) }
            else { try await api.reject(id: id, reason: opinion.isEmpty ? "驳回" : opinion) }
            return true
        } catch {
            phase = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
            return false
        }
    }
}

/// 审批详情 + 通过/驳回。
struct ApprovalDetailView: View {
    let id: String
    var onActed: () -> Void

    @EnvironmentObject private var session: SessionManager
    @Environment(\.dismiss) private var dismiss
    @StateObject private var vm = ApprovalDetailViewModel()

    var body: some View {
        Group {
            switch vm.phase {
            case .idle, .loading: LoadingView()
            case .failed(let m): ErrorStateView(message: m) { Task { await vm.load(session.api, id: id) } }
            case .loaded, .empty: form
            }
        }
        .navigationTitle("审批详情")
        .navigationBarTitleDisplayMode(.inline)
        .task { if vm.phase == .idle { await vm.load(session.api, id: id) } }
    }

    @ViewBuilder
    private var form: some View {
        Form {
            if let d = vm.detail {
                Section("信息") {
                    LabeledContent("标题", value: d.title ?? "—")
                    LabeledContent("单号", value: d.requestNo ?? "—")
                    LabeledContent("申请人", value: d.applicantName ?? "—")
                    LabeledContent("流程", value: d.flowName ?? "—")
                    LabeledContent("当前节点", value: d.currentNodeName ?? "—")
                    LabeledContent("状态", value: d.status ?? "—")
                }
                if let desc = d.description, !desc.isEmpty {
                    Section("说明") { Text(desc) }
                }
            }
            Section("审批意见") {
                TextField("可选,默认同意/驳回", text: $vm.opinion, axis: .vertical).lineLimit(1...3)
            }
            Section {
                HStack(spacing: Theme.Space.lg) {
                    Button(role: .destructive) {
                        Task { if await vm.act(session.api, id: id, approve: false) { onActed(); dismiss() } }
                    } label: { Text("驳回").frame(maxWidth: .infinity) }
                    .buttonStyle(.bordered)

                    Button {
                        Task { if await vm.act(session.api, id: id, approve: true) { onActed(); dismiss() } }
                    } label: { Text("通过").frame(maxWidth: .infinity) }
                    .buttonStyle(.borderedProminent)
                }
                .disabled(vm.acting)
            }
        }
    }
}

/// 状态徽标。
struct StatusBadge: View {
    let status: String
    private var color: Color {
        switch status {
        case "approved", "通过", "已通过": return .green
        case "rejected", "驳回", "已驳回": return .red
        case "pending", "待审批", "审批中": return .orange
        default: return .secondary
        }
    }
    var body: some View {
        Text(status.isEmpty ? "—" : status)
            .font(.caption2).bold()
            .padding(.horizontal, Theme.Space.sm).padding(.vertical, 2)
            .background(color.opacity(0.15))
            .foregroundColor(color)
            .clipShape(Capsule())
    }
}
