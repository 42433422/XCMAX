import SwiftUI

@MainActor
final class EnterpriseModuleViewModel: ObservableObject {
    @Published var rows: [EnterpriseRow] = []
    @Published var phase: LoadPhase = .idle

    func load(_ api: APIClient, kind: EnterpriseModuleView.Kind) async {
        phase = .loading
        do {
            switch kind {
            case .customers:
                rows = (try await api.customers().items ?? []).map {
                    EnterpriseRow(id: $0.idValue, title: $0.name ?? "客户#\($0.idValue)", subtitle: $0.phone ?? "", status: nil)
                }
            case .shipments:
                rows = (try await api.shipments().items ?? []).map {
                    EnterpriseRow(id: $0.idValue, title: $0.orderNumber ?? "发货#\($0.idValue)", subtitle: "", status: $0.status)
                }
            case .serviceBridge:
                rows = (try await api.serviceBridgeRequests().items ?? []).map {
                    EnterpriseRow(id: $0.idValue, title: $0.title ?? "工单#\($0.idValue)", subtitle: $0.description ?? "", status: $0.status)
                }
            }
            phase = rows.isEmpty ? .empty : .loaded
        } catch {
            phase = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
        }
    }
}

struct EnterpriseRow: Identifiable, Hashable {
    let id: Int
    let title: String
    let subtitle: String
    let status: String?
}

/// 企业模块通用列表(客户/发货/服务桥)(对标 Android `EnterpriseScreens`)。
struct EnterpriseModuleView: View {
    enum Kind { case customers, shipments, serviceBridge
        var title: String {
            switch self { case .customers: return "客户"; case .shipments: return "发货"; case .serviceBridge: return "服务桥工单" }
        }
        var emptyIcon: String {
            switch self { case .customers: return "person.text.rectangle"; case .shipments: return "shippingbox"; case .serviceBridge: return "arrow.left.arrow.right.circle" }
        }
    }

    let kind: Kind
    @EnvironmentObject private var session: SessionManager
    @StateObject private var vm = EnterpriseModuleViewModel()

    var body: some View {
        Group {
            switch vm.phase {
            case .idle, .loading: LoadingView()
            case .failed(let m): ErrorStateView(message: m) { Task { await vm.load(session.api, kind: kind) } }
            case .empty: EmptyStateView(icon: kind.emptyIcon, title: "暂无数据")
            case .loaded:
                List(vm.rows) { row in
                    VStack(alignment: .leading, spacing: 3) {
                        HStack {
                            Text(row.title).fontWeight(.medium)
                            Spacer()
                            if let s = row.status, !s.isEmpty { StatusBadge(status: s) }
                        }
                        if !row.subtitle.isEmpty {
                            Text(row.subtitle).font(.footnote).foregroundColor(.secondary).lineLimit(2)
                        }
                    }
                    .padding(.vertical, 2)
                }
                .listStyle(.insetGrouped)
                .refreshable { await vm.load(session.api, kind: kind) }
            }
        }
        .navigationTitle(kind.title)
        .navigationBarTitleDisplayMode(.inline)
        .task { if vm.phase == .idle { await vm.load(session.api, kind: kind) } }
    }
}
