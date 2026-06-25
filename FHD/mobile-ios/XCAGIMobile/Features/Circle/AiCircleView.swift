import SwiftUI

@MainActor
final class AiCircleViewModel: ObservableObject {
    @Published var posts: [CirclePost] = []
    @Published var phase: LoadPhase = .idle
    /// 评论/发帖等操作的轻量反馈(对标安卓 Snackbar:操作失败不静默)。
    @Published var actionMessage: String?

    func load(_ api: APIClient) async {
        phase = .loading
        do {
            posts = try await api.circlePosts()
            phase = posts.isEmpty ? .empty : .loaded
        } catch {
            phase = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
        }
    }

    func toggleLike(_ api: APIClient, post: CirclePost) async {
        guard let pid = post.id, let idx = posts.firstIndex(where: { $0.id == pid }) else { return }
        // 乐观更新
        let wasLiked = posts[idx].likedByMe ?? false
        posts[idx].likedByMe = !wasLiked
        posts[idx].likeCount = max(0, (posts[idx].likeCount ?? 0) + (wasLiked ? -1 : 1))
        do { try await api.circleToggleLike(postId: pid) }
        catch {
            posts[idx].likedByMe = wasLiked
            posts[idx].likeCount = max(0, (posts[idx].likeCount ?? 0) + (wasLiked ? 1 : -1))
            actionMessage = "点赞失败,请稍后重试"
        }
    }

    /// 评论:失败给反馈(对标安卓 — 不再静默吞错)。
    func addComment(_ api: APIClient, post: CirclePost, body: String) async {
        let text = body.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let pid = post.id, !text.isEmpty else { return }
        do {
            try await api.circleAddComment(postId: pid, body: text)
            await load(api)
        } catch {
            actionMessage = (error as? LocalizedError)?.errorDescription
                ?? "评论失败,请稍后重试"
        }
    }

    /// 发帖(对标安卓 createPost / createAiCirclePost)。
    func createPost(_ api: APIClient, body: String) async -> Bool {
        let text = body.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return false }
        do {
            try await api.createPost(body: text)
            await load(api)
            actionMessage = "已发布到交流圈"
            return true
        } catch {
            actionMessage = (error as? LocalizedError)?.errorDescription
                ?? "发布失败,请稍后重试"
            return false
        }
    }
}

/// AI 交流圈(朋友圈)(对标 Android `AiCircleScreens`)。
///
/// 在 iOS 真实动态数据(`CirclePost`)之上补齐安卓视觉与交互:企业生态头部、能力标签 chip、
/// 友好相对时间、发帖入口、点作者进员工主页;评论/点赞/发帖失败均给反馈,不静默。
struct AiCircleView: View {
    @EnvironmentObject private var session: SessionManager
    @StateObject private var vm = AiCircleViewModel()
    @State private var composing = false

    var body: some View {
        Group {
            switch vm.phase {
            case .idle, .loading: LoadingView()
            case .failed(let m): ErrorStateView(message: m) { Task { await vm.load(session.api) } }
            case .empty:
                EmptyStateView(icon: "photo.on.rectangle.angled",
                               title: "圈子还很安静",
                               subtitle: "成为第一个在企业生态里发声的人")
            case .loaded: feed
            }
        }
        .navigationTitle("AI 交流圈")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button { composing = true } label: { Image(systemName: "square.and.pencil") }
                    .accessibilityLabel("发布动态")
            }
        }
        .navigationDestination(for: CircleAuthorRoute.self) { route in
            // 点作者进员工主页(复用通讯录里的员工档案页,对标安卓 AiEmployeeProfileScreen)。
            EmployeeProfileView(employee: route.toEmployeeProfile())
        }
        .sheet(isPresented: $composing) {
            CirclePostComposer { text in
                let ok = await vm.createPost(session.api, body: text)
                if ok { composing = false }
            }
        }
        // 操作反馈(对标安卓 Snackbar):失败不静默。
        .alert("提示", isPresented: Binding(
            get: { vm.actionMessage != nil },
            set: { if !$0 { vm.actionMessage = nil } }
        )) {
            Button("好", role: .cancel) { vm.actionMessage = nil }
        } message: {
            Text(vm.actionMessage ?? "")
        }
        .task { if vm.phase == .idle { await vm.load(session.api) } }
    }

    private var feed: some View {
        List {
            CircleHeader(posts: vm.posts, displayName: session.session.displayName)
                .listRowInsets(EdgeInsets())
                .listRowSeparator(.hidden)
                .listRowBackground(Color.clear)

            ForEach(vm.posts) { post in
                CirclePostCard(
                    post: post,
                    relativeTime: RelativeTime.format(post.createdAt),
                    onLike: { Task { await vm.toggleLike(session.api, post: post) } },
                    onComment: { text in Task { await vm.addComment(session.api, post: post, body: text) } }
                )
                .listRowInsets(EdgeInsets(top: 6, leading: 12, bottom: 6, trailing: 12))
                .listRowSeparator(.hidden)
            }
        }
        .listStyle(.plain)
        .refreshable { await vm.load(session.api) }
    }
}

// MARK: - 企业生态头部(对标安卓 AiCircleHeader)

private struct CircleHeader: View {
    let posts: [CirclePost]
    let displayName: String

    /// 出现过的 AI 员工作者(去重),用于「值守伙伴」头像簇与计数。
    private var employees: [CirclePost] {
        var seen = Set<String>()
        var out: [CirclePost] = []
        for p in posts where (p.employeeId?.isEmpty == false) {
            let key = p.employeeId ?? ""
            if seen.insert(key).inserted { out.append(p) }
        }
        return out
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // 「封面照」深岩灰底色(对标安卓 0xFF3F4A4D),承载白字。
            ZStack(alignment: .bottom) {
                Color(red: 0.247, green: 0.290, blue: 0.302)
                HStack(alignment: .bottom) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("AI员工交流圈")
                            .font(.title3).fontWeight(.semibold)
                            .foregroundColor(.white)
                        Text("\(employees.count) 位智能伙伴正在企业账号里值守")
                            .font(.caption)
                            .foregroundColor(.white.opacity(0.86))
                    }
                    Spacer(minLength: Theme.Space.md)
                    VStack(alignment: .trailing, spacing: 6) {
                        Text(displayName.isEmpty ? "当前账号" : displayName)
                            .font(.subheadline).fontWeight(.semibold)
                            .foregroundColor(.white)
                            .lineLimit(1)
                        AvatarView(text: displayName.isEmpty ? "我" : displayName, size: 46)
                            .overlay(RoundedRectangle(cornerRadius: 6).stroke(.white, lineWidth: 2))
                    }
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 16)
            }
            .frame(height: 144)

            // 「企业账号生态」说明 + 值守头像簇。
            HStack(alignment: .center, spacing: Theme.Space.md) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("企业账号生态")
                        .font(.subheadline).fontWeight(.semibold)
                    Text("员工动态、能力更新和协同消息会在这里汇总。")
                        .font(.caption).foregroundColor(.secondary)
                        .lineLimit(1)
                }
                Spacer()
                if !employees.isEmpty {
                    HStack(spacing: -10) {
                        ForEach(Array(employees.prefix(3)), id: \.idValue) { e in
                            AvatarView(text: e.authorName ?? "AI", url: e.authorAvatar, size: 30)
                                .overlay(Circle().stroke(Theme.cardBackground, lineWidth: 1.5))
                        }
                    }
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 10)
            .background(Theme.cardBackground)
        }
    }
}

// MARK: - 动态卡片

private struct CirclePostCard: View {
    let post: CirclePost
    let relativeTime: String
    var onLike: () -> Void
    var onComment: (String) -> Void

    @State private var commenting = false
    @State private var commentText = ""

    /// 该作者是否为可进主页的 AI 员工(对标安卓:点作者头像/名字进员工主页)。
    private var employeeRoute: CircleAuthorRoute? {
        guard let eid = post.employeeId, !eid.isEmpty else { return nil }
        return CircleAuthorRoute(employeeId: eid,
                                 name: post.authorName ?? "AI 员工",
                                 avatar: post.authorAvatar,
                                 summary: post.body)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Space.sm) {
            authorRow
            if let body = post.body, !body.isEmpty {
                Text(body).font(.subheadline)
            }
            abilityChips
            actionBar
            commentsBlock
            if commenting { commentField }
        }
        .padding(Theme.Space.md)
        .background(Theme.cardBackground.opacity(0.5))
        .cornerRadius(Theme.Radius.md)
    }

    @ViewBuilder private var authorRow: some View {
        let header = HStack(spacing: Theme.Space.sm) {
            AvatarView(text: post.authorName ?? "AI", url: post.authorAvatar, size: 38)
            VStack(alignment: .leading, spacing: 1) {
                Text(post.authorName ?? "AI 员工").fontWeight(.medium)
                Text(relativeTime).font(.caption2).foregroundColor(.secondary)
            }
            Spacer(minLength: 0)
            if employeeRoute != nil {
                Image(systemName: "chevron.right")
                    .font(.caption2).foregroundColor(Color.secondary.opacity(0.6))
            }
        }
        .contentShape(Rectangle())

        if let route = employeeRoute {
            // 点作者进员工主页。
            NavigationLink(value: route) { header }.buttonStyle(.plain)
        } else {
            header
        }
    }

    @ViewBuilder private var abilityChips: some View {
        let labels = CircleAbility.labels(for: post)
        if !labels.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: Theme.Space.xs) {
                    ForEach(labels, id: \.self) { AbilityChip(label: $0) }
                }
            }
        }
    }

    private var actionBar: some View {
        HStack(spacing: Theme.Space.lg) {
            Button(action: onLike) {
                Label("\(post.likeCount ?? 0)",
                      systemImage: (post.likedByMe ?? false) ? "heart.fill" : "heart")
                    .foregroundColor((post.likedByMe ?? false) ? .red : .secondary)
            }
            Button { withAnimation { commenting.toggle() } } label: {
                Label("\(post.comments?.count ?? 0)", systemImage: "bubble.right")
                    .foregroundColor(.secondary)
            }
            Spacer()
        }
        .font(.footnote)
        .buttonStyle(.plain)
    }

    @ViewBuilder private var commentsBlock: some View {
        if let comments = post.comments, !comments.isEmpty {
            VStack(alignment: .leading, spacing: 3) {
                ForEach(comments, id: \.idValue) { c in
                    (Text(c.authorName ?? "匿名").bold() + Text(":\(c.body ?? "")"))
                        .font(.caption).foregroundColor(.secondary)
                }
            }
            .padding(Theme.Space.sm)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.cardBackground)
            .cornerRadius(Theme.Radius.sm)
        }
    }

    private var commentField: some View {
        HStack {
            TextField("写评论…", text: $commentText)
                .textFieldStyle(.roundedBorder)
            Button("发送") {
                onComment(commentText); commentText = ""; commenting = false
            }
            .disabled(commentText.trimmingCharacters(in: .whitespaces).isEmpty)
        }
        .font(.footnote)
    }
}

// MARK: - 能力标签 chip(对标安卓 AiAbilityChip）

private struct AbilityChip: View {
    let label: String
    var body: some View {
        Text(label)
            .font(.caption2)
            .padding(.horizontal, Theme.Space.sm).padding(.vertical, 3)
            .background(Theme.brand.opacity(0.12))
            .foregroundColor(Theme.brand)
            .clipShape(Capsule())
    }
}

/// 从动态派生能力标签(对标安卓 abilityLabels:为 AI 员工动态贴上「可对话/市场资料/…」)。
private enum CircleAbility {
    static func labels(for post: CirclePost) -> [String] {
        var out: [String] = []
        let kind = (post.authorKind ?? "").lowercased()
        if let eid = post.employeeId, !eid.isEmpty {
            out.append("AI员工")
            out.append("可对话")
        } else if kind.contains("user") || post.authorUserId != nil {
            out.append("我的动态")
        }
        if (post.likeCount ?? 0) > 0 { out.append("\(post.likeCount ?? 0) 赞") }
        if let c = post.comments?.count, c > 0 { out.append("\(c) 评论") }
        return Array(out.prefix(3))
    }
}

// MARK: - 发帖 composer(对标安卓 createPost 入口）

private struct CirclePostComposer: View {
    /// 返回 true 表示发布成功(由父级关闭 sheet)。
    let onSubmit: (String) async -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @State private var submitting = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                TextEditor(text: $text)
                    .padding(Theme.Space.md)
                    .overlay(alignment: .topLeading) {
                        if text.isEmpty {
                            Text("分享你和 AI 员工的协同进展…")
                                .foregroundColor(.secondary)
                                .padding(.horizontal, Theme.Space.md + 4)
                                .padding(.vertical, Theme.Space.md + 8)
                                .allowsHitTesting(false)
                        }
                    }
                Spacer(minLength: 0)
            }
            .navigationTitle("发布动态")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    if submitting {
                        ProgressView()
                    } else {
                        Button("发布") {
                            submitting = true
                            Task {
                                await onSubmit(text)
                                submitting = false
                            }
                        }
                        .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                }
            }
        }
    }
}

// MARK: - 点作者 → 员工主页（对标安卓 AiEmployeeProfileScreen)

/// 交流圈作者(AI 员工)主页路由。
///
/// 动态只带 `employeeId` / `authorName` / `authorAvatar`(无 modId),据此构造一个轻量
/// `EmployeeProfile` 复用通讯录的员工档案页(对标安卓「点作者进员工主页」)。
struct CircleAuthorRoute: Hashable {
    let employeeId: String
    let name: String
    let avatar: String?
    let summary: String?

    func toEmployeeProfile() -> EmployeeProfile {
        EmployeeProfile(
            modId: "",
            modName: "",
            modDescription: "",
            industryName: "",
            employeeId: employeeId,
            name: name,
            title: name,
            summary: (summary?.isEmpty == false ? summary : nil)
                ?? "由当前账号生态同步到手机端的 AI 员工,可直接发起会话。",
            apiBasePath: "",
            phoneChannel: "mobile",
            workflowPlaceholder: false,
            profileSource: "企业账号生态",
            marketPkgId: "",
            avatarUrl: avatar
        )
    }
}

// MARK: - 友好相对时间（对标安卓 momentTime / 友好相对时间）

/// 把后端 ISO8601 `created_at` 解析成「刚刚 / x分钟前 / x小时前 / 昨天 / x天前 / 日期」。
enum RelativeTime {
    private static let isoFractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    private static let iso: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()
    /// 兜底:无时区的 "yyyy-MM-dd'T'HH:mm:ss" / "yyyy-MM-dd HH:mm:ss"。
    private static let plain: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f
    }()
    private static let plainSpace: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd HH:mm:ss"
        return f
    }()
    private static let dateOnly: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "zh_CN")
        f.dateFormat = "M月d日"
        return f
    }()

    static func parse(_ raw: String?) -> Date? {
        guard let raw, !raw.isEmpty else { return nil }
        if let d = isoFractional.date(from: raw) { return d }
        if let d = iso.date(from: raw) { return d }
        if let d = plain.date(from: raw) { return d }
        if let d = plainSpace.date(from: raw) { return d }
        return nil
    }

    static func format(_ raw: String?) -> String {
        guard let date = parse(raw) else { return "" }
        let seconds = Date().timeIntervalSince(date)
        if seconds < 0 { return "刚刚" }
        if seconds < 60 { return "刚刚" }
        if seconds < 3600 { return "\(Int(seconds / 60))分钟前" }
        if seconds < 86_400 { return "\(Int(seconds / 3600))小时前" }
        if seconds < 172_800 { return "昨天" }
        if seconds < 604_800 { return "\(Int(seconds / 86_400))天前" }
        return dateOnly.string(from: date)
    }
}
