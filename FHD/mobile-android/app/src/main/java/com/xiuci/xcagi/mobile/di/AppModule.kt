package com.xiuci.xcagi.mobile.di

import com.google.gson.Gson
import com.xiuci.xcagi.mobile.core.datastore.SessionStore
import com.xiuci.xcagi.mobile.core.network.AuthInterceptor
import com.xiuci.xcagi.mobile.core.network.MobileCookieJar
import com.xiuci.xcagi.mobile.core.network.ServerRouter
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import java.util.concurrent.TimeUnit
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object AppModule {

    @Provides
    @Singleton
    fun provideGson(): Gson = Gson()

    @Provides
    @Singleton
    fun provideServerRouter(): ServerRouter = ServerRouter()

    @Provides
    @Singleton
    fun provideOkHttp(
        authInterceptor: AuthInterceptor,
        cookieJar: MobileCookieJar,
    ): OkHttpClient {
        val log = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BASIC
        }
        return OkHttpClient.Builder()
            .cookieJar(cookieJar)
            .addInterceptor(authInterceptor)
            .addInterceptor(log)
            // 与后端 xcagi_compat_chat_helpers.py 的首包超时(20s)/总超时(120s)对齐，
            // 避免 LLM 上游 SSL 握手间歇性超时时移动端先于后端报错。
            .connectTimeout(20, TimeUnit.SECONDS)
            .readTimeout(120, TimeUnit.SECONDS)
            .build()
    }

}
