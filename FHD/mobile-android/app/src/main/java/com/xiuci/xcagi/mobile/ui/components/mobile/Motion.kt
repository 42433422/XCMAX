package com.xiuci.xcagi.mobile.ui.components.mobile

import androidx.compose.animation.EnterTransition
import androidx.compose.animation.ExitTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut

/** 全局淡入淡出动效时长（Tab / 路由切换复用）。 */
object WeMotion {
    const val FadeDurationMs = 250
}

object WeFadeTransition {
    fun enter(): EnterTransition = fadeIn(tween(WeMotion.FadeDurationMs))

    fun exit(): ExitTransition = fadeOut(tween(WeMotion.FadeDurationMs))
}
