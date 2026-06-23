package com.xiuci.xcagi.mobile.navigation

import com.xiuci.xcagi.mobile.model.ChatMsg

/** 从超级员工助手消息中解析仍可操作（未合并/未丢弃）的开发任务分支。 */
private val SUPER_EMPLOYEE_BRANCH_RE = Regex("(super-employee/[\\w./-]+)")

private fun resolveActiveGitBranchesFromRows(messages: Iterable<Pair<String, String>>): List<String> {
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

fun resolveActiveGitBranches(messages: List<ChatMsg>): List<String> =
    resolveActiveGitBranchesFromRows(messages.map { it.role to it.text })

fun resolveActiveGitBranchesFromPairs(messages: List<Pair<String, String>>): List<String> =
    resolveActiveGitBranchesFromRows(messages)

fun resolveLatestGitBranch(messages: List<ChatMsg>): String? =
    resolveActiveGitBranches(messages).lastOrNull()

fun resolveLatestGitBranchFromPairs(messages: List<Pair<String, String>>): String? =
    resolveActiveGitBranchesFromPairs(messages).lastOrNull()

fun shortGitBranchLabel(branch: String): String =
    branch.substringAfterLast('/').ifBlank { branch }
