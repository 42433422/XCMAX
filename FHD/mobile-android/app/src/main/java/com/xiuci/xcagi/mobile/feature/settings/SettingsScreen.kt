package com.xiuci.xcagi.mobile.feature.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.BugReport
import androidx.compose.material.icons.filled.DarkMode
import androidx.compose.material.icons.filled.Fingerprint
import androidx.compose.material.icons.filled.LightMode
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.SystemUpdate
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.WeBlockButton
import com.xiuci.xcagi.mobile.ui.components.mobile.WeField
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSectionCaption
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSwitch
import com.xiuci.xcagi.mobile.ui.components.mobile.WeTopBar
import com.xiuci.xcagi.mobile.ui.theme.Spacing
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme

@Composable
fun SettingsScreen(vm: AppViewModel, onBack: () -> Unit) {
    val biometric by vm.biometricEnabled.collectAsState()
    val themeMode by vm.themeMode.collectAsState()
    var feedback by remember { mutableStateOf("") }

    Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.surface)) {
        WeTopBar(title = "设置", onBack = onBack, showRightSearch = false, showRightAdd = false)

        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.spacedBy(Spacing.sm),
        ) {
            item {
                WeSectionCaption("安全")
                WeCellGroup {
                    WeCell(
                        title = "生物识别解锁",
                        subtitle = if (biometric) "已开启" else "未开启",
                        icon = Icons.Default.Fingerprint,
                        iconTint = XcagiTheme.extra.brandBlue,
                        iconBg = MaterialTheme.colorScheme.primaryContainer,
                        showArrow = false,
                        showDivider = false,
                        trailing = {
                            WeSwitch(
                                checked = biometric,
                                onCheckedChange = { vm.setBiometricEnabled(it) },
                            )
                        },
                    )
                }
            }

            item {
                WeSectionCaption("外观")
                WeCellGroup {
                    WeCell(
                        title = "主题模式",
                        subtitle = themeLabel(themeMode),
                        icon = Icons.Default.Palette,
                        iconTint = MaterialTheme.colorScheme.secondary,
                        iconBg = MaterialTheme.colorScheme.secondaryContainer,
                        showArrow = false,
                        showDivider = false,
                    )
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .padding(horizontal = Spacing.lg, vertical = Spacing.sm),
                        horizontalArrangement = Arrangement.spacedBy(Spacing.sm),
                    ) {
                        ThemeModeChip("跟随", Icons.Default.Tune, themeMode == "system") {
                            vm.setThemeMode("system")
                        }
                        ThemeModeChip("浅色", Icons.Default.LightMode, themeMode == "light") {
                            vm.setThemeMode("light")
                        }
                        ThemeModeChip("深色", Icons.Default.DarkMode, themeMode == "dark") {
                            vm.setThemeMode("dark")
                        }
                    }
                }
            }

            item {
                WeSectionCaption("反馈")
                WeCellGroup {
                    WeCell(
                        title = "问题反馈",
                        subtitle = "提交后进入企业支持队列",
                        icon = Icons.Default.BugReport,
                        iconTint = XcagiTheme.extra.warning,
                        iconBg = XcagiTheme.extra.warning.copy(alpha = 0.14f),
                        showArrow = false,
                        showDivider = false,
                    )
                    WeField(
                        value = feedback,
                        onValueChange = { feedback = it.take(500) },
                        modifier = Modifier.padding(horizontal = Spacing.lg),
                        placeholder = "描述问题或建议",
                        singleLine = false,
                    )
                    Spacer(Modifier.height(Spacing.sm))
                    WeBlockButton(
                        text = "提交反馈",
                        onClick = { vm.submitFeedback(feedback) { feedback = "" } },
                        enabled = feedback.isNotBlank(),
                    )
                    Spacer(Modifier.height(Spacing.md))
                }
            }

            item {
                WeSectionCaption("版本")
                WeCellGroup {
                    WeCell(
                        title = "检查更新",
                        subtitle = "获取企业版移动端最新构建",
                        icon = Icons.Default.SystemUpdate,
                        iconTint = XcagiTheme.extra.success,
                        iconBg = MaterialTheme.colorScheme.secondaryContainer,
                        showArrow = true,
                        showDivider = false,
                        onClick = { vm.checkForUpdate(manual = true) },
                    )
                }
                Spacer(Modifier.height(Spacing.xxl))
            }
        }
    }
}

@Composable
private fun RowScope.ThemeModeChip(
    label: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    selected: Boolean,
    onClick: () -> Unit,
) {
    val bg =
        if (selected) XcagiTheme.extra.brandBlue
        else MaterialTheme.colorScheme.surfaceVariant
    val fg =
        if (selected) MaterialTheme.colorScheme.onPrimary
        else MaterialTheme.colorScheme.onSurfaceVariant
    Box(
        Modifier
            .weight(1f)
            .height(38.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(bg)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(5.dp)) {
            Icon(icon, contentDescription = null, tint = fg, modifier = Modifier.size(15.dp))
            Text(label, color = fg, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Medium)
        }
    }
}

private fun themeLabel(mode: String): String =
    when (mode) {
        "dark" -> "深色"
        "light" -> "浅色"
        else -> "跟随系统"
    }
