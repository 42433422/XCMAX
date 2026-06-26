package com.xiuci.xcagi.mobile.core.model

/** AI 群聊消息气泡 UI：讨论 → 分工 → 派单 → 汇报 → 验收（含误验收待复核）。 */
data class AiGroupMessageKindUi(
    val badge: String,
    val bubbleTone: AiGroupBubbleTone,
    val needsReview: Boolean,
)

enum class AiGroupBubbleTone {
    CHAT,
    DISCUSSION,
    ROUTING,
    WORK,
    ACCEPTANCE,
    ACCEPTANCE_REVIEW,
}

object AiGroupMessageUi {
    fun resolve(kind: String?, status: String?, body: String?): AiGroupMessageKindUi {
        val k = kind.orEmpty().trim().lowercase()
        val bodyText = body.orEmpty()
        return when (k) {
            "discussion", "super_discussion" ->
                AiGroupMessageKindUi("讨论", AiGroupBubbleTone.DISCUSSION, false)
            "routing_decision" ->
                AiGroupMessageKindUi("分工", AiGroupBubbleTone.ROUTING, false)
            "work_order" ->
                AiGroupMessageKindUi("派单", AiGroupBubbleTone.WORK, false)
            "work_report", "relay_work_report" ->
                AiGroupMessageKindUi("汇报", AiGroupBubbleTone.WORK, false)
            "work_acceptance" -> {
                val needsReview =
                    status.orEmpty().trim().lowercase() == "needs_review" || bodyText.contains("需要复核")
                if (needsReview) {
                    AiGroupMessageKindUi("待复核", AiGroupBubbleTone.ACCEPTANCE_REVIEW, true)
                } else {
                    AiGroupMessageKindUi("可验收", AiGroupBubbleTone.ACCEPTANCE, false)
                }
            }
            else -> AiGroupMessageKindUi("", AiGroupBubbleTone.CHAT, false)
        }
    }

    fun sendingLabel(dispatchMode: Boolean): String =
        if (dispatchMode) "员工正在执行并汇报…" else "AI 成员正在讨论并回复…"
}
