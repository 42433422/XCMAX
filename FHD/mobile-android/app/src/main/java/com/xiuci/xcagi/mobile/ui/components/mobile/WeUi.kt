package com.xiuci.xcagi.mobile.ui.components.mobile

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
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
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
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
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

// ─────────────────────────────────────────────────────────────────────────────
// WeStatusBarSpacer  ─  状态栏占位（与白色顶栏融合）
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun WeStatusBarSpacer() {
    Spacer(Modifier.fillMaxWidth().background(MobileTokens.surfaceWhite))
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
            .border(0.5.dp, MobileTokens.divider, CircleShape)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            icon,
            contentDescription = null,
            modifier = Modifier.size(18.dp),
            tint = MobileTokens.textPrimary,
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
) {
    TopAppBar(
        title = {
            Text(
                title,
                fontSize = 17.sp,
                fontWeight = FontWeight.Medium,
                color = MobileTokens.textPrimary,
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
                        tint = MobileTokens.textPrimary,
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
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.padding(end = 12.dp),
            ) {
                // 连接状态标签
                if (rightLabel != null) {
                    val dotColor = if (rightLabelIsAgent) MobileTokens.brandBlue else MobileTokens.successGreen
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
                            horizontalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            Box(
                                Modifier
                                    .size(6.dp)
                                    .clip(CircleShape)
                                    .background(dotColor.copy(alpha = pulseAlpha))
                            )
                            Text(
                                rightLabel,
                                fontSize = 11.sp,
                                color = MobileTokens.brandBlue,
                            )
                        }
                    } else {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            Box(
                                Modifier
                                    .size(6.dp)
                                    .clip(CircleShape)
                                    .background(dotColor)
                            )
                            Text(
                                rightLabel,
                                fontSize = 11.sp,
                                color = MobileTokens.textTertiary,
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
            }
        },
        colors = TopAppBarDefaults.topAppBarColors(
            containerColor = MobileTokens.surfaceWhite,
            titleContentColor = MobileTokens.textPrimary,
            navigationIconContentColor = MobileTokens.textPrimary,
            actionIconContentColor = MobileTokens.textPrimary,
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
        containerColor = MobileTokens.surfaceWhite,
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
            .background(MobileTokens.surfaceBg)
            .padding(horizontal = 16.dp, vertical = 6.dp),
    ) {
        Text(
            text,
            style = MaterialTheme.typography.labelSmall,
            color = MobileTokens.textTertiary,
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
            .padding(horizontal = 12.dp),
        shape = RoundedCornerShape(12.dp),
        color = MobileTokens.surfaceWhite,
        shadowElevation = 1.dp,
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
    iconTint: Color = MobileTokens.iconFgBlue,
    iconBg: Color = MobileTokens.iconBgBlue,
    iconSize: Dp = 36.dp,
    iconIconSize: Dp = 20.dp,
    subtitle: String = "",
    value: String = "",
    showArrow: Boolean = true,
    showDivider: Boolean = true,
    trailing: @Composable (() -> Unit)? = null,
    titleColor: Color = MobileTokens.textPrimary,
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
                .padding(horizontal = 16.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (icon != null) {
                Box(
                    modifier = Modifier
                        .size(iconSize)
                        .clip(RoundedCornerShape(8.dp))
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
                        color = MobileTokens.textTertiary,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            if (value.isNotBlank()) {
                Text(
                    value,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MobileTokens.textTertiary,
                )
                if (showArrow) {
                    Spacer(Modifier.width(4.dp))
                }
            }
            when {
                trailing != null -> trailing()
                showArrow -> Icon(
                    Icons.AutoMirrored.Filled.KeyboardArrowRight,
                    contentDescription = null,
                    modifier = Modifier.size(16.dp),
                    tint = MobileTokens.textDisabled,
                )
            }
        }
        if (showDivider) {
            HorizontalDivider(
                modifier = Modifier.padding(start = if (icon != null) 16.dp + iconSize + 14.dp else 16.dp),
                thickness = 0.5.dp,
                color = MobileTokens.divider,
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
                .padding(horizontal = 16.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                label,
                style = MaterialTheme.typography.bodyLarge.copy(fontWeight = FontWeight.Medium),
                color = MobileTokens.textPrimary,
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
                    color = MobileTokens.textPrimary,
                ),
                decorationBox = { inner ->
                    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterStart) {
                        if (value.isEmpty() && placeholder.isNotBlank()) {
                            Text(
                                placeholder,
                                style = MaterialTheme.typography.bodyMedium,
                                color = MobileTokens.textDisabled,
                            )
                        }
                        inner()
                    }
                },
            )
        }
        if (showDivider) {
            HorizontalDivider(
                modifier = Modifier.padding(start = 16.dp),
                thickness = 0.5.dp,
                color = MobileTokens.divider,
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
                .padding(start = 16.dp, end = 8.dp, top = 4.dp, bottom = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                label,
                style = MaterialTheme.typography.bodyLarge.copy(fontWeight = FontWeight.Medium),
                color = MobileTokens.textPrimary,
                modifier = Modifier.width(80.dp),
            )
            BasicTextField(
                value = value,
                onValueChange = onValueChange,
                modifier = Modifier.weight(1f),
                singleLine = true,
                keyboardOptions = keyboardOptions,
                textStyle = MaterialTheme.typography.bodyMedium.copy(
                    color = MobileTokens.textPrimary,
                ),
                decorationBox = { inner ->
                    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterStart) {
                        if (value.isEmpty() && placeholder.isNotBlank()) {
                            Text(
                                placeholder,
                                style = MaterialTheme.typography.bodyMedium,
                                color = MobileTokens.textDisabled,
                            )
                        }
                        inner()
                    }
                },
            )
            TextButton(
                onClick = onAction,
                contentPadding = PaddingValues(horizontal = 8.dp),
            ) {
                Text(
                    actionLabel,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MobileTokens.brandBlue,
                )
            }
        }
        if (showDivider) {
            HorizontalDivider(
                modifier = Modifier.padding(start = 16.dp),
                thickness = 0.5.dp,
                color = MobileTokens.divider,
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
            .padding(horizontal = 16.dp),
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
                    .padding(vertical = 12.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    opt.label,
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
                    color = if (selected) MobileTokens.brandBlue else MobileTokens.textSecondary,
                    textAlign = TextAlign.Center,
                )
                Spacer(Modifier.height(8.dp))
                Box(
                    Modifier
                        .fillMaxWidth(0.5f)
                        .height(2.5.dp)
                        .clip(RoundedCornerShape(1.25.dp))
                        .background(
                            if (selected) MobileTokens.brandBlue else Color.Transparent,
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
            .padding(horizontal = MobileTokens.authHorizontalMargin),
        shape = MobileTokens.cornerAuthCard,
        color = MobileTokens.surfaceWhite,
        tonalElevation = 0.dp,
        shadowElevation = 0.dp,
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
                    .padding(top = 16.dp, bottom = 0.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    opt.label,
                    fontSize = 16.sp,
                    fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
                    color = if (selected) MobileTokens.authTextPrimary else MobileTokens.authTextMuted,
                    textAlign = TextAlign.Center,
                )
                Spacer(Modifier.height(10.dp))
                Box(
                    Modifier
                        .fillMaxWidth()
                        .height(2.5.dp)
                        .background(
                            if (selected) MobileTokens.brandBlue else Color.Transparent,
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
            .padding(horizontal = 20.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                label,
                fontSize = 16.sp,
                color = MobileTokens.authTextPrimary,
                modifier = Modifier.width(72.dp),
            )
            BasicTextField(
                value = value,
                onValueChange = onValueChange,
                modifier = Modifier.weight(1f),
                singleLine = singleLine,
                visualTransformation = visualTransformation,
                keyboardOptions = keyboardOptions,
                textStyle = MaterialTheme.typography.bodyLarge.copy(
                    color = MobileTokens.authTextPrimary,
                    fontSize = 16.sp,
                ),
                decorationBox = { inner ->
                    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterStart) {
                        if (value.isEmpty() && placeholder.isNotBlank()) {
                            Text(
                                placeholder,
                                fontSize = 16.sp,
                                color = MobileTokens.authPlaceholder,
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
                color = MobileTokens.authDivider,
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
            .padding(horizontal = 20.dp)
            .clickable(enabled = enabled) {
                focusRequester.requestFocus()
                keyboard?.show()
            },
    ) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally),
        ) {
            repeat(cellCount) { index ->
                val char = digits.getOrNull(index)?.toString() ?: ""
                val focused = digits.length == index
                Box(
                    Modifier
                        .weight(1f)
                        .height(48.dp)
                        .clip(MobileTokens.cornerCardSmall)
                        .background(MobileTokens.surfaceWhite)
                        .border(
                            width = if (focused) 1.5.dp else 1.dp,
                            color = if (focused) MobileTokens.brandBlue else MobileTokens.authDivider,
                            shape = MobileTokens.cornerCardSmall,
                        ),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        char,
                        fontSize = 20.sp,
                        fontWeight = FontWeight.Medium,
                        color = MobileTokens.authTextPrimary,
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
        Spacer(Modifier.height(8.dp))
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
                .padding(horizontal = 20.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("验证码", fontSize = 16.sp, color = MobileTokens.authTextPrimary)
            Text(
                actionLabel,
                fontSize = 14.sp,
                color = if (actionEnabled) MobileTokens.brandBlue else MobileTokens.authTextMuted,
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
            .padding(horizontal = 20.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                label,
                fontSize = 16.sp,
                color = MobileTokens.authTextPrimary,
                modifier = Modifier.width(72.dp),
            )
            BasicTextField(
                value = value,
                onValueChange = onValueChange,
                modifier = Modifier.weight(1f),
                singleLine = true,
                keyboardOptions = keyboardOptions,
                textStyle = MaterialTheme.typography.bodyLarge.copy(
                    color = MobileTokens.authTextPrimary,
                    fontSize = 16.sp,
                ),
                decorationBox = { inner ->
                    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterStart) {
                        if (value.isEmpty() && placeholder.isNotBlank()) {
                            Text(
                                placeholder,
                                fontSize = 16.sp,
                                color = MobileTokens.authPlaceholder,
                            )
                        }
                        inner()
                    }
                },
            )
            Text(
                actionLabel,
                fontSize = 14.sp,
                color = MobileTokens.brandBlue,
                modifier = Modifier
                    .clickable(onClick = onAction)
                    .padding(start = 8.dp),
            )
        }
        if (showDivider) {
            HorizontalDivider(
                thickness = 0.5.dp,
                color = MobileTokens.authDivider,
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
            .padding(horizontal = MobileTokens.authHorizontalMargin)
            .height(48.dp),
        enabled = enabled,
        shape = MobileTokens.cornerAuthButton,
        colors = ButtonDefaults.buttonColors(
            containerColor = MobileTokens.brandBlue,
            contentColor = Color.White,
            disabledContainerColor = MobileTokens.brandBlue.copy(alpha = 0.4f),
            disabledContentColor = Color.White.copy(alpha = 0.7f),
        ),
        elevation = ButtonDefaults.buttonElevation(
            defaultElevation = 0.dp,
            disabledElevation = 0.dp,
        ),
    ) {
        Text(text, fontSize = 16.sp, fontWeight = FontWeight.Medium)
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
            .background(MobileTokens.authPageBg)
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
                Spacer(Modifier.height(20.dp))
                Text(
                    title,
                    fontSize = 22.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = MobileTokens.authTextPrimary,
                    textAlign = TextAlign.Center,
                )
                Text(
                    subtitle,
                    fontSize = 13.sp,
                    color = MobileTokens.authTextMuted,
                    textAlign = TextAlign.Center,
                    maxLines = 2,
                    modifier = Modifier
                        .padding(horizontal = 40.dp)
                        .padding(top = 8.dp),
                )
            }

            WeAuthCard(content = formContent)

            Column(
                Modifier
                    .fillMaxWidth()
                    .padding(top = 32.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                content = actions,
            )

            Spacer(Modifier.height(24.dp))
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
            .padding(horizontal = 16.dp)
            .height(44.dp),
        enabled = enabled,
        shape = RoundedCornerShape(8.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = MobileTokens.brandBlue,
            contentColor = Color.White,
            disabledContainerColor = MobileTokens.brandBlue.copy(alpha = 0.4f),
            disabledContentColor = Color.White.copy(alpha = 0.7f),
        ),
        elevation = ButtonDefaults.buttonElevation(defaultElevation = 0.dp),
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
            .padding(horizontal = 16.dp)
            .height(48.dp),
        enabled = enabled,
        shape = RoundedCornerShape(8.dp),
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
            .padding(horizontal = 16.dp)
            .height(48.dp),
        enabled = enabled,
        shape = RoundedCornerShape(8.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = MobileTokens.surfaceWhite,
            contentColor = MobileTokens.dangerRed,
        ),
        border = BorderStroke(1.dp, MobileTokens.dangerRed),
        elevation = ButtonDefaults.buttonElevation(defaultElevation = 0.dp),
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
            .background(MobileTokens.dangerRed),
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
        shape = RoundedCornerShape(20.dp),
        color = MobileTokens.surfaceBg,
        tonalElevation = 0.dp,
        shadowElevation = 0.dp,
    ) {
        Row(
            Modifier.padding(4.dp),
            horizontalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            options.forEach { opt ->
                val selected = opt.id == selectedId
                Surface(
                    modifier = Modifier
                        .clip(RoundedCornerShape(16.dp))
                        .clickable { onSelect(opt.id) },
                    color = if (selected) MobileTokens.brandBlueLight else Color.Transparent,
                    tonalElevation = 0.dp,
                    shadowElevation = 0.dp,
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
                                tint = if (selected) MobileTokens.brandBlue else MobileTokens.textTertiary,
                            )
                            Spacer(Modifier.width(4.dp))
                        }
                        Text(
                            opt.label,
                            style = MaterialTheme.typography.bodyMedium.copy(
                                fontWeight = if (selected) FontWeight.Medium else FontWeight.Normal,
                            ),
                            color = if (selected) MobileTokens.brandBlue else MobileTokens.textTertiary,
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
            .background(MobileTokens.surfaceWhite)
            .padding(horizontal = 12.dp, vertical = 8.dp),
    ) {
        Surface(
            shape = RoundedCornerShape(8.dp),
            color = MobileTokens.surfaceWhite,
            border = androidx.compose.foundation.BorderStroke(0.5.dp, MobileTokens.divider),
            shadowElevation = 0.dp,
        ) {
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                BasicTextField(
                    value = value,
                    onValueChange = onValueChange,
                    modifier = Modifier.weight(1f),
                    singleLine = true,
                    textStyle = MaterialTheme.typography.bodyMedium.copy(
                        color = MobileTokens.textPrimary,
                    ),
                    decorationBox = { inner ->
                        Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterStart) {
                            if (value.isEmpty()) {
                                Text(
                                    placeholder,
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MobileTokens.textDisabled,
                                )
                            }
                            inner()
                        }
                    },
                )
            }
        }
        Spacer(Modifier.height(8.dp))
        Row(
            Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
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
            .border(0.5.dp, MobileTokens.divider, CircleShape)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            icon,
            contentDescription = null,
            modifier = Modifier.size(20.dp),
            tint = MobileTokens.textPrimary,
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
        shape = RoundedCornerShape(16.dp),
        color = if (selected) MobileTokens.brandBlueLight else MobileTokens.surfaceWhite,
        border = androidx.compose.foundation.BorderStroke(0.5.dp, MobileTokens.divider),
    ) {
        Row(
            Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                Modifier
                    .size(14.dp)
                    .clip(CircleShape)
                    .background(if (selected) MobileTokens.brandBlue else MobileTokens.textTertiary),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    if (selected) "✓" else label.take(1),
                    style = MaterialTheme.typography.labelSmall,
                    color = Color.White,
                )
            }
            Spacer(Modifier.width(4.dp))
            Text(
                label,
                style = MaterialTheme.typography.bodySmall,
                color = if (selected) MobileTokens.brandBlue else MobileTokens.textTertiary,
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
            color = MobileTokens.dangerRed,
        )
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WeBottomNavBar  ─  微信风底栏：白底+品牌色选中
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
    Surface(
        modifier = modifier,
        shadowElevation = 3.dp,
        color = MobileTokens.surfaceWhite,
    ) {
        HorizontalDivider(
            thickness = 0.5.dp,
            color = MobileTokens.divider,
        )
        Row(
            Modifier
                .fillMaxWidth()
                .padding(top = 6.dp, bottom = 8.dp),
        ) {
            items.forEach { item ->
                val selected = currentRoute == item.route
                Column(
                    Modifier
                        .weight(1f)
                        .clickable { onSelect(item.route) }
                        .padding(vertical = 2.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Box(contentAlignment = Alignment.TopEnd) {
                        val scale by animateFloatAsState(
                            targetValue = if (selected) 1.1f else 1f,
                            animationSpec = tween(200),
                            label = "navScale",
                        )
                        Icon(
                            item.icon,
                            contentDescription = item.label,
                            modifier = Modifier.size(24.dp).graphicsLayer { scaleX = scale; scaleY = scale },
                            tint = if (selected) MobileTokens.brandBlue else MobileTokens.textTertiary,
                        )
                        if (item.badge > 0) {
                            WeBadge(count = item.badge)
                        }
                    }
                    Spacer(Modifier.height(2.dp))
                    Text(
                        item.label,
                        style = MaterialTheme.typography.labelSmall.copy(
                            fontWeight = if (selected) FontWeight.Medium else FontWeight.Normal,
                        ),
                        color = if (selected) MobileTokens.brandBlue else MobileTokens.textTertiary,
                    )
                }
            }
        }
    }
}
