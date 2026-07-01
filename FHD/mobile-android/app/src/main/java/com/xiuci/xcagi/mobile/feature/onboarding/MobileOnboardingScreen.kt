package com.xiuci.xcagi.mobile.feature.onboarding

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.CloudDone
import androidx.compose.material.icons.filled.Extension
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.core.model.ListItem
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileScaffold

private val stepTitles = listOf("认识XC", "行业定型", "补基础线")

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MobileOnboardingScreen(
        vm: AppViewModel,
        onFinish: () -> Unit,
        onBack: () -> Unit,
) {
    val industries by vm.onboardingIndustries.collectAsState()
    val industryStatus by vm.industryBootstrapStatus.collectAsState()
    var step by remember { mutableIntStateOf(0) }
    var selectedIndustryId by remember { mutableStateOf("") }

    LaunchedEffect(Unit) {
        vm.loadMobileOnboarding()
    }
    LaunchedEffect(industries) {
        if (selectedIndustryId.isBlank() && industries.isNotEmpty()) {
            selectedIndustryId = industries.first().id
        }
    }

    val effectiveIndustryId = selectedIndustryId.ifBlank { industries.firstOrNull()?.id ?: "通用" }
    val selectedIndustry = industries.firstOrNull { it.id == effectiveIndustryId }
    val selectedIndustryTitle = selectedIndustry?.title ?: effectiveIndustryId

    MobileScaffold(
            title = "启动配置",
            onBack = onBack,
            onRefresh = {
                vm.loadMobileOnboarding()
            },
    ) { _ ->
        Column(
                modifier =
                        Modifier
                                .fillMaxSize()
                                .verticalScroll(rememberScrollState())
                                .padding(horizontal = 20.dp, vertical = 16.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            StepRail(current = step)
            when (step) {
                0 ->
                        IntroStep(
                                onNext = { step = 1 },
                                onFinish = onFinish,
                        )
                1 ->
                        IndustryStep(
                                industries = industries,
                                selectedIndustryId = effectiveIndustryId,
                                onSelect = { selectedIndustryId = it },
                                onNext = {
                                    vm.selectOnboardingIndustry(effectiveIndustryId) { step = 2 }
                                },
                                onReload = vm::loadMobileOnboarding,
                        )
                2 ->
                        CapabilityStep(
                                industryTitle = selectedIndustryTitle,
                                status = industryStatus,
                                onInstall = { vm.bootstrapIndustry(effectiveIndustryId) },
                                onNext = onFinish,
                                onReload = vm::loadMobileOnboarding,
                        )
            }
        }
    }
}

@Composable
private fun StepRail(current: Int) {
    Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        stepTitles.forEachIndexed { index, title ->
            Surface(
                    modifier = Modifier.weight(1f),
                    shape = RoundedCornerShape(8.dp),
                    color =
                            if (index <= current) MaterialTheme.colorScheme.primaryContainer
                            else MaterialTheme.colorScheme.surfaceVariant,
            ) {
                Text(
                        title,
                        modifier = Modifier.padding(vertical = 8.dp),
                        style = MaterialTheme.typography.labelMedium,
                        color =
                                if (index <= current) MaterialTheme.colorScheme.onPrimaryContainer
                                else MaterialTheme.colorScheme.onSurfaceVariant,
                        fontWeight = if (index == current) FontWeight.SemiBold else FontWeight.Normal,
                        maxLines = 1,
                )
            }
        }
    }
}

@Composable
private fun IntroStep(
        onNext: () -> Unit,
        onFinish: () -> Unit,
) {
    FlowBlock(
            icon = Icons.Default.CloudDone,
            title = "移动端将独立连接 XCAGI 宿主",
            body = "注册或登录后先同步账号、市场令牌和企业会话，再按行业装齐基础能力。",
    )
    Button(onClick = onNext, modifier = Modifier.fillMaxWidth()) { Text("开始行业配置") }
    OutlinedButton(onClick = onFinish, modifier = Modifier.fillMaxWidth()) { Text("稍后进入应用") }
}

@Composable
private fun IndustryStep(
        industries: List<ListItem>,
        selectedIndustryId: String,
        onSelect: (String) -> Unit,
        onNext: () -> Unit,
        onReload: () -> Unit,
) {
    FlowBlock(
            icon = Icons.Default.Extension,
            title = "选择行业",
            body = "这里使用后端行业目录，和桌面端的行业筛选来源一致。",
    )
    if (industries.isEmpty()) {
        StatusBlock("行业目录暂未同步，刷新后继续。")
        OutlinedButton(onClick = onReload, modifier = Modifier.fillMaxWidth()) { Text("刷新行业目录") }
    } else {
        industries.take(8).forEach { item ->
            SelectableRow(
                    title = item.title,
                    subtitle = item.subtitle.ifBlank { "装齐 ${item.title} 基础能力" },
                    selected = item.id == selectedIndustryId,
                    onClick = { onSelect(item.id) },
            )
        }
    }
    Button(onClick = onNext, modifier = Modifier.fillMaxWidth(), enabled = selectedIndustryId.isNotBlank()) {
        Text("继续")
    }
}

@Composable
private fun CapabilityStep(
        industryTitle: String,
        status: String,
        onInstall: () -> Unit,
        onNext: () -> Unit,
        onReload: () -> Unit,
) {
    FlowBlock(
            icon = Icons.Default.CheckCircle,
            title = "装齐 $industryTitle 基础包",
            body = "移动端直接调用市场安装接口，补齐宿主基础包和行业种子能力。",
    )
    StatusBlock(status.ifBlank { "等待检查行业基础能力状态" })
    Button(onClick = onInstall, modifier = Modifier.fillMaxWidth()) { Text("装齐基础包") }
    OutlinedButton(onClick = onReload, modifier = Modifier.fillMaxWidth()) { Text("重新检查") }
    Button(onClick = onNext, modifier = Modifier.fillMaxWidth()) { Text("进入应用") }
}

@Composable
private fun FlowBlock(
        icon: ImageVector,
        title: String,
        body: String,
) {
    Surface(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(8.dp),
            color = MaterialTheme.colorScheme.surfaceVariant,
    ) {
        Row(
                modifier = Modifier.padding(14.dp),
                verticalAlignment = Alignment.Top,
                horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Icon(icon, contentDescription = null, modifier = Modifier.size(24.dp))
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                Text(body, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun SelectableRow(
        title: String,
        subtitle: String,
        selected: Boolean,
        onClick: () -> Unit,
) {
    Surface(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(8.dp),
            color =
                    if (selected) MaterialTheme.colorScheme.primaryContainer
                    else MaterialTheme.colorScheme.surfaceVariant,
            onClick = onClick,
    ) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(
                    title,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
            )
            Text(
                    subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun StatusBlock(text: String) {
    Surface(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(8.dp),
            color = MaterialTheme.colorScheme.surfaceVariant,
    ) {
        Column(Modifier.padding(14.dp)) {
            Text(text, style = MaterialTheme.typography.bodyMedium)
            Spacer(Modifier.height(2.dp))
        }
    }
}
