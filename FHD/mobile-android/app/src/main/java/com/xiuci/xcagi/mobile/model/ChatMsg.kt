package com.xiuci.xcagi.mobile.model

/** 一条聊天消息的发送状态，用于气泡的「发送中 / 已送达 / 失败」指示。 */
enum class ChatStatus { SENDING, SENT, FAILED }

/**
 * 主聊天消息模型（替代原来的 Pair<String, String>）。
 *
 * - [role]   "user" / "assistant"
 * - [text]   正文
 * - [ts]     发送时间（毫秒）；0 表示未知（不展示时间戳），缓存层已持久化真实 ts
 * - [status] 发送状态（流式中=SENDING，完成=SENT，出错=FAILED）
 * - [quote]  被引用消息的折叠原文（仅 user 引用回复时有值），用于气泡内的引用框
 */
data class ChatMsg(
    val role: String,
    val text: String,
    val ts: Long = 0L,
    val status: ChatStatus = ChatStatus.SENT,
    val quote: String? = null,
)
