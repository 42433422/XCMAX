package com.xiuci.xcagi.mobile.ui.components.mobile

import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.foundation.LocalIndication
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.InteractionSource
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.semantics.Role

/**
 * 按压质感（press affordance）—— 统一控件「手感」的单一真相源。
 *
 * 大厂级 App（微信/支付宝/飞书）几乎所有可点控件按下时都会有一次
 * 微缩 + 触觉反馈，正是这种细节让控件「有质感」而非「很简单」。
 * 本文件把这套手感抽成可复用 Modifier，避免逐控件重复实现。
 */
object Press {
    /** 默认按下缩放比例：克制但可感知。 */
    const val Scale = 0.97f

    /** 小型/图标类控件按下缩放：略深一档，强化「实体被按」感。 */
    const val ScaleStrong = 0.92f

    /** 回弹动效——中等刚度弹簧，无过冲，干净利落。 */
    val SpringSpec
        get() = spring<Float>(
            dampingRatio = Spring.DampingRatioNoBouncy,
            stiffness = Spring.StiffnessMediumLow,
        )
}

/**
 * 监听 [interactionSource] 的按下态并对控件做微缩，仅负责「缩放」本身。
 *
 * 用于 Material3 [androidx.compose.material3.Button] 等自带点击逻辑、
 * 但可外接 interactionSource 的控件：把同一个 source 传给控件，
 * 再用本 Modifier 包一层缩放即可。
 */
@Composable
fun Modifier.scaleOnPress(
    interactionSource: InteractionSource,
    pressedScale: Float = Press.Scale,
): Modifier {
    val pressed by interactionSource.collectIsPressedAsState()
    val scale by animateFloatAsState(
        targetValue = if (pressed) pressedScale else 1f,
        animationSpec = Press.SpringSpec,
        label = "pressScale",
    )
    return this.graphicsLayer {
        scaleX = scale
        scaleY = scale
    }
}

/**
 * 一体化「可点击 + 按压质感」Modifier：缩放 + 涟漪 + 轻触反馈一次到位。
 *
 * 替代裸 `Modifier.clickable(onClick = ...)`——后者只有涟漪、没有缩放与触感，
 * 正是「质感很简单」的根因。
 */
fun Modifier.pressClickable(
    enabled: Boolean = true,
    haptic: Boolean = true,
    pressedScale: Float = Press.Scale,
    role: Role? = null,
    onClick: () -> Unit,
): Modifier = composed {
    val interactionSource = remember { MutableInteractionSource() }
    val haptics = rememberHaptics()
    this
        .scaleOnPress(interactionSource, pressedScale)
        .clickable(
            interactionSource = interactionSource,
            indication = LocalIndication.current,
            enabled = enabled,
            role = role,
            onClick = {
                if (haptic) haptics.tap()
                onClick()
            },
        )
}
