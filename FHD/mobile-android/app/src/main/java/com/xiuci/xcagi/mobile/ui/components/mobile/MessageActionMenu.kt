package com.xiuci.xcagi.mobile.ui.components.mobile

import android.widget.Toast
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Box
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString

/**
 * 消息气泡长按动作菜单 —— 统一各聊天界面的「复制 / 引用 / 删除」。
 *
 * 用法：把气泡内容放进 [content]，并把回调返回的 [Modifier] 挂到气泡 Surface 上以接收长按。
 * - 「复制」始终提供（写入系统剪贴板 + 确认触感 + 「已复制」Toast）。
 * - 「引用」「删除」仅在传入对应回调时显示，便于各屏按能力裁剪。
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun MessageActionMenu(
    text: String,
    onReply: (() -> Unit)? = null,
    onDelete: (() -> Unit)? = null,
    content: @Composable (Modifier) -> Unit,
) {
    val clipboard = LocalClipboardManager.current
    val context = LocalContext.current
    val haptics = rememberHaptics()
    var expanded by remember { mutableStateOf(false) }
    Box {
        content(
            Modifier.combinedClickable(
                onClick = {},
                onLongClickLabel = "更多",
                onLongClick = {
                    if (text.isNotBlank() || onDelete != null) {
                        haptics.tap()
                        expanded = true
                    }
                },
            ),
        )
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            DropdownMenuItem(
                text = { Text("复制") },
                onClick = {
                    expanded = false
                    if (text.isNotBlank()) {
                        clipboard.setText(AnnotatedString(text))
                        haptics.confirm()
                        Toast.makeText(context, "已复制", Toast.LENGTH_SHORT).show()
                    }
                },
            )
            if (onReply != null) {
                DropdownMenuItem(
                    text = { Text("引用") },
                    onClick = { expanded = false; onReply() },
                )
            }
            if (onDelete != null) {
                DropdownMenuItem(
                    text = { Text("删除") },
                    onClick = { expanded = false; onDelete() },
                )
            }
        }
    }
}
