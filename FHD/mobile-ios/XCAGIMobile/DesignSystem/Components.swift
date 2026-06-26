import SwiftUI

/// 头像:有 `url` 时加载真实头像,加载中/失败回退名字首字色块(对标 Android AppAvatar)。
struct AvatarView: View {
    let text: String
    var url: String? = nil
    var size: CGFloat = 44

    private var initial: String {
        let t = text.trimmingCharacters(in: .whitespaces)
        return t.isEmpty ? "AI" : String(t.prefix(1))
    }

    private var resolvedURL: URL? {
        guard let raw = url?.trimmingCharacters(in: .whitespaces), !raw.isEmpty else { return nil }
        return URL(string: raw)
    }

    var body: some View {
        Group {
            if let resolvedURL {
                AsyncImage(url: resolvedURL) { phase in
                    if case .success(let image) = phase {
                        image.resizable().scaledToFill()
                    } else {
                        textAvatar   // 加载中 / 失败 → 首字母回退
                    }
                }
            } else {
                textAvatar
            }
        }
        .frame(width: size, height: size)
        .clipShape(Circle())
    }

    private var textAvatar: some View {
        Text(initial)
            .font(.system(size: size * 0.42, weight: .semibold))
            .foregroundColor(.white)
            .frame(width: size, height: size)
            .background(Color.avatarTint(for: text))
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
