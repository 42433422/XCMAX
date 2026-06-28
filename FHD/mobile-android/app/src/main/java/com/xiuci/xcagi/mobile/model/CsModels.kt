package com.xiuci.xcagi.mobile.model

import com.google.gson.annotations.SerializedName

data class CsInfoDto(
    @SerializedName("cs_available") val available: Boolean = false,
    @SerializedName("cs_name") val name: String = "",
    @SerializedName("cs_avatar") val avatar: String? = null,
    @SerializedName("cs_online") val online: Boolean = false,
)

data class CsMessageResponseDto(
    @SerializedName("message_id") val messageId: String = "",
    @SerializedName("request_id") val requestId: Int = 0,
    @SerializedName("reply") val reply: String = "",
    @SerializedName("backend") val backend: String = "",
    @SerializedName("timestamp") val timestamp: String = "",
)

data class CsMessagesListDto(
    @SerializedName("messages") val messages: List<CsMessageItemDto> = emptyList(),
)

data class CsMessageItemDto(
    @SerializedName("message_id") val messageId: String = "",
    @SerializedName("sender") val sender: String = "",   // "cs" | "user"
    @SerializedName("body") val body: String = "",
    @SerializedName("timestamp") val timestamp: String = "",
    @SerializedName("msg_type") val msgType: String = "text",  // text | image | file | card
)

// ── 管理端客服收件箱(运营者视角)──

data class AdminCsInboxDto(
    @SerializedName("conversations") val conversations: List<AdminCsInboxItemDto> = emptyList(),
)

data class AdminCsInboxItemDto(
    @SerializedName("conversationId") val conversationId: Int = 0,
    @SerializedName("customerName") val customerName: String = "",
    @SerializedName("lastMessageAt") val lastMessageAt: String = "",
    @SerializedName("unreadCount") val unreadCount: Int = 0,
)

data class AdminCsMessagesDto(
    @SerializedName("messages") val messages: List<AdminCsMessageItemDto> = emptyList(),
)

data class AdminCsMessageItemDto(
    @SerializedName("messageId") val messageId: String = "",
    @SerializedName("fromCustomer") val fromCustomer: Boolean = false,
    @SerializedName("senderName") val senderName: String = "",
    @SerializedName("body") val body: String = "",
    @SerializedName("timestamp") val timestamp: String = "",
)
