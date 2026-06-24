import SwiftUI

/// 根路由:启动 → 合规同意 → 登录 / 主界面(对标 Android `XcagiNavHost` 顶层分流)。
struct RootView: View {
    @EnvironmentObject private var session: SessionManager
    @EnvironmentObject private var network: NetworkMonitor

    var body: some View {
        VStack(spacing: 0) {
            if !network.isOnline {
                OfflineBanner()
            }
            content
        }
        .task {
            session.bootstrap()
        }
    }

    @ViewBuilder
    private var content: some View {
        switch session.phase {
        case .launching:
            LoadingView(title: "正在启动…")
        case .login:
            if !session.session.legalConsented {
                LegalConsentView()
            } else {
                LoginView()
            }
        case .main:
            MainShell()
        }
    }
}
