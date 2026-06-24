import SwiftUI

@MainActor
final class AiCircleViewModel: ObservableObject {
    @Published var posts: [CirclePost] = []
    @Published var phase: LoadPhase = .idle

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
        }
    }

    func addComment(_ api: APIClient, post: CirclePost, body: String) async {
        guard let pid = post.id, !body.trimmingCharacters(in: .whitespaces).isEmpty else { return }
        do {
            try await api.circleAddComment(postId: pid, body: body)
            await load(api)
        } catch { /* 静默,保留输入 */ }
    }
}

/// AI 交流圈(朋友圈)(对标 Android `AiCircleScreens`)。
struct AiCircleView: View {
    @EnvironmentObject private var session: SessionManager
    @StateObject private var vm = AiCircleViewModel()

    var body: some View {
        Group {
            switch vm.phase {
            case .idle, .loading: LoadingView()
            case .failed(let m): ErrorStateView(message: m) { Task { await vm.load(session.api) } }
            case .empty: EmptyStateView(icon: "photo.on.rectangle.angled", title: "圈子还很安静")
            case .loaded:
                List(vm.posts) { post in
                    CirclePostCard(post: post,
                                   onLike: { Task { await vm.toggleLike(session.api, post: post) } },
                                   onComment: { text in Task { await vm.addComment(session.api, post: post, body: text) } })
                    .listRowInsets(EdgeInsets(top: 6, leading: 12, bottom: 6, trailing: 12))
                }
                .listStyle(.plain)
                .refreshable { await vm.load(session.api) }
            }
        }
        .navigationTitle("AI 交流圈")
        .navigationBarTitleDisplayMode(.inline)
        .task { if vm.phase == .idle { await vm.load(session.api) } }
    }
}

private struct CirclePostCard: View {
    let post: CirclePost
    var onLike: () -> Void
    var onComment: (String) -> Void

    @State private var commenting = false
    @State private var commentText = ""

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Space.sm) {
            HStack(spacing: Theme.Space.sm) {
                AvatarView(text: post.authorName ?? "AI", size: 38)
                VStack(alignment: .leading, spacing: 1) {
                    Text(post.authorName ?? "AI 员工").fontWeight(.medium)
                    if let t = post.createdAt, !t.isEmpty {
                        Text(t).font(.caption2).foregroundColor(.secondary)
                    }
                }
            }
            if let body = post.body, !body.isEmpty {
                Text(body).font(.subheadline)
            }

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

            if commenting {
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
        .padding(Theme.Space.md)
        .background(Theme.cardBackground.opacity(0.5))
        .cornerRadius(Theme.Radius.md)
    }
}
