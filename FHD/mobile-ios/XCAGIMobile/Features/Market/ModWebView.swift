import SwiftUI
import Foundation
import WebKit

/// MOD 承载 WebView(对标 Android `ModWebViewScreen` 的 WKWebView 注入登录态)。
///
/// 三类承载页,鉴权方式不同(精确对标 Android `feature/web/WebViewTokenScript.kt`):
/// 1. MODstore 市场页(`/workbench/...`、modstore 根):靠 `localStorage.modstore_token`(+ refresh),不加 `Authorization` 头。
/// 2. FHD 企业页(局域网 http 或 `xiu-ci.com/fhd-api` 等 https FHD 页):同时注入 `Bearer` 头 + `session_id` cookie。
/// 3. 其它:仅带 `Bearer` 头。
///
/// 关键修复:旧实现用 `absoluteString.contains("xiu-ci.com")` 笼统判市场,
/// 会把 `https://xiu-ci.com/fhd-api/mod/{id}/` 这种 FHD 企业 mod 页误判成市场页,
/// 导致 FHD 页既不注入 session cookie、又被剥掉 `Authorization` 头 → 未鉴权加载。
/// 这里改成精确 host/path 判定区分 MODstore 与 FHD。
struct ModWebView: UIViewRepresentable {
    let url: URL
    /// FHD access token(Bearer + session_id cookie 用)。
    let fhdAccess: String
    /// market access token(MODstore localStorage 用;缺失时调用方回退 FHD token)。
    var marketAccess: String = ""
    var marketRefresh: String = ""

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        let fhdTok = fhdAccess.trimmingCharacters(in: .whitespaces)
        let marketTok = marketAccess.trimmingCharacters(in: .whitespaces)

        let isMarket = ModWebView.isMarketURL(url)
        let isFhd = ModWebView.isFhdURL(url)

        let injectMarket = isMarket && !marketTok.isEmpty
        let injectFhd = isFhd && !fhdTok.isEmpty

        if injectMarket || injectFhd {
            let source = ModWebView.injectScript(
                marketAccess: injectMarket ? marketTok : "",
                marketRefresh: injectMarket ? marketRefresh.trimmingCharacters(in: .whitespaces) : "",
                fhdAccess: injectFhd ? fhdTok : ""
            )
            let script = WKUserScript(source: source,
                                      injectionTime: .atDocumentStart, forMainFrameOnly: true)
            config.userContentController.addUserScript(script)
        }

        let web = WKWebView(frame: .zero, configuration: config)
        web.allowsBackForwardNavigationGestures = true

        var req = URLRequest(url: url)
        req.setValue("ios", forHTTPHeaderField: "X-XCAGI-Client")
        // 与 Android 一致:市场页靠 localStorage(modstore_token),不加 Authorization;
        // FHD/其它页带 Bearer(FHD 页同时由上面的脚本注入 session_id cookie)。
        if !injectMarket && !fhdTok.isEmpty {
            req.setValue("Bearer \(fhdTok)", forHTTPHeaderField: "Authorization")
        }
        web.load(req)
        return web
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}

    // MARK: - 精确判定(对标 Android feature/web/WebViewTokenScript.kt)

    /// MODstore 市场 / 云端工作台页:modstore 主机 + `/workbench`(或非 `/fhd-api` 根路径)。
    /// 显式排除 `/fhd-api` 路径(那是 FHD 企业页,不能当市场页剥鉴权)。
    static func isMarketURL(_ url: URL) -> Bool {
        guard let host = url.host?.lowercased() else { return false }
        guard ModWebView.isModstoreHost(host) else { return false }
        let path = url.path.lowercased()
        // FHD 企业页(同主机不同路径)不算市场页。
        if path.hasPrefix("/fhd-api") { return false }
        // 云端工作台 mod 承载页 + modstore 自有页面。
        return true
    }

    /// FHD 企业页:局域网 http 主机,或 `xiu-ci.com/fhd-api` 这类 https FHD 页。
    /// 这些页需要 `session_id` cookie + `Bearer` 头双鉴权。
    static func isFhdURL(_ url: URL) -> Bool {
        let scheme = url.scheme?.lowercased() ?? ""
        let host = url.host?.lowercased() ?? ""
        let path = url.path.lowercased()

        // 局域网/桌面端:http 私网或 localhost。
        if scheme == "http", ModWebView.isLanHost(host) {
            return true
        }
        // 公网 FHD 企业页:modstore 主机但路径在 /fhd-api 下。
        if scheme == "https", ModWebView.isModstoreHost(host), path.hasPrefix("/fhd-api") {
            return true
        }
        return false
    }

    /// 是否 MODstore / 官网主机(`xiu-ci.com` 及其子域)。
    static func isModstoreHost(_ host: String) -> Bool {
        host == "xiu-ci.com" || host.hasSuffix(".xiu-ci.com")
    }

    /// 是否局域网 / 本机主机(对标 Android `shouldInjectFhdSession` 的私网判定)。
    static func isLanHost(_ host: String) -> Bool {
        if host == "localhost" || host == "127.0.0.1" { return true }
        if host.hasPrefix("192.168.") { return true }
        if host.hasPrefix("10.") { return true }
        // 172.16.0.0 – 172.31.255.255
        if host.hasPrefix("172.") {
            let parts = host.split(separator: ".")
            if parts.count >= 2, let second = Int(parts[1]), (16...31).contains(second) {
                return true
            }
        }
        return false
    }

    /// 注入脚本(对标 Android `buildTokenInjectScript`):
    /// market → `localStorage.modstore_token`(+ refresh);FHD → `session_id` cookie。
    static func injectScript(marketAccess: String, marketRefresh: String, fhdAccess: String) -> String {
        func esc(_ s: String) -> String {
            s.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "'", with: "\\'")
        }
        var lines = ""
        if !marketAccess.isEmpty {
            lines += "localStorage.setItem('modstore_token','\(esc(marketAccess))');"
        }
        if !marketRefresh.isEmpty {
            lines += "localStorage.setItem('modstore_refresh_token','\(esc(marketRefresh))');"
        }
        if !fhdAccess.isEmpty {
            lines += "document.cookie = 'session_id=\(esc(fhdAccess)); path=/; SameSite=Lax';"
        }
        return """
        (function() {
          try {
            \(lines)
            window.__XCAGI_CLIENT__ = 'ios';
            document.documentElement.classList.add('xcagi-client-ios');
            window.dispatchEvent(new Event('xcagi-client-ready'));
          } catch (e) {}
        })();
        """
    }
}

/// MOD 页面承载(全屏 WebView)。注入双 token(market access + FHD access)。
struct ModWebViewScreen: View {
    let title: String
    let urlString: String
    @EnvironmentObject private var session: SessionManager

    var body: some View {
        Group {
            if let url = URL(string: urlString) {
                let tokens = session.marketTokensForWeb()
                ModWebView(url: url,
                           fhdAccess: tokens.fhd,
                           marketAccess: tokens.access)
                    .ignoresSafeArea(edges: .bottom)
            } else {
                ErrorStateView(message: "无效的页面地址:\(urlString)")
            }
        }
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
    }
}
