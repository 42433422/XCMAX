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

internal object AuthHeaderPolicy {
    private fun normalizedBase(base: String): String = base.trim().trimEnd('/')

    fun isEnterpriseFhdRequest(url: String, enterpriseFhdBaseUrl: String): Boolean {
        val base = normalizedBase(enterpriseFhdBaseUrl)
        if (base.isBlank()) return false
        return url == base || url.startsWith("$base/")
    }

    fun isModstoreRequest(
        url: String,
        modstoreBaseUrl: String,
        enterpriseFhdBaseUrl: String,
    ): Boolean {
        val base = normalizedBase(modstoreBaseUrl)
        if (base.isBlank()) return false
        return (url == base || url.startsWith("$base/")) &&
            !isEnterpriseFhdRequest(url, enterpriseFhdBaseUrl)
    }

    fun selectBearer(
        url: String,
        fhdToken: String,
        marketToken: String,
        modstoreBaseUrl: String,
        enterpriseFhdBaseUrl: String,
    ): String {
        val fhd = fhdToken.trim()
        val market = marketToken.trim()
        return when {
            isEnterpriseFhdRequest(url, enterpriseFhdBaseUrl) -> fhd
            isModstoreRequest(url, modstoreBaseUrl, enterpriseFhdBaseUrl) -> market
            fhd.isNotBlank() -> fhd
            else -> market
        }
    }

    fun shouldAttachSelectedBearer(
        isPublicAuthWriteRequest: Boolean,
        callerAuthorization: String,
        selectedBearer: String,
    ): Boolean =
        !isPublicAuthWriteRequest && callerAuthorization.isBlank() && selectedBearer.isNotBlank()
}

@Singleton
class AuthInterceptor @Inject constructor(
    private val sessionStore: SessionStore,
    private val cookieJar: MobileCookieJar,
) : Interceptor {
    private fun isPublicAuthWriteRequest(url: HttpUrl): Boolean {
        val path = url.encodedPath.trimEnd('/')
        return path.endsWith("/api/auth/login") ||
            path.endsWith("/api/auth/register") ||
            path.endsWith("/api/auth/login-with-phone-code") ||
            path.endsWith("/" + ApiEndpoints.AUTH_LOGIN) ||
            path.endsWith("/" + ApiEndpoints.AUTH_REGISTER) ||
            path.endsWith("/" + ApiEndpoints.AUTH_LOGIN_WITH_PHONE_CODE) ||
            path.endsWith("/" + ApiEndpoints.AUTH_REFRESH) ||
            path.endsWith("/" + ApiEndpoints.AUTH_OIDC_EXCHANGE) ||
            path.endsWith("/" + ApiEndpoints.AUTH_QR_CONFIRM) ||
            path.endsWith("/" + ApiEndpoints.PAIRING_ISSUE) ||
            path.endsWith("/" + ApiEndpoints.PAIRING_EXCHANGE) ||
            path.endsWith("/" + ApiEndpoints.RELAY_MOBILE_CONFIRM) ||
            path.endsWith("/" + ApiEndpoints.RELAY_MOBILE_CONFIRM_CODE)
    }

    override fun intercept(chain: Interceptor.Chain): Response {
        val fhdToken = runBlocking { sessionStore.fhdAccessFlow.first() }
        val marketToken = runBlocking { sessionStore.marketTokenFlow.first() }
        val sessionId = runBlocking { sessionStore.fhdSessionId() }
        val request = chain.request()
        val url = request.url.toString()
        val bearer =
            AuthHeaderPolicy.selectBearer(
                url = url,
                fhdToken = fhdToken,
                marketToken = marketToken,
                modstoreBaseUrl = BuildConfig.MODSTORE_BASE_URL,
                enterpriseFhdBaseUrl = BuildConfig.ENTERPRISE_FHD_BASE_URL,
            )

        val builder = request.newBuilder()
            .header("X-XCAGI-Client", "android")
            .header("X-XCAGI-SKU", ProductSkuConfig.sku)
        if (sessionId.isNotBlank() && request.header("X-Session-ID").isNullOrBlank()) {
            builder.header("X-Session-ID", sessionId)
        }
        if (request.method.uppercase() in setOf("POST", "PUT", "PATCH", "DELETE")) {
            val csrf = cookieJar.csrfToken(request.url)
            if (csrf.isNotBlank()) {
                builder.header("X-CSRF-Token", csrf)
            }
        }
        val callerAuthorization = request.header("Authorization").orEmpty().trim()
        if (AuthHeaderPolicy.shouldAttachSelectedBearer(
                isPublicAuthWriteRequest = isPublicAuthWriteRequest(request.url),
                callerAuthorization = callerAuthorization,
                selectedBearer = bearer,
            )) {
            builder.header("Authorization", "Bearer $bearer")
        }
        return chain.proceed(builder.build())
    }
}
