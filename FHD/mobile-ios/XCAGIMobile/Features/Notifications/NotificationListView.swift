import SwiftUI

/// 通知中心(对标 Android `NotificationListScreen`):开启推送 + 展示已收到通知。
struct NotificationListView: View {
    @EnvironmentObject private var session: SessionManager
    @ObservedObject private var push = PushManager.shared
    @ObservedObject private var store = NotificationStore.shared

    var body: some View {
        List {
            Section("推送") {
                HStack {
                    Label("通知授权", systemImage: push.authorized ? "bell.badge.fill" : "bell.slash")
                    Spacer()
                    Text(push.authorized ? "已开启" : "未开启").foregroundColor(.secondary)
                }
                if !push.authorized {
                    Button("开启推送通知") {
                        Task { await push.requestAuthorizationAndRegister() }
                    }
                }
                if let token = push.deviceToken {
                    Text("设备令牌:\(token.prefix(16))…")
                        .font(.caption2.monospaced()).foregroundColor(.secondary)
                }
            }

            Section("消息") {
                if store.items.isEmpty {
                    Text("暂无通知").foregroundColor(.secondary)
                } else {
                    ForEach(store.items) { n in
                        VStack(alignment: .leading, spacing: 3) {
                            Text(n.title).fontWeight(.medium)
                            if !n.body.isEmpty { Text(n.body).font(.footnote).foregroundColor(.secondary) }
                            Text(n.date, style: .time).font(.caption2).foregroundColor(.secondary)
                        }
                        .padding(.vertical, 2)
                    }
                }
            }
        }
        .navigationTitle("通知中心")
        .navigationBarTitleDisplayMode(.inline)
        .task { await push.refreshStatus() }
        .onChange(of: push.deviceToken) { _ in
            Task { await session.registerPushIfPossible() }
        }
    }
}
