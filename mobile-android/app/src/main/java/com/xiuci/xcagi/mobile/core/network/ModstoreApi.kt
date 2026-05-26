package com.xiuci.xcagi.mobile.core.network

import com.xiuci.xcagi.mobile.core.model.MarketAuthResponse
import com.xiuci.xcagi.mobile.core.model.MarketMeResponse
import com.xiuci.xcagi.mobile.core.model.MarketLoginBody
import com.xiuci.xcagi.mobile.core.model.MarketPasswordLoginBody
import com.xiuci.xcagi.mobile.core.model.MarketRegisterBody
import com.xiuci.xcagi.mobile.core.model.MarketSendCodeBody
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.Query

interface ModstoreApi {
    @POST("api/auth/send-phone-code")
    suspend fun sendPhoneCode(@Body body: MarketSendCodeBody): Map<String, Any?>

    @POST("api/auth/register")
    suspend fun register(@Body body: MarketRegisterBody): MarketAuthResponse

    @POST("api/auth/login")
    suspend fun loginWithPassword(@Body body: MarketPasswordLoginBody): MarketAuthResponse

    @POST("api/auth/login-with-phone-code")
    suspend fun loginWithPhoneCode(@Body body: MarketLoginBody): MarketAuthResponse

    @GET("api/auth/me")
    suspend fun authMe(): MarketMeResponse

    @GET("api/market/catalog")
    suspend fun marketCatalog(
        @Header("Authorization") auth: String? = null,
        @Query("limit") limit: Int = 20,
    ): Map<String, Any?>
}
