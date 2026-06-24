import SwiftUI

/// 发现页(对标 Android `DiscoverScreen`):汇集圈子/群聊/企业模块/工具入口。
struct DiscoverView: View {
    var body: some View {
        NavigationStack {
            List {
                Section("协作") {
                    NavigationRow(icon: "photo.on.rectangle.angled", tint: .pink, title: "AI 交流圈") { AiCircleView() }
                    NavigationRow(icon: "person.3.fill", tint: .blue, title: "AI 群聊") { AiGroupListView() }
                    NavigationRow(icon: "checkmark.seal.fill", tint: .green, title: "审批") { ApprovalListView() }
                }
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
    }
}

/// 带图标的导航行。
struct NavigationRow<Destination: View>: View {
    let icon: String
    let tint: Color
    let title: String
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
                Text(title)
            }
        }
    }
}
