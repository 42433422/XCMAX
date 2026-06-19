package com.xiuci.xcagi.mobile.core.im

import kotlin.math.min

/**
 * WebSocket 重连指数退避延迟计算。
 *
 * 基础延迟 5s，每次翻倍，上限 5 分钟。
 * - attempt 0 → 5s
 * - attempt 1 → 10s
 * - attempt 2 → 20s
 * - attempt 6+ → 300s (5min cap)
 */
object ReconnectBackoff {
    private const val BASE_DELAY_MS = 5_000L
    private const val MAX_DELAY_MS = 300_000L

    fun delayForAttempt(attempt: Int): Long {
        val safeAttempt = attempt.coerceAtLeast(0).coerceAtMost(6)
        val delay = BASE_DELAY_MS * (1L shl safeAttempt)
        return min(delay, MAX_DELAY_MS)
    }
}
