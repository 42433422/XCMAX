package com.xiuci.xcagi.mobile.ui.components.mobile

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.xiuci.xcagi.mobile.ui.theme.Spacing
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme

data class ChatToolCardAction(
    val icon: ImageVector,
    val title: String,
    val subtitle: String,
    val onClick: () -> Unit,
)

@Composable
fun ChatComposerBar(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    busy: Boolean,
    onSend: () -> Unit,
    onStop: (() -> Unit)? = null,
    onVoice: (() -> Unit)? = null,
    showTools: Boolean,
    onToggleTools: () -> Unit,
    toolActions: List<ChatToolCardAction>,
    modifier: Modifier = Modifier,
    topContent: (@Composable ColumnScope.() -> Unit)? = null,
) {
    val canSend = value.isNotBlank() && !busy
    val canStop = busy && onStop != null
    val focusManager = LocalFocusManager.current
    val keyboardController = LocalSoftwareKeyboardController.current
    Surface(color = MaterialTheme.colorScheme.surface, modifier = modifier.fillMaxWidth()) {
        Column {
            HorizontalDivider(thickness = 0.5.dp, color = MaterialTheme.colorScheme.outlineVariant)
            topContent?.invoke(this)
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 8.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                if (onVoice != null) {
                    ChatComposerIconButton(
                        icon = Icons.Default.Mic,
                        contentDescription = "语音",
                        onClick = onVoice,
                    )
                }

                Surface(
                    shape = RoundedCornerShape(10.dp),
                    color = MaterialTheme.colorScheme.surface,
                    modifier = Modifier.weight(1f).height(38.dp),
                ) {
                    BasicTextField(
                        value = value,
                        onValueChange = onValueChange,
                        modifier = Modifier.padding(horizontal = 12.dp).fillMaxSize(),
                        singleLine = true,
                        textStyle = MaterialTheme.typography.bodyMedium.copy(
                            color = MaterialTheme.colorScheme.onSurface,
                            fontSize = 15.sp,
                        ),
                        cursorBrush = SolidColor(XcagiTheme.extra.brandBlue),
                        decorationBox = { inner ->
                            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.CenterStart) {
                                if (value.isEmpty()) {
                                    Text(
                                        placeholder,
                                        style = MaterialTheme.typography.bodyMedium.copy(fontSize = 15.sp),
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                }
                                inner()
                            }
                        },
                    )
                }

                ChatComposerIconButton(
                    icon = Icons.Default.Add,
                    contentDescription = "更多工具",
                    iconSize = 26.dp,
                    selected = showTools,
                    onClick = {
                        keyboardController?.hide()
                        focusManager.clearFocus(force = true)
                        onToggleTools()
                    },
                )
                if (canSend || canStop) {
                    ChatSendPill(canStop = canStop, onSend = onSend, onStop = onStop)
                }
            }
            if (showTools && toolActions.isNotEmpty()) {
                ChatToolCardPanel(
                    actions = toolActions,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp)
                        .padding(top = 8.dp, bottom = Spacing.lg),
                )
            }
        }
    }
}

@Composable
private fun ChatComposerIconButton(
    icon: ImageVector,
    contentDescription: String,
    onClick: () -> Unit,
    selected: Boolean = false,
    iconSize: androidx.compose.ui.unit.Dp = 22.dp,
) {
    IconButton(onClick = onClick, modifier = Modifier.size(38.dp)) {
        Icon(
            icon,
            contentDescription = contentDescription,
            tint = if (selected) XcagiTheme.extra.brandBlue else MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.size(iconSize),
        )
    }
}

@Composable
private fun ChatSendPill(
    canStop: Boolean,
    onSend: () -> Unit,
    onStop: (() -> Unit)?,
) {
    Surface(
        shape = RoundedCornerShape(8.dp),
        color = if (canStop) MaterialTheme.colorScheme.errorContainer else XcagiTheme.extra.brandBlue,
        modifier = Modifier
            .height(38.dp)
            .clickable {
                if (canStop) onStop?.invoke() else onSend()
            },
    ) {
        Box(
            Modifier.padding(horizontal = 17.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                if (canStop) "停止" else "发送",
                style = MaterialTheme.typography.labelLarge.copy(
                    fontWeight = FontWeight.Medium,
                    fontSize = 15.sp,
                ),
                color = if (canStop) MaterialTheme.colorScheme.error else Color.White,
            )
        }
    }
}

@Composable
fun ChatToolCardPanel(
    actions: List<ChatToolCardAction>,
    modifier: Modifier = Modifier,
    columns: Int = 4,
) {
    if (actions.isEmpty()) return
    Column(
        modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(18.dp),
    ) {
        actions.chunked(columns).forEach { rowTools ->
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                rowTools.forEach { tool ->
                    ChatToolCard(tool = tool, modifier = Modifier.weight(1f))
                }
                repeat(columns - rowTools.size) {
                    Spacer(Modifier.weight(1f))
                }
            }
        }
    }
}

@Composable
private fun ChatToolCard(tool: ChatToolCardAction, modifier: Modifier = Modifier) {
    Column(
        modifier
            .height(92.dp)
            .clip(RoundedCornerShape(8.dp))
            .clickable(onClick = tool.onClick)
            .padding(top = 1.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            Modifier
                .size(62.dp)
                .clip(RoundedCornerShape(8.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.62f)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                tool.icon,
                contentDescription = tool.title,
                tint = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.size(27.dp),
            )
        }
        Spacer(Modifier.height(8.dp))
        Text(
            tool.title,
            style = MaterialTheme.typography.labelMedium.copy(fontSize = 13.sp),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.widthIn(max = 82.dp),
        )
    }
}
