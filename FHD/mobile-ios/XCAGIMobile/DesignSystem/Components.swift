import SwiftUI

/// 消息页头像布局 SSOT,对齐 Android `MessageAvatarLayout`。
enum MessageAvatarLayout {
    static let headerAvatarSize: CGFloat = 44
    static let headerAvatarCornerRadius: CGFloat = 10
    static let topBarAvatarSize: CGFloat = 32

    static let conversationAvatarSize: CGFloat = 52
    static let conversationAvatarCornerRadius: CGFloat = 8
    static let conversationRowHorizontalPadding: CGFloat = 16
    static let conversationRowVerticalPadding: CGFloat = 11
    static let conversationAvatarTextGap: CGFloat = 12
    static let conversationDividerExtraInset: CGFloat = 4
    static let conversationDividerStart: CGFloat =
        conversationRowHorizontalPadding +
        conversationAvatarSize +
        conversationAvatarTextGap +
        conversationDividerExtraInset

    static let unreadBadgeOffsetX: CGFloat = 5
    static let unreadBadgeOffsetY: CGFloat = -5
    static let unreadBadgeSize: CGFloat = 21
    static let unreadBadgeLargeSize: CGFloat = 25
    static let onlineIndicatorSize: CGFloat = 14
    static let onlineIndicatorOffsetY: CGFloat = 2
    static let onlineIndicatorPadding: CGFloat = 2.5

    static let bubbleAvatarSize: CGFloat = 40
    static let bubbleAvatarCornerRadius: CGFloat = 8
    static let bubbleAvatarGap: CGFloat = 8
    static let bubbleTopPaddingWithAvatar: CGFloat = 12
    static let bubbleTopPaddingWithoutAvatar: CGFloat = 4
    static let bubbleAvatarReservedWidth: CGFloat = bubbleAvatarSize + bubbleAvatarGap
    static let emptyStateAvatarSize: CGFloat = 72
    static let emptyStateAvatarCornerRadius: CGFloat = 20

    static let employeePickerAvatarSize: CGFloat = 44
    static let employeePickerAvatarCornerRadius: CGFloat = 4
    static let employeePickerRowHorizontalPadding: CGFloat = 12
    static let employeePickerRowVerticalPadding: CGFloat = 10
    static let employeePickerAvatarTextGap: CGFloat = 12
    static let employeePickerDividerStart: CGFloat =
        employeePickerRowHorizontalPadding +
        employeePickerAvatarSize +
        employeePickerAvatarTextGap

    static let customerServiceBubbleAvatarSize: CGFloat = 36
    static let customerServiceBubbleIconSize: CGFloat = 24
    static let customerServiceBubbleAvatarGap: CGFloat = 8
}

/// 固定图片头像兜底,对齐 Android `AppAvatarFallback`。
enum AppAvatarFallback: Hashable {
    case user
    case assistant
    case customerService
    case aiEmployee
    case codex
    case claude
    case cursor
    case trae

    var assetName: String? {
        switch self {
        case .user: return "avatar_default_user"
        case .assistant: return "avatar_assistant"
        case .customerService, .aiEmployee: return "avatar_default_ai_employee"
        case .codex: return "codex_app_icon"
        case .claude: return "claude_app_icon"
        case .cursor: return "cursor_app_icon"
        case .trae: return "trae_app_icon"
        }
    }
}

/// 头像:有 `url` 时加载真实头像,加载中/失败回退固定图片(对标 Android AppAvatar)。
struct AvatarView: View {
    let text: String
    var url: String? = nil
    var fallback: AppAvatarFallback = .aiEmployee
    var size: CGFloat = 44
    var cornerRadius: CGFloat = 8

    private var resolvedURL: URL? {
        guard let raw = url?.trimmingCharacters(in: .whitespacesAndNewlines), !raw.isEmpty else { return nil }
        return URL(string: raw)
    }

    var body: some View {
        Group {
            if let resolvedURL {
                AsyncImage(url: resolvedURL) { phase in
                    switch phase {
                    case .success(let image):
                        image.resizable().scaledToFill()
                    case .empty, .failure:
                        fallbackAvatar
                    @unknown default:
                        fallbackAvatar
                    }
                }
            } else {
                fallbackAvatar
            }
        }
        .frame(width: size, height: size)
        .background(Color(uiColor: .secondarySystemFill))
        .clipShape(shape)
        .overlay(shape.stroke(Color.white.opacity(0.10), lineWidth: 0.5))
        .contentShape(shape)
        .accessibilityLabel(text)
    }

    private var shape: RoundedRectangle {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
    }

    @ViewBuilder
    private var fallbackAvatar: some View {
        if let assetName = fallback.assetName {
            Image(assetName)
                .resizable()
                .scaledToFill()
        } else {
            Image("avatar_default_ai_employee")
                .resizable()
                .scaledToFill()
        }
    }
}

/// 加载中占位。
struct LoadingView: View {
    var title: String = "加载中…"
    var body: some View {
        VStack(spacing: Theme.Space.md) {
            ProgressView()
            Text(title).font(.footnote).foregroundColor(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// 错误状态 + 重试。
struct ErrorStateView: View {
    let message: String
    var retry: (() -> Void)?

    var body: some View {
        VStack(spacing: Theme.Space.md) {
            Image(systemName: "exclamationmark.triangle")
                .font(.largeTitle).foregroundColor(.orange)
            Text(message)
                .font(.subheadline).foregroundColor(.secondary)
                .multilineTextAlignment(.center)
            if let retry {
                Button("重试", action: retry).buttonStyle(.bordered)
            }
        }
        .padding()
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// 空列表占位。
struct EmptyStateView: View {
    var icon: String = "tray"
    let title: String
    var subtitle: String?

    var body: some View {
        VStack(spacing: Theme.Space.sm) {
            Image(systemName: icon).font(.largeTitle).foregroundColor(.secondary)
            Text(title).font(.subheadline).foregroundColor(.secondary)
            if let subtitle {
                Text(subtitle).font(.caption).foregroundColor(Color.secondary.opacity(0.7))
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding()
    }
}

/// 离线横幅(对标安卓离线 banner)。
struct OfflineBanner: View {
    var body: some View {
        HStack(spacing: Theme.Space.sm) {
            Image(systemName: "wifi.slash")
            Text("网络已断开,正在使用离线数据")
            Spacer()
        }
        .font(.footnote)
        .foregroundColor(.white)
        .padding(.horizontal, Theme.Space.lg)
        .padding(.vertical, Theme.Space.sm)
        .background(Color.orange)
    }
}

/// 「待真机/后续」诚实占位页(对标 PARITY_MATRIX 中尚未填充的能力)。
struct WorkInProgressView: View {
    let title: String
    let note: String

    var body: some View {
        VStack(spacing: Theme.Space.md) {
            Image(systemName: "hammer").font(.largeTitle).foregroundColor(Theme.brand)
            Text(title).font(.headline)
            Text(note)
                .font(.subheadline).foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
    }
}
