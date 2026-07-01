import SwiftUI

/// 固定伙伴名片规格(对标 Android `fixedPartnerProfileSpec`)。
struct FixedPartnerSpec {
    let alias: String
    let accountId: String
    let summary: String
    let source: String
    let abilityLabels: [String]
    let circleLabels: [String]

    /// 归一化 kind → 规格。未知 kind 落到「助理」。
    static func forKind(_ rawKind: String, fallbackName: String) -> FixedPartnerSpec {
        let k = "\(rawKind) \(fallbackName)".lowercased()
        if k.contains("codex") {
            return .init(alias: "全设备协同 · 排比派工", accountId: "XCAGI-CODEX",
                         summary: "把开发、测试、打包、提交类任务派发到在线的 Codex 工作设备协同完成;普通问题可直接对话。",
                         source: "XCAGI 超级员工 · Codex 通道",
                         abilityLabels: ["多设备派工", "开发任务", "测试验证", "打包提交"],
                         circleLabels: ["派工", "协同", "开发"])
        }
        if k.contains("cursor") {
            return .init(alias: "全设备协同 · Agent", accountId: "XCAGI-CURSOR",
                         summary: "把开发、修改、验证类任务派发到在线 Cursor 工作设备协同完成;不可用时保留本地对话入口。",
                         source: "XCAGI 超级员工 · Cursor 通道",
                         abilityLabels: ["多设备派工", "代码修改", "测试验证", "Agent 协同"],
                         circleLabels: ["派工", "协同", "开发"])
        }
        if k.contains("claude") {
            return .init(alias: "全设备协同 · 排比派工", accountId: "XCAGI-CLAUDE",
                         summary: "与 Codex 同构的超级员工,把任务派发到在线 Claude 工作设备;派工不可用时回退本机 Claude 直答。",
                         source: "XCAGI 超级员工 · Claude 通道",
                         abilityLabels: ["多设备派工", "开发任务", "测试验证", "本地直答"],
                         circleLabels: ["派工", "协同", "开发"])
        }
        if k.contains("trae") {
            return .init(alias: "全设备协同 · Trae", accountId: "XCAGI-TRAE",
                         summary: "把开发、检查、执行类任务派发到在线 Trae 工作设备协同完成。",
                         source: "XCAGI 超级员工 · Trae 通道",
                         abilityLabels: ["多设备派工", "开发任务", "桌面执行", "验证回传"],
                         circleLabels: ["派工", "协同", "开发"])
        }
        if k.contains("cs") || k.contains("service") {
            return .init(alias: "企业服务顾问", accountId: "XCAGI-CS",
                         summary: "用于企业服务接待、问题反馈、订单跟进与人工协同支持。",
                         source: "企业服务通道",
                         abilityLabels: ["服务咨询", "进度跟进", "问题反馈", "人工协同"],
                         circleLabels: ["服务", "协同", "反馈"])
        }
        return .init(alias: "企业智能助手", accountId: "XCAGI-AI-C",
                     summary: "负责智能对话、快速分析、识图入口和企业协同问答。",
                     source: "XCAGI 企业版内置伙伴",
                     abilityLabels: ["智能对话", "快速模式", "深度分析", "拍照识图"],
                     circleLabels: ["对话", "分析", "识图"])
    }
}

/// 固定伙伴名片(对标 Android `FixedPartnerProfileScreen`):头像/简介/能力标签 + 发消息/查看交流圈。
struct FixedPartnerProfileView: View {
    let contact: FixedContactDto

    private var spec: FixedPartnerSpec { FixedPartnerSpec.forKind(contact.kind, fallbackName: contact.name) }
    private var isCs: Bool { contact.kind.lowercased().contains("cs") || contact.kind == "dedicated_cs" }
    private var peerKind: ChatPeerKind { ChatPeerKind.resolve(id: contact.id, kind: contact.kind, title: contact.name) }
    private var fixedAvatarURL: String? {
        guard peerKind == .employee, contact.avatar.hasPrefix("http") else { return nil }
        return contact.avatar
    }

    var body: some View {
        ScrollView {
            VStack(spacing: Theme.Space.lg) {
                header
                summaryCard
                chipsSection(title: "能力", labels: spec.abilityLabels)
                chipsSection(title: "交流圈", labels: spec.circleLabels)
                actions
            }
            .padding(Theme.Space.lg)
        }
        .navigationTitle("名片")
        .navigationBarTitleDisplayMode(.inline)
    }

    private var header: some View {
        VStack(spacing: Theme.Space.sm) {
            AvatarView(
                text: contact.name,
                url: fixedAvatarURL,
                fallback: peerKind.avatarFallback,
                size: MessageAvatarLayout.emptyStateAvatarSize,
                cornerRadius: MessageAvatarLayout.emptyStateAvatarCornerRadius
            )
            Text(contact.name).font(.title3).bold()
            Text(spec.alias).font(.footnote).foregroundColor(.secondary)
            Text(spec.accountId).font(.caption2.monospaced()).foregroundColor(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, Theme.Space.md)
    }

    private var summaryCard: some View {
        VStack(alignment: .leading, spacing: Theme.Space.sm) {
            Text(contact.summary.isEmpty ? spec.summary : contact.summary)
                .font(.subheadline)
            Text(spec.source).font(.caption).foregroundColor(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Theme.Space.md)
        .background(Theme.cardBackground)
        .cornerRadius(Theme.Radius.md)
    }

    private func chipsSection(title: String, labels: [String]) -> some View {
        VStack(alignment: .leading, spacing: Theme.Space.sm) {
            Text(title).font(.footnote).foregroundColor(.secondary)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: Theme.Space.sm) {
                    ForEach(labels, id: \.self) { label in
                        Text(label)
                            .font(.caption)
                            .padding(.horizontal, Theme.Space.md).padding(.vertical, Theme.Space.xs)
                            .background(Theme.brand.opacity(0.12))
                            .foregroundColor(Theme.brand)
                            .clipShape(Capsule())
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var actions: some View {
        VStack(spacing: Theme.Space.md) {
            NavigationLink {
                if isCs { CsChatView(title: contact.name) }
                else { ChatView(title: contact.name, sessionId: contact.id.isEmpty ? "assistant" : contact.id, peerKind: peerKind, aiAvatarURL: fixedAvatarURL) }
            } label: {
                Label("发消息", systemImage: "bubble.left.fill").frame(maxWidth: .infinity).padding(.vertical, Theme.Space.sm)
            }
            .buttonStyle(.borderedProminent)

            NavigationLink {
                AiCircleView()
            } label: {
                Label("查看交流圈", systemImage: "photo.on.rectangle.angled").frame(maxWidth: .infinity).padding(.vertical, Theme.Space.sm)
            }
            .buttonStyle(.bordered)
        }
        .padding(.top, Theme.Space.sm)
    }
}
