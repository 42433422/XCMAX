package com.xiuci.xcagi.mobile.feature.bridge

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Forum
import androidx.compose.material3.MaterialTheme
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
import com.xiuci.xcagi.mobile.core.model.ListItem
import com.xiuci.xcagi.mobile.ui.components.mobile.WeBlockButton
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeField
import com.xiuci.xcagi.mobile.ui.components.mobile.WeScreen
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSectionCaption
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme
import androidx.compose.foundation.layout.Arrangement

const val CUSTOMER_SERVICE_REQUEST_TYPE = "mobile_ai_customer_service"

@Composable
fun BridgeScreen(
        vm: AppViewModel,
        title: String = "服务桥接",
        sectionTitle: String = "待处理工单",
        emptyTitle: String = "暂无工单",
        emptySubtitle: String = "企业端有新工单后会同步到这里",
        replyTitle: String = "回复",
        replyPlaceholder: String = "输入处理意见或补充说明",
        requestType: String? = null,
        respondedBy: String = "android",
        onBack: (() -> Unit)? = null,
) {
    val items by vm.items.collectAsState()
    var reply by remember { mutableStateOf("") }
    var selectedId by remember { mutableStateOf(0) }
    val customerServiceMode = requestType == CUSTOMER_SERVICE_REQUEST_TYPE
    LaunchedEffect(requestType) { vm.loadBridge(requestType = requestType) }
    LaunchedEffect(customerServiceMode, items) {
        if (customerServiceMode && items.isNotEmpty()) {
            val firstId = items.first().bridgeId()
            val stillVisible = items.any { it.bridgeId() == selectedId }
            if (firstId > 0 && (selectedId <= 0 || !stillVisible)) {
                selectedId = firstId
            }
        }
    }
    val selectedItem =
            if (selectedId > 0) items.firstOrNull { it.bridgeId() == selectedId }
            else if (customerServiceMode) items.firstOrNull()
            else null

    WeScreen(
            title = title,
            onBack = onBack,
            scrollable = false,
    ) {
        LazyColumn(
                modifier = Modifier.weight(1f).fillMaxWidth(),
                contentPadding = PaddingValues(vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(0.dp),
        ) {
            item { WeSectionCaption(sectionTitle) }
            item {
                WeCellGroup {
                    if (items.isEmpty()) {
                        WeCell(
                                title = emptyTitle,
                                subtitle = emptySubtitle,
                                icon = Icons.Default.Forum,
                                iconTint = MaterialTheme.colorScheme.onSurfaceVariant,
                                iconBg = MaterialTheme.colorScheme.surfaceVariant,
                                showArrow = false,
                                showDivider = false,
                        )
                    } else {
                        items.forEachIndexed { idx, item ->
                            val id = item.bridgeId()
                            val cellTitle =
                                    if (customerServiceMode) {
                                        item.customerServiceTitle()
                                    } else item.title
                            val cellSubtitle =
                                    if (customerServiceMode) {
                                        item.customerServiceSubtitle()
                                    } else item.subtitle.ifBlank { "等待处理" }
                            WeCell(
                                    title = cellTitle,
                                    subtitle = cellSubtitle,
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
            if (customerServiceMode && selectedItem != null) {
                item { Spacer(Modifier.height(12.dp)) }
                item { WeSectionCaption("当前客户") }
                item {
                    WeCellGroup {
                        WeCell(
                                title = selectedItem.customerServiceTitle(),
                                subtitle = "状态：${selectedItem.customerServiceStatus()}",
                                icon = Icons.Default.Forum,
                                showArrow = false,
                        )
                        WeCell(
                                title = "客户原话",
                                subtitle =
                                        selectedItem.payloadText("description")
                                                .ifBlank { selectedItem.title }
                                                .ifBlank { "暂无内容" },
                                icon = Icons.Default.Forum,
                                showArrow = false,
                        )
                        WeCell(
                                title = "已回复",
                                subtitle = selectedItem.payloadText("response").ifBlank { "尚未人工回复" },
                                icon = Icons.Default.Forum,
                                showArrow = false,
                                showDivider = false,
                        )
                    }
                }
            }
        }

        WeSectionCaption(if (selectedId > 0) "$replyTitle #$selectedId" else replyTitle)
        WeCellGroup {
            WeField(
                    value = reply,
                    onValueChange = { reply = it },
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                    placeholder = replyPlaceholder,
                    singleLine = false,
            )
        }
        Spacer(Modifier.height(12.dp))
        WeBlockButton(
                text = "发送回复",
                onClick = {
                    vm.bridgeRespond(selectedId, reply, respondedBy = respondedBy) {
                        reply = ""
                        vm.loadBridge(requestType = requestType)
                    }
                },
                enabled = selectedId > 0 && reply.isNotBlank(),
        )
        Spacer(Modifier.height(16.dp))
    }
}

private fun ListItem.bridgeId(): Int = id.toIntOrNull() ?: 0

private fun ListItem.payloadText(key: String): String = "${payload[key] ?: ""}".trim()

private fun ListItem.customerServiceTitle(): String =
        payloadText("source_instance_name")
                .ifBlank { payloadText("username") }
                .ifBlank { title }
                .ifBlank { "客户消息" }

private fun ListItem.customerServiceStatus(): String =
        payloadText("status").ifBlank { subtitle }.ifBlank { "pending" }

private fun ListItem.customerServiceSubtitle(): String {
    val description = payloadText("description").ifBlank { title }
    val status = customerServiceStatus()
    return if (description.isBlank()) status else "$description · $status"
}
