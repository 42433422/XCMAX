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
    @State private var respondTarget: EnterpriseRow?

    var body: some View {
        Group {
            switch vm.phase {
            case .idle, .loading: LoadingView()
            case .failed(let m): ErrorStateView(message: m) { Task { await vm.load(session.api, kind: kind) } }
            case .empty: EmptyStateView(icon: kind.emptyIcon, title: "暂无数据")
            case .loaded:
                List(vm.rows) { row in
                    if kind == .serviceBridge {
                        Button { respondTarget = row } label: { rowContent(row) }
                            .buttonStyle(.plain)
                    } else {
                        rowContent(row)
                    }
                }
                .listStyle(.insetGrouped)
                .refreshable { await vm.load(session.api, kind: kind) }
            }
        }
        .navigationTitle(kind.title)
        .navigationBarTitleDisplayMode(.inline)
        .sheet(item: $respondTarget) { row in
            BridgeRespondSheet(row: row) {
                await vm.load(session.api, kind: kind)
            }
        }
        .task { if vm.phase == .idle { await vm.load(session.api, kind: kind) } }
    }

    private func rowContent(_ row: EnterpriseRow) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack {
                Text(row.title).fontWeight(.medium)
                Spacer()
                if let s = row.status, !s.isEmpty { StatusBadge(status: s) }
                if kind == .serviceBridge { Image(systemName: "chevron.right").font(.caption).foregroundColor(.secondary) }
            }
            if !row.subtitle.isEmpty {
                Text(row.subtitle).font(.footnote).foregroundColor(.secondary).lineLimit(2)
            }
        }
        .padding(.vertical, 2)
    }
}

/// 服务桥工单回复表单(对标 Android `BridgeScreen`)。
private struct BridgeRespondSheet: View {
    let row: EnterpriseRow
    var onDone: () async -> Void

    @EnvironmentObject private var session: SessionManager
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @State private var status = "resolved"
    @State private var submitting = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                Section(row.title) {
                    if !row.subtitle.isEmpty { Text(row.subtitle).font(.footnote).foregroundColor(.secondary) }
                }
                Section("处理结果") {
                    Picker("状态", selection: $status) {
                        Text("已处理").tag("resolved")
                        Text("处理中").tag("processing")
                        Text("已关闭").tag("closed")
                    }
                    TextField("输入处理意见或补充说明", text: $text, axis: .vertical).lineLimit(2...5)
                }
                if let e = error { Section { Text(e).font(.footnote).foregroundColor(.red) } }
            }
            .navigationTitle("回复工单")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("提交") { submit() }
                        .disabled(text.trimmingCharacters(in: .whitespaces).isEmpty || submitting)
                }
            }
        }
        .presentationDetents([.medium, .large])
    }

    private func submit() {
        submitting = true
        error = nil
        Task {
            do {
                try await session.api.serviceBridgeRespond(id: row.id, response: text, status: status)
                await onDone()
                dismiss()
            } catch {
                self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
            submitting = false
        }
    }
}
