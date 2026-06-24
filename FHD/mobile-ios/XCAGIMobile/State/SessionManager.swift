import Foundation
import SwiftUI

/// 应用级会话状态 + 依赖中枢(对标 Android `AppViewModel` 的会话部分 + DI)。
///
/// 持有 `APIClient`,管理登录态/基址/账号信息,并为各 feature 派生 SSE / IM 客户端。
/// 以 `@EnvironmentObject` 注入全局。
@MainActor
final class SessionManager: ObservableObject {
    enum Phase { case launching, login, main }

    @Published var phase: Phase = .launching
    @Published var session: PersistedSession
    @Published var lastError: String?

    private let store = SessionStore.shared
    private(set) var api: APIClient

    init() {
        let persisted = SessionStore.shared.load()
        self.session = persisted
        let base = persisted.baseURL.isEmpty ? AppConfig.defaultBaseURL : persisted.baseURL
        self.api = APIClient(baseURL: base, accessToken: persisted.accessToken)
    }

    /// 当前生效基址(已持久化 > SKU 默认)。
    var resolvedBaseURL: String {
        session.baseURL.isEmpty ? AppConfig.defaultBaseURL : session.baseURL
    }

    var colorScheme: ColorScheme? {
        switch session.themeMode {
        case "light": return .light
        case "dark": return .dark
        default: return nil
        }
    }

    /// App 启动:有令牌进主界面,否则进登录页。
    func bootstrap() {
        if session.baseURL.isEmpty {
            session.baseURL = AppConfig.defaultBaseURL
        }
        api.setBaseURL(resolvedBaseURL)
        api.setAccessToken(session.accessToken)
        phase = session.isLoggedIn ? .main : .login
    }

    // MARK: - 登录 / 登出 / 配对

    func login(username: String, password: String, loginAccountKind: String) async {
        lastError = nil
        do {
            let data = try await api.login(username: username, password: password, accountKind: loginAccountKind)
            guard let token = data.accessToken, !token.isEmpty else {
                lastError = "登录失败:未返回访问令牌"
                return
            }
            session.accessToken = token
            session.sessionId = data.sessionId ?? ""
            session.loginAccountKind = loginAccountKind
            session.accountKind = data.accountKind ?? (data.marketIsEnterprise == true ? "enterprise" : loginAccountKind)
            session.displayName = data.user?.displayName ?? data.user?.username ?? username
            session.companyBrand = data.companyBrand ?? ""
            api.setAccessToken(token)
            store.saveSession(session)
            phase = .main
        } catch {
            lastError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    /// 桌面端绑定码:换取局域网主机基址并切换。
    func applyPairing(code: String) async {
        lastError = nil
        do {
            let data = try await api.pairingExchange(code: code)
            let newBase = data.apiBaseUrl ?? data.baseUrl ?? ""
            guard !newBase.isEmpty else {
                lastError = "绑定失败:未返回主机地址"
                return
            }
            session.baseURL = APIClient.normalize(newBase)
            api.setBaseURL(session.baseURL)
            store.saveSession(session)
        } catch {
            lastError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    func logout() {
        store.clearSession()
        session.accessToken = ""
        session.sessionId = ""
        session.displayName = ""
        api.setAccessToken("")
        phase = .login
    }

    // MARK: - 偏好

    func updatePreferences(biometricEnabled: Bool, themeMode: String) {
        session.biometricEnabled = biometricEnabled
        session.themeMode = themeMode
        store.savePreferences(biometricEnabled: biometricEnabled, themeMode: themeMode)
    }

    func acceptLegalConsent() {
        session.legalConsented = true
        store.saveLegalConsent(true)
    }

    /// 已登录且拿到 APNs token 时,上报设备(对标 Android PushRegistrar)。
    func registerPushIfPossible() async {
        guard session.isLoggedIn, let token = PushManager.shared.deviceToken else { return }
        try? await api.registerDevice(pushToken: token)
    }

    // MARK: - 派生客户端

    func makeSSEClient() -> SSEChatClient {
        SSEChatClient(baseURL: resolvedBaseURL, accessToken: session.accessToken)
    }

    func makeIMClient() -> IMWebSocketClient {
        IMWebSocketClient(baseURL: resolvedBaseURL, sessionId: session.sessionId)
    }
}
