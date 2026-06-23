package com.xiuci.xcagi.mobile.navigation

import com.xiuci.xcagi.mobile.model.ChatMsg
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class GitBranchPolicyTest {
    @Test
    fun `collects multiple active branches in order`() {
        val messages =
            listOf(
                ChatMsg("assistant", "已推送 super-employee/codex/task-a"),
                ChatMsg("assistant", "继续 super-employee/cursor/task-b"),
            )
        assertEquals(
            listOf(
                "super-employee/codex/task-a",
                "super-employee/cursor/task-b",
            ),
            resolveActiveGitBranches(messages),
        )
        assertEquals("super-employee/cursor/task-b", resolveLatestGitBranch(messages))
    }

    @Test
    fun `removes only merged branch when reply names it`() {
        val messages =
            listOf(
                ChatMsg("assistant", "分支 super-employee/codex/task-a 就绪"),
                ChatMsg("assistant", "分支 super-employee/cursor/task-b 就绪"),
                ChatMsg("assistant", "✅ 已合并 super-employee/codex/task-a → origin/main"),
            )
        assertEquals(
            listOf("super-employee/cursor/task-b"),
            resolveActiveGitBranches(messages),
        )
    }

    @Test
    fun `legacy clear-all when disposition has no branch name`() {
        val messages =
            listOf(
                ChatMsg("assistant", "super-employee/codex/task-a"),
                ChatMsg("assistant", "✅ 已合并并推送"),
            )
        assertEquals(emptyList<String>(), resolveActiveGitBranches(messages))
        assertNull(resolveLatestGitBranch(messages))
    }

    @Test
    fun `ignores user messages`() {
        val messages = listOf(ChatMsg("user", "super-employee/codex/fake"))
        assertEquals(emptyList<String>(), resolveActiveGitBranches(messages))
    }

    @Test
    fun `pair compatibility wrapper keeps old tests readable`() {
        val messages = listOf("assistant" to "super-employee/codex/task-a")

        assertEquals(listOf("super-employee/codex/task-a"), resolveActiveGitBranchesFromPairs(messages))
        assertEquals("super-employee/codex/task-a", resolveLatestGitBranchFromPairs(messages))
    }

    @Test
    fun `short label uses last path segment`() {
        assertEquals("ui-2-83194-279100", shortGitBranchLabel("super-employee/cursor_agent/ui-2-83194-279100"))
    }
}
