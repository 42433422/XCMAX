import SwiftUI

/// 应用入口(对标 Android `MainActivity` / 鸿蒙 `EntryAbility`)。
@main
struct XCAGIMobileApp: App {
    @StateObject private var sessionManager = SessionManager()
    @StateObject private var networkMonitor = NetworkMonitor()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(sessionManager)
                .environmentObject(networkMonitor)
                .preferredColorScheme(sessionManager.colorScheme)
        }
    }
}
