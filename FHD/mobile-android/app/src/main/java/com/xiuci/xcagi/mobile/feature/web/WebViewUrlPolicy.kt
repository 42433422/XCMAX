package com.xiuci.xcagi.mobile.feature.web

import android.net.Uri
import com.xiuci.xcagi.mobile.BuildConfig

object WebViewUrlPolicy {
    fun isAllowed(url: String, extraLanHost: String? = null): Boolean =
        UrlHostPolicy.isTrustedWebViewUrl(url, extraLanHost)

    fun modstoreHost(): String = Uri.parse(BuildConfig.MODSTORE_BASE_URL).host.orEmpty()
}
