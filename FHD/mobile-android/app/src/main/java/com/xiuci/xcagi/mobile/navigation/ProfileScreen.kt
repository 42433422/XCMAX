package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Settings
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.BuildConfig
import com.xiuci.xcagi.mobile.R
import com.xiuci.xcagi.mobile.core.ProductSkuConfig
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.ComplianceFooter
import com.xiuci.xcagi.mobile.ui.components.mobile.WeAvatar
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeRedActionCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeScreen
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSpacer

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
    val serverModeLabel by vm.serverModeLabel.collectAsState()
    val fhdHost by vm.fhdHost.collectAsState()
    val autoProbe by vm.autoLanProbe.collectAsState()
    val autoSync by vm.autoSync.collectAsState()
    val hub by vm.homeHub.collectAsState()
    val appConfig by vm.appConfig.collectAsState()
    var showDelete by remember { mutableStateOf(false) }
    var deletePassword by remember { mutableStateOf("") }

    WeScreen(title = "我的", scrollable = true) {
        WeCellGroup {
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(16.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                WeAvatar(
                    size = 64.dp,
                    content = {
                        Icon(
                            painter = painterResource(R.mipmap.ic_launcher),
                            contentDescription = null,
                            modifier = Modifier.size(48.dp),
                            tint = Color.Unspecified,
                        )
                    },
                )
                Spacer(Modifier.width(16.dp))
                Column(Modifier.weight(1f)) {
                    Text(
                        displayName.ifBlank { "未登录" },
                        style = MaterialTheme.typography.titleMedium,
                    )
                    Text(
                        ProductSkuConfig.displayEditionLabel,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        serverModeLabel,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        WeSpacer(12.dp)

        WeCellGroup {
            WeCell(
                title = "连接电脑",
                subtitle = if (fhdHost.isBlank()) "未配置，可使用云端工作台" else "当前：$fhdHost",
                showArrow = true,
                onClick = onConnectPc,
            )
            WeCell(
                title = "后台自动发现电脑",
                trailing = {
                    Switch(autoProbe, { vm.setAutoLanProbe(it) })
                },
                showDivider = true,
            )
            WeCell(
                title = "后台自动同步",
                subtitle = hub.syncLabel,
                trailing = {
                    Switch(autoSync, { vm.setAutoSync(it) })
                },
                showDivider = true,
            )
            WeCell(
                title = "立即同步工作数据",
                value = if (hub.syncing) "同步中…" else "",
                showArrow = false,
                showDivider = false,
                onClick = { if (!hub.syncing) vm.runSyncNow() },
            )
        }

        WeSpacer(12.dp)

        WeCellGroup {
            WeCell(
                title = "设置",
                icon = Icons.Default.Settings,
                showArrow = true,
                onClick = onSettings,
            )
            WeCell(
                title = "关于",
                subtitle = stringResource(R.string.company_name),
                icon = Icons.Default.Info,
                showArrow = true,
                showDivider = false,
                onClick = onAbout,
            )
        }

        WeSpacer(8.dp)
        Text(
            "版本 ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 16.dp),
        )

        WeSpacer(16.dp)
        ComplianceFooter(appConfig)
        WeSpacer(8.dp)
        WeRedActionCell(text = "退出登录", onClick = onLogout)
        WeSpacer(8.dp)
        WeRedActionCell(text = "注销账号", onClick = { showDelete = true })
    }

    if (showDelete) {
        androidx.compose.material3.AlertDialog(
            onDismissRequest = { showDelete = false },
            title = { Text("注销账号") },
            text = {
                Column {
                    Text("注销后无法恢复，请确认密码。")
                    OutlinedTextField(
                        deletePassword,
                        { deletePassword = it },
                        label = { Text("密码") },
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
