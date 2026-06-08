package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileScaffold
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileStatusChip
import com.xiuci.xcagi.mobile.ui.components.mobile.WeBlockButton
import com.xiuci.xcagi.mobile.ui.components.mobile.WeBlockOutlinedButton
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSectionCaption
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSpacer
import com.xiuci.xcagi.mobile.ui.components.mobile.WeTopBar
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileTokens

@Composable
fun ApprovalListScreen(
    vm: AppViewModel,
    onItemClick: (Int) -> Unit,
) {
    val items by vm.items.collectAsState()
    val loading by vm.listLoading.collectAsState()
    val error by vm.listError.collectAsState()

    LaunchedEffect(Unit) { vm.loadApprovals() }

    MobileScaffold(
        title = "审批",
        onRefresh = vm::loadApprovals,
        loading = loading,
        error = error,
        empty = items.isEmpty(),
        emptyMessage = "暂无待办审批",
        onRetry = vm::loadApprovals,
    ) {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(0.dp),
        ) {
            item {
                WeSectionCaption("待处理")
            }
            item {
                WeCellGroup {
                    items.forEachIndexed { idx, item ->
                        val id = item.id.toIntOrNull() ?: 0
                        val statusText = item.payload["status"]?.toString() ?: item.subtitle
                        WeCell(
                            title = item.title,
                            subtitle = item.subtitle.ifBlank {
                                item.payload["applicant_name"]?.toString().orEmpty()
                            },
                            showDivider = idx < items.lastIndex,
                            showArrow = id > 0,
                            trailing = {
                                if (statusText.isNotBlank()) {
                                    MobileStatusChip(statusText)
                                }
                            },
                            onClick = if (id > 0) ({ onItemClick(id) }) else null,
                        )
                    }
                }
            }
        }
    }
}

@Composable
fun ApprovalDetailScreen(vm: AppViewModel, id: Int, onBack: () -> Unit) {
    val detail by vm.approvalDetail.collectAsState()
    val loading by vm.approvalDetailLoading.collectAsState()
    var opinion by remember { mutableStateOf("") }
    var confirmAction by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(id) { vm.loadApprovalDetail(id) }

    MobileScaffold(
        title = detail?.title ?: "审批详情",
        onBack = onBack,
        loading = loading,
        error = if (!loading && detail == null) "无法加载审批详情" else null,
        empty = false,
        onRetry = { vm.loadApprovalDetail(id) },
    ) {
        val d = detail ?: return@MobileScaffold

        Column(
            Modifier
                .fillMaxSize()
                .padding(vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(0.dp),
        ) {
            // ── 基本信息 ──────────────────────────────────
            WeSectionCaption("审批信息")
            WeCellGroup {
                WeCell(
                    title = "单号",
                    value = d.requestNo.ifBlank { "#${d.id}" },
                    showDivider = true,
                    trailing = { MobileStatusChip(d.status) },
                )
                WeCell(title = "发起人", value = d.applicantName, showDivider = d.flowName.isNotBlank())
                if (d.flowName.isNotBlank()) {
                    WeCell(title = "流程", value = d.flowName, showDivider = d.currentNodeName.isNotBlank())
                }
                if (d.currentNodeName.isNotBlank()) {
                    WeCell(title = "当前节点", value = d.currentNodeName, showDivider = d.submittedAt.isNotBlank())
                }
                if (d.submittedAt.isNotBlank()) {
                    WeCell(title = "提交时间", value = d.submittedAt, showDivider = d.description.isNotBlank())
                }
                if (d.description.isNotBlank()) {
                    WeCell(title = "说明", subtitle = d.description, showDivider = false)
                }
            }

            WeSpacer(16.dp)

            // ── 审批意见 ──────────────────────────────────
            WeSectionCaption("审批意见")
            WeCellGroup {
                OutlinedTextField(
                    value = opinion,
                    onValueChange = { opinion = it },
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 8.dp),
                    placeholder = { Text("输入审批意见（可选）") },
                    minLines = 2,
                    colors = androidx.compose.material3.OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = androidx.compose.ui.graphics.Color.Transparent,
                        unfocusedBorderColor = androidx.compose.ui.graphics.Color.Transparent,
                    ),
                )
            }

            WeSpacer(8.dp)
            Text(
                "复杂编辑请在电脑端处理",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 16.dp),
            )

            WeSpacer(16.dp)

            val canAct = d.status.contains("pending", ignoreCase = true) || d.status.contains("待")
            WeBlockButton(
                text = "通过",
                onClick = { confirmAction = "approve" },
                enabled = canAct,
            )
            WeSpacer(8.dp)
            WeBlockOutlinedButton(
                text = "驳回",
                onClick = { confirmAction = "reject" },
                enabled = canAct,
            )
        }
    }

    confirmAction?.let { action ->
        AlertDialog(
            onDismissRequest = { confirmAction = null },
            title = { Text(if (action == "approve") "确认通过" else "确认驳回") },
            text = { Text(if (action == "approve") "确定通过该审批？" else "确定驳回该审批？") },
            confirmButton = {
                TextButton({
                    if (action == "approve") vm.approve(id, opinion, onBack)
                    else vm.reject(id, opinion, onBack)
                    confirmAction = null
                }) { Text("确定") }
            },
            dismissButton = {
                TextButton({ confirmAction = null }) { Text("取消") }
            },
        )
    }
}
