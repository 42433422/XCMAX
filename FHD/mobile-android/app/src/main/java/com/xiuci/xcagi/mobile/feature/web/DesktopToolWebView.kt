package com.xiuci.xcagi.mobile.feature.web

import android.annotation.SuppressLint
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import com.xiuci.xcagi.mobile.ui.components.mobile.WeTopBar

/**
 * 桌面工具 WebView 容器（探索 Tab 点击桌面端工具项后打开）。
 *
 * 带标题栏 + 返回按钮，注入 FHD session token 后加载桌面端页面。
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun DesktopToolWebView(
    url: String,
    title: String,
    bearer: String,
    marketAccess: String = "",
    marketRefresh: String = "",
    fhdAccess: String = "",
    onBack: () -> Unit = {},
) {
    val injectMarket = shouldInjectMarketTokens(url) && marketAccess.isNotBlank()
    val injectFhd = shouldInjectFhdSession(url) && fhdAccess.isNotBlank()
    val injectScript = injectMarket || injectFhd

    Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.surface)) {
        WeTopBar(title = title, onBack = onBack)
        AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { ctx ->
                WebView(ctx).apply {
                    settings.javaScriptEnabled = true
                    settings.domStorageEnabled = true
                    webViewClient = object : WebViewClient() {
                        override fun onPageFinished(view: WebView?, finishedUrl: String?) {
                            if (injectScript) {
                                view?.evaluateJavascript(
                                    buildTokenInjectScript(
                                        accessToken = if (injectMarket) marketAccess else "",
                                        refreshToken = if (injectMarket) marketRefresh else "",
                                        fhdAccessToken = if (injectFhd) fhdAccess else "",
                                    ),
                                    null,
                                )
                            }
                        }
                    }
                    val headers = buildMap {
                        put("X-XCAGI-Client", "android")
                        if (bearer.isNotBlank() && !injectMarket) {
                            put("Authorization", bearer)
                        }
                    }
                    loadUrl(url, headers)
                }
            },
        )
    }
}
