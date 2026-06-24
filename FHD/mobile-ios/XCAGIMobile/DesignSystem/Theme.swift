import SwiftUI

/// 设计令牌(对标安卓 Compose 主题色板)。
enum Theme {
    static let brand = Color("AccentColor")
    static let brandFallback = Color(red: 0.149, green: 0.404, blue: 0.918)

    static let cardBackground = Color(uiColor: .secondarySystemGroupedBackground)
    static let screenBackground = Color(uiColor: .systemGroupedBackground)

    enum Space {
        static let xs: CGFloat = 4
        static let sm: CGFloat = 8
        static let md: CGFloat = 12
        static let lg: CGFloat = 16
        static let xl: CGFloat = 24
    }

    enum Radius {
        static let sm: CGFloat = 8
        static let md: CGFloat = 12
        static let lg: CGFloat = 16
    }
}

extension Color {
    /// 由字符串稳定派生一个柔和头像底色。
    static func avatarTint(for seed: String) -> Color {
        let palette: [Color] = [
            .blue, .green, .orange, .purple, .pink, .teal, .indigo, .mint, .cyan, .brown,
        ]
        var hash = 5381
        for byte in seed.utf8 { hash = ((hash << 5) &+ hash) &+ Int(byte) }
        let idx = abs(hash) % palette.count
        return palette[idx].opacity(0.85)
    }
}
