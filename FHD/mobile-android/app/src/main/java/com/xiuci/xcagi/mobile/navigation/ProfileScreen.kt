package com.xiuci.xcagi.mobile.navigation

import android.content.Intent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.BuildConfig
import com.xiuci.xcagi.mobile.R
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.ComplianceFooter
import com.xiuci.xcagi.mobile.ui.components.mobile.LocalProfileAvatar
import com.xiuci.xcagi.mobile.ui.components.mobile.WeBadge
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeRedActionCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSectionCaption
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSpacer
import com.xiuci.xcagi.mobile.ui.components.mobile.WeTopBar
import com.xiuci.xcagi.mobile.ui.theme.Elevation
import com.xiuci.xcagi.mobile.ui.theme.Spacing
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme
import androidx.compose.foundation.text.KeyboardOptions

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
    val accountKindLabel by vm.accountKindLabel.collectAsState()
    val avatarUri by vm.avatarUri.collectAsState()
    val fhdHost by vm.fhdHost.collectAsState()
    val hub by vm.homeHub.collectAsState()
    val appConfig by vm.appConfig.collectAsState()
    var showDelete by remember { mutableStateOf(false) }
    var deletePassword by remember { mutableStateOf("") }
    var showProfileEditor by remember { mutableStateOf(false) }
    var profileNameDraft by remember { mutableStateOf("") }
    val ctx = LocalContext.current
    val avatarPicker =
        rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
            if (uri != null) {
                runCatching {
                    ctx.contentResolver.takePersistableUriPermission(
                        uri,
                        Intent.FLAG_GRANT_READ_URI_PERMISSION,
                    )
                }
                vm.updateAvatarUri(uri.toString())
            }
        }

    Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.surface)) {
        WeTopBar(title = "个人")

        LazyColumn(state = rememberLazyListState()) {
            // ── 用户信息区（白底+头像+微信号+同步按钮+右侧箭头） ──
            item {
                WeCellGroup {
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .clickable {
                                profileNameDraft = displayName
                                showProfileEditor = true
                            }
                            .padding(Spacing.lg),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(
                            contentAlignment = Alignment.BottomEnd,
                        ) {
                            LocalProfileAvatar(
                                displayName = displayName.ifBlank { "U" },
                                avatarUri = avatarUri,
                                size = 56.dp,
                            )
                            Box(
                                Modifier
                                    .size(18.dp)
                                    .clip(CircleShape)
                                    .background(MaterialTheme.colorScheme.surface)
                                    .padding(2.dp)
                                    .clip(CircleShape)
                                    .background(XcagiTheme.extra.brandBlue),
                                contentAlignment = Alignment.Center,
                            ) {
                                Icon(
                                    Icons.Default.Photo,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.onPrimary,
                                    modifier = Modifier.size(11.dp),
                                )
                            }
                        }
                        Spacer(Modifier.width(14.dp))
                        Column(Modifier.weight(1f)) {
                            Text(
                                displayName.ifBlank { "未登录" },
                                style = MaterialTheme.typography.titleLarge,
                                color = MaterialTheme.colorScheme.onSurface,
                            )
                            Spacer(Modifier.height(Spacing.xs))
                            Text(
                                accountKindLabel,
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.outline,
                            )
                            if (fhdHost.isNotBlank()) {
                                Spacer(Modifier.height(2.dp))
                                Text(
                                    fhdHost,
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.outline,
                                )
                            }
                            Spacer(Modifier.height(Spacing.sm))
                            Row(horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
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
                            tint = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f),
                        )
                    }
                }
            }

            // ── 状态/服务 ──
            item {
                WeSpacer(Spacing.sm)
                WeCellGroup {
                    WeCell(
                        title = "连接电脑",
                        subtitle = "扫码绑定局域网 FHD",
                        icon = Icons.Default.QrCode2,
                        iconTint = MaterialTheme.colorScheme.secondary,
                        iconBg = MaterialTheme.colorScheme.secondaryContainer,
                        showArrow = true,
                        onClick = onConnectPc,
                    )
                    WeCell(
                        title = "服务",
                        subtitle = accountKindLabel,
                        icon = Icons.Default.Verified,
                        iconTint = MaterialTheme.colorScheme.secondary,
                        iconBg = MaterialTheme.colorScheme.secondaryContainer,
                        showArrow = true,
                        showDivider = false,
                        onClick = onSettings,
                    )
                }
            }

            // ── 设置 ──
            item {
                WeSpacer(Spacing.sm)
                WeCellGroup {
                    WeCell(
                        title = "设置",
                        icon = Icons.Default.Settings,
                        iconTint = MaterialTheme.colorScheme.primary,
                        iconBg = MaterialTheme.colorScheme.primaryContainer,
                        showArrow = true,
                        onClick = onSettings,
                    )
                    WeCell(
                        title = "关于",
                        subtitle = stringResource(R.string.company_name),
                        icon = Icons.Default.AccountBalanceWallet,
                        iconTint = XcagiTheme.extra.warning,
                        iconBg = MaterialTheme.colorScheme.primaryContainer,
                        showArrow = true,
                        showDivider = false,
                        onClick = onAbout,
                    )
                }
            }

            // ── 退出 ──
            item {
                WeSpacer(Spacing.lg)
                WeSectionCaption("账号管理")
                WeCellGroup {
                    WeRedActionCell(text = "退出登录", onClick = onLogout)
                }
                WeSpacer(Spacing.sm)
                WeCellGroup {
                    WeRedActionCell(text = "注销账号", onClick = { showDelete = true })
                }
                WeSpacer(Spacing.sm)
            }

            item {
                WeSpacer(Spacing.sm)
                Text(
                    "版本 ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline,
                    modifier = Modifier.fillMaxWidth().padding(Spacing.lg),
                )
                WeSpacer(Spacing.sm)
                ComplianceFooter(appConfig)
                WeSpacer(Spacing.xxl)
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
                        shape = MaterialTheme.shapes.small,
                        visualTransformation = PasswordVisualTransformation(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
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

    if (showProfileEditor) {
        ProfileEditorDialog(
            displayName = displayName.ifBlank { "未登录" },
            avatarUri = avatarUri,
            draftName = profileNameDraft,
            onDraftNameChange = { profileNameDraft = it.take(32) },
            onPickAvatar = { avatarPicker.launch(arrayOf("image/*")) },
            onClearAvatar = vm::clearAvatar,
            onDismiss = { showProfileEditor = false },
            onSave = {
                vm.updateProfileName(profileNameDraft)
                showProfileEditor = false
            },
        )
    }
}

@Composable
private fun ProfileEditorDialog(
    displayName: String,
    avatarUri: String,
    draftName: String,
    onDraftNameChange: (String) -> Unit,
    onPickAvatar: () -> Unit,
    onClearAvatar: () -> Unit,
    onDismiss: () -> Unit,
    onSave: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("个人资料") },
        text = {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                LocalProfileAvatar(
                    displayName = draftName.ifBlank { displayName },
                    avatarUri = avatarUri,
                    size = 76.dp,
                )
                Spacer(Modifier.height(12.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(Spacing.sm)) {
                    TextButton(onClick = onPickAvatar) { Text("更换头像") }
                    TextButton(
                        onClick = onClearAvatar,
                        enabled = avatarUri.isNotBlank(),
                    ) { Text("移除") }
                }
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = draftName,
                    onValueChange = onDraftNameChange,
                    label = { Text("昵称") },
                    singleLine = true,
                    shape = MaterialTheme.shapes.small,
                )
                Spacer(Modifier.height(6.dp))
                Text(
                    "${draftName.length}/32",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        },
        confirmButton = {
            TextButton(onClick = onSave, enabled = draftName.isNotBlank()) { Text("保存") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
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
            .clip(MaterialTheme.shapes.medium)
            .border(0.5.dp, MaterialTheme.colorScheme.outlineVariant, MaterialTheme.shapes.medium)
            .clickable(onClick = onClick)
            .padding(horizontal = 10.dp, vertical = Spacing.xs),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            icon,
            contentDescription = null,
            modifier = Modifier.size(14.dp),
            tint = MaterialTheme.colorScheme.outline,
        )
        Spacer(Modifier.width(Spacing.xs))
        Text(
            label,
            style = MaterialTheme.typography.labelSmall,
            color = if (selected) XcagiTheme.extra.brandBlue else MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
