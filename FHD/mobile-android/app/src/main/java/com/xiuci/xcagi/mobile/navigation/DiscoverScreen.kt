package com.xiuci.xcagi.mobile.navigation

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material.icons.filled.Dashboard
import androidx.compose.material.icons.filled.Extension
import androidx.compose.material.icons.filled.QrCodeScanner
import androidx.compose.material.icons.filled.Store
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeScreen
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSectionCaption
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSpacer

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DiscoverScreen(
    onWorkbench: () -> Unit,
    onMods: () -> Unit,
    onMarket: () -> Unit,
    onScan: () -> Unit,
    onOcr: () -> Unit,
) {
    WeScreen(title = "发现", scrollable = true) {
        WeSectionCaption("工作台")
        WeCellGroup {
            WeCell(
                title = "工作台",
                subtitle = "MODstore 网页版 · 完整 Mod 能力",
                icon = Icons.Default.Dashboard,
                iconTint = Color(0xFF10AEFF),
                showArrow = true,
                showDivider = false,
                onClick = onWorkbench,
            )
        }

        WeSpacer(12.dp)
        WeSectionCaption("扩展与市场")
        WeCellGroup {
            WeCell(
                title = "已安装 Mod",
                icon = Icons.Default.Extension,
                iconTint = Color(0xFF576B95),
                showArrow = true,
                onClick = onMods,
            )
            WeCell(
                title = "MODstore 市场",
                subtitle = "浏览与安装行业 Mod",
                icon = Icons.Default.Store,
                iconTint = Color(0xFFFA9D3B),
                showArrow = true,
                showDivider = false,
                onClick = onMarket,
            )
        }

        WeSpacer(12.dp)
        WeSectionCaption("工具")
        WeCellGroup {
            WeCell(
                title = "扫一扫",
                subtitle = "扫码连接电脑或确认登录",
                icon = Icons.Default.QrCodeScanner,
                iconTint = Color(0xFF07C160),
                showArrow = true,
                onClick = onScan,
            )
            WeCell(
                title = "OCR 拍照识别",
                subtitle = "完整识别请在工作台或 PC 端使用",
                icon = Icons.Default.CameraAlt,
                iconTint = Color(0xFF353740),
                showArrow = true,
                showDivider = false,
                onClick = onOcr,
            )
        }
    }
}
