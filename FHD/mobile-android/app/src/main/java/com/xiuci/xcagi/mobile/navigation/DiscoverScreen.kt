package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material.icons.filled.Explore
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.QrCodeScanner
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileTokens
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSectionCaption
import com.xiuci.xcagi.mobile.ui.components.mobile.WeTopBar

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DiscoverScreen(
    onScan: () -> Unit,
    onOcr: () -> Unit,
) {
    Column(Modifier.fillMaxSize().background(MobileTokens.surfaceWhite)) {
        WeTopBar(
            title = "发现",
            showRightSearch = false,
        )

        LazyColumn(state = rememberLazyListState()) {
            item {
                WeSectionCaption("工具")
                WeCellGroup {
                    WeCell(
                        title = "扫一扫",
                        subtitle = "扫码、条码、二维码",
                        icon = Icons.Default.QrCodeScanner,
                        iconTint = MobileTokens.iconFgBlue,
                        iconBg = MobileTokens.iconBgBlue,
                        showArrow = true,
                        onClick = onScan,
                    )
                    WeCell(
                        title = "OCR 拍照识别",
                        subtitle = "拍照识别文字与文档",
                        icon = Icons.Default.CameraAlt,
                        iconTint = MobileTokens.iconFgCyan,
                        iconBg = MobileTokens.iconBgCyan,
                        showArrow = true,
                        showDivider = false,
                        onClick = onOcr,
                    )
                }
            }

            item {
                WeSectionCaption("服务")
                WeCellGroup {
                    WeCell(
                        title = "Agent 控制",
                        subtitle = "远程操控电脑，执行任务和命令",
                        icon = Icons.Default.Explore,
                        iconTint = MobileTokens.iconFgGreen,
                        iconBg = MobileTokens.iconBgGreen,
                        showArrow = true,
                        showDivider = false,
                        onClick = onScan,
                    )
                }
            }

            item {
                WeSectionCaption("动态")
                WeCellGroup {
                    WeCell(
                        title = "通知与公告",
                        subtitle = "企业公告与系统通知",
                        icon = Icons.Default.Notifications,
                        iconTint = MobileTokens.iconFgRed,
                        iconBg = MobileTokens.iconBgRed,
                        showArrow = true,
                        showDivider = false,
                        onClick = { /* notifications */ },
                    )
                }
            }
        }
    }
}
