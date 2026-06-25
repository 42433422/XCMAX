import SwiftUI

// MARK: - 发货离线缓存(对标 Android `ShipmentCacheEntity` + `cachedShipmentItems`)
//
// Android 在 Room 里持久化发货列表,远端失败时回落本地缓存并给行 subtitle 追加「离线缓存」、
// 列表层再据此弹「网络不可用，已显示本地缓存」横幅。iOS 无 Room,这里用 UserDefaults+JSON
// 复刻同一兜底链路(只发货维度需要,客户/库存与 Android 一致不缓存)。

/// 发货离线缓存载体(`EnterpriseRow` 不 Codable,这里用扁平镜像)。
private struct CachedShipment: Codable {
    let id: Int
    let title: String
    let status: String
}

/// 发货离线缓存读写(对标 Android `db.shipmentDao()`)。线程安全靠串行队列。
private enum ShipmentCache {
    private static let key = "enterprise.shipments.cache.v1"
    private static let queue = DispatchQueue(label: "com.xiuci.xcagi.shipment-cache")

    static func save(_ rows: [EnterpriseRow]) {
        let payload = rows.map { CachedShipment(id: $0.id, title: $0.title, status: $0.status ?? "") }
        queue.sync {
            if let data = try? JSONEncoder().encode(payload) {
                UserDefaults.standard.set(data, forKey: key)
            }
        }
    }

    /// 读回缓存并按 Android 规则给 subtitle 追加「离线缓存」标记。
    static func load() -> [EnterpriseRow] {
        queue.sync {
            guard let data = UserDefaults.standard.data(forKey: key),
                  let payload = try? JSONDecoder().decode([CachedShipment].self, from: data)
            else { return [] }
            return payload.map {
                let mark = [$0.status, "离线缓存"].filter { !$0.isEmpty }.joined(separator: " · ")
                return EnterpriseRow(id: $0.id, title: $0.title, subtitle: mark, status: $0.status.isEmpty ? nil : $0.status)
            }
        }
    }
}

@MainActor
final class EnterpriseModuleViewModel: ObservableObject {
    @Published var rows: [EnterpriseRow] = []
    @Published var phase: LoadPhase = .idle
    /// 离线缓存兜底时的提示横幅(对标 Android「网络不可用，已显示本地缓存」)。
    @Published var offlineNotice: String?

    func load(_ api: APIClient, kind: EnterpriseModuleView.Kind) async {
        phase = .loading
        offlineNotice = nil
        do {
            switch kind {
            case .customers:
                rows = (try await api.customers().items ?? []).map {
                    EnterpriseRow(id: $0.idValue, title: $0.name ?? "客户#\($0.idValue)", subtitle: $0.phone ?? "", status: nil)
                }
            case .shipments:
                let fresh = (try await api.shipments().items ?? []).map {
                    EnterpriseRow(id: $0.idValue, title: $0.orderNumber ?? "发货#\($0.idValue)", subtitle: "", status: $0.status)
                }
                // 成功:刷新本地缓存(对标 Android shipments() 远端成功即写 Room)。
                ShipmentCache.save(fresh)
                rows = fresh
            case .inventory:
                rows = (try await api.inventoryItems()).map { item in
                    let qty = item.quantity.map { String($0) } ?? "—"
                    let unit = item.unit ?? ""
                    let detail = [item.sku, "库存 \(qty)\(unit)"].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · ")
                    return EnterpriseRow(id: item.idValue, title: item.name ?? "物料#\(item.idValue)", subtitle: detail, status: nil)
                }
            case .serviceBridge:
                rows = (try await api.serviceBridgeRequests().items ?? []).map {
                    EnterpriseRow(id: $0.idValue, title: $0.title ?? "工单#\($0.idValue)", subtitle: $0.description ?? "", status: $0.status)
                }
            }
            phase = rows.isEmpty ? .empty : .loaded
        } catch {
            // 发货:远端失败时回落离线缓存(对标 Android cachedShipmentItems 兜底)。
            if kind == .shipments {
                let cached = ShipmentCache.load()
                if !cached.isEmpty {
                    rows = cached
                    offlineNotice = "网络不可用，已显示本地缓存"
                    phase = .loaded
                    return
                }
            }
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

/// 企业模块通用列表(客户/发货/库存/服务桥)(对标 Android `EnterpriseScreens` 的 `ErpScreen` + 服务桥)。
///
/// 客户/发货/库存三类共享一个分段胶囊容器(对标 Android `ErpScreen` 的 `WeModeCapsule`),
/// 顶部切换即可在三维度间跳转;服务桥工单走独立条目(可回复工单)。
struct EnterpriseModuleView: View {
    enum Kind: String, CaseIterable {
        case customers, shipments, inventory, serviceBridge

        var title: String {
            switch self {
            case .customers: return "客户"
            case .shipments: return "发货"
            case .inventory: return "库存"
            case .serviceBridge: return "服务桥工单"
            }
        }

        var emptyIcon: String {
            switch self {
            case .customers: return "person.text.rectangle"
            case .shipments: return "shippingbox"
            case .inventory: return "archivebox"
            case .serviceBridge: return "arrow.left.arrow.right.circle"
            }
        }

        /// 空态文案按类型细化(对标 Android `ListEmptyState` 的「暂无${title}数据」)。
        var emptyTitle: String {
            switch self {
            case .customers: return "暂无客户数据"
            case .shipments: return "暂无发货数据"
            case .inventory: return "暂无库存数据"
            case .serviceBridge: return "暂无服务桥工单"
            }
        }

        var emptySubtitle: String {
            switch self {
            case .customers: return "客户由电脑端企业模块录入,下拉刷新或连接电脑后重试。"
            case .shipments: return "发货单由电脑端企业模块创建,下拉刷新或连接电脑后重试。"
            case .inventory: return "库存来自电脑端 ERP,下拉刷新或连接电脑后重试。"
            case .serviceBridge: return "暂无待处理工单,新工单到达后会出现在这里。"
            }
        }

        /// 是否归入分段胶囊容器(客户/发货/库存三类联动,对标 Android `ErpScreen`)。
        var isErpSegment: Bool { self != .serviceBridge }
    }

    let kind: Kind
    @EnvironmentObject private var session: SessionManager
    @StateObject private var vm = EnterpriseModuleViewModel()
    @State private var respondTarget: EnterpriseRow?
    @State private var segment: Kind

    /// ERP 分段维度(对标 Android `ErpScreen` 胶囊顺序:客户 / 发货 / 库存)。
    private static let erpSegments: [Kind] = [.customers, .shipments, .inventory]

    init(kind: Kind) {
        self.kind = kind
        _segment = State(initialValue: kind.isErpSegment ? kind : .customers)
    }

    /// 当前生效维度:ERP 类看胶囊选中项,服务桥固定。
    private var activeKind: Kind { kind.isErpSegment ? segment : kind }

    var body: some View {
        VStack(spacing: 0) {
            if kind.isErpSegment {
                EnterpriseSegmentCapsule(segments: Self.erpSegments, selection: $segment)
                    .padding(.horizontal, Theme.Space.lg)
                    .padding(.vertical, Theme.Space.sm)
            }
            content
        }
        .background(Theme.screenBackground)
        .navigationTitle(kind.isErpSegment ? "业务" : kind.title)
        .navigationBarTitleDisplayMode(.inline)
        .sheet(item: $respondTarget) { row in
            BridgeRespondSheet(row: row) {
                await vm.load(session.api, kind: activeKind)
            }
        }
        .task { if vm.phase == .idle { await vm.load(session.api, kind: activeKind) } }
        // 胶囊切换:重新加载对应维度。
        .onChange(of: segment) { _ in
            Task { await vm.load(session.api, kind: activeKind) }
        }
    }

    @ViewBuilder
    private var content: some View {
        switch vm.phase {
        case .idle, .loading:
            LoadingView()
        case .failed(let m):
            ErrorStateView(message: m) { Task { await vm.load(session.api, kind: activeKind) } }
        case .empty:
            ScrollView {
                EmptyStateView(icon: activeKind.emptyIcon, title: activeKind.emptyTitle, subtitle: activeKind.emptySubtitle)
                    .frame(minHeight: 360)
            }
            .refreshable { await vm.load(session.api, kind: activeKind) }
        case .loaded:
            List {
                if let notice = vm.offlineNotice {
                    Section {
                        HStack(spacing: Theme.Space.sm) {
                            Image(systemName: "wifi.slash").foregroundColor(.orange)
                            Text(notice).font(.footnote).foregroundColor(.secondary)
                        }
                    }
                }
                Section(activeKind.title + "记录") {
                    ForEach(vm.rows) { row in
                        if activeKind == .serviceBridge {
                            Button { respondTarget = row } label: { rowContent(row) }
                                .buttonStyle(.plain)
                        } else {
                            rowContent(row)
                        }
                    }
                }
            }
            .listStyle(.insetGrouped)
            .refreshable { await vm.load(session.api, kind: activeKind) }
        }
    }

    private func rowContent(_ row: EnterpriseRow) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack {
                Text(row.title).fontWeight(.medium)
                Spacer()
                if let s = row.status, !s.isEmpty { StatusBadge(status: s) }
                if activeKind == .serviceBridge {
                    Image(systemName: "chevron.right").font(.caption).foregroundColor(.secondary)
                }
            }
            if !row.subtitle.isEmpty {
                Text(row.subtitle).font(.footnote).foregroundColor(.secondary).lineLimit(2)
            }
        }
        .padding(.vertical, 2)
    }
}

/// 客户/发货/库存分段胶囊(对标 Android `WeModeCapsule`)。
private struct EnterpriseSegmentCapsule: View {
    let segments: [EnterpriseModuleView.Kind]
    @Binding var selection: EnterpriseModuleView.Kind

    var body: some View {
        HStack(spacing: 0) {
            ForEach(segments, id: \.self) { seg in
                let active = seg == selection
                Button {
                    if seg != selection { selection = seg }
                } label: {
                    Text(seg.title)
                        .font(.subheadline.weight(active ? .semibold : .regular))
                        .foregroundColor(active ? .white : .secondary)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, Theme.Space.sm)
                        .background(
                            active ? Theme.brandFallback : Color.clear,
                            in: Capsule()
                        )
                }
                .buttonStyle(.plain)
            }
        }
        .padding(3)
        .background(Color(uiColor: .secondarySystemFill), in: Capsule())
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
