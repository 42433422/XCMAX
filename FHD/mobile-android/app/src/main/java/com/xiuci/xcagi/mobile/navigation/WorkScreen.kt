package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountBalance
import androidx.compose.material.icons.filled.Chat
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.Inventory
import androidx.compose.material.icons.filled.LocalShipping
import androidx.compose.material.icons.filled.People
import androidx.compose.material.icons.filled.Task
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.core.ProductSkuConfig
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.WeBadge
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeScreen
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSectionCaption
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSpacer

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkScreen(
    vm: AppViewModel,
    onApproval: () -> Unit,
    onErpTab: (Int) -> Unit,
    onIm: () -> Unit,
    onBridge: () -> Unit,
    onLongTail: () -> Unit,
    onConnectPc: () -> Unit,
) {
    val hub by vm.homeHub.collectAsState()
    val fhdHost by vm.fhdHost.collectAsState()
    val approvalCount by vm.approvalPendingCount.collectAsState()

    LaunchedEffect(Unit) {
        vm.loadHomeHub()
        vm.refreshApprovalCount()
    }

    WeScreen(title = "工作", scrollable = true) {
        WeCellGroup {
            WeCell(
                title = if (fhdHost.isBlank()) "未连接电脑" else "电脑：${fhdHost.substringBefore(':')}",
                subtitle = if (hub.pcOnline) "在线 · ${hub.syncLabel}" else "离线或未配置 · 可使用云端",
                icon = Icons.Default.Computer,
                iconTint = if (hub.pcOnline) Color(0xFF07C160) else MaterialTheme.colorScheme.onSurfaceVariant,
                showArrow = true,
                showDivider = false,
                onClick = onConnectPc,
            )
        }

        if (ProductSkuConfig.showsEnterpriseNav) {
            WeSpacer(12.dp)
            WeSectionCaption("待办与审批")
            WeCellGroup {
                WeCell(
                    title = "审批",
                    subtitle = "待处理审批单",
                    icon = Icons.Default.Task,
                    iconTint = Color(0xFF10AEFF),
                    showArrow = true,
                    showDivider = false,
                    trailing = {
                        if (approvalCount > 0) WeBadge(count = approvalCount)
                    },
                    onClick = onApproval,
                )
            }

            WeSpacer(12.dp)
            WeSectionCaption("业务数据")
            WeCellGroup {
                WeCell(
                    title = "客户",
                    icon = Icons.Default.People,
                    iconTint = Color(0xFF576B95),
                    showArrow = true,
                    onClick = { onErpTab(0) },
                )
                WeCell(
                    title = "发货",
                    icon = Icons.Default.LocalShipping,
                    iconTint = Color(0xFFFA9D3B),
                    showArrow = true,
                    onClick = { onErpTab(1) },
                )
                WeCell(
                    title = "库存",
                    icon = Icons.Default.Inventory,
                    iconTint = Color(0xFF07C160),
                    showArrow = true,
                    showDivider = false,
                    onClick = { onErpTab(2) },
                )
            }
        }

        WeSpacer(12.dp)
        WeSectionCaption("协作与工具")
        WeCellGroup {
            WeCell(
                title = "IM 消息",
                subtitle = "原生会话（高级）",
                icon = Icons.Default.Chat,
                iconTint = Color(0xFF07C160),
                showArrow = true,
                onClick = onIm,
            )
            WeCell(
                title = "Service Bridge",
                subtitle = "服务桥接与回复",
                icon = Icons.Default.AccountBalance,
                iconTint = Color(0xFF576B95),
                showArrow = true,
                onClick = onBridge,
            )
            if (ProductSkuConfig.showsEnterpriseNav) {
                WeCell(
                    title = "财务摘要",
                    subtitle = "标签打印请在 PC 端操作",
                    icon = Icons.Default.AccountBalance,
                    iconTint = Color(0xFFFA5151),
                    showArrow = true,
                    showDivider = false,
                    onClick = onLongTail,
                )
            }
        }
    }
}
