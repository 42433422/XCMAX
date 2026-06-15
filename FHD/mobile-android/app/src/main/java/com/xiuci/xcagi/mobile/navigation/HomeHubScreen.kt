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
import androidx.compose.material.icons.filled.Chat
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.Dashboard
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
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileTokens

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun HomeHubScreen(
    vm: AppViewModel,
    onChat: () -> Unit,
    onWorkbench: () -> Unit,
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
                containerColor = Color.White,
                titleContentColor = MobileTokens.textPrimary,
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
                        .padding(horizontal = MobileTokens.pageHorizontal, vertical = 8.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    // ── 电脑状态卡片（白底，飞书风格） ──
                    Card(
                        shape = MobileTokens.cornerCard,
                        colors = CardDefaults.cardColors(containerColor = Color.White),
                        elevation = CardDefaults.cardElevation(defaultElevation = 0.dp),
                    ) {
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .clickable(onClick = onConnectPc)
                                .padding(16.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Box(
                                Modifier
                                    .size(40.dp)
                                    .clip(RoundedCornerShape(8.dp))
                                    .background(MobileTokens.iconBgBlue),
                                contentAlignment = Alignment.Center,
                            ) {
                                Icon(
                                    Icons.Default.Computer,
                                    contentDescription = null,
                                    modifier = Modifier.size(22.dp),
                                    tint = MobileTokens.iconFgBlue,
                                )
                            }
                            Spacer(Modifier.height(12.dp))
                            Column(Modifier.weight(1f).padding(start = 12.dp)) {
                                Text(
                                    "我的电脑",
                                    style = MaterialTheme.typography.bodyLarge.copy(fontWeight = FontWeight.Medium),
                                    color = MobileTokens.textPrimary,
                                )
                                Spacer(Modifier.height(2.dp))
                                Text(
                                    if (fhdHost.isBlank()) "未连接 · 可使用云端能力" else "主机：$fhdHost",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MobileTokens.textTertiary,
                                )
                                Text(
                                    serverLabel,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MobileTokens.textTertiary,
                                )
                            }
                            Box(
                                Modifier
                                    .size(8.dp)
                                    .clip(RoundedCornerShape(4.dp))
                                    .background(if (hub.pcOnline) MobileTokens.successGreen else MobileTokens.textDisabled),
                            )
                        }
                    }

                    // ── 操作按钮行 ──
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        OutlinedButton(
                            onClick = onConnectPc,
                            modifier = Modifier.weight(1f),
                            shape = MobileTokens.cornerCardSmall,
                        ) {
                            Icon(Icons.Default.Computer, null, Modifier.padding(end = 4.dp).size(16.dp))
                            Text("连接电脑")
                        }
                        Button(
                            onClick = { vm.runSyncNow() },
                            enabled = hub.pcOnline && !hub.syncing,
                            modifier = Modifier.weight(1f),
                            shape = MobileTokens.cornerCardSmall,
                            colors = ButtonDefaults.buttonColors(
                                containerColor = MobileTokens.brandBlue,
                            ),
                            elevation = ButtonDefaults.buttonElevation(defaultElevation = 0.dp),
                        ) {
                            Icon(Icons.Default.Sync, null, Modifier.padding(end = 4.dp).size(16.dp))
                            Text(if (hub.syncing) "同步中…" else "立即同步")
                        }
                    }

                    // ── 快捷入口（宫格风格） ──
                    Text(
                        "快捷入口",
                        style = MaterialTheme.typography.labelMedium.copy(fontWeight = FontWeight.Medium),
                        color = MobileTokens.textTertiary,
                    )
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        QuickEntryCard(
                            icon = Icons.Default.Chat,
                            label = "AI 对话",
                            iconBg = MobileTokens.iconBgGreen,
                            iconFg = MobileTokens.iconFgGreen,
                            modifier = Modifier.weight(1f),
                            onClick = onChat,
                        )
                        QuickEntryCard(
                            icon = Icons.Default.Dashboard,
                            label = "工作台",
                            iconBg = MobileTokens.iconBgBlue,
                            iconFg = MobileTokens.iconFgBlue,
                            modifier = Modifier.weight(1f),
                            onClick = onWorkbench,
                        )
                    }

                    // ── Mod 列表 ──
                    Text(
                        if (hub.modsFromCloud) "MODstore 推荐" else stringResource(R.string.app_name) + " · 已安装 Mod",
                        style = MaterialTheme.typography.labelMedium.copy(fontWeight = FontWeight.Medium),
                        color = MobileTokens.textTertiary,
                    )
                    if (hub.mods.isEmpty()) {
                        Text(
                            "连接电脑后可查看本机 Mod；已登录云端账号时也可在工作台浏览全部能力。",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MobileTokens.textTertiary,
                        )
                    } else {
                        hub.mods.chunked(2).forEach { row ->
                            Row(
                                Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(8.dp),
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
        shape = MobileTokens.cornerCard,
        colors = CardDefaults.cardColors(containerColor = Color.White),
        elevation = CardDefaults.cardElevation(defaultElevation = 0.dp),
    ) {
        Column(
            Modifier.padding(14.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Box(
                Modifier
                    .size(40.dp)
                    .clip(RoundedCornerShape(8.dp))
                    .background(iconBg),
                contentAlignment = Alignment.Center,
            ) {
                Icon(icon, contentDescription = null, tint = iconFg, modifier = Modifier.size(22.dp))
            }
            Spacer(Modifier.height(8.dp))
            Text(label, style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium), color = MobileTokens.textPrimary)
        }
    }
}

@Composable
private fun ModTile(mod: ListItem, modifier: Modifier = Modifier, onClick: () -> Unit) {
    Card(
        modifier.clickable(onClick = onClick),
        shape = MobileTokens.cornerCard,
        colors = CardDefaults.cardColors(containerColor = Color.White),
        elevation = CardDefaults.cardElevation(defaultElevation = 0.dp),
    ) {
        Row(
            Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                Modifier
                    .size(32.dp)
                    .clip(RoundedCornerShape(8.dp))
                    .background(MobileTokens.iconBgPurple),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    Icons.Default.Extension,
                    contentDescription = null,
                    tint = MobileTokens.iconFgPurple,
                    modifier = Modifier.size(18.dp),
                )
            }
            Spacer(Modifier.height(8.dp))
            Text(mod.title, style = MaterialTheme.typography.bodyMedium, maxLines = 2, color = MobileTokens.textPrimary)
        }
    }
}
