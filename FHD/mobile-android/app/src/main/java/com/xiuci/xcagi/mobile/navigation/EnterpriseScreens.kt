package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.clickable
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.core.model.ListItem
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileListSkeleton
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileScaffold
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeModeCapsule
import com.xiuci.xcagi.mobile.ui.components.mobile.WeModeOption
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSectionCaption
import com.xiuci.xcagi.mobile.ui.theme.Spacing

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EnterpriseListScreen(
    title: String,
    vm: AppViewModel,
    load: () -> Unit,
    onItemClick: ((String) -> Unit)? = null,
) {
    val items by vm.items.collectAsState()
    val loading by vm.listLoading.collectAsState()
    val error by vm.listError.collectAsState()

    LaunchedEffect(title) { load() }

    EnterpriseScaffold(
        title = title,
        onRefresh = load,
        loading = loading,
        error = error,
        isEmpty = items.isEmpty(),
        onRetry = load,
    ) {
        WeCellGroup {
            items.forEachIndexed { idx, item ->
                WeCell(
                    title = item.title,
                    subtitle = item.subtitle,
                    showArrow = onItemClick != null,
                    showDivider = idx < items.lastIndex,
                    onClick = onItemClick?.let { cb -> { cb(item.id) } },
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ErpTabListScreen(
    tabIndex: Int,
    vm: AppViewModel,
    onBack: () -> Unit,
) {
    val titles = listOf("客户", "发货", "库存")
    val title = titles.getOrElse(tabIndex) { "业务" }

    fun reload() {
        when (tabIndex) {
            0 -> vm.loadCustomers()
            1 -> vm.loadShipments()
            else -> vm.loadInventory()
        }
    }

    LaunchedEffect(tabIndex) { reload() }

    val items by vm.items.collectAsState()
    val loading by vm.listLoading.collectAsState()
    val error by vm.listError.collectAsState()

    MobileScaffold(
        title = title,
        onBack = onBack,
        onRefresh = ::reload,
        loading = loading,
        error = error,
        empty = items.isEmpty(),
        emptyMessage = "暂无${title}数据",
        onRetry = ::reload,
    ) { _ ->
        WeCellGroup {
            items.forEachIndexed { idx, item ->
                WeCell(
                    title = item.title,
                    subtitle = item.subtitle,
                    showDivider = idx < items.lastIndex,
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ErpScreen(vm: AppViewModel) {
    var tab by remember { mutableIntStateOf(0) }
    val titles = listOf("客户", "发货", "库存")
    val title = titles[tab]
    val modes = remember {
        listOf(
            WeModeOption("0", "客户"),
            WeModeOption("1", "发货"),
            WeModeOption("2", "库存"),
        )
    }

    fun reload() {
        when (tab) {
            0 -> vm.loadCustomers()
            1 -> vm.loadShipments()
            else -> vm.loadInventory()
        }
    }

    LaunchedEffect(tab) { reload() }

    val items by vm.items.collectAsState()
    val loading by vm.listLoading.collectAsState()
    val error by vm.listError.collectAsState()

    MobileScaffold(
        title = "业务",
        onRefresh = ::reload,
        loading = loading && items.isNotEmpty(),
        empty = false,
        onRetry = ::reload,
    ) {
        Column(Modifier.fillMaxSize()) {
            Box(
                Modifier
                    .fillMaxWidth()
                    .background(MaterialTheme.colorScheme.background)
                    .padding(horizontal = Spacing.lg, vertical = Spacing.sm),
                contentAlignment = Alignment.Center,
            ) {
                WeModeCapsule(
                    options = modes,
                    selectedId = tab.toString(),
                    onSelect = { tab = it.toIntOrNull() ?: 0 },
                )
            }
            Box(Modifier.fillMaxSize()) {
                when {
                    loading && items.isEmpty() -> MobileListSkeleton()
                    error != null && items.isEmpty() -> ListErrorState(error!!, ::reload)
                    items.isEmpty() && !loading -> ListEmptyState(title, ::reload)
                    else -> LazyColumn(
                        modifier = Modifier.fillMaxSize(),
                        contentPadding = PaddingValues(vertical = 12.dp),
                        verticalArrangement = Arrangement.spacedBy(0.dp),
                    ) {
                        item { WeSectionCaption("${title}记录") }
                        item {
                            WeCellGroup {
                                items.forEachIndexed { idx, item ->
                                    WeCell(
                                        title = item.title,
                                        subtitle = item.subtitle,
                                        showArrow = false,
                                        showDivider = idx < items.lastIndex,
                                    )
                                }
                            }
                        }
                    }
                }
                if (loading && items.isNotEmpty()) {
                    CircularProgressIndicator(
                        Modifier
                            .align(Alignment.TopCenter)
                            .padding(8.dp),
                    )
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun EnterpriseScaffold(
    title: String,
    onRefresh: () -> Unit,
    loading: Boolean,
    error: String?,
    isEmpty: Boolean,
    onRetry: () -> Unit,
    content: @Composable () -> Unit,
) {
    MobileScaffold(
        title = title,
        onRefresh = onRefresh,
        loading = loading,
        error = error,
        empty = isEmpty,
        emptyMessage = "暂无${title}数据",
        onRetry = onRetry,
    ) {
        content()
    }
}

@Composable
private fun EnterpriseListCard(item: ListItem, onClick: ((String) -> Unit)?) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .then(
                if (onClick != null) Modifier.clickable { onClick(item.id) } else Modifier,
            ),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Column(Modifier.padding(14.dp)) {
            Text(item.title, style = MaterialTheme.typography.titleMedium)
            if (item.subtitle.isNotBlank()) {
                Text(
                    item.subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }
        }
    }
}

@Composable
private fun ListSkeleton() {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(6) {
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = MaterialTheme.shapes.medium,
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                ),
            ) {
                Column(Modifier.padding(14.dp)) {
                    Box(
                        Modifier
                            .fillMaxWidth(0.55f)
                            .height(14.dp)
                            .padding(bottom = 8.dp),
                    )
                    Box(
                        Modifier
                            .fillMaxWidth(0.35f)
                            .height(12.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun ListEmptyState(title: String, onRetry: () -> Unit) {
    Column(
        Modifier
            .fillMaxSize()
            .padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text("暂无${title}数据", style = MaterialTheme.typography.titleMedium)
        Text(
            "下拉刷新或连接电脑后重试。",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(top = 8.dp, bottom = 16.dp),
        )
        Button(onClick = onRetry) { Text("刷新") }
    }
}

@Composable
private fun ListErrorState(message: String, onRetry: () -> Unit) {
    Column(
        Modifier
            .fillMaxSize()
            .padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text("加载失败", style = MaterialTheme.typography.titleMedium)
        Text(
            message,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.error,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(top = 8.dp, bottom = 16.dp),
        )
        Button(onClick = onRetry) { Text("重试") }
    }
}
