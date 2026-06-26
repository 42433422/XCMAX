package com.xiuci.xcagi.mobile.feature.market

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Extension
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.xiuci.xcagi.mobile.core.model.ListItem
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileScaffold
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSectionCaption
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme

private val marketPaymentChannels =
        listOf(
                "mobile_h5" to "手机网页",
                "alipay" to "支付宝",
                "wechat_h5" to "微信支付",
        )

private fun marketPaymentChannelTitle(id: String): String =
        marketPaymentChannels.firstOrNull { it.first == id }?.second ?: "手机网页"

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MarketListScreen(
        vm: AppViewModel,
        onUse: (String) -> Unit,
        onBack: () -> Unit,
) {
    val items by vm.items.collectAsState()
    val loading by vm.listLoading.collectAsState()
    val error by vm.listError.collectAsState()
    val industries by vm.onboardingIndustries.collectAsState()
    val industryStatus by vm.industryBootstrapStatus.collectAsState()
    val paymentPlans by vm.paymentPlans.collectAsState()
    val paymentStatus by vm.paymentStatus.collectAsState()
    val uriHandler = LocalUriHandler.current
    var paymentChannel by remember { mutableStateOf("mobile_h5") }
    LaunchedEffect(Unit) { vm.loadMarket() }

    MobileScaffold(
            title = "MODstore",
            onBack = onBack,
            onRefresh = vm::loadMarket,
            loading = loading,
            error = error,
            empty = false,
            emptyMessage = "暂无 Mod",
            onRetry = vm::loadMarket,
    ) { _ ->
        LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(0.dp),
        ) {
            item { WeSectionCaption("行业初始化") }
            item {
                WeCellGroup {
                    if (industries.isEmpty()) {
                        WeCell(
                                title = "行业目录",
                                subtitle = industryStatus.ifBlank { "登录后自动同步可选行业" },
                                icon = Icons.Default.Extension,
                                iconTint = XcagiTheme.extra.brandBlue,
                                iconBg = MaterialTheme.colorScheme.primaryContainer,
                                showArrow = false,
                        )
                    } else {
                        industries.take(6).forEachIndexed { idx, item ->
                            WeCell(
                                    title = item.title,
                                    subtitle = item.subtitle.ifBlank { industryStatus.ifBlank { "装齐行业基础能力" } },
                                    icon = Icons.Default.Extension,
                                    iconTint = XcagiTheme.extra.brandBlue,
                                    iconBg = MaterialTheme.colorScheme.primaryContainer,
                                    showArrow = false,
                                    showDivider = idx < industries.take(6).lastIndex,
                                    trailing = {
                                        TextButton(onClick = { vm.bootstrapIndustry(item.id) }) {
                                            Text("装齐", color = XcagiTheme.extra.brandBlue)
                                        }
                                    },
                            )
                        }
                    }
                }
            }

            item { WeSectionCaption("模型服务") }
            item {
                WeCellGroup {
                    WeCell(
                            title = "手机充值渠道",
                            subtitle = "当前：${marketPaymentChannelTitle(paymentChannel)}",
                            icon = Icons.Default.Extension,
                            iconTint = XcagiTheme.extra.brandBlue,
                            iconBg = MaterialTheme.colorScheme.primaryContainer,
                            showArrow = false,
                    )
                    marketPaymentChannels.forEach { (id, title) ->
                        WeCell(
                                title = title,
                                subtitle = if (paymentChannel == id) "当前充值与购买渠道" else "切换到$title",
                                icon = Icons.Default.Extension,
                                iconTint = XcagiTheme.extra.brandBlue,
                                iconBg = MaterialTheme.colorScheme.primaryContainer,
                                showArrow = false,
                                trailing = {
                                    TextButton(onClick = { paymentChannel = id }) {
                                        Text(
                                                if (paymentChannel == id) "当前" else "选择",
                                                color = XcagiTheme.extra.brandBlue,
                                        )
                                    }
                                },
                        )
                    }
                    WeCell(
                            title = "钱包充值",
                            subtitle = paymentStatus.ifBlank { "用当前手机渠道充值 50 元" },
                            icon = Icons.Default.Extension,
                            iconTint = XcagiTheme.extra.brandBlue,
                            iconBg = MaterialTheme.colorScheme.primaryContainer,
                            showArrow = false,
                            trailing = {
                                TextButton(
                                        onClick = {
                                            vm.checkoutWalletRecharge("50", paymentChannel) { url ->
                                                uriHandler.openUri(url)
                                            }
                                        }
                                ) {
                                    Text("充50", color = XcagiTheme.extra.brandBlue)
                                }
                            },
                    )
                    if (paymentPlans.isEmpty()) {
                        WeCell(
                                title = "套餐与钱包",
                                subtitle = paymentStatus.ifBlank { "刷新后同步市场套餐与会员状态" },
                                icon = Icons.Default.Extension,
                                iconTint = XcagiTheme.extra.brandBlue,
                                iconBg = MaterialTheme.colorScheme.primaryContainer,
                                showArrow = false,
                                trailing = {
                                    TextButton(onClick = { vm.refreshPaymentAndWallet() }) {
                                        Text("刷新", color = XcagiTheme.extra.brandBlue)
                                    }
                                },
                        )
                    } else {
                        paymentPlans.take(4).forEachIndexed { idx, plan ->
                            WeCell(
                                    title = plan.title,
                                    subtitle = plan.subtitle.ifBlank { paymentStatus.ifBlank { "市场统一收银台" } },
                                    icon = Icons.Default.Extension,
                                    iconTint = XcagiTheme.extra.brandBlue,
                                    iconBg = MaterialTheme.colorScheme.primaryContainer,
                                    showArrow = false,
                                    showDivider = idx < paymentPlans.take(4).lastIndex,
                                    trailing = {
                                        TextButton(
                                                onClick = {
                                                    vm.checkoutPayment(plan.id, paymentChannel) { url ->
                                                        uriHandler.openUri(url)
                                                    }
                                                }
                                        ) {
                                            Text("购买", color = XcagiTheme.extra.brandBlue)
                                        }
                                    },
                            )
                        }
                    }
                }
            }

            item { WeSectionCaption("可用能力") }
            item {
                WeCellGroup {
                    if (items.isEmpty()) {
                        WeCell(
                                title = "暂无可用能力",
                                subtitle = "先装齐行业能力或刷新市场目录",
                                icon = Icons.Default.Extension,
                                iconTint = XcagiTheme.extra.brandBlue,
                                iconBg = MaterialTheme.colorScheme.primaryContainer,
                                showArrow = false,
                        )
                    }
                    items.forEachIndexed { idx, item ->
                        WeCell(
                                title = item.title,
                                subtitle = item.subtitle.ifBlank { "从企业端同步的能力包" },
                                icon = Icons.Default.Extension,
                                iconTint = XcagiTheme.extra.brandBlue,
                                iconBg = MaterialTheme.colorScheme.primaryContainer,
                                showArrow = false,
                                showDivider = idx < items.lastIndex,
                                trailing = {
                                    TextButton(onClick = { onUse(item.id) }) {
                                        Text("使用", color = XcagiTheme.extra.brandBlue)
                                    }
                                },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun MarketModCard(item: ListItem, onUse: () -> Unit) {
    Row(
            Modifier.fillMaxWidth()
                    .clip(MaterialTheme.shapes.medium)
                    .background(MaterialTheme.colorScheme.surface)
                    .padding(14.dp),
            verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
                Modifier.size(44.dp)
                        .clip(RoundedCornerShape(8.dp))
                        .background(MaterialTheme.colorScheme.secondaryContainer),
                contentAlignment = Alignment.Center,
        ) {
            Icon(
                    Icons.Default.Extension,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.secondary
            )
        }
        Column(
                Modifier.weight(1f).padding(horizontal = 12.dp),
        ) {
            Text(
                    item.title,
                    fontSize = 16.sp,
                    fontWeight = FontWeight.Medium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
            )
            Text(
                    item.subtitle.ifBlank { "浏览并安装行业 Mod" },
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(top = 2.dp),
            )
        }
        Button(onClick = onUse, shape = MaterialTheme.shapes.medium) { Text("使用") }
    }
}
