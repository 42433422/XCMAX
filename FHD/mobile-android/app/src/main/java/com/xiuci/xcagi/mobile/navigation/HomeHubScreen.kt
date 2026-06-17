package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
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
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.Extension
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.R
import com.xiuci.xcagi.mobile.core.model.ListItem
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.theme.Elevation
import com.xiuci.xcagi.mobile.ui.theme.Spacing
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun HomeHubScreen(
    vm: AppViewModel,
    onChat: () -> Unit,
    onConnectPc: () -> Unit,
    onModClick: (String) -> Unit,
) {
    val hub by vm.homeHub.collectAsState()
    val serverLabel by vm.serverModeLabel.collectAsState()
    val fhdHost by vm.fhdHost.collectAsState()

    LaunchedEffect(Unit) { vm.loadHomeHub() }

    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = {
                Text(
                    "首页",
                    style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Medium),
                )
            },
            colors = TopAppBarDefaults.topAppBarColors(
                containerColor = MaterialTheme.colorScheme.surface,
                titleContentColor = MaterialTheme.colorScheme.onSurface,
            ),
        )
        PullToRefreshBox(
            isRefreshing = hub.loading,
            onRefresh = { vm.loadHomeHub() },
            modifier = Modifier.weight(1f),
        ) {
            if (hub.loading && hub.mods.isEmpty()) {
                Column(
                    Modifier.fillMaxSize(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Center,
                ) {
                    CircularProgressIndicator()
                }
            } else {
                Column(
                    Modifier
                        .fillMaxSize()
                        .verticalScroll(rememberScrollState())
                        .padding(horizontal = Spacing.lg, vertical = Spacing.sm),
                    verticalArrangement = Arrangement.spacedBy(Spacing.md),
                ) {
                    // ── 电脑状态卡片（白底，飞书风格） ──
                    Card(
                        shape = MaterialTheme.shapes.medium,
                        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                        elevation = CardDefaults.cardElevation(defaultElevation = Elevation.none),
                    ) {
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .clickable(onClick = onConnectPc)
                                .padding(Spacing.lg),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Box(
                                Modifier
                                    .size(40.dp)
                                    .clip(MaterialTheme.shapes.small)
                                    .background(MaterialTheme.colorScheme.primaryContainer),
                                contentAlignment = Alignment.Center,
                            ) {
                                Icon(
                                    Icons.Default.Computer,
                                    contentDescription = null,
                                    modifier = Modifier.size(22.dp),
                                    tint = MaterialTheme.colorScheme.primary,
                                )
                            }
                            Spacer(Modifier.height(Spacing.md))
                            Column(Modifier.weight(1f).padding(start = Spacing.md)) {
                                Text(
                                    "我的电脑",
                                    style = MaterialTheme.typography.bodyLarge.copy(fontWeight = FontWeight.Medium),
                                    color = MaterialTheme.colorScheme.onSurface,
                                )
                                Spacer(Modifier.height(2.dp))
                                Text(
                                    if (fhdHost.isBlank()) "未连接电脑 · 使用远程能力" else "主机：$fhdHost",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.outline,
                                )
                                Text(
                                    serverLabel,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.outline,
                                )
                            }
                            Box(
                                Modifier
                                    .size(Spacing.sm)
                                    .clip(MaterialTheme.shapes.extraSmall)
                                    .background(if (hub.pcOnline) XcagiTheme.extra.success else MaterialTheme.colorScheme.outline.copy(alpha = 0.5f)),
                            )
                        }
                    }

                    // ── 操作按钮行 ──
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
                    ) {
                        OutlinedButton(
                            onClick = onConnectPc,
                            modifier = Modifier.weight(1f),
                            shape = MaterialTheme.shapes.small,
                        ) {
                            Icon(Icons.Default.Computer, null, Modifier.padding(end = Spacing.xs).size(16.dp))
                            Text("连接电脑")
                        }
                        Button(
                            onClick = { vm.runSyncNow() },
                            enabled = hub.pcOnline && !hub.syncing,
                            modifier = Modifier.weight(1f),
                            shape = MaterialTheme.shapes.small,
                            colors = ButtonDefaults.buttonColors(
                                containerColor = XcagiTheme.extra.brandBlue,
                            ),
                            elevation = ButtonDefaults.buttonElevation(defaultElevation = Elevation.none),
                        ) {
                            Icon(Icons.Default.Sync, null, Modifier.padding(end = Spacing.xs).size(16.dp))
                            Text(if (hub.syncing) "同步中…" else "立即同步")
                        }
                    }

                    // ── 快捷入口（宫格风格） ──
                    Text(
                        "快捷入口",
                        style = MaterialTheme.typography.labelMedium.copy(fontWeight = FontWeight.Medium),
                        color = MaterialTheme.colorScheme.outline,
                    )
                    Row(Modifier.fillMaxWidth()) {
                        QuickEntryCard(
                            icon = Icons.AutoMirrored.Filled.Chat,
                            label = "AI 对话",
                            iconBg = MaterialTheme.colorScheme.secondaryContainer,
                            iconFg = MaterialTheme.colorScheme.secondary,
                            modifier = Modifier.fillMaxWidth(),
                            onClick = onChat,
                        )
                    }

                    // ── Mod 列表 ──
                    Text(
                        if (hub.modsFromCloud) "企业同步能力" else stringResource(R.string.app_name) + " · 已安装 Mod",
                        style = MaterialTheme.typography.labelMedium.copy(fontWeight = FontWeight.Medium),
                        color = MaterialTheme.colorScheme.outline,
                    )
                    if (hub.mods.isEmpty()) {
                        Text(
                            "连接电脑或登录企业账号后，可同步已安装的智能伙伴和能力模块。",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.outline,
                        )
                    } else {
                        hub.mods.chunked(2).forEach { row ->
                            Row(
                                Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
                            ) {
                                row.forEach { mod ->
                                    ModTile(
                                        mod,
                                        Modifier.weight(1f),
                                    ) { onModClick(mod.id) }
                                }
                                if (row.size == 1) {
                                    Spacer(Modifier.weight(1f))
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun QuickEntryCard(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    iconBg: Color,
    iconFg: Color,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    Card(
        modifier.clickable(onClick = onClick),
        shape = MaterialTheme.shapes.medium,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = Elevation.none),
    ) {
        Column(
            Modifier.padding(14.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Box(
                Modifier
                    .size(40.dp)
                    .clip(MaterialTheme.shapes.small)
                    .background(iconBg),
                contentAlignment = Alignment.Center,
            ) {
                Icon(icon, contentDescription = null, tint = iconFg, modifier = Modifier.size(22.dp))
            }
            Spacer(Modifier.height(Spacing.sm))
            Text(label, style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium), color = MaterialTheme.colorScheme.onSurface)
        }
    }
}

@Composable
private fun ModTile(mod: ListItem, modifier: Modifier = Modifier, onClick: () -> Unit) {
    Card(
        modifier.clickable(onClick = onClick),
        shape = MaterialTheme.shapes.medium,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = Elevation.none),
    ) {
        Row(
            Modifier.padding(Spacing.md),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                Modifier
                    .size(32.dp)
                    .clip(MaterialTheme.shapes.small)
                    .background(MaterialTheme.colorScheme.primaryContainer),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    Icons.Default.Extension,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(18.dp),
                )
            }
            Spacer(Modifier.height(Spacing.sm))
            Text(mod.title, style = MaterialTheme.typography.bodyMedium, maxLines = 2, color = MaterialTheme.colorScheme.onSurface)
        }
    }
}
