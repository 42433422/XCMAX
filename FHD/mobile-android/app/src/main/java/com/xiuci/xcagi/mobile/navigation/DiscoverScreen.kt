package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountTree
import androidx.compose.material.icons.filled.Apps
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material.icons.filled.Chat
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Forum
import androidx.compose.material.icons.filled.Group
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Print
import androidx.compose.material.icons.filled.QrCodeScanner
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Storage
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import com.xiuci.xcagi.mobile.core.network.NavMenuItem
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSectionCaption
import com.xiuci.xcagi.mobile.ui.components.mobile.WeTopBar
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme

/** 核心 key → 原生路由映射（有原生页面的走原生，否则用 WebView 打开）。 */
private val NATIVE_ROUTE_MAP: Map<String, String> = mapOf(
    "chat" to Routes.AI_CHAT,
    "im" to Routes.IM,
    "ai-ecosystem" to Routes.AI_EMPLOYEES,
    "employee-workflow" to Routes.WORK,
    "settings" to Routes.SETTINGS,
)

/** 已在手机端其他入口（底部 Tab / AI交流圈等）原生实现，桌面工具分组中隐藏，避免重复。 */
private val HIDDEN_KEYS: Set<String> = setOf(
    "chat",   // 智能对话：底部 Tab 原生入口
    "im",     // 消息：底部 Tab 原生入口
)

/** FA 图标名 → Material 图标映射（简化版，未知图标用 Build 兜底）。 */
private fun iconForNav(item: NavMenuItem): ImageVector = when {
    item.key == "chat" || item.icon.contains("comment") -> Icons.Default.Chat
    item.key == "im" || item.icon.contains("envelope") -> Icons.Default.Forum
    item.key == "ai-ecosystem" || item.icon.contains("sitemap") -> Icons.Default.AccountTree
    item.key == "employee-workflow" || item.icon.contains("users") -> Icons.Default.Group
    item.key == "products" || item.icon.contains("cube") -> Icons.Default.Apps
    item.key == "orders" || item.icon.contains("file") -> Icons.Default.Description
    item.key == "print" || item.icon.contains("print") -> Icons.Default.Print
    item.key == "data-sources" || item.icon.contains("database") -> Icons.Default.Storage
    item.key == "settings" || item.icon.contains("cog") -> Icons.Default.Settings
    item.source == "mod" -> Icons.Default.Apps
    else -> Icons.Default.Build
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DiscoverScreen(
    vm: AppViewModel,
    onScan: () -> Unit,
    onOcr: () -> Unit,
    onAiCircle: () -> Unit,
    onNotifications: () -> Unit = {},
    onNavigate: (String) -> Unit = {},
    onOpenWebView: (String, String) -> Unit = { _, _ -> },
) {
    val navMenu by vm.navMenu.collectAsState()

    // 进入即与电脑端侧栏对齐：拉取最新 nav-menu（未配对时静默失败，保留旧值）。
    androidx.compose.runtime.LaunchedEffect(Unit) { vm.loadNavMenu() }

    Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.surface)) {
        WeTopBar(
            title = "探索",
            showRightSearch = false,
        )

        LazyColumn(state = rememberLazyListState()) {
            item {
                WeSectionCaption("AI交流")
                WeCellGroup {
                    WeCell(
                        title = "AI交流圈",
                        subtitle = "查看企业 AI 员工动态、主页和能力介绍",
                        icon = Icons.Default.Forum,
                        iconTint = XcagiTheme.extra.brandBlue,
                        iconBg = MaterialTheme.colorScheme.primaryContainer,
                        showArrow = true,
                        showDivider = false,
                        onClick = onAiCircle,
                    )
                    // AI群聊 已学微信移到「消息」页（6 个部门群直接出现在会话列表），此处不再单列。
                }
            }

            // 配对后动态显示桌面端工具（与侧栏对齐）
            val visibleNavMenu = navMenu.filter { it.key !in HIDDEN_KEYS }
            if (visibleNavMenu.isNotEmpty()) {
                item {
                    WeSectionCaption("桌面工具（与电脑端侧栏对齐）")
                    WeCellGroup {
                        visibleNavMenu.forEachIndexed { idx, item ->
                            val nativeRoute = NATIVE_ROUTE_MAP[item.key]
                            WeCell(
                                title = item.name,
                                subtitle = if (item.source == "mod") "Mod: ${item.mod_id ?: item.key}" else "点击打开",
                                icon = iconForNav(item),
                                iconTint = MaterialTheme.colorScheme.primary,
                                iconBg = MaterialTheme.colorScheme.primaryContainer,
                                showArrow = true,
                                showDivider = idx < visibleNavMenu.lastIndex,
                                onClick = {
                                    if (nativeRoute != null) {
                                        onNavigate(nativeRoute)
                                    } else {
                                        // 无原生路由，用 WebView 打开桌面端页面
                                        onOpenWebView(item.path, item.name)
                                    }
                                },
                            )
                        }
                    }
                }
            } else {
                item {
                    WeSectionCaption("桌面工具（与电脑端侧栏对齐）")
                    WeCellGroup {
                        WeCell(
                            title = "扫码绑定电脑端",
                            subtitle = "绑定后，电脑端侧栏的工具会同步到这里",
                            icon = Icons.Default.QrCodeScanner,
                            iconTint = MaterialTheme.colorScheme.primary,
                            iconBg = MaterialTheme.colorScheme.primaryContainer,
                            showArrow = true,
                            showDivider = false,
                            onClick = onScan,
                        )
                    }
                }
            }

            item {
                WeSectionCaption("工具")
                WeCellGroup {
                    WeCell(
                        title = "扫码绑定",
                        subtitle = "绑定企业端、管理端或电脑端登录",
                        icon = Icons.Default.QrCodeScanner,
                        iconTint = MaterialTheme.colorScheme.primary,
                        iconBg = MaterialTheme.colorScheme.primaryContainer,
                        showArrow = true,
                        onClick = onScan,
                    )
                    WeCell(
                        title = "OCR识别",
                        subtitle = "拍照识别文字与文档",
                        icon = Icons.Default.CameraAlt,
                        iconTint = MaterialTheme.colorScheme.tertiary,
                        iconBg = MaterialTheme.colorScheme.tertiaryContainer,
                        showArrow = true,
                        onClick = onOcr,
                    )
                    WeCell(
                        title = "通知与公告",
                        subtitle = "企业公告与系统通知",
                        icon = Icons.Default.Notifications,
                        iconTint = XcagiTheme.extra.danger,
                        iconBg = MaterialTheme.colorScheme.errorContainer,
                        showArrow = true,
                        showDivider = false,
                        onClick = onNotifications,
                    )
                }
            }
        }
    }
}
