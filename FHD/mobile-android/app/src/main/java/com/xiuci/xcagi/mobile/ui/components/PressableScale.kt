package com.xiuci.xcagi.mobile.ui.components

import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.foundation.LocalIndication
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.draw.scale
import androidx.compose.ui.semantics.Role
import com.xiuci.xcagi.mobile.ui.feedback.HapticKind
import com.xiuci.xcagi.mobile.ui.feedback.LocalXcagiHaptic

/**
 * 按下时缩放微交互 — XCAGI 质感基线。
 *
 * 纯视觉：按下→pressedScale(默认 0.96f)，松开→1f，spring 回弹。
 * 不包含触感/点击 — 适合需要自定义 interactionSource 的卡片/复合 Pressable。
 *
 * ```
 * val interaction = remember { MutableInteractionSource() }
 * Modifier.pressableScale(interaction).clickable(interactionSource = interaction, ...)
 * ```
 */
fun Modifier.pressableScale(
    interactionSource: MutableInteractionSource,
    pressedScale: Float = 0.96f,
    dampingRatio: Float = Spring.DampingRatioMediumBouncy,
    stiffness: Float = Spring.StiffnessLow,
): Modifier = composed {
    val pressed by interactionSource.collectIsPressedAsState()
    val scale by animateFloatAsState(
        targetValue = if (pressed) pressedScale else 1f,
        animationSpec = spring(dampingRatio = dampingRatio, stiffness = stiffness),
        label = "pressableScale",
    )
    this.scale(scale)
}

/**
 * 一站式按压：scale 微交互 + Ripple + 触感 + 点击。
 *
 * ```
 * Card(
 *   modifier = Modifier.hapticPressable(kind = HapticKind.Tap) { onClick() }
 * ) { ... }
 * ```
 *
 * @param enabled 是否启用点击与动画
 * @param kind 触感类型（Tap 轻按 / Confirm 确认 / Reject 拒绝 / None 无触感）
 * @param pressedScale 按下缩放比例（0.92–0.98 视尺寸而定，越大越不明显）
 */
fun Modifier.hapticPressable(
    enabled: Boolean = true,
    kind: HapticKind = HapticKind.Tap,
    pressedScale: Float = 0.96f,
    role: Role? = null,
    onClickLabel: String? = null,
    onClick: () -> Unit,
): Modifier = composed {
    val interactionSource = remember { MutableInteractionSource() }
    val haptic = LocalXcagiHaptic.current
    val pressed by interactionSource.collectIsPressedAsState()
    val scale by animateFloatAsState(
        targetValue = if (pressed && enabled) pressedScale else 1f,
        animationSpec = spring(
            dampingRatio = Spring.DampingRatioMediumBouncy,
            stiffness = Spring.StiffnessLow,
        ),
        label = "hapticPressable",
    )
    this
        .scale(scale)
        .clickable(
            interactionSource = interactionSource,
            indication = LocalIndication.current,
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
