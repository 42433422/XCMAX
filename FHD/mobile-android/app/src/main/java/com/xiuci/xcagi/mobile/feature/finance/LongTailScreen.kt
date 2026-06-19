package com.xiuci.xcagi.mobile.feature.finance

import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.filled.Analytics
import androidx.compose.material.icons.filled.LocalPrintshop
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeScreen
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSectionCaption
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme

@Composable
fun LongTailScreen(vm: AppViewModel) {
    val detail by vm.detailJson.collectAsState()
    LaunchedEffect(Unit) { vm.loadFinance() }

    WeScreen(title = "财务摘要") {
        WeSectionCaption("概览")
        WeCellGroup {
            WeCell(
                    title = if (detail.isBlank()) "暂无财务数据" else "财务看板已同步",
                    subtitle = financePreview(detail),
                    icon = Icons.Default.Analytics,
                    iconTint = XcagiTheme.extra.brandBlue,
                    iconBg = MaterialTheme.colorScheme.primaryContainer,
                    showArrow = false,
                    showDivider = false,
            )
        }
        Spacer(Modifier.height(16.dp))
        WeSectionCaption("操作")
        WeCellGroup {
            WeCell(
                    title = "凭证与收支",
                    subtitle = "查看应收、应付与交易记录",
                    icon = Icons.AutoMirrored.Filled.ReceiptLong,
                    iconTint = MaterialTheme.colorScheme.secondary,
                    iconBg = MaterialTheme.colorScheme.secondaryContainer,
                    showArrow = true,
                    showDivider = true,
                    onClick = { vm.snack("请在电脑端打开完整财务看板") },
            )
            WeCell(
                    title = "标签打印",
                    subtitle = "打印商品标签和条码模板",
                    icon = Icons.Default.LocalPrintshop,
                    iconTint = XcagiTheme.extra.warning,
                    iconBg = XcagiTheme.extra.warning.copy(alpha = 0.12f),
                    showArrow = true,
                    showDivider = false,
                    onClick = { vm.snack("请在电脑端完成标签打印") },
            )
        }
    }
}

private fun financePreview(raw: String): String {
    if (raw.isBlank()) return "连接企业后端后显示收入、成本、毛利与应付摘要"
    return raw
            .replace("{", "")
            .replace("}", "")
            .replace("success=true,", "")
            .replace("data=", "")
            .split(",")
            .map { it.trim() }
            .filter { it.isNotBlank() }
            .take(3)
            .joinToString(" · ")
            .take(120)
}
