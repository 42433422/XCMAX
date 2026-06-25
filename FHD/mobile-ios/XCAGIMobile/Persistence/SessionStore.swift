import Foundation

/// 持久化的会话快照(对标 mobile-harmony `PersistedSession`)。
struct PersistedSession {
    var accessToken: String = ""
    var sessionId: String = ""
    var baseURL: String = ""
    var accountKind: String = "enterprise"
    var loginAccountKind: String = "admin"
    var displayName: String = ""
    var companyBrand: String = ""
    var biometricEnabled: Bool = false
    var themeMode: String = "system"          // system / light / dark
    var legalConsented: Bool = false

    var isLoggedIn: Bool { !accessToken.isEmpty }
}

/// 本地持久化(对标 mobile-harmony `LocalStore` / Android `SessionStore`)。
///
/// 令牌存 Keychain;其余非高敏字段存 UserDefaults。重启后自动恢复登录态与偏好。
final class SessionStore {
    static let shared = SessionStore()

    private let defaults = UserDefaults.standard

    private enum Key {
        static let token = "access_token"          // Keychain
        static let sessionId = "session_id"          // Keychain
        static let baseURL = "base_url"
        static let accountKind = "account_kind"
        static let loginAccountKind = "login_account_kind"
        static let displayName = "display_name"
        static let companyBrand = "company_brand"
        static let biometric = "biometric_enabled"
        static let themeMode = "theme_mode"
        static let legalConsent = "legal_consented"
    }

    func load() -> PersistedSession {
        PersistedSession(
            accessToken: KeychainHelper.get(Key.token) ?? "",
            sessionId: KeychainHelper.get(Key.sessionId) ?? "",
            baseURL: defaults.string(forKey: Key.baseURL) ?? "",
            accountKind: defaults.string(forKey: Key.accountKind) ?? "enterprise",
            loginAccountKind: defaults.string(forKey: Key.loginAccountKind) ?? "admin",
            displayName: defaults.string(forKey: Key.displayName) ?? "",
            companyBrand: defaults.string(forKey: Key.companyBrand) ?? "",
            biometricEnabled: defaults.bool(forKey: Key.biometric),
            themeMode: defaults.string(forKey: Key.themeMode) ?? "system",
            legalConsented: defaults.bool(forKey: Key.legalConsent)
        )
    }

    func saveSession(_ s: PersistedSession) {
        KeychainHelper.set(s.accessToken, for: Key.token)
        KeychainHelper.set(s.sessionId, for: Key.sessionId)
        defaults.set(s.baseURL, forKey: Key.baseURL)
        defaults.set(s.accountKind, forKey: Key.accountKind)
        defaults.set(s.loginAccountKind, forKey: Key.loginAccountKind)
        defaults.set(s.displayName, forKey: Key.displayName)
        defaults.set(s.companyBrand, forKey: Key.companyBrand)
    }

    func savePreferences(biometricEnabled: Bool, themeMode: String) {
        defaults.set(biometricEnabled, forKey: Key.biometric)
        defaults.set(themeMode, forKey: Key.themeMode)
    }

    func saveLegalConsent(_ consented: Bool) {
        defaults.set(consented, forKey: Key.legalConsent)
    }

    /// 退出登录:清令牌与会话,保留主题/合规等本机偏好。
    func clearSession() {
        KeychainHelper.delete(Key.token)
        KeychainHelper.delete(Key.sessionId)
        defaults.removeObject(forKey: Key.displayName)
    }
}
