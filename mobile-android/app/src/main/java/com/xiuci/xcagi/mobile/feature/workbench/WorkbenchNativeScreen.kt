package com.xiuci.xcagi.mobile.feature.workbench

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.core.model.ListItem
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileGroupedList
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileListDivider
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileListRow
import com.xiuci.xcagi.mobile.ui.components.mobile.MobilePageHeader
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileTokens

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkbenchNativeScreen(
    vm: AppViewModel,
    onModClick: (String) -> Unit,
    onOpenMarket: () -> Unit,
) {
    val catalog by vm.workbenchCatalog.collectAsState()
    var query by remember { mutableStateOf("") }

    LaunchedEffect(Unit) {
        vm.refreshMarketTokens()
        vm.loadWorkbenchCatalog()
    }

    val filtered =
        remember(catalog.mods, query) {
            val q = query.trim()
            if (q.isBlank()) {
                catalog.mods
            } else {
                catalog.mods.filter { mod ->
                    mod.title.contains(q, ignoreCase = true) ||
                        mod.id.contains(q, ignoreCase = true) ||
                        mod.subtitle.contains(q, ignoreCase = true)
                }
            }
        }

    Column(
        Modifier
            .fillMaxSize()
            .background(MobileTokens.pageBackground()),
    ) {
        MobilePageHeader(title = "能力")
        PullToRefreshBox(
            isRefreshing = catalog.loading,
            onRefresh = { vm.loadWorkbenchCatalog() },
            modifier = Modifier.weight(1f),
        ) {
            Column(
                Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = MobileTokens.horizontalPagePadding, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                Text(
                    "云端 MOD 与 AI 能力目录。完整对话请使用「对话」Tab；复杂配置请在电脑端操作。",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                OutlinedTextField(
                    value = query,
                    onValueChange = { query = it },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    placeholder = { Text("搜索 Mod 名称或 ID") },
                )
                catalog.error?.let { err ->
                    Column(
                        Modifier.fillMaxWidth(),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Text(err, color = MaterialTheme.colorScheme.error)
                        Button(onClick = { vm.loadWorkbenchCatalog() }) {
                            Text("重试")
                        }
                    }
                }
                if (catalog.loading && catalog.mods.isEmpty() && catalog.error == null) {
                    Column(
                        Modifier
                            .fillMaxWidth()
                            .padding(vertical = 32.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        CircularProgressIndicator()
                    }
                } else {
                    MobileGroupedList {
                        MobileListRow(
                            title = "AI 市场",
                            subtitle = "浏览更多可安装的 Mod 与员工包",
                            showChevron = true,
                            onClick = onOpenMarket,
                        )
                        if (filtered.isNotEmpty()) {
                            MobileListDivider()
                        }
                        filtered.forEachIndexed { index, mod ->
                            if (index > 0) {
                                MobileListDivider()
                            }
                            CatalogModRow(mod = mod, onClick = { onModClick(mod.id) })
                        }
                    }
                    if (!catalog.loading && filtered.isEmpty() && catalog.error == null) {
                        Text(
                            if (query.isNotBlank()) "没有匹配的 Mod" else "暂无云端 Mod，请稍后下拉刷新",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(top = 8.dp),
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun CatalogModRow(mod: ListItem, onClick: () -> Unit) {
    MobileListRow(
        title = mod.title,
        subtitle = mod.subtitle.ifBlank { mod.id },
        showChevron = true,
        onClick = onClick,
    )
}
