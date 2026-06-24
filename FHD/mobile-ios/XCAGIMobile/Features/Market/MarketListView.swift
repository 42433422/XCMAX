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

/// 应用市场(对标 Android MOD 列表 + WebView 承载)。
/// 列表走 `/mods`;条目打开 WKWebView 承载页(注入登录态)。
struct MarketListView: View {
    @EnvironmentObject private var session: SessionManager
    @StateObject private var vm = MarketListViewModel()

    var body: some View {
        Group {
            switch vm.phase {
            case .idle, .loading: LoadingView()
            case .failed(let m): ErrorStateView(message: m) { Task { await vm.load(session.api) } }
            case .empty: EmptyStateView(icon: "bag", title: "暂无应用")
            case .loaded:
                List {
                    ForEach(vm.mods, id: \.stableId) { mod in
                        Section {
                            ForEach(menuItems(for: mod), id: \.self) { item in
                                NavigationLink(value: page(for: item)) {
                                    Label(item.label ?? item.id ?? "页面", systemImage: "square.grid.2x2")
                                }
                            }
                        } header: {
                            Text(mod.name ?? mod.stableId)
                        } footer: {
                            if let d = mod.description, !d.isEmpty { Text(d) }
                        }
                    }
                }
                .listStyle(.insetGrouped)
                .refreshable { await vm.load(session.api) }
            }
        }
        .navigationTitle("应用市场")
        .navigationBarTitleDisplayMode(.inline)
        .navigationDestination(for: ModPage.self) { p in
            ModWebViewScreen(title: p.title, urlString: p.urlString)
        }
        .task { if vm.phase == .idle { await vm.load(session.api) } }
    }

    private func menuItems(for mod: ModInfo) -> [ModMenuItem] {
        let items = (mod.frontendMenu ?? []) + (mod.menu ?? [])
        // 去重(按 path)并过滤空 path
        var seen = Set<String>()
        return items.filter { item in
            guard let p = item.path, !p.isEmpty else { return false }
            return seen.insert(p).inserted
        }
    }

    private func page(for item: ModMenuItem) -> ModPage {
        let path = item.path ?? "/"
        let cleaned = path.hasPrefix("/") ? String(path.dropFirst()) : path
        return ModPage(title: item.label ?? "页面", urlString: session.resolvedBaseURL + cleaned)
    }
}
