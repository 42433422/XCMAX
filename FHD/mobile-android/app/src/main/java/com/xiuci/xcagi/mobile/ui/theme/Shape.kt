package com.xiuci.xcagi.mobile.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Shapes
import androidx.compose.ui.unit.dp

/**
 * XCAGI 圆角系统 — 统一圆角值
 *
 * 阶梯：
 * - extraSmall  4dp  — 标签/徽标
 * - small       8dp  — 小卡片/输入框
 * - medium     12dp  — 卡片/弹层
 * - large      16dp  — 大卡片/对话框
 * - extraLarge 20dp  — 特殊场景
 */
val XcagiShapes = Shapes(
    extraSmall = RoundedCornerShape(4.dp),
    small = RoundedCornerShape(8.dp),
    medium = RoundedCornerShape(12.dp),
    large = RoundedCornerShape(16.dp),
    extraLarge = RoundedCornerShape(20.dp),
)

/** 阴影层级（elevation） */
object Elevation {
    val none = 0.dp
    val level1 = 1.dp     // 卡片
    val level2 = 3.dp     // 弹层/底部栏
    val level3 = 8.dp     // 对话框
}

/** 间距系统（4px 栅格） */
object Spacing {
    val xs = 4.dp
    val sm = 8.dp
    val md = 12.dp
    val lg = 16.dp
    val xl = 20.dp
    val xxl = 24.dp
    val xxxl = 32.dp
}
