package com.xiuci.xcagi.mobile.core.cs

import com.xiuci.xcagi.mobile.core.network.FhdApi
import com.xiuci.xcagi.mobile.core.network.ServerRouter
import com.xiuci.xcagi.mobile.model.CsInfoDto
import com.xiuci.xcagi.mobile.model.CsMessageItemDto
import com.xiuci.xcagi.mobile.model.CsMessagesListDto
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class CsRepository @Inject constructor(
    private val serverRouter: ServerRouter,
) {
    private val _messages = MutableStateFlow<List<CsMessageItemDto>>(emptyList())
    val messages: StateFlow<List<CsMessageItemDto>> = _messages

    private val _streaming = MutableStateFlow(false)
    val streaming: StateFlow<Boolean> = _streaming

    private val _csInfo = MutableStateFlow<CsInfoDto?>(null)
    val csInfo: StateFlow<CsInfoDto?> = _csInfo

    private var fhdApi: FhdApi? = null
    private var cachedBase: String? = null

    private fun api(): FhdApi {
        val base = serverRouter.fhdBaseUrl()
        if (fhdApi == null || cachedBase != base) {
            cachedBase = base
            fhdApi =
                Retrofit.Builder()
                    .baseUrl(base)
                    .client(OkHttpClient.Builder().build())
                    .addConverterFactory(GsonConverterFactory.create())
                    .build()
                    .create(FhdApi::class.java)
        }
        return fhdApi!!
    }

    suspend fun loadCsInfo(): Result<CsInfoDto> = runCatching {
        val resp = api().getCsInfo()
        if (!resp.isSuccessful) {
            throw Exception("CS info failed: ${resp.code()}")
        }
        val body = resp.body() ?: throw Exception("CS info response body is null")
        _csInfo.value = body
        body
    }

    suspend fun sendMessage(body: String): Result<String> = runCatching {
        _streaming.value = true
        try {
            val resp = api().sendCsMessage(mapOf("body" to body))
            if (!resp.isSuccessful) {
                throw Exception("Send CS message failed")
            }
            resp.body()?.messageId ?: throw Exception("Send CS message response body is null")
        } finally {
            _streaming.value = false
        }
    }

    suspend fun loadMessages(since: String? = null): Result<Unit> = runCatching {
        val resp = api().getCsMessages(since)
        if (!resp.isSuccessful) {
            throw Exception("Load CS messages failed")
        }
        val listBody = resp.body() ?: return@runCatching
        val newMsgs = listBody.messages
        _messages.value = if (since == null) newMsgs else _messages.value + newMsgs
    }

    fun stopStream() {
        _streaming.value = false
    }

    fun clearMessages() {
        _messages.value = emptyList()
    }
}
