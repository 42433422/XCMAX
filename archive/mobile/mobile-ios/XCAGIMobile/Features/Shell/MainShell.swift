import SwiftUI

/// 主壳:底部 Tab(对标 Android 底部导航 消息/通讯录/发现/我的)。
struct MainShell: View {
    @EnvironmentObject private var session: SessionManager

    var body: some View {
        TabView {
            ConversationListView()
                .tabItem { Label("消息", systemImage: "bubble.left.and.bubble.right.fill") }

            ContactsView()
                .tabItem { Label("通讯录", systemImage: "person.2.fill") }

            DiscoverView()
                .tabItem { Label("发现", systemImage: "safari.fill") }

            ProfileView()
                .tabItem { Label("我的", systemImage: "person.crop.circle.fill") }
        }
        .tint(Theme.brand)
    }
}
