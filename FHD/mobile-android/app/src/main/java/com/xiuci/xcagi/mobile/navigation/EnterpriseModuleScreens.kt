package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.WeTopBar
import com.xiuci.xcagi.mobile.ui.theme.Spacing

@Composable
fun SmartAnalysisScreen(
    vm: AppViewModel,
    onBack: () -> Unit,
    onOpenChat: (String) -> Unit,
) {
    EnterpriseModuleScreen(
        title = "智慧分析",
        status = "手机端已收敛为会话入口",
        actionText = "回到消息",
        onBack = onBack,
        onAction = { onOpenChat("analysis") },
    )
}

@Composable
fun AiOpenScreen(
    vm: AppViewModel,
    onBack: () -> Unit,
) {
    EnterpriseModuleScreen(
        title = "开放智控",
        status = "请在电脑端企业模块中使用",
        actionText = "返回",
        onBack = onBack,
        onAction = onBack,
    )
}

@Composable
fun BrainScreen(
    vm: AppViewModel,
    onBack: () -> Unit,
    onOpenMod: (String) -> Unit,
) {
    EnterpriseModuleScreen(
        title = "智脑集成",
        status = "员工编排由企业端模块承载",
        actionText = "打开能力库",
        onBack = onBack,
        onAction = { onOpenMod("xcagi-planner-bridge") },
    )
}

@Composable
fun ModStoreScreen(
    vm: AppViewModel,
    onBack: () -> Unit,
    onOpenMod: (String) -> Unit,
) {
    EnterpriseModuleScreen(
        title = "能力库",
        status = "安装与授权由企业端和管理端统一管理",
        actionText = "查看企业模块",
        onBack = onBack,
        onAction = { onOpenMod("xcagi-planner-bridge") },
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun EnterpriseModuleScreen(
    title: String,
    status: String,
    actionText: String,
    onBack: () -> Unit,
    onAction: () -> Unit,
) {
    Scaffold(
        topBar = { WeTopBar(title = title, onBack = onBack) },
        containerColor = MaterialTheme.colorScheme.background,
    ) { padding ->
        Column(
            modifier =
                Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .background(MaterialTheme.colorScheme.background)
                    .padding(horizontal = Spacing.lg, vertical = 36.dp),
            verticalArrangement = Arrangement.Center,
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Spacer(Modifier.height(10.dp))
            Text(
                text = status,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(22.dp))
            OutlinedButton(
                onClick = onAction,
                modifier = Modifier.fillMaxWidth(),
                colors =
                    ButtonDefaults.outlinedButtonColors(
                        contentColor = MaterialTheme.colorScheme.primary,
                    ),
            ) {
                Text(actionText)
                Icon(Icons.AutoMirrored.Filled.ArrowForward, contentDescription = null)
            }
        }
    }
}
