package com.xiuci.xcagi.mobile.navigation

/** 从超级员工助手消息中解析仍可操作（未合并/未丢弃）的开发任务分支。 */
private val SUPER_EMPLOYEE_BRANCH_RE = Regex("(super-employee/[\\w./-]+)")

fun resolveActiveGitBranches(messages: List<Pair<String, String>>): List<String> {
    val active = LinkedHashSet<String>()
    for ((role, text) in messages) {
        if (role != "assistant") continue
        SUPER_EMPLOYEE_BRANCH_RE.findAll(text).forEach { match ->
            active.add(match.groupValues[1])
        }
        if (text.contains("✅ 已合并") || text.contains("已丢弃分支")) {
            val disposed =
                SUPER_EMPLOYEE_BRANCH_RE.findAll(text).map { it.groupValues[1] }.toSet()
            if (disposed.isNotEmpty()) {
                active.removeAll(disposed)
            } else {
                // 兼容旧回复：未带分支名时仍清空全部候选。
                active.clear()
            }
        }
    }
    return active.toList()
}

fun resolveLatestGitBranch(messages: List<Pair<String, String>>): String? =
    resolveActiveGitBranches(messages).lastOrNull()

fun shortGitBranchLabel(branch: String): String =
    branch.substringAfterLast('/').ifBlank { branch }
