package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.AccountBalanceWallet
import androidx.compose.material.icons.filled.Brush
import androidx.compose.material.icons.filled.Photo
import androidx.compose.material.icons.filled.QrCode2
import androidx.compose.material.icons.filled.SentimentSatisfied
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Store
import androidx.compose.material.icons.filled.Tag
import androidx.compose.material.icons.filled.Verified
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.xiuci.xcagi.mobile.BuildConfig
import com.xiuci.xcagi.mobile.R
import com.xiuci.xcagi.mobile.core.ProductSkuConfig
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.ComplianceFooter
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileTokens
import com.xiuci.xcagi.mobile.ui.components.mobile.WeBadge
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeRedActionCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSectionCaption
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSpacer
import com.xiuci.xcagi.mobile.ui.components.mobile.WeTopBar

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProfileScreen(
    vm: AppViewModel,
    onConnectPc: () -> Unit,
    onAbout: () -> Unit,
    onSettings: () -> Unit,
    onLogout: () -> Unit,
) {
    val displayName by vm.displayName.collectAsState()
    val fhdHost by vm.fhdHost.collectAsState()
    val hub by vm.homeHub.collectAsState()
    val appConfig by vm.appConfig.collectAsState()
    var showDelete by remember { mutableStateOf(false) }
    var deletePassword by remember { mutableStateOf("") }

    Column(Modifier.fillMaxSize().background(MobileTokens.surfaceWhite)) {
        WeTopBar(title = "我的")

        LazyColumn(state = rememberLazyListState()) {
            // ── 用户信息区（白底+头像+微信号+同步按钮+右侧箭头） ──
            item {
                WeCellGroup {
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .clickable { /* 进入资料卡 */ }
                            .padding(16.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(
                            Modifier
                                .size(56.dp)
                                .clip(CircleShape)
                                .background(MobileTokens.brandBlueLight),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text(
                                displayName.take(1).ifBlank { "U" },
                                fontSize = 22.sp,
                                fontWeight = FontWeight.SemiBold,
                                color = MobileTokens.brandBlue,
                            )
                        }
                        Spacer(Modifier.width(14.dp))
                        Column(Modifier.weight(1f)) {
                            Text(
                                displayName.ifBlank { "未登录" },
                                fontSize = 18.sp,
                                fontWeight = FontWeight.Medium,
                                color = MobileTokens.textPrimary,
                            )
                            Spacer(Modifier.height(4.dp))
                            Text(
                                ProductSkuConfig.displayEditionLabel,
                                fontSize = 13.sp,
                                color = MobileTokens.textTertiary,
                            )
                            Spacer(Modifier.height(8.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                StatusPill(
                                    icon = Icons.Outlined.Refresh,
                                    label = if (hub.syncing) "同步中…" else "同步",
                                    selected = hub.syncing,
                                    onClick = { if (!hub.syncing) vm.runSyncNow() },
                                )
                            }
                        }
                        Icon(
                            Icons.AutoMirrored.Filled.KeyboardArrowRight,
                            contentDescription = null,
                            modifier = Modifier.size(18.dp),
                            tint = MobileTokens.textDisabled,
                        )
                    }
                }
            }

            // ── 状态/服务 ──
            item {
                WeSpacer(8.dp)
                WeCellGroup {
                    WeCell(
                        title = "服务",
                        subtitle = ProductSkuConfig.displayEditionLabel,
                        icon = Icons.Default.Verified,
                        iconTint = MobileTokens.iconFgGreen,
                        iconBg = MobileTokens.iconBgGreen,
                        showArrow = true,
                        showDivider = false,
                        onClick = onSettings,
                    )
                }
            }

            // ── 设置 ──
            item {
                WeSpacer(8.dp)
                WeCellGroup {
                    WeCell(
                        title = "设置",
                        icon = Icons.Default.Settings,
                        iconTint = MobileTokens.iconFgBlue,
                        iconBg = MobileTokens.iconBgBlue,
                        showArrow = true,
                        onClick = onSettings,
                    )
                    WeCell(
                        title = "关于",
                        subtitle = stringResource(R.string.company_name),
                        icon = Icons.Default.AccountBalanceWallet,
                        iconTint = MobileTokens.iconFgOrange,
                        iconBg = MobileTokens.iconBgOrange,
                        showArrow = true,
                        showDivider = false,
                        onClick = onAbout,
                    )
                }
            }

            // ── 退出 ──
            item {
                WeSpacer(16.dp)
                WeSectionCaption("账号管理")
                WeCellGroup {
                    WeRedActionCell(text = "退出登录", onClick = onLogout)
                }
                WeSpacer(8.dp)
                WeCellGroup {
                    WeRedActionCell(text = "注销账号", onClick = { showDelete = true })
                }
                WeSpacer(8.dp)
            }

            item {
                WeSpacer(8.dp)
                Text(
                    "版本 ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})",
                    fontSize = 11.sp,
                    color = MobileTokens.textTertiary,
                    modifier = Modifier.fillMaxWidth().padding(16.dp),
                )
                WeSpacer(8.dp)
                ComplianceFooter(appConfig)
                WeSpacer(24.dp)
            }
        }
    }

    if (showDelete) {
        AlertDialog(
            onDismissRequest = { showDelete = false },
            title = { Text("注销账号") },
            text = {
                Column {
                    Text("注销后无法恢复，请确认密码。")
                    OutlinedTextField(
                        deletePassword,
                        { deletePassword = it },
                        label = { Text("密码") },
                        shape = RoundedCornerShape(8.dp),
                    )
                }
            },
            confirmButton = {
                TextButton({
                    vm.deleteAccount(deletePassword) {
                        showDelete = false
                        onLogout()
                    }
                }) { Text("确认注销") }
            },
            dismissButton = {
                TextButton({ showDelete = false }) { Text("取消") }
            },
        )
    }
}

@Composable
private fun StatusPill(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    selected: Boolean = false,
    onClick: () -> Unit,
) {
    Row(
        Modifier
            .clip(RoundedCornerShape(14.dp))
            .border(0.5.dp, MobileTokens.divider, RoundedCornerShape(14.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 10.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            icon,
            contentDescription = null,
            modifier = Modifier.size(14.dp),
            tint = MobileTokens.textTertiary,
        )
        Spacer(Modifier.width(4.dp))
        Text(
            label,
            fontSize = 12.sp,
            color = if (selected) MobileTokens.brandBlue else MobileTokens.textSecondary,
        )
    }
}
