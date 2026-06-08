package com.xiuci.xcagi.mobile.core.model

data class ApprovalDetail(
    val id: Int,
    val title: String,
    val status: String,
    val requestNo: String,
    val applicantName: String,
    val description: String,
    val submittedAt: String,
    val currentNodeName: String,
    val flowName: String,
) {
    companion object {
        @Suppress("UNCHECKED_CAST")
        fun fromResponse(raw: Map<String, Any?>): ApprovalDetail? {
            val data = (raw["data"] as? Map<String, Any?>) ?: raw
            val id = (data["id"] as? Number)?.toInt() ?: return null
            return ApprovalDetail(
                id = id,
                title = data["title"]?.toString().orEmpty().ifBlank { "审批 #$id" },
                status = data["status"]?.toString().orEmpty(),
                requestNo = data["request_no"]?.toString().orEmpty(),
                applicantName = data["applicant_name"]?.toString().orEmpty().ifBlank { "—" },
                description = data["description"]?.toString().orEmpty(),
                submittedAt = data["submitted_at"]?.toString().orEmpty(),
                currentNodeName = data["current_node_name"]?.toString().orEmpty(),
                flowName = data["flow_name"]?.toString().orEmpty(),
            )
        }
    }
}
