package com.xiuci.xcagi.mobile.core.network

import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class MobileCookieJar @Inject constructor() : CookieJar {
    private val lock = Any()
    private val cookies = mutableListOf<Cookie>()

    override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
        if (cookies.isEmpty()) return
        synchronized(lock) {
            cookies.forEach { incoming ->
                this.cookies.removeAll {
                    it.name == incoming.name &&
                        it.domain == incoming.domain &&
                        it.path == incoming.path
                }
                this.cookies.add(incoming)
            }
        }
    }

    override fun loadForRequest(url: HttpUrl): List<Cookie> {
        val now = System.currentTimeMillis()
        synchronized(lock) {
            cookies.removeAll { it.expiresAt < now }
            return cookies.filter { it.matches(url) }
        }
    }

    fun csrfToken(url: HttpUrl): String {
        return loadForRequest(url)
            .firstOrNull { it.name == "csrf_token" }
            ?.value
            .orEmpty()
    }
}
