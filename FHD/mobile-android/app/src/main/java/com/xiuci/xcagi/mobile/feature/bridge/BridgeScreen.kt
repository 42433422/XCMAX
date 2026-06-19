package com.xiuci.xcagi.mobile.feature.bridge

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Forum
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.WeBlockButton
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeScreen
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSectionCaption
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme
import androidx.compose.foundation.layout.Arrangement

@Composable
fun BridgeScreen(vm: AppViewModel) {
    val items by vm.items.collectAsState()
    var reply by remember { mutableStateOf("") }
    var selectedId by remember { mutableStateOf(0) }
    LaunchedEffect(Unit) { vm.loadBridge() }

    WeScreen(
            title = "服务桥接",
            scrollable = false,
    ) {
        LazyColumn(
                modifier = Modifier.weight(1f).fillMaxWidth(),
                contentPadding = PaddingValues(vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(0.dp),
        ) {
            item { WeSectionCaption("待处理工单") }
            item {
                WeCellGroup {
                    if (items.isEmpty()) {
                        WeCell(
                                title = "暂无工单",
                                subtitle = "企业端有新工单后会同步到这里",
                                icon = Icons.Default.Forum,
                                iconTint = MaterialTheme.colorScheme.onSurfaceVariant,
                                iconBg = MaterialTheme.colorScheme.surfaceVariant,
                                showArrow = false,
                                showDivider = false,
                        )
                    } else {
                        items.forEachIndexed { idx, item ->
                            val id = item.id.toIntOrNull() ?: 0
                            WeCell(
                                    title = item.title,
                                    subtitle = item.subtitle.ifBlank { "等待处理" },
                                    icon = Icons.Default.Forum,
                                    iconTint =
                                            if (selectedId == id) XcagiTheme.extra.brandBlue
                                            else MaterialTheme.colorScheme.onSurfaceVariant,
                                    iconBg =
                                            if (selectedId == id) MaterialTheme.colorScheme.primaryContainer
                                            else MaterialTheme.colorScheme.surfaceVariant,
                                    showArrow = true,
                                    showDivider = idx < items.lastIndex,
                                    onClick = { selectedId = id },
                            )
                        }
                    }
                }
            }
        }

        WeSectionCaption(if (selectedId > 0) "回复 #$selectedId" else "回复")
        WeCellGroup {
            OutlinedTextField(
                    value = reply,
                    onValueChange = { reply = it },
                    modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 16.dp, vertical = 8.dp),
                    placeholder = { androidx.compose.material3.Text("输入处理意见或补充说明") },
                    minLines = 2,
                    maxLines = 4,
                    shape = RoundedCornerShape(8.dp),
                    colors =
                            androidx.compose.material3.OutlinedTextFieldDefaults.colors(
                                    focusedBorderColor = androidx.compose.ui.graphics.Color.Transparent,
                                    unfocusedBorderColor = androidx.compose.ui.graphics.Color.Transparent,
                            ),
            )
        }
        Spacer(Modifier.height(12.dp))
        WeBlockButton(
                text = "发送回复",
                onClick = {
                    vm.bridgeRespond(selectedId, reply) {
                        reply = ""
                        vm.loadBridge()
                    }
                },
                enabled = selectedId > 0 && reply.isNotBlank(),
        )
        Spacer(Modifier.height(16.dp))
    }
}
