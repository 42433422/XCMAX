import Foundation

/// 全局常量(对标 Android `BuildConfig` 与 mobile-harmony `BUILD_HARMONY.md`)。
///
/// 企业版默认走 `https://xiu-ci.com/fhd-api`;桌面端配对后由 `pairing/exchange`
/// 下发的 `api_base_url` 覆盖为局域网主机(默认端口 17500),并持久化。
enum AppConfig {
    /// 产品 SKU(对标 Android flavor:personal / enterprise)。
    enum Sku: String {
        case personal
        case enterprise
    }

    /// 当前构建的 SKU。iOS 单 target;如需个人版另起 scheme/配置即可。
    static let sku: Sku = .enterprise

    static let companyName = "成都修茈科技有限公司"

    /// MODstore(个人版)基址。
    static let modstoreBaseURL = "https://xiu-ci.com"

    /// 企业版 FHD 基址(注入 `/fhd-api`,与桌面企业版登录后端同源)。
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
