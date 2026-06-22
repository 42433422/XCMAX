package com.xiuci.xcagi.mobile.ui.feedback

import android.os.Build
import android.view.HapticFeedbackConstants
import android.view.View
import androidx.compose.foundation.LocalIndication
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Stable
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.semantics.Role

/**
 * XCAGI 触感反馈语义层 — SSOT
 *
 * 直接调用 [android.view.View.performHapticFeedback]，提供语义化 API（tap/select/confirm/reject/toggle）。
 * Compose 自带 `LocalHapticFeedback` 仅有 LongPress/TextHandleMove，不够用。
 *
 * 使用：
 * ```
 * val haptic = LocalXcagiHaptic.current
 * haptic.tap()                                    // 按钮/Tab
 * Modifier.hapticClickable { onClick() }          // 一行接入
 * Modifier.hapticClickable(kind = HapticKind.Confirm) { ... }
 * ```
 */
@Stable
class XcagiHaptic internal constructor(private val view: View) {

    /** 轻按 — 按钮、Tab、Chip、列表项点按 */
    fun tap() {
        view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
    }

    /** 选择节奏 — 滑动选择、Picker tick、Tab 切换 */
    fun select() {
        view.performHapticFeedback(HapticFeedbackConstants.CLOCK_TICK)
    }

    /** 确认 — 表单提交、订单完成、二步操作成功 */
    fun confirm() {
        val constant = if (Build.VERSION.SDK_INT >= 30) {
            HapticFeedbackConstants.CONFIRM
        } else {
            HapticFeedbackConstants.VIRTUAL_KEY
        }
        view.performHapticFeedback(constant)
    }

    /** 拒绝 / 错误 — 验证失败、不可用、危险操作阻断 */
    fun reject() {
        val constant = if (Build.VERSION.SDK_INT >= 30) {
            HapticFeedbackConstants.REJECT
        } else {
            HapticFeedbackConstants.LONG_PRESS
        }
        view.performHapticFeedback(constant)
    }

    /** 长按 — 上下文菜单触发、拖拽起手 */
    fun longPress() {
        view.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
    }

    /** 开关 — Switch/Checkbox 切换；API 34+ 区分 on/off，旧机型回落 [tap] */
    fun toggle(on: Boolean) {
        val constant = if (Build.VERSION.SDK_INT >= 34) {
            if (on) HapticFeedbackConstants.TOGGLE_ON else HapticFeedbackConstants.TOGGLE_OFF
        } else {
            HapticFeedbackConstants.VIRTUAL_KEY
        }
        view.performHapticFeedback(constant)
    }

    /** 手势结束 — 抽屉关闭、下拉刷新触发完成、滑动归位 */
    fun gestureEnd() {
        val constant = if (Build.VERSION.SDK_INT >= 30) {
            HapticFeedbackConstants.GESTURE_END
        } else {
            HapticFeedbackConstants.VIRTUAL_KEY
        }
        view.performHapticFeedback(constant)
    }
}

/** 语义级反馈类型 — 用于 [Modifier.hapticClickable] */
enum class HapticKind {
    Tap, Select, Confirm, Reject, LongPress, GestureEnd, None
}

/** 全局触感入口，由 [ProvideXcagiHaptic] 注入 */
val LocalXcagiHaptic = compositionLocalOf<XcagiHaptic> {
    error("XcagiHaptic 未提供 — 在根部包 ProvideXcagiHaptic { }")
}

@Composable
fun ProvideXcagiHaptic(content: @Composable () -> Unit) {
    val view = LocalView.current
    val haptic = remember(view) { XcagiHaptic(view) }
    androidx.compose.runtime.CompositionLocalProvider(LocalXcagiHaptic provides haptic) {
        content()
    }
}

/**
 * 一行接入触感的 clickable。
 *
 * 默认 [HapticKind.Tap]（轻按）。重要按钮用 Confirm，错误/不可用用 Reject。
 */
fun Modifier.hapticClickable(
    enabled: Boolean = true,
    kind: HapticKind = HapticKind.Tap,
    role: Role? = null,
    onClickLabel: String? = null,
    onClick: () -> Unit,
): Modifier = composed {
    val haptic = LocalXcagiHaptic.current
    clickable(
        enabled = enabled,
        role = role,
        onClickLabel = onClickLabel,
    ) {
        when (kind) {
            HapticKind.Tap -> haptic.tap()
            HapticKind.Select -> haptic.select()
            HapticKind.Confirm -> haptic.confirm()
            HapticKind.Reject -> haptic.reject()
            HapticKind.LongPress -> haptic.longPress()
            HapticKind.GestureEnd -> haptic.gestureEnd()
            HapticKind.None -> Unit
        }
        onClick()
    }
}

/** 受控 InteractionSource 版本 — 用于卡片/自定义 Pressable */
fun Modifier.hapticClickable(
    interactionSource: MutableInteractionSource,
    enabled: Boolean = true,
    kind: HapticKind = HapticKind.Tap,
    role: Role? = null,
    onClick: () -> Unit,
): Modifier = composed {
    val haptic = LocalXcagiHaptic.current
    clickable(
        interactionSource = interactionSource,
        indication = LocalIndication.current,
        enabled = enabled,
        role = role,
    ) {
        when (kind) {
            HapticKind.Tap -> haptic.tap()
            HapticKind.Select -> haptic.select()
            HapticKind.Confirm -> haptic.confirm()
            HapticKind.Reject -> haptic.reject()
            HapticKind.LongPress -> haptic.longPress()
            HapticKind.GestureEnd -> haptic.gestureEnd()
            HapticKind.None -> Unit
        }
        onClick()
    }
}
