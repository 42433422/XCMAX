package com.xiuci.xcagi.mobile.ui.components.mobile

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.ui.theme.Elevation
import com.xiuci.xcagi.mobile.ui.theme.Spacing
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme

// ─────────────────────────────────────────────────────────────────────────────
// WeStatusBarSpacer  ─  状态栏占位（与白色顶栏融合）
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun WeStatusBarSpacer() {
    Spacer(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surface))
}

// ─────────────────────────────────────────────────────────────────────────────
// WeTopBar  ─  微信风顶栏：左侧菜单/返回 + 居中标题 + 右侧搜索/添加圆形描边按钮
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun WeTopBarCircleAction(
    icon: ImageVector,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier
            .size(32.dp)
            .clip(CircleShape)
            .border(Elevation.level1, MaterialTheme.colorScheme.outlineVariant, CircleShape)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            icon,
            contentDescription = null,
            modifier = Modifier.size(18.dp),
            tint = MaterialTheme.colorScheme.onSurface,
        )
    }
}

@Composable
fun WeTopBarAvatarAction(
    text: String,
    onClick: () -> Unit,
    containerColor: Color,
    modifier: Modifier = Modifier,
    contentColor: Color = Color.White,
) {
    Box(
        modifier
            .size(32.dp)
            .clip(CircleShape)
            .background(containerColor)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = text.take(2),
            style = MaterialTheme.typography.labelMedium,
            color = contentColor,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WeTopBar(
    title: String,
    onBack: (() -> Unit)? = null,
    showLeftMenu: Boolean = false,
    onLeftMenu: (() -> Unit)? = null,
    showRightSearch: Boolean = false,
    onRightSearch: (() -> Unit)? = null,
    showRightAdd: Boolean = false,
    onRightAdd: (() -> Unit)? = null,
    rightLabel: String? = null,
    rightLabelIsAgent: Boolean = false,
    customActions: (@Composable RowScope.() -> Unit)? = null,
) {
    TopAppBar(
        title = {
            Text(
                title,
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        },
        navigationIcon = {
            when {
                onBack != null -> IconButton(onClick = onBack) {
                    Icon(
                        Icons.AutoMirrored.Filled.ArrowBack,
                        contentDescription = "返回",
                        tint = MaterialTheme.colorScheme.onSurface,
                    )
                }
                showLeftMenu -> WeTopBarCircleAction(
                    icon = Icons.Default.Add,
                    onClick = { onLeftMenu?.invoke() },
                )
            }
        },
        actions = {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
                modifier = Modifier.padding(end = Spacing.md),
            ) {
                // 连接状态标签
                if (rightLabel != null) {
                    val dotColor = if (rightLabelIsAgent) XcagiTheme.extra.brandBlue else XcagiTheme.extra.success
                    if (rightLabelIsAgent) {
                        val infiniteTransition = rememberInfiniteTransition(label = "agentPulse")
                        val pulseAlpha by infiniteTransition.animateFloat(
                            initialValue = 0.5f,
                            targetValue = 1f,
                            animationSpec = infiniteRepeatable(
                                animation = tween(800),
                                repeatMode = RepeatMode.Reverse,
                            ),
                        )
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(Spacing.xs),
                        ) {
                            Box(
                                Modifier
                                    .size(6.dp)
                                    .clip(CircleShape)
                                    .background(dotColor.copy(alpha = pulseAlpha))
                            )
                            Text(
                                rightLabel,
                                style = MaterialTheme.typography.labelSmall,
                                color = XcagiTheme.extra.brandBlue,
                            )
                        }
                    } else {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(Spacing.xs),
                        ) {
                            Box(
                                Modifier
                                    .size(6.dp)
                                    .clip(CircleShape)
                                    .background(dotColor)
                            )
                            Text(
                                rightLabel,
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
                if (showRightSearch) {
                    WeTopBarCircleAction(
                        icon = Icons.Default.Search,
                        onClick = { onRightSearch?.invoke() },
                    )
                }
                if (showRightAdd) {
                    WeTopBarCircleAction(
                        icon = Icons.Default.Add,
                        onClick = { onRightAdd?.invoke() },
                    )
                }
                customActions?.invoke(this)
            }
        },
        colors = TopAppBarDefaults.topAppBarColors(
            containerColor = MaterialTheme.colorScheme.surface,
            titleContentColor = MaterialTheme.colorScheme.onSurface,
            navigationIconContentColor = MaterialTheme.colorScheme.onSurface,
            actionIconContentColor = MaterialTheme.colorScheme.onSurface,
        ),
    )
}

// ─────────────────────────────────────────────────────────────────────────────
// WeScreen  ─  页面骨架
// ─────────────────────────────────────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WeScreen(
    title: String,
    onBack: (() -> Unit)? = null,
    showLeftMenu: Boolean = false,
    onLeftMenu: (() -> Unit)? = null,
    showRightSearch: Boolean = false,
    onRightSearch: (() -> Unit)? = null,
    showRightAdd: Boolean = false,
    onRightAdd: (() -> Unit)? = null,
    scrollable: Boolean = true,
    contentPadding: PaddingValues = PaddingValues(0.dp),
    content: @Composable ColumnScope.() -> Unit,
) {
    Scaffold(
        topBar = {
            WeTopBar(
                title = title,
                onBack = onBack,
                showLeftMenu = showLeftMenu,
                onLeftMenu = onLeftMenu,
                showRightSearch = showRightSearch,
                onRightSearch = onRightSearch,
                showRightAdd = showRightAdd,
                onRightAdd = onRightAdd,
            )
        },
        containerColor = MaterialTheme.colorScheme.surface,
    ) { padding ->
        if (scrollable) {
            Column(
                Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .verticalScroll(rememberScrollState())
                    .padding(contentPadding),
                content = content,
            )
        } else {
            Column(
                Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .padding(contentPadding),
                content = content,
            )
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WeSectionCaption  ─  灰底分组标题
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun WeSectionCaption(text: String, modifier: Modifier = Modifier) {
    Box(
        modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.background)
            .padding(horizontal = Spacing.lg, vertical = 6.dp),
    ) {
        Text(
            text,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WeCellGroup  ─  无内边距列表容器（顶部圆角+灰分割线）
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun WeCellGroup(
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = Spacing.md),
        shape = MaterialTheme.shapes.medium,
        color = MaterialTheme.colorScheme.surface,
        shadowElevation = Elevation.level1,
    ) {
        Column(content = content)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WeCell  ─  微信风通用行：左彩色方块图标 + 标题 + 副标题/右值 + 箭头
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun WeCell(
    title: String,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    iconTint: Color = XcagiTheme.extra.brandBlue,
    iconBg: Color = MaterialTheme.colorScheme.primaryContainer,
    iconSize: Dp = 36.dp,
    iconIconSize: Dp = 20.dp,
    subtitle: String = "",
    value: String = "",
    showArrow: Boolean = true,
    showDivider: Boolean = true,
    trailing: @Composable (() -> Unit)? = null,
    titleColor: Color = MaterialTheme.colorScheme.onSurface,
    onClick: (() -> Unit)? = null,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .then(
                if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier
            ),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = Spacing.lg, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (icon != null) {
                Box(
                    modifier = Modifier
                        .size(iconSize)
                        .clip(MaterialTheme.shapes.small)
                        .background(iconBg),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        icon,
                        contentDescription = null,
                        modifier = Modifier.size(iconIconSize),
                        tint = iconTint,
                    )
                }
                Spacer(Modifier.width(14.dp))
            }
            Column(Modifier.weight(1f)) {
                Text(
                    title,
                    style = MaterialTheme.typography.bodyLarge,
                    color = titleColor,
                )
                if (subtitle.isNotBlank()) {
                    Text(
                        subtitle,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            if (value.isNotBlank()) {
                Text(
                    value,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (showArrow) {
                    Spacer(Modifier.width(Spacing.xs))
                }
            }
            when {
                trailing != null -> trailing()
                showArrow -> Icon(
                    Icons.AutoMirrored.Filled.KeyboardArrowRight,
                    contentDescription = null,
                    modifier = Modifier.size(16.dp),
                    tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.62f),
                )
            }
        }
        if (showDivider) {
            HorizontalDivider(
                modifier = Modifier.padding(start = if (icon != null) 16.dp + iconSize + 14.dp else 16.dp),
                thickness = 0.5.dp,
                color = MaterialTheme.colorScheme.outlineVariant,
            )
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WeInputCell  ─  分组内输入行
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun WeInputCell(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    placeholder: String = "",
    showDivider: Boolean = true,
    singleLine: Boolean = true,
    visualTransformation: VisualTransformation = VisualTransformation.None,
    keyboardOptions: androidx.compose.foundation.text.KeyboardOptions = androidx.compose.foundation.text.KeyboardOptions.Default,
) {
    Column(modifier = modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = Spacing.lg, vertical = Spacing.xs),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                label,
                style = MaterialTheme.typography.bodyLarge.copy(fontWeight = FontWeight.Medium),
                color = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.width(80.dp),
            )
            BasicTextField(
                value = value,
                onValueChange = onValueChange,
                modifier = Modifier.weight(1f),
                singleLine = singleLine,
                visualTransformation = visualTransformation,
                keyboardOptions = keyboardOptions,
                textStyle = MaterialTheme.typography.bodyMedium.copy(
                    color = MaterialTheme.colorScheme.onSurface,
                ),
                decorationBox = { inner ->
                    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterStart) {
                        if (value.isEmpty() && placeholder.isNotBlank()) {
                            Text(
                                placeholder,
                                style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.66f),
                            )
                        }
                        inner()
                    }
                },
            )
        }
        if (showDivider) {
            HorizontalDivider(
                modifier = Modifier.padding(start = Spacing.lg),
                thickness = 0.5.dp,
                color = MaterialTheme.colorScheme.outlineVariant,
            )
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WeInputActionCell  ─  分组内输入行 + 右侧品牌色文字按钮
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun WeInputActionCell(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    actionLabel: String,
    onAction: () -> Unit,
    modifier: Modifier = Modifier,
    placeholder: String = "",
    showDivider: Boolean = true,
    keyboardOptions: androidx.compose.foundation.text.KeyboardOptions = androidx.compose.foundation.text.KeyboardOptions.Default,
) {
    Column(modifier = modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = Spacing.lg, end = Spacing.sm, top = Spacing.xs, bottom = Spacing.xs),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                label,
                style = MaterialTheme.typography.bodyLarge.copy(fontWeight = FontWeight.Medium),
                color = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.width(80.dp),
            )
            BasicTextField(
                value = value,
                onValueChange = onValueChange,
                modifier = Modifier.weight(1f),
                singleLine = true,
                keyboardOptions = keyboardOptions,
                textStyle = MaterialTheme.typography.bodyMedium.copy(
                    color = MaterialTheme.colorScheme.onSurface,
                ),
                decorationBox = { inner ->
                    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterStart) {
                        if (value.isEmpty() && placeholder.isNotBlank()) {
                            Text(
                                placeholder,
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.72f),
                            )
                        }
                        inner()
                    }
                },
            )
            TextButton(
                onClick = onAction,
                contentPadding = PaddingValues(horizontal = Spacing.sm),
            ) {
                Text(
                    actionLabel,
                    style = MaterialTheme.typography.bodyMedium,
                    color = XcagiTheme.extra.brandBlue,
                )
            }
        }
        if (showDivider) {
            HorizontalDivider(
                modifier = Modifier.padding(start = Spacing.lg),
                thickness = 0.5.dp,
                color = MaterialTheme.colorScheme.outlineVariant,
            )
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WeUnderlineTabs  ─  纯文字 Tab + 品牌色下划线
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun WeUnderlineTabs(
    options: List<WeModeOption>,
    selectedId: String,
    onSelect: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = Spacing.lg),
    ) {
        options.forEach { opt ->
            val selected = opt.id == selectedId
            Column(
                modifier = Modifier
                    .weight(1f)
                    .clickable(
                        interactionSource = remember { MutableInteractionSource() },
                        indication = null,
                        onClick = { onSelect(opt.id) },
                    )
                    .padding(vertical = Spacing.md),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    opt.label,
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
                    color = if (selected) XcagiTheme.extra.brandBlue else MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                )
                Spacer(Modifier.height(Spacing.sm))
                Box(
                    Modifier
                        .fillMaxWidth(0.5f)
                        .height(2.5.dp)
                        .clip(RoundedCornerShape(1.25.dp))
                        .background(
                            if (selected) XcagiTheme.extra.brandBlue else Color.Transparent,
                        ),
                )
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Auth 专用组件
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun WeAuthCard(
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = Spacing.xxl),
        shape = MaterialTheme.shapes.medium,
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = Elevation.none,
        shadowElevation = Elevation.none,
    ) {
        Column(content = content)
    }
}

@Composable
fun WeAuthTabs(
    options: List<WeModeOption>,
    selectedId: String,
    onSelect: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier.fillMaxWidth(),
    ) {
        options.forEach { opt ->
            val selected = opt.id == selectedId
            Column(
                modifier = Modifier
                    .weight(1f)
                    .clickable(
                        interactionSource = remember { MutableInteractionSource() },
                        indication = null,
                        onClick = { onSelect(opt.id) },
                    )
                    .padding(top = Spacing.lg, bottom = 0.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    opt.label,
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
                    color = if (selected) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                )
                Spacer(Modifier.height(10.dp))
                Box(
                    Modifier
                        .fillMaxWidth()
                        .height(2.5.dp)
                        .background(
                            if (selected) XcagiTheme.extra.brandBlue else Color.Transparent,
                        ),
                )
            }
        }
    }
}

@Composable
fun WeAuthInputField(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    placeholder: String = "",
    showDivider: Boolean = true,
    singleLine: Boolean = true,
    visualTransformation: VisualTransformation = VisualTransformation.None,
    keyboardOptions: androidx.compose.foundation.text.KeyboardOptions = androidx.compose.foundation.text.KeyboardOptions.Default,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = Spacing.xl),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                label,
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.width(72.dp),
            )
            BasicTextField(
                value = value,
                onValueChange = onValueChange,
                modifier = Modifier.weight(1f),
                singleLine = singleLine,
                visualTransformation = visualTransformation,
                keyboardOptions = keyboardOptions,
                textStyle = MaterialTheme.typography.bodyLarge,
                decorationBox = { inner ->
                    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterStart) {
                        if (value.isEmpty() && placeholder.isNotBlank()) {
                            Text(
                                placeholder,
                                style = MaterialTheme.typography.bodyLarge,
                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.72f),
                            )
                        }
                        inner()
                    }
                },
            )
        }
        if (showDivider) {
            HorizontalDivider(
                thickness = 0.5.dp,
                color = MaterialTheme.colorScheme.outlineVariant,
            )
        }
    }
}

/** 6 格验证码输入 */
@Composable
fun WeOtpCells(
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    cellCount: Int = 6,
    enabled: Boolean = true,
) {
    val focusRequester = remember { FocusRequester() }
    val keyboard = LocalSoftwareKeyboardController.current
    val digits = value.filter { it.isDigit() }.take(cellCount)

    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = Spacing.xl)
            .clickable(enabled = enabled) {
                focusRequester.requestFocus()
                keyboard?.show()
            },
    ) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(Spacing.sm, Alignment.CenterHorizontally),
        ) {
            repeat(cellCount) { index ->
                val char = digits.getOrNull(index)?.toString() ?: ""
                val focused = digits.length == index
                Box(
                    Modifier
                        .weight(1f)
                        .height(48.dp)
                        .clip(MaterialTheme.shapes.small)
                        .background(MaterialTheme.colorScheme.surface)
                        .border(
                            width = if (focused) 1.5.dp else 1.dp,
                            color = if (focused) XcagiTheme.extra.brandBlue else MaterialTheme.colorScheme.outlineVariant,
                            shape = MaterialTheme.shapes.small,
                        ),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        char,
                        style = MaterialTheme.typography.headlineSmall,
                        fontWeight = FontWeight.Medium,
                        color = MaterialTheme.colorScheme.onSurface,
                        textAlign = TextAlign.Center,
                    )
                }
            }
        }
        BasicTextField(
            value = digits,
            onValueChange = { raw ->
                onValueChange(raw.filter { it.isDigit() }.take(cellCount))
            },
            modifier = Modifier
                .size(1.dp)
                .focusRequester(focusRequester),
            enabled = enabled,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
            keyboardActions = KeyboardActions(onDone = { keyboard?.hide() }),
        )
        Spacer(Modifier.height(Spacing.sm))
    }
}

@Composable
fun WeAuthOtpField(
    actionLabel: String,
    onAction: () -> Unit,
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    actionEnabled: Boolean = true,
) {
    Column(modifier = modifier.fillMaxWidth()) {
        Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = Spacing.xl, vertical = Spacing.sm),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("验证码", style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurface)
            Text(
                actionLabel,
                style = MaterialTheme.typography.bodySmall,
                color = if (actionEnabled) XcagiTheme.extra.brandBlue else MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.clickable(enabled = actionEnabled, onClick = onAction),
            )
        }
        WeOtpCells(value = value, onValueChange = onValueChange, enabled = actionEnabled)
    }
}

@Composable
fun WeAuthInputActionField(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    actionLabel: String,
    onAction: () -> Unit,
    modifier: Modifier = Modifier,
    placeholder: String = "",
    showDivider: Boolean = true,
    keyboardOptions: androidx.compose.foundation.text.KeyboardOptions = androidx.compose.foundation.text.KeyboardOptions.Default,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = Spacing.xl),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                label,
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.width(72.dp),
            )
            BasicTextField(
                value = value,
                onValueChange = onValueChange,
                modifier = Modifier.weight(1f),
                singleLine = true,
                keyboardOptions = keyboardOptions,
                textStyle = MaterialTheme.typography.bodyLarge,
                decorationBox = { inner ->
                    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterStart) {
                        if (value.isEmpty() && placeholder.isNotBlank()) {
                            Text(
                                placeholder,
                                style = MaterialTheme.typography.bodyLarge,
                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.72f),
                            )
                        }
                        inner()
                    }
                },
            )
            Text(
                actionLabel,
                style = MaterialTheme.typography.bodySmall,
                color = XcagiTheme.extra.brandBlue,
                modifier = Modifier
                    .clickable(onClick = onAction)
                    .padding(start = Spacing.sm),
            )
        }
        if (showDivider) {
            HorizontalDivider(
                thickness = 0.5.dp,
                color = MaterialTheme.colorScheme.outlineVariant,
            )
        }
    }
}

@Composable
fun WeAuthGreenButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    Button(
        onClick = onClick,
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = Spacing.xxl)
            .height(48.dp),
        enabled = enabled,
        shape = MaterialTheme.shapes.small,
        colors = ButtonDefaults.buttonColors(
            containerColor = XcagiTheme.extra.brandBlue,
            contentColor = Color.White,
            disabledContainerColor = XcagiTheme.extra.brandBlue.copy(alpha = 0.4f),
            disabledContentColor = Color.White.copy(alpha = 0.7f),
        ),
        elevation = ButtonDefaults.buttonElevation(
            defaultElevation = Elevation.none,
            disabledElevation = Elevation.none,
        ),
    ) {
        Text(text, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium)
    }
}

@Composable
fun AuthScreenLayout(
    title: String,
    subtitle: String,
    logoContent: @Composable () -> Unit,
    modifier: Modifier = Modifier,
    logoSize: Dp = 80.dp,
    footer: @Composable () -> Unit = {},
    formContent: @Composable ColumnScope.() -> Unit,
    actions: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .imePadding(),
    ) {
        Column(
            Modifier
                .weight(1f)
                .verticalScroll(rememberScrollState()),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Column(
                Modifier
                    .fillMaxWidth()
                    .heightIn(min = 220.dp)
                    .padding(top = 56.dp, bottom = 28.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center,
            ) {
                WeAvatar(size = logoSize, content = logoContent)
                Spacer(Modifier.height(Spacing.xl))
                Text(
                    title,
                    style = MaterialTheme.typography.headlineMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onSurface,
                    textAlign = TextAlign.Center,
                )
                Text(
                    subtitle,
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                    maxLines = 2,
                    modifier = Modifier
                        .padding(horizontal = 40.dp)
                        .padding(top = Spacing.sm),
                )
            }

            WeAuthCard(content = formContent)

            Column(
                Modifier
                    .fillMaxWidth()
                    .padding(top = Spacing.xxxl),
                horizontalAlignment = Alignment.CenterHorizontally,
                content = actions,
            )

            Spacer(Modifier.height(Spacing.xxl))
        }

        footer()
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WeGreenButton  ─  品牌主色全宽主按钮
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun WeGreenButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    Button(
        onClick = onClick,
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = Spacing.lg)
            .height(44.dp),
        enabled = enabled,
        shape = MaterialTheme.shapes.small,
        colors = ButtonDefaults.buttonColors(
            containerColor = XcagiTheme.extra.brandBlue,
            contentColor = Color.White,
            disabledContainerColor = XcagiTheme.extra.brandBlue.copy(alpha = 0.4f),
            disabledContentColor = Color.White.copy(alpha = 0.7f),
        ),
        elevation = ButtonDefaults.buttonElevation(defaultElevation = Elevation.none),
    ) {
        Text(text, style = MaterialTheme.typography.bodyLarge.copy(fontWeight = FontWeight.Medium))
    }
}

@Composable
fun WeBlockButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    WeGreenButton(text, onClick, modifier, enabled)
}

@Composable
fun WeBlockOutlinedButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    OutlinedButton(
        onClick = onClick,
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = Spacing.lg)
            .height(48.dp),
        enabled = enabled,
        shape = MaterialTheme.shapes.small,
    ) {
        Text(text, style = MaterialTheme.typography.bodyLarge)
    }
}

@Composable
fun WeBlockDangerButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    Button(
        onClick = onClick,
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = Spacing.lg)
            .height(48.dp),
        enabled = enabled,
        shape = MaterialTheme.shapes.small,
        colors = ButtonDefaults.buttonColors(
            containerColor = MaterialTheme.colorScheme.surface,
            contentColor = XcagiTheme.extra.danger,
        ),
        border = BorderStroke(1.dp, XcagiTheme.extra.danger),
        elevation = ButtonDefaults.buttonElevation(defaultElevation = Elevation.none),
    ) {
        Text(text, style = MaterialTheme.typography.bodyLarge)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WeAvatar  ─  圆角方形头像
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun WeAvatar(
    content: @Composable () -> Unit,
    modifier: Modifier = Modifier,
    size: Dp = 64.dp,
) {
    Box(
        modifier = modifier
            .size(size)
            .clip(RoundedCornerShape(size * 0.22f)),
        contentAlignment = Alignment.Center,
    ) {
        content()
    }
}

@Composable
fun WeSpacer(height: Dp = 16.dp) {
    Spacer(Modifier.height(height))
}

// ─────────────────────────────────────────────────────────────────────────────
// WeBadge  ─  红点 / 数字角标
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun WeBadge(
    count: Int,
    modifier: Modifier = Modifier,
    showDot: Boolean = false,
) {
    if (count <= 0 && !showDot) return
    val size = when {
        showDot && count <= 0 -> 8.dp
        count in 1..9 -> 18.dp
        else -> 20.dp
    }
    Box(
        modifier = modifier
            .size(size)
            .clip(CircleShape)
            .background(XcagiTheme.extra.danger),
        contentAlignment = Alignment.Center,
    ) {
        if (count > 0) {
            Text(
                if (count > 99) "99+" else count.toString(),
                style = MaterialTheme.typography.labelSmall,
                color = Color.White,
            )
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WeModeCapsule  ─  微信风模式切换胶囊（白底圆角+选中浅蓝底+品牌色文字）
// ─────────────────────────────────────────────────────────────────────────────

data class WeModeOption(
    val id: String,
    val label: String,
    val icon: ImageVector? = null,
    val hint: String = "",
)

@Composable
fun WeModeCapsule(
    options: List<WeModeOption>,
    selectedId: String,
    onSelect: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier,
        shape = MaterialTheme.shapes.extraLarge,
        color = MaterialTheme.colorScheme.background,
        tonalElevation = Elevation.none,
        shadowElevation = Elevation.none,
    ) {
        Row(
            Modifier.padding(Spacing.xs),
            horizontalArrangement = Arrangement.spacedBy(Spacing.xs),
        ) {
            options.forEach { opt ->
                val selected = opt.id == selectedId
                Surface(
                    modifier = Modifier
                        .clip(MaterialTheme.shapes.large)
                        .clickable { onSelect(opt.id) },
                    color = if (selected) MaterialTheme.colorScheme.primaryContainer else Color.Transparent,
                    tonalElevation = Elevation.none,
                    shadowElevation = Elevation.none,
                ) {
                    Row(
                        Modifier.padding(horizontal = 14.dp, vertical = 6.dp),
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        if (opt.icon != null) {
                            Icon(
                                opt.icon,
                                contentDescription = null,
                                modifier = Modifier.size(16.dp),
                                tint = if (selected) XcagiTheme.extra.brandBlue else MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            Spacer(Modifier.width(Spacing.xs))
                        }
                        Text(
                            opt.label,
                            style = MaterialTheme.typography.bodyMedium.copy(
                                fontWeight = if (selected) FontWeight.Medium else FontWeight.Normal,
                            ),
                            color = if (selected) XcagiTheme.extra.brandBlue else MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                }
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WeChatInputBar  ─  微信风底部输入条：白底圆角 + 左操作芯片 + 右圆形按钮
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun WeChatInputBar(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    onSend: () -> Unit,
    onStop: () -> Unit,
    streaming: Boolean,
    modifier: Modifier = Modifier,
    onVoice: (() -> Unit)? = null,
    onDeepThinking: (() -> Unit)? = null,
    deepThinking: Boolean = false,
    onSmartSearch: (() -> Unit)? = null,
    smartSearch: Boolean = false,
) {
    Column(
        modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surface)
            .padding(horizontal = Spacing.md, vertical = Spacing.sm),
    ) {
        Surface(
            shape = MaterialTheme.shapes.small,
            color = MaterialTheme.colorScheme.surface,
            border = androidx.compose.foundation.BorderStroke(0.5.dp, MaterialTheme.colorScheme.outlineVariant),
            shadowElevation = Elevation.none,
        ) {
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = Spacing.md, vertical = Spacing.sm),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                BasicTextField(
                    value = value,
                    onValueChange = onValueChange,
                    modifier = Modifier.weight(1f),
                    singleLine = true,
                    textStyle = MaterialTheme.typography.bodyMedium.copy(
                        color = MaterialTheme.colorScheme.onSurface,
                    ),
                    decorationBox = { inner ->
                        Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterStart) {
                            if (value.isEmpty()) {
                                Text(
                                    placeholder,
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.72f),
                                )
                            }
                            inner()
                        }
                    },
                )
            }
        }
        Spacer(Modifier.height(Spacing.sm))
        Row(
            Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
        ) {
            if (onDeepThinking != null) {
                WeInputChip(
                    label = "深度思考",
                    selected = deepThinking,
                    onClick = onDeepThinking,
                )
            }
            if (onSmartSearch != null) {
                WeInputChip(
                    label = "智能搜索",
                    selected = smartSearch,
                    onClick = onSmartSearch,
                )
            }
            Spacer(Modifier.weight(1f))
            if (onVoice != null) {
                WeCircleAction(icon = Icons.Default.Mic, onClick = onVoice)
            }
            WeCircleAction(
                icon = if (streaming) Icons.Default.Stop else Icons.AutoMirrored.Filled.Send,
                onClick = { if (streaming) onStop() else onSend() },
            )
        }
    }
}

@Composable
private fun WeCircleAction(
    icon: ImageVector,
    onClick: () -> Unit,
) {
    Box(
        Modifier
            .size(36.dp)
            .clip(CircleShape)
            .border(0.5.dp, MaterialTheme.colorScheme.outlineVariant, CircleShape)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            icon,
            contentDescription = null,
            modifier = Modifier.size(20.dp),
            tint = MaterialTheme.colorScheme.onSurface,
        )
    }
}

@Composable
private fun WeInputChip(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
) {
    Surface(
        modifier = Modifier.clickable(onClick = onClick),
        shape = MaterialTheme.shapes.large,
        color = if (selected) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surface,
        border = androidx.compose.foundation.BorderStroke(0.5.dp, MaterialTheme.colorScheme.outlineVariant),
    ) {
        Row(
            Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                Modifier
                    .size(14.dp)
                    .clip(CircleShape)
                    .background(if (selected) XcagiTheme.extra.brandBlue else MaterialTheme.colorScheme.onSurfaceVariant),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    if (selected) "✓" else label.take(1),
                    style = MaterialTheme.typography.labelSmall,
                    color = Color.White,
                )
            }
            Spacer(Modifier.width(Spacing.xs))
            Text(
                label,
                style = MaterialTheme.typography.bodySmall,
                color = if (selected) XcagiTheme.extra.brandBlue else MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WeRedActionCell  ─  红字居中 cell
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun WeRedActionCell(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(vertical = 14.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text,
            style = MaterialTheme.typography.bodyLarge,
            color = XcagiTheme.extra.danger,
        )
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WeBottomNavBar  ─  浮动胶囊底栏：高密度 IM 首页风格
// ─────────────────────────────────────────────────────────────────────────────

data class WeBottomNavItem(
    val route: String,
    val label: String,
    val icon: ImageVector,
    val badge: Int = 0,
)

@Composable
fun WeBottomNavBar(
    items: List<WeBottomNavItem>,
    currentRoute: String?,
    onSelect: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier
            .fillMaxWidth()
            .navigationBarsPadding()
            .padding(start = Spacing.xl, end = Spacing.xl, top = 6.dp, bottom = 10.dp),
        contentAlignment = Alignment.Center,
    ) {
        Surface(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(30.dp),
            color = MaterialTheme.colorScheme.surface,
            shadowElevation = Elevation.level3,
            tonalElevation = Elevation.none,
        ) {
            Row(
                Modifier
                    .fillMaxWidth()
                    .height(66.dp)
                    .padding(horizontal = 6.dp, vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                items.forEach { item ->
                    val selected = currentRoute == item.route
                    Column(
                        modifier = Modifier
                            .weight(1f)
                            .fillMaxHeight()
                            .clip(RoundedCornerShape(24.dp))
                            .background(
                                if (selected) XcagiTheme.extra.n50 else Color.Transparent,
                            )
                            .clickable { onSelect(item.route) },
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.Center,
                    ) {
                        BadgedBox(
                            badge = {
                                if (item.badge > 0) {
                                    Badge(
                                        containerColor = XcagiTheme.extra.danger,
                                        contentColor = Color.White,
                                    ) {
                                        Text(if (item.badge > 99) "99+" else "${item.badge}")
                                    }
                                }
                            },
                        ) {
                            Icon(
                                item.icon,
                                contentDescription = item.label,
                                modifier = Modifier.size(23.dp),
                                tint =
                                    if (selected) XcagiTheme.extra.brandBlue
                                    else MaterialTheme.colorScheme.onSurface,
                            )
                        }
                        Spacer(Modifier.height(2.dp))
                        Text(
                            item.label,
                            style = MaterialTheme.typography.labelSmall.copy(
                                fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
                            ),
                            color =
                                if (selected) XcagiTheme.extra.brandBlue
                                else XcagiTheme.extra.n600,
                            maxLines = 1,
                        )
                    }
                }
            }
        }
    }
}
