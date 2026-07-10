package com.xiuci.xcagi.mobile.feature.modhost

import android.annotation.SuppressLint
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import com.xiuci.xcagi.mobile.feature.web.UrlHostPolicy
import com.xiuci.xcagi.mobile.feature.web.buildTokenInjectScript
import com.xiuci.xcagi.mobile.feature.web.shouldInjectFhdSession
import com.xiuci.xcagi.mobile.feature.web.shouldInjectMarketTokens

@SuppressLint("SetJavaScriptEnabled")
@Composable
fun ModWebViewScreen(
    url: String,
    bearer: String,
    marketAccess: String = "",
    marketRefresh: String = "",
    fhdAccess: String = "",
) {
    if (!UrlHostPolicy.isTrustedWebViewUrl(url)) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text(
                "页面地址不受信任，已阻止加载",
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(24.dp),
            )
        }
        return
    }
    AndroidView(
        modifier = Modifier.fillMaxSize(),
        factory = { ctx ->
            WebView(ctx).apply {
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                webViewClient = object : WebViewClient() {
                    override fun shouldOverrideUrlLoading(view: WebView?, request: android.webkit.WebResourceRequest?): Boolean {
                        val nextUrl = request?.url?.toString() ?: return true
                        return !UrlHostPolicy.isTrustedWebViewUrl(nextUrl)
                    }

                    @Deprecated("Deprecated in Android API")
                    override fun shouldOverrideUrlLoading(view: WebView?, nextUrl: String?): Boolean =
                        nextUrl.isNullOrBlank() || !UrlHostPolicy.isTrustedWebViewUrl(nextUrl)

                    override fun onPageFinished(view: WebView?, finishedUrl: String?) {
                        val currentUrl = finishedUrl ?: return
                        val injectMarket = shouldInjectMarketTokens(currentUrl) && marketAccess.isNotBlank()
                        val injectFhd = shouldInjectFhdSession(currentUrl) && fhdAccess.isNotBlank()
                        if (injectMarket || injectFhd) {
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
                    if (bearer.isNotBlank() && shouldInjectFhdSession(url)) {
                        put("Authorization", bearer)
                    }
                }
                loadUrl(url, headers)
            }
        },
    )
}
