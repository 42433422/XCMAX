package com.xiuci.xcagi.mobile.ui.components.mobile

import android.os.Build
import android.view.HapticFeedbackConstants
import android.view.View
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalView

/**
 * 全局触觉反馈助手 —— 统一高频交互的「手感」。
 *
 * 通过宿主 [View.performHapticFeedback] 触发，遵循系统「触感反馈」开关；
 * 关闭时静默无副作用。用 [rememberHaptics] 在 Composable 中获取实例。
 */
class Haptics internal constructor(private val view: View) {
    /** 轻触：按钮点击、Tab 切换等高频动作。 */
    fun tap() {
        view.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
    }

    /** 点击：列表项 / 菜单项等普通点击（上下文点击，比 tap 略实）。 */
    fun click() {
        view.performHapticFeedback(HapticFeedbackConstants.CONTEXT_CLICK)
    }

    /** 长按：唤起长按操作面板 / 菜单时的强反馈。 */
    fun longClick() {
        view.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
    }

    /** 确认：发送消息、提交等带「完成感」的动作（低版本回退到轻触）。 */
    fun confirm() {
        val constant =
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) HapticFeedbackConstants.CONFIRM
            else HapticFeedbackConstants.KEYBOARD_TAP
        view.performHapticFeedback(constant)
    }
}

@Composable
fun rememberHaptics(): Haptics {
    val view = LocalView.current
    return remember(view) { Haptics(view) }
}
