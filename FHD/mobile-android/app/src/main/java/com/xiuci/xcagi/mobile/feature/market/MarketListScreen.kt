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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
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
    LaunchedEffect(Unit) { vm.loadMarket() }

    MobileScaffold(
            title = "MODstore",
            onBack = onBack,
            onRefresh = vm::loadMarket,
            loading = loading,
            error = error,
            empty = items.isEmpty(),
            emptyMessage = "暂无 Mod",
            onRetry = vm::loadMarket,
    ) { _ ->
        LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(0.dp),
        ) {
            item { WeSectionCaption("可用能力") }
            item {
                WeCellGroup {
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
