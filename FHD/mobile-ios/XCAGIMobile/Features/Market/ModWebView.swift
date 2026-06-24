import SwiftUI
import Foundation
import WebKit

/// MOD 承载 WebView(对标 Android `ModWebViewScreen` 的 WKWebView 注入登录态)。
/// 同源 FHD:Authorization 头 + `X-XCAGI-Client`;并在 documentStart 注入令牌到 localStorage。
struct ModWebView: UIViewRepresentable {
    let url: URL
    let bearer: String

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        let token = bearer.trimmingCharacters(in: .whitespaces)
        let isMarket = ModWebView.isMarketURL(url)
        let isFhdLan = ModWebView.isFhdLanURL(url)

        if !token.isEmpty {
            let script = WKUserScript(source: ModWebView.injectScript(token: token, isMarket: isMarket, isFhdLan: isFhdLan),
                                      injectionTime: .atDocumentStart, forMainFrameOnly: true)
            config.userContentController.addUserScript(script)
        }
        let web = WKWebView(frame: .zero, configuration: config)
        web.allowsBackForwardNavigationGestures = true

        var req = URLRequest(url: url)
        req.setValue("ios", forHTTPHeaderField: "X-XCAGI-Client")
        // 与 Android 一致:市场页靠 localStorage(modstore_token),不加 Authorization;其余加 Bearer。
        if !token.isEmpty && !isMarket {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        web.load(req)
        return web
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}

    // 对标 Android feature/web/WebViewTokenScript.kt:精确镜像注入键名与判定。
    static func isMarketURL(_ url: URL) -> Bool {
        url.absoluteString.lowercased().contains("xiu-ci.com")
    }

    static func isFhdLanURL(_ url: URL) -> Bool {
        let s = url.absoluteString.lowercased()
        guard !isMarketURL(url), s.hasPrefix("http://") else { return false }
        return s.contains("127.0.0.1") || s.contains("192.168.") || s.contains("10.") || s.contains("localhost")
    }

    static func injectScript(token: String, isMarket: Bool, isFhdLan: Bool) -> String {
        let esc = token.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "'", with: "\\'")
        var lines = ""
        if isMarket {
            lines += "localStorage.setItem('modstore_token','\(esc)');"
        }
        if isFhdLan {
            lines += "document.cookie = 'session_id=\(esc); path=/; SameSite=Lax';"
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

/// MOD 页面承载(全屏 WebView)。
struct ModWebViewScreen: View {
    let title: String
    let urlString: String
    @EnvironmentObject private var session: SessionManager

    var body: some View {
        Group {
            if let url = URL(string: urlString) {
                ModWebView(url: url, bearer: session.session.accessToken)
                    .ignoresSafeArea(edges: .bottom)
            } else {
                ErrorStateView(message: "无效的页面地址:\(urlString)")
            }
        }
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
    }
}
