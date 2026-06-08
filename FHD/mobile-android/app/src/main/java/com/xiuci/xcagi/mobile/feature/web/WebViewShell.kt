package com.xiuci.xcagi.mobile.feature.web

import android.annotation.SuppressLint
import android.graphics.Bitmap
import android.net.Uri
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.browser.customtabs.CustomTabsIntent
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView

@SuppressLint("SetJavaScriptEnabled")
@Composable
fun WebViewShell(
    url: String,
    modifier: Modifier = Modifier,
    extraHeaders: Map<String, String> = emptyMap(),
    onPageFinished: ((WebView) -> Unit)? = null,
    enableFileChooser: Boolean = false,
) {
    var loading by remember { mutableStateOf(true) }
    var progress by remember { mutableIntStateOf(0) }
    var loadError by remember { mutableStateOf<String?>(null) }
    var webViewRef by remember { mutableStateOf<WebView?>(null) }
    var fileCallback by remember { mutableStateOf<ValueCallback<Array<Uri>>?>(null) }
    val filePicker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        fileCallback?.onReceiveValue(uri?.let { arrayOf(it) })
        fileCallback = null
    }

    Box(modifier.fillMaxSize()) {
        AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { ctx ->
                WebView(ctx).apply {
                    settings.javaScriptEnabled = true
                    settings.domStorageEnabled = true
                    settings.databaseEnabled = true
                    settings.loadWithOverviewMode = true
                    settings.useWideViewPort = true
                    webChromeClient = object : WebChromeClient() {
                        override fun onProgressChanged(view: WebView?, newProgress: Int) {
                            progress = newProgress
                            if (newProgress >= 100) loading = false
                        }

                        override fun onShowFileChooser(
                            webView: WebView?,
                            filePathCallback: ValueCallback<Array<Uri>>?,
                            fileChooserParams: FileChooserParams?,
                        ): Boolean {
                            if (!enableFileChooser) return false
                            fileCallback?.onReceiveValue(null)
                            fileCallback = filePathCallback
                            filePicker.launch("*/*")
                            return true
                        }
                    }
                    webViewClient = object : WebViewClient() {
                        override fun shouldOverrideUrlLoading(
                            view: WebView?,
                            request: WebResourceRequest?,
                        ): Boolean {
                            val target = request?.url?.toString() ?: return false
                            if (WebViewUrlPolicy.isAllowed(target)) return false
                            CustomTabsIntent.Builder().build().launchUrl(ctx, android.net.Uri.parse(target))
                            return true
                        }

                        override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                            loading = true
                            loadError = null
                            progress = 0
                        }

                        override fun onPageFinished(view: WebView?, finishedUrl: String?) {
                            loading = false
                            progress = 100
                            view?.let { onPageFinished?.invoke(it) }
                        }

                        override fun onReceivedError(
                            view: WebView?,
                            request: WebResourceRequest?,
                            error: WebResourceError?,
                        ) {
                            if (request?.isForMainFrame == true) {
                                loading = false
                                loadError = error?.description?.toString() ?: "页面加载失败"
                            }
                        }
                    }
                    webViewRef = this
                    loadUrl(url, extraHeaders)
                }
            },
            update = { view ->
                if (view.url != url && !loading) {
                    view.loadUrl(url, extraHeaders)
                }
            },
        )

        if (loading && progress < 100) {
            LinearProgressIndicator(
                progress = { progress / 100f },
                modifier = Modifier
                    .fillMaxWidth()
                    .align(Alignment.TopCenter),
            )
        }

        loadError?.let { err ->
            Column(
                Modifier
                    .align(Alignment.Center)
                    .padding(24.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(err, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
                Button(
                    onClick = {
                        loadError = null
                        loading = true
                        webViewRef?.reload()
                    },
                    modifier = Modifier.padding(top = 12.dp),
                ) { Text("重试") }
            }
        }
    }
}
