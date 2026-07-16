import SwiftUI

/// 发现页(对标 Android `DiscoverScreen`):汇集圈子/群聊/企业模块/工具入口,
/// 并在配对后动态同步桌面端侧栏工具(`loadNavMenu`,与电脑端侧栏对齐)。
struct DiscoverView: View {
    @EnvironmentObject private var session: SessionManager

    /// 桌面端侧栏工具(配对后拉取;未配对/失败时为空,静默保留)。
    @State private var navMenu: [NavMenuItem] = []

    var body: some View {
        NavigationStack {
            List {
                Section("协作") {
                    NavigationRow(icon: "photo.on.rectangle.angled", tint: .pink, title: "AI 交流圈") { AiCircleView() }
                    NavigationRow(icon: "person.3.fill", tint: .blue, title: "AI 群聊") { AiGroupListView() }
                    NavigationRow(icon: "checkmark.seal.fill", tint: .green, title: "审批") { ApprovalListView() }
                }

                // 配对后动态显示桌面端工具(与侧栏对齐,对标 Android visibleNavMenu)。
                desktopToolsSection

                Section("企业模块") {
                    NavigationRow(icon: "person.text.rectangle.fill", tint: .indigo, title: "客户") { EnterpriseModuleView(kind: .customers) }
                    NavigationRow(icon: "shippingbox.fill", tint: .orange, title: "发货") { EnterpriseModuleView(kind: .shipments) }
                    NavigationRow(icon: "arrow.left.arrow.right.circle.fill", tint: .teal, title: "服务桥工单") { EnterpriseModuleView(kind: .serviceBridge) }
                }
                Section("工具") {
                    NavigationRow(icon: "qrcode.viewfinder", tint: .purple, title: "扫一扫") { ScanQrView() }
                    NavigationRow(icon: "doc.text.viewfinder", tint: .brown, title: "OCR 文字识别") { OcrView() }
                    NavigationRow(icon: "bell.badge.fill", tint: .red, title: "通知中心") { NotificationListView() }
                    NavigationRow(icon: "bag.fill", tint: .cyan, title: "应用市场") { MarketListView() }
                    NavigationRow(icon: "bubble.left.and.text.bubble.right.fill", tint: .mint, title: "即时通讯 IM") { ImMessengerView() }
                }
            }
            .navigationTitle("发现")
        }
        // 进入即与电脑端侧栏对齐:拉取最新 nav-menu(未配对时静默失败,保留旧值)。
        .task { await loadNavMenu() }
    }

    /// 桌面工具分组(对标 Android `DiscoverScreen` 的 "桌面工具(与电脑端侧栏对齐)" 段)。
    /// 有桌面工具 → 逐项渲染(原生 key 走原生页,其余用 WebView 承载);
    /// 无 → 显示「扫码绑定电脑端」引导。
    @ViewBuilder
    private var desktopToolsSection: some View {
        let visible = navMenu.filter { key in
            !DiscoverNav.hiddenKeys.contains(key.key ?? "")
        }
        Section("桌面工具(与电脑端侧栏对齐)") {
            if visible.isEmpty {
                NavigationRow(icon: "qrcode.viewfinder", tint: Theme.brandFallback,
                              title: "扫码绑定电脑端",
                              subtitle: "绑定后,电脑端侧栏的工具会同步到这里") { ScanQrView() }
            } else {
                ForEach(visible) { item in
                    DesktopToolRow(item: item)
                }
            }
        }
    }

    /// 拉取桌面侧栏菜单(对标 Android `vm.loadNavMenu()`)。
    private func loadNavMenu() async {
        if let data = try? await session.api.loadNavMenu(), let items = data.items {
            navMenu = items
        }
    }
}

/// 桌面工具行:原生 key → 原生页面;否则用 `ModWebViewScreen` 承载桌面端页面
/// (对标 Android `NATIVE_ROUTE_MAP` + `onOpenWebView` 分支)。
private struct DesktopToolRow: View {
    let item: NavMenuItem

    var body: some View {
        let key = item.key ?? ""
        let title = item.name ?? key
        let subtitle = (item.source == "mod") ? "Mod: \(item.modId ?? key)" : "点击打开"
        let icon = DiscoverNav.icon(for: item)
        let route = DiscoverNav.nativeRoute(for: key)

        NavigationRow(icon: icon, tint: Theme.brandFallback, title: title, subtitle: subtitle) {
            switch route {
            case .aiEcosystem: AiCircleView()
            case .employeeWorkflow: AiGroupListView()
            case .settings: SettingsView()
            case .web: ModWebViewScreen(title: title, urlString: item.path ?? "")
            }
        }
    }
}

/// 桌面工具映射表(对标 Android `NATIVE_ROUTE_MAP` / `HIDDEN_KEYS` / `iconForNav`)。
enum DiscoverNav {
    /// 核心 key → 原生路由(有原生页面的走原生,否则用 WebView 打开)。
    enum Route {
        case aiEcosystem, employeeWorkflow, settings, web
    }

    /// 已在其他原生入口(底部 Tab / AI交流圈)实现,桌面工具分组中隐藏,避免重复。
    static let hiddenKeys: Set<String> = [
        "chat",  // 智能对话:底部 Tab 原生入口
        "im",    // 消息:底部 Tab 原生入口
    ]

    /// 核心 key → 原生路由(对标 Android `NATIVE_ROUTE_MAP`;无映射回退 WebView)。
    static func nativeRoute(for key: String) -> Route {
        switch key {
        case "ai-ecosystem": return .aiEcosystem
        case "employee-workflow": return .employeeWorkflow
        case "settings": return .settings
        default: return .web
        }
    }

    /// FA 图标名 → SF Symbol 映射(简化版,未知图标用 wrench 兜底;对标 Android `iconForNav`)。
    static func icon(for item: NavMenuItem) -> String {
        let key = item.key ?? ""
        let icon = item.icon ?? ""
        if key == "chat" || icon.contains("comment") { return "bubble.left.fill" }
        if key == "im" || icon.contains("envelope") { return "envelope.fill" }
        if key == "ai-ecosystem" || icon.contains("sitemap") { return "rectangle.connected.to.line.below" }
        if key == "employee-workflow" || icon.contains("users") { return "person.2.fill" }
        if key == "products" || icon.contains("cube") { return "square.grid.2x2.fill" }
        if key == "orders" || icon.contains("file") { return "doc.text.fill" }
        if key == "print" || icon.contains("print") { return "printer.fill" }
        if key == "data-sources" || icon.contains("database") { return "cylinder.split.1x2.fill" }
        if key == "settings" || icon.contains("cog") { return "gearshape.fill" }
        if item.source == "mod" { return "square.grid.2x2.fill" }
        return "wrench.and.screwdriver.fill"
    }
}

/// 带图标的导航行。
struct NavigationRow<Destination: View>: View {
    let icon: String
    let tint: Color
    let title: String
    var subtitle: String? = nil
    @ViewBuilder var destination: () -> Destination

    var body: some View {
        NavigationLink {
            destination()
        } label: {
            HStack(spacing: Theme.Space.md) {
                Image(systemName: icon)
                    .foregroundColor(.white)
                    .frame(width: 30, height: 30)
                    .background(tint)
                    .cornerRadius(Theme.Radius.sm)
                if let subtitle {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(title)
                        Text(subtitle).font(.caption).foregroundColor(.secondary)
                    }
                } else {
                    Text(title)
                }
            }
        }
    }
}
