package com.xiuci.xcagi.mobile.core.network

import com.xiuci.xcagi.mobile.BuildConfig
import com.xiuci.xcagi.mobile.core.ProductSkuConfig
import com.xiuci.xcagi.mobile.core.datastore.SessionStore
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import okhttp3.Interceptor
import okhttp3.HttpUrl
import okhttp3.Response
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class AuthInterceptor @Inject constructor(
    private val sessionStore: SessionStore,
) : Interceptor {
    private fun isPublicAuthWriteRequest(url: HttpUrl): Boolean {
        val path = url.encodedPath.trimEnd('/')
        return path.endsWith("/api/auth/login") ||
            path.endsWith("/api/auth/login-with-phone-code") ||
            path.endsWith("/api/mobile/v1/auth/login") ||
            path.endsWith("/api/mobile/v1/auth/login-with-phone-code") ||
            path.endsWith("/api/mobile/v1/auth/refresh") ||
            path.endsWith("/api/mobile/v1/auth/oidc/exchange") ||
            path.endsWith("/api/mobile/v1/auth/qr/confirm")
    }

    override fun intercept(chain: Interceptor.Chain): Response {
        val fhdToken = runBlocking { sessionStore.fhdAccessFlow.first() }
        val marketToken = runBlocking { sessionStore.marketTokenFlow.first() }
        val request = chain.request()
        val url = request.url.toString()
        val modstoreHost = BuildConfig.MODSTORE_BASE_URL.trimEnd('/')
        val isModstore = url.startsWith(modstoreHost)

        val bearer = when {
            isModstore && marketToken.isNotBlank() -> marketToken
            fhdToken.isNotBlank() -> fhdToken
            marketToken.isNotBlank() -> marketToken
            else -> ""
        }

        val builder = request.newBuilder()
            .header("X-XCAGI-Client", "android")
            .header("X-XCAGI-SKU", ProductSkuConfig.sku)
        if (!isPublicAuthWriteRequest(request.url) && bearer.isNotBlank()) {
            builder.header("Authorization", "Bearer $bearer")
        }
        return chain.proceed(builder.build())
    }
}
