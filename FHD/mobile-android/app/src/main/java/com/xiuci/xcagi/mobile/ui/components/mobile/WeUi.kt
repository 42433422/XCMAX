package com.xiuci.xcagi.mobile.ui.components.mobile

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp

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
        shape = RoundedCornerShape(10.dp),
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 0.dp,
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
            OutlinedTextField(
                value = value,
                onValueChange = onValueChange,
                modifier = Modifier.weight(1f),
                placeholder = if (placeholder.isNotBlank()) {
                    { Text(placeholder, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                } else null,
                singleLine = singleLine,
                visualTransformation = visualTransformation,
                keyboardOptions = keyboardOptions,
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = Color.Transparent,
                    unfocusedBorderColor = Color.Transparent,
                    errorBorderColor = Color.Transparent,
                    disabledBorderColor = Color.Transparent,
                ),
                textStyle = MaterialTheme.typography.bodyMedium,
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
// WeBlockButton  ─  全宽圆角主按钮（填充 primary）
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun WeBlockButton(
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
    ) {
        Text(text, style = MaterialTheme.typography.bodyLarge)
    }
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
            .clip(RoundedCornerShape(size * 0.22f))
            .background(MaterialTheme.colorScheme.primaryContainer),
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
        color = MaterialTheme.colorScheme.surfaceVariant,
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
                    color = if (selected) MaterialTheme.colorScheme.surface else Color.Transparent,
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
                                tint = if (selected) MobileTokens.accent() else MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            Spacer(Modifier.width(4.dp))
                        }
                        Text(
                            opt.label,
                            style = MaterialTheme.typography.labelLarge,
                            color = if (selected) MobileTokens.accent() else MaterialTheme.colorScheme.onSurfaceVariant,
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
// WeChatInputBar  ─  底部大圆角输入条 + chips
// ─────────────────────────────────────────────────────────────────────────────

@Composable
fun WeChatInputBar(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    deepThinking: Boolean,
    onDeepThinkingChange: (Boolean) -> Unit,
    smartSearch: Boolean,
    onSmartSearchChange: (Boolean) -> Unit,
    onSend: () -> Unit,
    onStop: () -> Unit,
    streaming: Boolean,
    modifier: Modifier = Modifier,
    onAttach: (() -> Unit)? = null,
    onVoice: (() -> Unit)? = null,
) {
    Column(
        modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 8.dp),
    ) {
        Surface(
            shape = MobileTokens.cornerInputBar,
            color = MaterialTheme.colorScheme.surface,
            shadowElevation = 1.dp,
        ) {
            Column(Modifier.padding(12.dp)) {
                OutlinedTextField(
                    value = value,
                    onValueChange = onValueChange,
                    modifier = Modifier.fillMaxWidth(),
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
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        WeInputChip(
                            label = "深度思考",
                            selected = deepThinking,
                            onClick = { onDeepThinkingChange(!deepThinking) },
                        )
                        WeInputChip(
                            label = "智能搜索",
                            selected = smartSearch,
                            onClick = { onSmartSearchChange(!smartSearch) },
                        )
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        if (onAttach != null) {
                            IconButton(onClick = onAttach, modifier = Modifier.size(36.dp)) {
                                Icon(
                                    Icons.Default.Add,
                                    contentDescription = "更多",
                                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                        if (onVoice != null) {
                            IconButton(onClick = onVoice, modifier = Modifier.size(36.dp)) {
                                Icon(
                                    Icons.Default.Mic,
                                    contentDescription = "语音",
                                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                        IconButton(
                            onClick = { if (streaming) onStop() else onSend() },
                            modifier = Modifier.size(36.dp),
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
