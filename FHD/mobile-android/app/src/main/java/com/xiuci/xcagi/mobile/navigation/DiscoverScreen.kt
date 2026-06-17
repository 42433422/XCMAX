package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material.icons.filled.Explore
import androidx.compose.material.icons.filled.Forum
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.QrCodeScanner
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSectionCaption
import com.xiuci.xcagi.mobile.ui.components.mobile.WeTopBar
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DiscoverScreen(
    onScan: () -> Unit,
    onOcr: () -> Unit,
    onAiCircle: () -> Unit,
) {
    Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.surface)) {
        WeTopBar(
            title = "探索",
            showRightSearch = false,
        )

        LazyColumn(state = rememberLazyListState()) {
            item {
                WeSectionCaption("识别工具")
                WeCellGroup {
                    WeCell(
                        title = "扫码识别",
                        subtitle = "读取二维码、条码与设备绑定码",
                        icon = Icons.Default.QrCodeScanner,
                        iconTint = MaterialTheme.colorScheme.primary,
                        iconBg = MaterialTheme.colorScheme.primaryContainer,
                        showArrow = true,
                        onClick = onScan,
                    )
                    WeCell(
                        title = "OCR 拍照识别",
                        subtitle = "拍照识别文字与文档",
                        icon = Icons.Default.CameraAlt,
                        iconTint = MaterialTheme.colorScheme.tertiary,
                        iconBg = MaterialTheme.colorScheme.primaryContainer,
                        showArrow = true,
                        showDivider = false,
                        onClick = onOcr,
                    )
                }
            }

            item {
                WeSectionCaption("AI生态")
                WeCellGroup {
                    WeCell(
                        title = "AI交流圈",
                        subtitle = "查看企业 AI 员工动态和主页",
                        icon = Icons.Default.Forum,
                        iconTint = XcagiTheme.extra.brandBlue,
                        iconBg = MaterialTheme.colorScheme.primaryContainer,
                        showArrow = true,
                        showDivider = false,
                        onClick = onAiCircle,
                    )
                }
            }

            item {
                WeSectionCaption("连接")
                WeCellGroup {
                    WeCell(
                        title = "Agent 接管",
                        subtitle = "远程控制电脑，执行任务和命令",
                        icon = Icons.Default.Explore,
                        iconTint = MaterialTheme.colorScheme.secondary,
                        iconBg = MaterialTheme.colorScheme.secondaryContainer,
                        showArrow = true,
                        showDivider = false,
                        onClick = onScan,
                    )
                }
            }

            item {
                WeSectionCaption("更新")
                WeCellGroup {
                    WeCell(
                        title = "通知与公告",
                        subtitle = "企业公告与系统通知",
                        icon = Icons.Default.Notifications,
                        iconTint = XcagiTheme.extra.danger,
                        iconBg = MaterialTheme.colorScheme.errorContainer,
                        showArrow = true,
                        showDivider = false,
                        onClick = { /* notifications */ },
                    )
                }
            }
        }
    }
}
