package com.xiuci.xcagi.mobile.feature.web

import android.annotation.SuppressLint
import android.os.Handler
import android.os.Looper
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
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
    onUrlOverride: ((String) -> Boolean)? = null,
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
                    if (onUrlOverride != null) {
                        addJavascriptInterface(WebLocationBridge(onUrlOverride), "XcagiAndroid")
                    }
                    webViewClient = object : WebViewClient() {
                        override fun shouldOverrideUrlLoading(
                            view: WebView?,
                            request: WebResourceRequest?,
                        ): Boolean {
                            val nextUrl = request?.url?.toString() ?: return false
                            return onUrlOverride?.invoke(nextUrl) == true
                        }

                        @Deprecated("Deprecated in Android API")
                        override fun shouldOverrideUrlLoading(view: WebView?, nextUrl: String?): Boolean {
                            if (nextUrl.isNullOrBlank()) return false
                            return onUrlOverride?.invoke(nextUrl) == true
                        }

                        override fun onPageFinished(view: WebView?, finishedUrl: String?) {
                            if (onUrlOverride != null) {
                                view?.evaluateJavascript(webLocationBridgeScript(), null)
                            }
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

private class WebLocationBridge(
    private val onUrlOverride: (String) -> Boolean,
) {
    private val mainHandler = Handler(Looper.getMainLooper())

    @JavascriptInterface
    fun onLocationChanged(url: String?) {
        val nextUrl = url?.takeIf { it.isNotBlank() } ?: return
        mainHandler.post { onUrlOverride(nextUrl) }
    }
}

private fun webLocationBridgeScript(): String =
    """
    (function(){
      if (window.__xcagiAndroidLocationBridgeInstalled) return;
      window.__xcagiAndroidLocationBridgeInstalled = true;
      function notify(){
        try {
          if (window.XcagiAndroid && window.XcagiAndroid.onLocationChanged) {
            window.XcagiAndroid.onLocationChanged(String(window.location.href || ""));
          }
        } catch(e) {}
      }
      ["pushState","replaceState"].forEach(function(name){
        var original = window.history && window.history[name];
        if (!original) return;
        window.history[name] = function(){
          var result = original.apply(this, arguments);
          notify();
          return result;
        };
      });
      window.addEventListener("popstate", notify);
      notify();
    })();
    """.trimIndent()
