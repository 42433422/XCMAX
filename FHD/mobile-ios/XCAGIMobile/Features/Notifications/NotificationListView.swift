import SwiftUI

/// 通知类型(对标 Android `NotificationType`):决定分类图标与主题色。
enum NotificationKind: CaseIterable {
    case system, announcement, update, alert, success

    /// 分类图标(SF Symbol,对标 Android Material 图标)。
    var icon: String {
        switch self {
        case .system: return "info.circle.fill"
        case .announcement: return "megaphone.fill"
        case .update: return "wrench.and.screwdriver.fill"
        case .alert: return "exclamationmark.triangle.fill"
        case .success: return "checkmark.circle.fill"
        }
    }

    var label: String {
        switch self {
        case .system: return "系统通知"
        case .announcement: return "企业公告"
        case .update: return "版本更新"
        case .alert: return "紧急提醒"
        case .success: return "任务完成"
        }
    }

    /// 分类主题色(对标 Android `NotificationType.tint()`)。
    var tint: Color {
        switch self {
        case .system: return .blue
        case .announcement: return Theme.brandFallback
        case .update: return .green
        case .alert: return .red
        case .success: return .teal
        }
    }
}

/// 一条企业/系统通知项(对标 Android `NotificationItem`)。
struct NotificationEntry: Identifiable {
    let id: String
    let kind: NotificationKind
    let title: String
    let content: String
    let date: Date
    var read: Bool = false
}

/// 通知中心(对标 Android `NotificationListScreen`):
/// 推送授权 + 企业/系统通知列表(分类图标 + 已读态交互)+ 实时收到的推送。
struct NotificationListView: View {
    @EnvironmentObject private var session: SessionManager
    @ObservedObject private var push = PushManager.shared
    @ObservedObject private var store = NotificationStore.shared

    /// 企业/系统通知种子数据(对标 Android `remember { ... }` 的本地通知列表)。
    @State private var entries: [NotificationEntry] = NotificationListView.seedEntries()
    /// 本次会话点开过的已读 id(对标 Android `readIds`)。
    @State private var readIds: Set<String> = []

    private static let dateFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "MM-dd HH:mm"
        return f
    }()

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
            }

            Section("通知与公告") {
                if entries.isEmpty {
                    Text("暂无通知").foregroundColor(.secondary)
                } else {
                    ForEach(entries) { entry in
                        NotificationCell(
                            entry: entry,
                            isRead: entry.read || readIds.contains(entry.id),
                            dateText: Self.dateFormatter.string(from: entry.date)
                        )
                        .contentShape(Rectangle())
                        .onTapGesture { readIds.insert(entry.id) }
                    }
                }
            }

            // 实时收到的推送(iOS 本地 NotificationStore,前台横幅会记录到此)。
            if !store.items.isEmpty {
                Section("最新推送") {
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

    /// 企业/系统通知种子(对标 Android `NotificationListScreen` 的 5 条本地通知)。
    private static func seedEntries() -> [NotificationEntry] {
        let now = Date()
        let hour: TimeInterval = 3600
        let day: TimeInterval = 24 * 3600
        return [
            NotificationEntry(
                id: "1", kind: .announcement,
                title: "欢迎使用 XCAGI 企业版",
                content: "您的企业 AI 助手已就绪。可以随时和小C助理对话,或前往 AI员工 页面查看企业智能伙伴。",
                date: now.addingTimeInterval(-2 * hour)
            ),
            NotificationEntry(
                id: "2", kind: .system,
                title: "数据同步完成",
                content: "您的会话和 AI 员工列表已同步至最新状态。",
                date: now.addingTimeInterval(-5 * hour), read: true
            ),
            NotificationEntry(
                id: "3", kind: .update,
                title: "新功能:语音输入",
                content: "聊天页和客服页现已支持语音输入,点击麦克风按钮即可将语音转为文字。",
                date: now.addingTimeInterval(-day)
            ),
            NotificationEntry(
                id: "4", kind: .success,
                title: "账号配对成功",
                content: "您的移动端已成功配对企业端,可以开始使用全部功能。",
                date: now.addingTimeInterval(-2 * day), read: true
            ),
            NotificationEntry(
                id: "5", kind: .alert,
                title: "请及时更新应用",
                content: "检测到新版本可用,建议尽快更新以获得最新功能和安全修复。",
                date: now.addingTimeInterval(-3 * day), read: true
            ),
        ]
    }
}

/// 单条通知行(对标 Android `NotificationCell`):分类图标 + 未读高亮 + 红点 + 加粗标题。
private struct NotificationCell: View {
    let entry: NotificationEntry
    let isRead: Bool
    let dateText: String

    var body: some View {
        HStack(alignment: .top, spacing: Theme.Space.md) {
            // 分类图标(圆形底色)。
            Image(systemName: entry.kind.icon)
                .font(.system(size: 18))
                .foregroundColor(entry.kind.tint)
                .frame(width: 40, height: 40)
                .background(Circle().fill(entry.kind.tint.opacity(0.12)))

            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .center, spacing: 6) {
                    Text(entry.title)
                        .fontWeight(isRead ? .medium : .bold)
                        .lineLimit(1)
                    Spacer(minLength: 0)
                    if !isRead {
                        Circle().fill(Color.red).frame(width: 8, height: 8)
                    }
                }
                Text(entry.content)
                    .font(.footnote)
                    .foregroundColor(.secondary)
                    .lineLimit(2)
                Text(dateText)
                    .font(.caption2)
                    .foregroundColor(Color(uiColor: .tertiaryLabel))
            }
        }
        .padding(.vertical, 4)
        .listRowBackground(isRead ? Color.clear : entry.kind.tint.opacity(0.06))
    }
}
