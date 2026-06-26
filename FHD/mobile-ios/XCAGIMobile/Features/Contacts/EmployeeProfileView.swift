import SwiftUI

// 员工档案页 + 派生档案模型(全量对标 Android `AiCircleScreens.kt`:
// `AiEmployeeProfile` / `aiEmployeeProfiles()` / `AiEmployeeProfileScreen`)。
//
// iOS 的 `WorkflowEmployeeInfo` 字段少于安卓(无 market_* 一族),按 API 清单约定
// 新字段全部可空、缺失即视为空串——与安卓 data class 的空默认值语义一致,
// 因此派生逻辑可逐字段对标,缺的市场字段自然退化为空(不影响展示与回退链)。

// MARK: - 派生档案模型(对标 Android AiEmployeeProfile)

/// 由 `ModInfo` + `WorkflowEmployeeInfo` 派生的 AI 员工档案(对标 Android `AiEmployeeProfile`)。
struct EmployeeProfile: Identifiable, Hashable {
    let modId: String
    let modName: String
    let modDescription: String
    let industryName: String
    let employeeId: String
    let name: String
    let title: String
    let summary: String
    let apiBasePath: String
    let phoneChannel: String
    let workflowPlaceholder: Bool
    let profileSource: String
    let marketPkgId: String
    let avatarUrl: String?

    var id: String { "\(modId):\(employeeId)" }
    var key: String { id }

    /// 复合会话 ID:`employee:modId:employeeId`(对标 Android `onOpenChat`)。
    var conversationId: String { "employee:\(modId):\(employeeId)" }

    /// 来源标签(对标 Android `sourceLabel`)。
    var sourceLabel: String {
        if !marketPkgId.isEmpty { return "AI市场 · \(modName.isEmpty ? "已安装员工" : modName)" }
        if !modName.isEmpty { return modName }
        if !profileSource.isEmpty { return profileSource }
        return "当前账号生态"
    }

    /// 能力标签(对标 Android `abilityLabels()`)。
    func abilityLabels() -> [String] {
        var labels: [String] = []
        if !phoneChannel.isEmpty { labels.append("可对话") }
        if !apiBasePath.isEmpty { labels.append("可执行任务") }
        if !industryName.isEmpty { labels.append(industryName) }
        if workflowPlaceholder { labels.append("待完善") }
        if !marketPkgId.isEmpty { labels.append("市场资料") }
        if labels.isEmpty { labels.append("生态同步") }
        return Array(labels.prefix(4))
    }

    /// 列表副标题里的联系人线(对标 Android `contactLine()`)。
    var contactLine: String {
        [
            phoneChannel.contactChannelLabel,
            employeeId.isEmpty ? "" : "AI号 \(employeeId)",
            apiBasePath.isEmpty ? "" : "入口 \(apiBasePath)",
        ]
        .filter { !$0.isEmpty }
        .joined(separator: " · ")
    }
}

private extension String {
    /// 联系渠道可读标签(对标 Android `contactChannelLabel()`)。
    var contactChannelLabel: String {
        switch trimmingCharacters(in: .whitespaces) {
        case "admin-duty": return "管理端工作台"
        case "mobile", "mobile-chat": return "手机端会话"
        case "": return ""
        default: return trimmingCharacters(in: .whitespaces)
        }
    }
}

extension Array where Element == ModInfo {
    /// 从 MOD 列表展开 AI 员工档案(对标 Android `List<ModInfo>.aiEmployeeProfiles()`)。
    func aiEmployeeProfiles() -> [EmployeeProfile] {
        var seen = Set<String>()
        var result: [EmployeeProfile] = []
        for mod in self {
            let modId = (mod.id ?? "").trimmingCharacters(in: .whitespaces)
            let modName = (mod.name ?? "").isEmpty ? modId : (mod.name ?? "")
            for employee in mod.workflowEmployees ?? [] {
                let employeeId = (employee.id ?? "").trimmingCharacters(in: .whitespaces)
                let name = employee.displayName
                if employeeId.isEmpty || name.isEmpty { continue }
                let key = "\(modId):\(employeeId)"
                if seen.contains(key) { continue } // 防止后端返回重复 employee
                seen.insert(key)

                let summary = firstNonBlank(
                    employee.panelSummary,
                    mod.description,
                    "由当前账号生态的 \(modName) 同步到手机端。"
                )
                result.append(
                    EmployeeProfile(
                        modId: modId,
                        modName: modName,
                        modDescription: mod.description ?? "",
                        industryName: mod.industry?.name ?? "",
                        employeeId: employeeId,
                        name: name,
                        title: firstNonBlank(employee.panelTitle, name),
                        summary: summary,
                        apiBasePath: employee.apiBasePath ?? "",
                        phoneChannel: employee.phoneChannel ?? "",
                        workflowPlaceholder: employee.workflowPlaceholder ?? false,
                        profileSource: employee.employeeSource ?? "",
                        marketPkgId: "",
                        avatarUrl: employee.resolvedAvatar
                    )
                )
            }
        }
        return result
    }
}

private extension WorkflowEmployeeInfo {
    /// 展示名(对标 Android `displayName()`:label → panel_title → id)。
    var displayName: String {
        firstNonBlank(label, panelTitle, id)
    }
}

extension Array where Element == EmployeeProfile {
    func findEmployee(modId: String, employeeId: String) -> EmployeeProfile? {
        first { $0.modId == modId && $0.employeeId == employeeId }
    }
}

/// 取第一个非空白字符串(对标 Android `ifBlank` 链)。
private func firstNonBlank(_ candidates: String?...) -> String {
    for c in candidates {
        if let c, !c.trimmingCharacters(in: .whitespaces).isEmpty { return c }
    }
    return ""
}

// MARK: - 员工档案页(对标 Android AiEmployeeProfileScreen)

/// 员工档案页:头像 / AI号 / 来源 / 员工资料 / 能做什么 / 交流圈预览 / 发消息 / 进交流圈。
/// 点列表里的员工先进此页(对标 Android「点员工先进档案」)。
struct EmployeeProfileView: View {
    let employee: EmployeeProfile

    @EnvironmentObject private var session: SessionManager

    var body: some View {
        ScrollView {
            VStack(spacing: Theme.Space.sm) {
                contactHeader
                profileCell(title: "员工资料", subtitle: employee.summary, showArrow: true)
                circlePreview
                profileCell(title: "能做什么",
                            subtitle: employee.abilityLabels().joined(separator: "、"),
                            showArrow: false)
                profileCell(title: "来源", subtitle: employee.sourceLabel, showArrow: false)

                // 发消息:进 SSE 对话页,sessionId = employee:modId:employeeId
                NavigationLink {
                    ChatView(title: employee.name, sessionId: employee.conversationId)
                } label: {
                    actionRow(text: "发消息", icon: "bubble.left.and.bubble.right.fill")
                }

                // 进入 AI 交流圈
                NavigationLink {
                    EmployeeCirclePreviewView(employee: employee)
                } label: {
                    actionRow(text: "进入 AI 交流圈", icon: "bubble.left.and.text.bubble.right.fill")
                }
            }
            .padding(.bottom, Theme.Space.xl)
        }
        .background(Theme.screenBackground.ignoresSafeArea())
        .navigationBarTitleDisplayMode(.inline)
    }

    // 头像 + 昵称 + AI号 + 来源(对标 Android AiEmployeeContactHeader)
    private var contactHeader: some View {
        HStack(alignment: .top, spacing: Theme.Space.md) {
            AvatarView(text: employee.name, url: employee.avatarUrl, size: 62)
            VStack(alignment: .leading, spacing: 5) {
                Text(employee.name)
                    .font(.title3.weight(.semibold))
                Text("昵称：\(employee.title)")
                    .font(.subheadline).foregroundColor(.secondary)
                    .padding(.top, 3)
                Text("AI号：\(employee.employeeId)")
                    .font(.subheadline).foregroundColor(.secondary)
                    .lineLimit(1)
                Text("来源：\(employee.sourceLabel)")
                    .font(.footnote).foregroundColor(.secondary)
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, Theme.Space.lg)
        .padding(.vertical, Theme.Space.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.cardBackground)
    }

    // 通用资料行(对标 Android AiProfilePlainCell)
    private func profileCell(title: String, subtitle: String, showArrow: Bool) -> some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 6) {
                Text(title).font(.body)
                if !subtitle.isEmpty {
                    Text(subtitle)
                        .font(.footnote).foregroundColor(.secondary)
                        .lineLimit(2)
                }
            }
            Spacer(minLength: Theme.Space.sm)
            if showArrow {
                Image(systemName: "chevron.right")
                    .font(.footnote).foregroundColor(.secondary.opacity(0.6))
            }
        }
        .padding(.horizontal, Theme.Space.lg)
        .padding(.vertical, Theme.Space.md)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.cardBackground)
    }

    // 交流圈预览卡(对标 Android AiProfileCirclePreview)
    private var circlePreview: some View {
        NavigationLink {
            EmployeeCirclePreviewView(employee: employee)
        } label: {
            VStack(alignment: .leading, spacing: Theme.Space.md) {
                HStack(spacing: Theme.Space.sm) {
                    Image(systemName: "bubble.left.and.text.bubble.right.fill")
                        .foregroundColor(Theme.brand)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("AI交流圈").font(.body).foregroundColor(.primary)
                        Text("进入交流圈 · 查看 \(employee.name) 的动态与能力更新")
                            .font(.footnote).foregroundColor(.secondary)
                            .lineLimit(1)
                    }
                    Spacer(minLength: 0)
                    Image(systemName: "chevron.right")
                        .font(.footnote).foregroundColor(.secondary.opacity(0.6))
                }
                let abilities = Array(employee.abilityLabels().prefix(3))
                if !abilities.isEmpty {
                    HStack(spacing: Theme.Space.sm) {
                        ForEach(abilities, id: \.self) { label in
                            previewTile(label: label)
                        }
                    }
                    .padding(.leading, 30)
                }
            }
            .padding(.horizontal, Theme.Space.lg)
            .padding(.vertical, Theme.Space.lg)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.cardBackground)
        }
        .buttonStyle(.plain)
    }

    private func previewTile(label: String) -> some View {
        let color = Color.avatarTint(for: "\(employee.key):\(label)")
        return Text(String(label.prefix(2)))
            .font(.caption.weight(.semibold))
            .foregroundColor(color)
            .frame(width: 44, height: 44)
            .background(color.opacity(0.16))
            .clipShape(RoundedCornerShape(Theme.Radius.sm))
    }

    // 居中操作行(对标 Android AiProfileActionRow)
    private func actionRow(text: String, icon: String) -> some View {
        HStack(spacing: Theme.Space.sm) {
            Image(systemName: icon).foregroundColor(Theme.brand)
            Text(text).font(.body.weight(.medium)).foregroundColor(Theme.brand)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, Theme.Space.lg)
        .background(Theme.cardBackground)
    }
}

/// 圆角矩形 shape(SwiftUI 无内置便捷构造,封装一个小工具)。
private struct RoundedCornerShape: Shape {
    let radius: CGFloat
    init(_ radius: CGFloat) { self.radius = radius }
    func path(in rect: CGRect) -> Path {
        Path(roundedRect: rect, cornerRadius: radius)
    }
}

// MARK: - 员工交流圈预览(对标 Android AiCircleScreen 的单员工动态)

/// 从员工档案进入的交流圈视图:展示该员工真实动态(circle/posts 过滤到该 employeeId)+ 发帖。
/// 忠实复用共享地基 `api.circlePosts()` / `api.createPost(body:)`(item ③)。
struct EmployeeCirclePreviewView: View {
    let employee: EmployeeProfile

    @EnvironmentObject private var session: SessionManager
    @State private var posts: [CirclePost] = []
    @State private var phase: LoadPhase = .idle
    @State private var draft = ""
    @State private var posting = false

    var body: some View {
        Group {
            switch phase {
            case .idle, .loading:
                LoadingView()
            case .failed(let m):
                ErrorStateView(message: m) { Task { await load() } }
            default:
                content
            }
        }
        .navigationTitle("AI交流圈")
        .navigationBarTitleDisplayMode(.inline)
        .task { if case .idle = phase { await load() } }
    }

    private var employeePosts: [CirclePost] {
        posts.filter { ($0.employeeId ?? "") == employee.employeeId }
    }

    private var content: some View {
        VStack(spacing: 0) {
            List {
                Section {
                    headerCard
                }
                if employeePosts.isEmpty {
                    Section {
                        Text("\(employee.name) 还没有发布动态。")
                            .font(.footnote).foregroundColor(.secondary)
                    }
                } else {
                    Section("最新动态") {
                        ForEach(employeePosts) { post in
                            postRow(post)
                        }
                    }
                }
            }
            .listStyle(.insetGrouped)
            .refreshable { await load() }

            composer
        }
    }

    private var headerCard: some View {
        HStack(spacing: Theme.Space.md) {
            AvatarView(text: employee.name, url: employee.avatarUrl, size: 50)
            VStack(alignment: .leading, spacing: 4) {
                Text(employee.name).font(.headline)
                Text(employee.sourceLabel)
                    .font(.caption).foregroundColor(.secondary).lineLimit(1)
                HStack(spacing: Theme.Space.sm) {
                    ForEach(Array(employee.abilityLabels().prefix(3)), id: \.self) { label in
                        Text(label)
                            .font(.caption2)
                            .padding(.horizontal, Theme.Space.sm)
                            .padding(.vertical, 3)
                            .background(Theme.brand.opacity(0.12))
                            .foregroundColor(Theme.brand)
                            .clipShape(Capsule())
                    }
                }
                .padding(.top, 2)
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, Theme.Space.xs)
    }

    private func postRow(_ post: CirclePost) -> some View {
        VStack(alignment: .leading, spacing: Theme.Space.xs) {
            HStack(spacing: Theme.Space.sm) {
                AvatarView(text: post.authorName ?? employee.name, url: post.authorAvatar ?? employee.avatarUrl, size: 36)
                VStack(alignment: .leading, spacing: 1) {
                    Text(post.authorName ?? employee.name).font(.subheadline.weight(.medium))
                    if let created = post.createdAt, !created.isEmpty {
                        Text(created).font(.caption2).foregroundColor(.secondary)
                    }
                }
                Spacer(minLength: 0)
            }
            Text(post.body ?? "")
                .font(.body)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.vertical, Theme.Space.xs)
    }

    // 发帖输入条(item ③ createPost)
    private var composer: some View {
        HStack(spacing: Theme.Space.sm) {
            TextField("说点什么…", text: $draft, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(1...4)
            Button {
                Task { await submit() }
            } label: {
                if posting {
                    ProgressView()
                } else {
                    Image(systemName: "paperplane.fill")
                }
            }
            .disabled(posting || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }
        .padding(.horizontal, Theme.Space.md)
        .padding(.vertical, Theme.Space.sm)
        .background(Theme.cardBackground)
    }

    private func load() async {
        phase = .loading
        do {
            posts = try await session.api.circlePosts()
            phase = .loaded
        } catch {
            phase = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
        }
    }

    private func submit() async {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !posting else { return }
        posting = true
        defer { posting = false }
        do {
            try await session.api.createPost(body: text)
            draft = ""
            await load()
        } catch {
            session.lastError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }
}
