package com.xiuci.xcagi.mobile.feature.modhost

import android.annotation.SuppressLint
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
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
    val injectMarket = shouldInjectMarketTokens(url) && marketAccess.isNotBlank()
    val injectFhd = shouldInjectFhdSession(url) && fhdAccess.isNotBlank()
    val injectScript = injectMarket || injectFhd
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
