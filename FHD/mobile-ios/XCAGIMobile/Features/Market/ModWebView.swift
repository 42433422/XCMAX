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
        if !token.isEmpty {
            // 注入常见登录态键(具体键名可按 Web 端 token 存储约定再校准)。
            let js = """
            try {
              localStorage.setItem('access_token', '\(token)');
              localStorage.setItem('fhd_access_token', '\(token)');
              localStorage.setItem('token', '\(token)');
            } catch (e) {}
            """
            let script = WKUserScript(source: js, injectionTime: .atDocumentStart, forMainFrameOnly: true)
            config.userContentController.addUserScript(script)
        }
        let web = WKWebView(frame: .zero, configuration: config)
        web.allowsBackForwardNavigationGestures = true

        var req = URLRequest(url: url)
        req.setValue("ios", forHTTPHeaderField: "X-XCAGI-Client")
        if !token.isEmpty { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        web.load(req)
        return web
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}
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
