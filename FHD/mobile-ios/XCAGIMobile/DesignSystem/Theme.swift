import SwiftUI

/// 设计令牌(对标 `FHD/config/mobile_design_tokens.json` 与安卓 Compose 主题色板)。
enum Theme {
    static let brand = Color("AccentColor")
    static let brandFallback = Color(red: 0.388, green: 0.400, blue: 0.945)
    static let brandContainer = Color(red: 0.918, green: 0.922, blue: 0.996)
    static let brandGradientEnd = Color(red: 0.486, green: 0.227, blue: 0.929)
    static let success = Color(red: 0.063, green: 0.725, blue: 0.506)
    static let warning = Color(red: 0.961, green: 0.620, blue: 0.043)
    static let danger = Color(red: 0.937, green: 0.267, blue: 0.267)

    static let cardBackground = Color(uiColor: .secondarySystemGroupedBackground)
    static let screenBackground = Color(uiColor: .systemGroupedBackground)

    enum Space {
        static let xs: CGFloat = 4
        static let sm: CGFloat = 8
        static let md: CGFloat = 12
        static let lg: CGFloat = 16
        static let xl: CGFloat = 20
        static let xxl: CGFloat = 24
        static let xxxl: CGFloat = 32
    }

    enum Radius {
        static let xs: CGFloat = 4
        static let sm: CGFloat = 8
        static let md: CGFloat = 12
        static let lg: CGFloat = 16
        static let xl: CGFloat = 20
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
