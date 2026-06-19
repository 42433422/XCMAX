package com.xiuci.xcagi.mobile.feature.list

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileScaffold
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSectionCaption

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ListScreen(
        title: String,
        vm: AppViewModel,
        load: () -> Unit,
        onClick: ((String) -> Unit)?,
        onBack: (() -> Unit)? = null,
) {
    val items by vm.items.collectAsState()
    val loading by vm.listLoading.collectAsState()
    val error by vm.listError.collectAsState()
    LaunchedEffect(Unit) { load() }

    MobileScaffold(
            title = title,
            onBack = onBack,
            onRefresh = load,
            loading = loading,
            error = error,
            empty = items.isEmpty(),
            emptyMessage = "暂无数据",
            onRetry = load,
    ) { _ ->
        LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(0.dp),
        ) {
            item { WeSectionCaption(title) }
            item {
                WeCellGroup {
                    items.forEachIndexed { idx, item ->
                        WeCell(
                                title = item.title,
                                subtitle = item.subtitle,
                                showArrow = onClick != null,
                                showDivider = idx < items.lastIndex,
                                onClick = onClick?.let { cb -> { cb(item.id) } },
                        )
                    }
                }
            }
        }
    }
}
