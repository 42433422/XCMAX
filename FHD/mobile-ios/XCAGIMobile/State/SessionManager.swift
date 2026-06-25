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

    /// 当前登录用户 ID(SSE 对话 user_id / IM 自身判定用)。登录 me() 后填充。
    @Published var userId: Int = 0
    /// 已绑定的中继电脑执行端 ID(超级员工 / git 操作经中继需要)。
    @Published var relayDesktopId: String = ""
    /// 市场(MODstore)access token(企业模块 WebView 注入用;登录后由 handoff 同步)。
    private(set) var marketAccessToken: String = ""

    private let store = SessionStore.shared
    private let defaults = UserDefaults.standard
    private(set) var api: APIClient

    /// 本地缓存(聊天 / IM 历史 / 会话列表预览)。
    let cache = LocalCache.shared

    private enum ExtraKey {
        static let userId = "session_user_id"
        static let relayDesktopId = "relay_desktop_id"
        static let marketToken = "market_access_token"
    }

    init() {
        let persisted = SessionStore.shared.load()
        self.session = persisted
        let base = persisted.baseURL.isEmpty ? AppConfig.defaultBaseURL : persisted.baseURL
        self.api = APIClient(baseURL: base, accessToken: persisted.accessToken)
        self.userId = UserDefaults.standard.integer(forKey: ExtraKey.userId)
        self.relayDesktopId = UserDefaults.standard.string(forKey: ExtraKey.relayDesktopId) ?? ""
        self.marketAccessToken = UserDefaults.standard.string(forKey: ExtraKey.marketToken) ?? ""
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
            if let uid = data.user?.id, uid > 0 { setUserId(uid) }
            phase = .main
            // 后台补齐 userId(部分后端登录回包不含 user.id)。
            if userId <= 0 { await refreshUserId() }
        } catch {
            lastError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    /// 手机号验证码登录(对标 Android loginMarketPhone / mobileLoginWithPhone)。
    func loginWithPhone(phone: String, code: String) async {
        lastError = nil
        do {
            let data = try await api.loginPhone(phone: phone, code: code, accountKind: session.loginAccountKind == "admin" ? "admin" : "enterprise")
            guard let token = data.accessToken, !token.isEmpty else {
                lastError = "登录失败:未返回访问令牌"; return
            }
            session.accessToken = token
            session.sessionId = data.sessionId ?? ""
            session.accountKind = data.accountKind ?? "enterprise"
            session.displayName = data.user?.displayName ?? data.user?.username ?? phone
            session.companyBrand = data.companyBrand ?? ""
            api.setAccessToken(token)
            store.saveSession(session)
            if let uid = data.user?.id, uid > 0 { setUserId(uid) }
            phase = .main
            if userId <= 0 { await refreshUserId() }
        } catch {
            lastError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    /// 发送手机验证码(注册 / 登录前置)。返回是否成功。
    @discardableResult
    func sendPhoneCode(phone: String) async -> Bool {
        do { try await api.sendCode(phone: phone); return true }
        catch { lastError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription; return false }
    }

    /// 注销账号(App Store 硬要求)。成功后清本地会话回到登录页。
    @discardableResult
    func deleteAccount(password: String) async -> Bool {
        lastError = nil
        do {
            try await api.deleteAccount(password: password)
            logout()
            return true
        } catch {
            lastError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            return false
        }
    }

    private func refreshUserId() async {
        if let uid = try? await api.me().user?.id, uid > 0 { setUserId(uid) }
    }

    private func setUserId(_ uid: Int) {
        userId = uid
        defaults.set(uid, forKey: ExtraKey.userId)
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

    /// 应用配对二维码(对标 Android pairing 分发:relay v3 走中继短码,其余走 pairing/exchange code)。
    func applyPairingQr(_ raw: String) async {
        guard let payload = PairingQrCodec.parse(raw) else {
            lastError = "二维码格式无法识别"
            return
        }
        // v3 云中继绑定:记录 relayDesktopId,后续超级员工/git 操作经中继。
        if payload.version == 3, !payload.relayId.isEmpty {
            setRelayDesktopId(payload.relayId)
            lastError = nil
            return
        }
        // host:port 直连:直接切基址。
        if !payload.host.isEmpty, payload.port > 0 {
            session.baseURL = APIClient.normalize(PairingQrCodec.formatHostPort(host: payload.host, port: payload.port))
            api.setBaseURL(session.baseURL)
            store.saveSession(session)
            lastError = nil
            return
        }
        // 短码 / nonce:走 pairing/exchange 换主机基址。
        let code = payload.token.isEmpty ? payload.nonce : payload.token
        await applyPairing(code: code)
    }

    func setRelayDesktopId(_ id: String) {
        relayDesktopId = id
        defaults.set(id, forKey: ExtraKey.relayDesktopId)
    }

    func setMarketAccessToken(_ token: String) {
        marketAccessToken = token
        defaults.set(token, forKey: ExtraKey.marketToken)
    }

    func logout() {
        store.clearSession()
        session.accessToken = ""
        session.sessionId = ""
        session.displayName = ""
        api.setAccessToken("")
        userId = 0
        relayDesktopId = ""
        marketAccessToken = ""
        defaults.removeObject(forKey: ExtraKey.userId)
        defaults.removeObject(forKey: ExtraKey.relayDesktopId)
        defaults.removeObject(forKey: ExtraKey.marketToken)
        cache.clearAll()
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

    // MARK: - 对话(SSE 流式 + 本地缓存;item ① + ②)

    /// 流式对话(对标 Android streamChat):
    /// - 入口先把 user 消息写入本地缓存,并取最近 6 条作为 context.recent_messages;
    /// - 经 APIClient.streamChat 补 source/mode/user_id/context/industry + 单次重试;
    /// - done 时把最终回复写入本地缓存(供下次冷启动秒出)。
    /// industry 留空:后端按 session account_kind 自动派生(与 Android 一致,手机端不传)。
    func streamChat(message: String,
                    sessionId: String = "default",
                    onToken: @escaping (String) -> Void,
                    onDone: @escaping (String) -> Void,
                    onError: @escaping (String) -> Void) async {
        cache.cache(role: "user", text: message, sessionId: sessionId)
        let recent = cache.messages(sessionId: sessionId)
            .suffix(6)
            .map { ChatContextMessage(role: $0.role, content: $0.text) }

        var accumulated = ""
        do {
            for try await chunk in api.streamChat(message: message, userId: userId, recentMessages: Array(recent)) {
                switch chunk {
                case .token(let t):
                    accumulated += t
                    onToken(t)
                case .done(let full):
                    let text = full.isEmpty ? accumulated : full
                    if !text.isEmpty { cache.cache(role: "assistant", text: text, sessionId: sessionId) }
                    onDone(text)
                    return
                }
            }
            if !accumulated.isEmpty { cache.cache(role: "assistant", text: accumulated, sessionId: sessionId) }
            onDone(accumulated)
        } catch {
            let msg = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            onError(msg)
        }
    }

    // MARK: - 市场 MOD WebView(item ⑨)

    /// 解析某 MOD 的 WebView 地址(在线走电脑端 mod/{id}/,离线走 MODstore workbench)。
    /// 在线判定:基址可达(对企业默认基址做一次健康探测)。
    func modWebUrl(modId: String) async -> String {
        let online = await isHostOnline()
        return api.modWebUrl(modId: modId, online: online)
    }

    /// 注入 MOD WebView 的双 token(market access + FHD access;对标 Android marketTokensForWeb)。
    /// 优先 market token,缺失回退 FHD access token。
    func marketTokensForWeb() -> (access: String, fhd: String) {
        let access = marketAccessToken.isEmpty ? session.accessToken : marketAccessToken
        return (access, session.accessToken)
    }

    /// 健康探测当前基址(GET api/mobile/v1/health),失败即视为离线。
    func isHostOnline() async -> Bool {
        guard let url = URL(string: resolvedBaseURL + APIEndpoints.health) else { return false }
        var req = URLRequest(url: url)
        req.timeoutInterval = 4
        if !session.accessToken.isEmpty {
            req.setValue("Bearer \(session.accessToken)", forHTTPHeaderField: "Authorization")
        }
        if let (_, resp) = try? await URLSession.shared.data(for: req),
           let code = (resp as? HTTPURLResponse)?.statusCode {
            return code < 400
        }
        return false
    }

    // MARK: - 派生客户端

    func makeSSEClient() -> SSEChatClient {
        SSEChatClient(baseURL: resolvedBaseURL, accessToken: session.accessToken)
    }

    func makeIMClient() -> IMWebSocketClient {
        IMWebSocketClient(baseURL: resolvedBaseURL, sessionId: session.sessionId)
    }
}
