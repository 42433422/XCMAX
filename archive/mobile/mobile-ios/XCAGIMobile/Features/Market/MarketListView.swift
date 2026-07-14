import SwiftUI

@MainActor
final class MarketListViewModel: ObservableObject {
    @Published var mods: [ModInfo] = []
    @Published var phase: LoadPhase = .idle

    func load(_ api: APIClient) async {
        phase = .loading
        do {
            mods = try await api.mods().items ?? []
            phase = mods.isEmpty ? .empty : .loaded
        } catch {
            phase = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
        }
    }
}

/// MOD 路由(标题 + 完整 URL)。
struct ModPage: Hashable {
    let title: String
    let urlString: String
}

/// 应用市场(对标 Android `MarketListScreen` + `requestModOpen` 云端门控)。
///
/// 列表走 `/mods`,每个 mod 一行 + 「使用」按钮(非按 menu 逐项导航,与安卓一致)。
/// 点「使用」时:
/// - 先做健康探测决定在线/离线(对标 `repo.modOpensInCloudWorkbench`)。
/// - 离线(纯云端)→ 提示「该功能需在电脑端使用」(对标安卓 `onCloud` 的 snack)。
/// - 在线 → 解析 `modWebUrl`(在线 `{fhd}mod/{id}/`,离线 workbench)后用 WKWebView 承载并注入双 token。
struct MarketListView: View {
    @EnvironmentObject private var session: SessionManager
    @StateObject private var vm = MarketListViewModel()

    @State private var pendingPage: ModPage?
    @State private var opening: String?           // 正在解析的 modId(按钮 loading 态)
    @State private var cloudGateMessage: String?  // 非空 → 弹「需在电脑端使用」

    var body: some View {
        Group {
            switch vm.phase {
            case .idle, .loading: LoadingView()
            case .failed(let m): ErrorStateView(message: m) { Task { await vm.load(session.api) } }
            case .empty: EmptyStateView(icon: "bag", title: "暂无应用", subtitle: "从企业端同步的能力包将在此出现")
            case .loaded:
                List {
                    Section {
                        ForEach(vm.mods, id: \.stableId) { mod in
                            MarketModRow(
                                title: mod.name ?? mod.stableId,
                                subtitle: (mod.description?.isEmpty == false ? mod.description! : "从企业端同步的能力包"),
                                busy: opening == mod.stableId,
                                onUse: { requestOpen(mod) }
                            )
                        }
                    } header: {
                        Text("可用能力")
                    }
                }
                .listStyle(.insetGrouped)
                .refreshable { await vm.load(session.api) }
            }
        }
        .navigationTitle("应用市场")
        .navigationBarTitleDisplayMode(.inline)
        .navigationDestination(isPresented: Binding(
            get: { pendingPage != nil },
            set: { if !$0 { pendingPage = nil } }
        )) {
            if let p = pendingPage {
                ModWebViewScreen(title: p.title, urlString: p.urlString)
            }
        }
        .alert("提示", isPresented: Binding(
            get: { cloudGateMessage != nil },
            set: { if !$0 { cloudGateMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(cloudGateMessage ?? "")
        }
        .task { if vm.phase == .idle { await vm.load(session.api) } }
    }

    /// 对标 Android `vm.requestModOpen(id, onCloud, onNative)`:
    /// 离线(纯云端工作台)→ 提示需电脑端;在线 → 解析 URL 后导航承载页。
    private func requestOpen(_ mod: ModInfo) {
        let modId = mod.id ?? mod.stableId
        guard opening == nil else { return }
        opening = mod.stableId
        Task {
            let online = await session.isHostOnline()
            if !online {
                // 离线时 mod 在云端工作台打开 → 与安卓一致提示需在电脑端使用。
                cloudGateMessage = "该功能需在电脑端使用"
                opening = nil
                return
            }
            let urlString = session.api.modWebUrl(modId: modId, online: true)
            pendingPage = ModPage(title: mod.name ?? mod.stableId, urlString: urlString)
            opening = nil
        }
    }
}

/// 单个 mod 行(对标安卓 `WeCell`:图标 + 标题/副标题 + 「使用」)。
private struct MarketModRow: View {
    let title: String
    let subtitle: String
    let busy: Bool
    let onUse: () -> Void

    var body: some View {
        HStack(spacing: Theme.Space.md) {
            Image(systemName: "square.grid.2x2.fill")
                .font(.system(size: 18, weight: .semibold))
                .foregroundColor(Theme.brand)
                .frame(width: 36, height: 36)
                .background(Theme.brand.opacity(0.12))
                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.sm))

            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.body)
                    .lineLimit(1)
                Text(subtitle)
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .lineLimit(1)
            }

            Spacer(minLength: Theme.Space.sm)

            Button(action: onUse) {
                if busy {
                    ProgressView()
                } else {
                    Text("使用").fontWeight(.medium)
                }
            }
            .buttonStyle(.borderless)
            .disabled(busy)
        }
        .padding(.vertical, 2)
        .contentShape(Rectangle())
    }
}
