package com.xiuci.xcagi.mobile.ui.components.mobile

import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.runtime.remember
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
import androidx.compose.ui.unit.sp

private val WeChatGreen = Color(0xFF07C160)

// ─────────────────────────────────────────────────────────────────────────────
// WeTopBar  ─  扁平无底部阴影顶栏，居中标题
// ─────────────────────────────────────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WeTopBar(
    title: String,
    onBack: (() -> Unit)? = null,
    actions: @Composable () -> Unit = {},
) {
    TopAppBar(
        title = {
            Text(
                title,
                style = MaterialTheme.typography.titleMedium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        },
        navigationIcon = {
            if (onBack != null) {
                IconButton(onClick = onBack) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                }
            }
        },
        actions = { actions() },
        colors = TopAppBarDefaults.topAppBarColors(
            containerColor = MaterialTheme.colorScheme.surface,
            titleContentColor = MaterialTheme.colorScheme.onSurface,
            navigationIconContentColor = MaterialTheme.colorScheme.onSurface,
            actionIconContentColor = MaterialTheme.colorScheme.onSurface,
        ),
        windowInsets = androidx.compose.foundation.layout.WindowInsets(0),
    )
    HorizontalDivider(
        thickness = 0.5.dp,
        color = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f),
    )
}

// ─────────────────────────────────────────────────────────────────────────────
// WeScreen  ─  灰底可滚动页面骨架
// ─────────────────────────────────────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WeScreen(
    title: String,
    onBack: (() -> Unit)? = null,
    topBarActions: @Composable () -> Unit = {},
    scrollable: Boolean = true,
    contentPadding: PaddingValues = PaddingValues(vertical = 12.dp),
    content: @Composable ColumnScope.() -> Unit,
) {
    Scaffold(
        topBar = { WeTopBar(title, onBack, topBarActions) },
        containerColor = MaterialTheme.colorScheme.background,
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
// WeSectionCaption  ─  分组上方小灰标题
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun WeSectionCaption(text: String, modifier: Modifier = Modifier) {
    Text(
        text,
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = modifier.padding(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 4.dp),
    )
}

// ─────────────────────────────────────────────────────────────────────────────
// WeCellGroup  ─  白底圆角分组容器，子项间自动插入左缩进发丝分隔线
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun WeCellGroup(
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp),
        shape = MobileTokens.cornerCard,
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 0.dp,
        shadowElevation = 0.dp,
    ) {
        Column(content = content)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WeCell  ─  通用行：可选前置图标 + 标题 + 副标题/右值 + 可选尾部
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun WeCell(
    title: String,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    iconTint: Color = MaterialTheme.colorScheme.primary,
    subtitle: String = "",
    value: String = "",
    showArrow: Boolean = false,
    showDivider: Boolean = true,
    trailing: @Composable (() -> Unit)? = null,
    onClick: (() -> Unit)? = null,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 13.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (icon != null) {
                Box(
                    modifier = Modifier
                        .size(32.dp)
                        .clip(RoundedCornerShape(8.dp))
                        .background(iconTint.copy(alpha = 0.12f)),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        icon,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                        tint = iconTint,
                    )
                }
            }
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(title, style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurface)
                if (subtitle.isNotBlank()) {
                    Text(
                        subtitle,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            if (value.isNotBlank()) {
                Text(value, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            when {
                trailing != null -> trailing()
                showArrow -> Icon(
                    Icons.AutoMirrored.Filled.KeyboardArrowRight,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        if (showDivider) {
            HorizontalDivider(
                modifier = Modifier.padding(start = if (icon != null) 60.dp else 16.dp),
                thickness = 0.5.dp,
                color = MaterialTheme.colorScheme.outline.copy(alpha = 0.4f),
            )
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WeInputCell  ─  分组内输入行（左标签 + 无边框输入框）
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
                style = MaterialTheme.typography.bodyLarge,
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
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
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
                color = MaterialTheme.colorScheme.outline.copy(alpha = 0.4f),
            )
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WeInputActionCell  ─  分组内输入行 + 右侧绿色文字按钮
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
                style = MaterialTheme.typography.bodyLarge,
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
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
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
                    color = WeChatGreen,
                )
            }
        }
        if (showDivider) {
            HorizontalDivider(
                modifier = Modifier.padding(start = 16.dp),
                thickness = 0.5.dp,
                color = MaterialTheme.colorScheme.outline.copy(alpha = 0.4f),
            )
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WeUnderlineTabs  ─  纯文字 Tab + 绿色下划线
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
                    color = if (selected) WeChatGreen else MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                )
                Spacer(Modifier.height(8.dp))
                Box(
                    Modifier
                        .fillMaxWidth(0.5f)
                        .height(2.dp)
                        .background(if (selected) WeChatGreen else Color.Transparent),
                )
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Auth 专用组件  ─  登录/注册页精致布局（对标微信）
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
        color = MaterialTheme.colorScheme.surface,
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
                        .height(2.dp)
                        .background(if (selected) MobileTokens.accent() else Color.Transparent),
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

/** Kimi 风 6 格验证码输入，保留单一字符串回调供 loginPhone API 使用。 */
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
                        .clip(MobileTokens.cornerCard)
                        .background(MaterialTheme.colorScheme.surface)
                        .border(
                            width = if (focused) 1.5.dp else 1.dp,
                            color = if (focused) MobileTokens.accent() else MobileTokens.authDivider,
                            shape = MobileTokens.cornerCard,
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
                color = if (actionEnabled) MobileTokens.accent() else MobileTokens.authTextMuted,
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
                color = MobileTokens.accent(),
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
            .height(50.dp),
        enabled = enabled,
        shape = MobileTokens.cornerAuthButton,
        colors = ButtonDefaults.buttonColors(
            containerColor = MaterialTheme.colorScheme.primary,
            contentColor = MaterialTheme.colorScheme.onPrimary,
            disabledContainerColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.4f),
            disabledContentColor = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.7f),
        ),
        elevation = ButtonDefaults.buttonElevation(0.dp, 0.dp, 0.dp, 0.dp, 0.dp),
    ) {
        Text(text, fontSize = 17.sp, fontWeight = FontWeight.Medium)
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
// WeGreenButton  ─  微信绿全宽主按钮
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
            .height(48.dp),
        enabled = enabled,
        shape = RoundedCornerShape(12.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = WeChatGreen,
            contentColor = Color.White,
            disabledContainerColor = WeChatGreen.copy(alpha = 0.4f),
            disabledContentColor = Color.White.copy(alpha = 0.7f),
        ),
    ) {
        Text(text, style = MaterialTheme.typography.bodyLarge)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WeThirdPartyLoginRow  ─  微信 / 抖音第三方登录占位（后端 OAuth 未就绪）
// ─────────────────────────────────────────────────────────────────────────────

private val DouyinPink = Color(0xFFFE2C55)

@Composable
fun WeThirdPartyLoginRow(
    onWeChat: () -> Unit,
    onDouyin: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = MobileTokens.authHorizontalMargin),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        HorizontalDivider(
            thickness = 0.5.dp,
            color = MobileTokens.authDivider,
            modifier = Modifier.padding(bottom = 16.dp),
        )
        Text(
            "其他登录方式",
            fontSize = 13.sp,
            color = MobileTokens.authTextMuted,
            modifier = Modifier.padding(bottom = 12.dp),
        )
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(24.dp, Alignment.CenterHorizontally),
        ) {
            WeThirdPartyChip(label = "微信", color = WeChatGreen, onClick = onWeChat)
            WeThirdPartyChip(label = "抖音", color = DouyinPink, onClick = onDouyin)
        }
    }
}

@Composable
private fun WeThirdPartyChip(
    label: String,
    color: Color,
    onClick: () -> Unit,
) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier.clickable(onClick = onClick),
    ) {
        Box(
            Modifier
                .size(48.dp)
                .clip(CircleShape)
                .background(color.copy(alpha = 0.12f)),
            contentAlignment = Alignment.Center,
        ) {
            Text(label.take(1), fontSize = 18.sp, fontWeight = FontWeight.SemiBold, color = color)
        }
        Spacer(Modifier.height(6.dp))
        Text(label, fontSize = 12.sp, color = MobileTokens.authTextMuted)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WeBlockButton  ─  全宽圆角主按钮（微信绿）
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun WeBlockButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    WeGreenButton(text, onClick, modifier, enabled)
}

// ─────────────────────────────────────────────────────────────────────────────
// WeBlockOutlinedButton  ─  全宽圆角次按钮（描边）
// ─────────────────────────────────────────────────────────────────────────────

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
            .height(50.dp),
        enabled = enabled,
        shape = RoundedCornerShape(10.dp),
    ) {
        Text(text, style = MaterialTheme.typography.bodyLarge)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WeBlockDangerButton  ─  全宽圆角危险按钮（白底红字）
// ─────────────────────────────────────────────────────────────────────────────

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
            .height(50.dp),
        enabled = enabled,
        shape = RoundedCornerShape(10.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = MaterialTheme.colorScheme.surface,
            contentColor = MaterialTheme.colorScheme.error,
        ),
    ) {
        Text(text, style = MaterialTheme.typography.bodyLarge)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WeAvatar  ─  圆角方形头像（微信式）
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun WeAvatar(
    content: @Composable () -> Unit,
    modifier: Modifier = Modifier,
    size: androidx.compose.ui.unit.Dp = 64.dp,
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

// ─────────────────────────────────────────────────────────────────────────────
// WeSpacer  ─  分组间隔
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun WeSpacer(height: androidx.compose.ui.unit.Dp = 16.dp) {
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
    Box(
        modifier = modifier
            .clip(CircleShape)
            .background(MaterialTheme.colorScheme.error)
            .padding(
                horizontal = if (count > 0 && count < 10) 5.dp else if (count >= 10) 4.dp else 0.dp,
                vertical = if (count > 0) 1.dp else 0.dp,
            )
            .then(if (showDot && count <= 0) Modifier.size(8.dp) else Modifier),
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
// WeModeCapsule  ─  DeepSeek 式模式切换胶囊
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
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(24.dp),
        color = MaterialTheme.colorScheme.surface,
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
                        .weight(1f)
                        .clickable { onSelect(opt.id) },
                    shape = RoundedCornerShape(20.dp),
                    color = if (selected) MaterialTheme.colorScheme.background else Color.Transparent,
                    tonalElevation = 0.dp,
                    shadowElevation = 0.dp,
                ) {
                    Row(
                        Modifier.padding(vertical = 10.dp, horizontal = 8.dp),
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        if (opt.icon != null) {
                            Icon(
                                opt.icon,
                                contentDescription = null,
                                modifier = Modifier.size(16.dp),
                                tint = if (selected) WeChatGreen else MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            Spacer(Modifier.width(4.dp))
                        }
                        Text(
                            opt.label,
                            style = MaterialTheme.typography.labelLarge,
                            color = if (selected) WeChatGreen else MaterialTheme.colorScheme.onSurfaceVariant,
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
// ChatToolRow  ─  模式 + 联网 + 更多（主工具栏一行）
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun ChatToolRow(
    modeOptions: List<WeModeOption>,
    selectedModeId: String,
    onModeSelect: (String) -> Unit,
    smartSearch: Boolean,
    onSmartSearchChange: (Boolean) -> Unit,
    onMore: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier
            .fillMaxWidth()
            .padding(horizontal = MobileTokens.horizontalPagePadding, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        WeModeCapsule(
            options = modeOptions,
            selectedId = selectedModeId,
            onSelect = onModeSelect,
            modifier = Modifier.weight(1f),
        )
        WeInputChip(
            label = "联网",
            selected = smartSearch,
            onClick = { onSmartSearchChange(!smartSearch) },
        )
        IconButton(onClick = onMore, modifier = Modifier.size(36.dp)) {
            Icon(
                Icons.Default.Add,
                contentDescription = "更多",
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WeChatInputBar  ─  底部大圆角输入条（工具收纳至 ChatToolRow / BottomSheet）
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
) {
    Column(
        modifier
            .fillMaxWidth()
            .padding(horizontal = MobileTokens.horizontalPagePadding, vertical = 8.dp),
    ) {
        Surface(
            shape = MobileTokens.cornerInputBar,
            color = MaterialTheme.colorScheme.surface,
            shadowElevation = 1.dp,
        ) {
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 8.dp, vertical = 4.dp),
                verticalAlignment = Alignment.Bottom,
            ) {
                OutlinedTextField(
                    value = value,
                    onValueChange = onValueChange,
                    modifier = Modifier.weight(1f),
                    placeholder = {
                        Text(
                            placeholder,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    },
                    maxLines = 4,
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = Color.Transparent,
                        unfocusedBorderColor = Color.Transparent,
                    ),
                )
                if (onVoice != null) {
                    IconButton(onClick = onVoice, modifier = Modifier.size(40.dp)) {
                        Icon(
                            Icons.Default.Mic,
                            contentDescription = "语音",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                IconButton(
                    onClick = { if (streaming) onStop() else onSend() },
                    modifier = Modifier.size(40.dp),
                ) {
                    Icon(
                        if (streaming) Icons.Default.Stop else Icons.AutoMirrored.Filled.Send,
                        contentDescription = if (streaming) "停止" else "发送",
                        tint = MobileTokens.accent(),
                    )
                }
            }
        }
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
        shape = RoundedCornerShape(14.dp),
        color = if (selected) MobileTokens.chipSelectedBg() else MobileTokens.chipUnselectedBg(),
    ) {
        Text(
            label,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
            style = MaterialTheme.typography.labelMedium,
            color = if (selected) MobileTokens.accent() else MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WeRedActionCell  ─  退出登录等红字居中 cell
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun WeRedActionCell(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    WeCellGroup(modifier) {
        Box(
            Modifier
                .fillMaxWidth()
                .clickable(onClick = onClick)
                .padding(vertical = 14.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text,
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.error,
            )
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WeBottomNavBar  ─  微信式 4 Tab 底栏
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
    Column(modifier) {
        HorizontalDivider(
            thickness = 0.5.dp,
            color = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f),
        )
        Surface(color = MaterialTheme.colorScheme.surface) {
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(vertical = 6.dp),
            ) {
                items.forEach { item ->
                    val selected = currentRoute == item.route
                    Column(
                        Modifier
                            .weight(1f)
                            .clickable { onSelect(item.route) }
                            .padding(vertical = 4.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Box {
                            Icon(
                                item.icon,
                                contentDescription = item.label,
                                modifier = Modifier.size(24.dp),
                                tint = if (selected) MobileTokens.accent() else MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            if (item.badge > 0) {
                                WeBadge(
                                    count = item.badge,
                                    modifier = Modifier.align(Alignment.TopEnd),
                                )
                            }
                        }
                        Text(
                            item.label,
                            style = MaterialTheme.typography.labelSmall,
                            color = if (selected) MobileTokens.accent() else MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(top = 2.dp),
                        )
                    }
                }
            }
        }
    }
}
