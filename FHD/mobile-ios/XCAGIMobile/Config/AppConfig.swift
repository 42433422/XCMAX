import Foundation

/// 全局常量(对标 Android `BuildConfig` 与 mobile-harmony `BUILD_HARMONY.md`)。
///
/// 当前对外主线为 `XCAGI`(`XCAGIMobile`),默认走 `https://xiu-ci.com/fhd-api`;
/// 冻结兼容线 `XCAGIMobilePersonal` 仅保留历史 `PERSONAL` 编译条件与 MODstore 基址。
/// 桌面端配对后由 `pairing/exchange` 下发的 `api_base_url` 覆盖为局域网主机(默认端口 17500),并持久化。
enum AppConfig {
    /// 构建 SKU。当前主发版使用 `enterprise`;`personal` 仅作冻结兼容。
    enum Sku: String {
        case personal
        case enterprise
    }

    /// 当前构建的 SKU。兼容 target `XCAGIMobilePersonal` 定义 `PERSONAL` 编译条件。
    #if PERSONAL
    static let sku: Sku = .personal
    #else
    static let sku: Sku = .enterprise
    #endif

    static let companyName = "成都修茈科技有限公司"

    /// 冻结兼容线(MODstore)基址。
    static let modstoreBaseURL = "https://xiu-ci.com"

    /// 当前主发版 FHD 基址(注入 `/fhd-api`,与桌面企业版登录后端同源)。
    static let enterpriseBaseURL = "https://xiu-ci.com/fhd-api"

    /// 桌面端默认端口(局域网配对回落)。
    static let desktopDefaultPort = 17500

    /// 当前 SKU 的默认基址。
    static var defaultBaseURL: String {
        switch sku {
        case .enterprise: return enterpriseBaseURL
        case .personal: return modstoreBaseURL
        }
    }

    /// 平台标识(用于设备注册 `platform` 字段)。
    static let platform = "ios"

    static let legalTermsURL = "https://xiu-ci.com/legal/terms"
    static let legalPrivacyURL = "https://xiu-ci.com/legal/privacy"
}
