package com.xiuci.xcagi.mobile.feature.ocr

import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.InsertDriveFile
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material.icons.filled.CloudDone
import androidx.compose.material.icons.filled.PhotoLibrary
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeScreen
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSectionCaption
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme

@Composable
fun OcrScreen(vm: AppViewModel, onBack: () -> Unit) {
    WeScreen(title = "拍照识别", onBack = onBack) {
        WeSectionCaption("入口")
        WeCellGroup {
            WeCell(
                    title = "拍照识别",
                    subtitle = "调用企业端 OCR 引擎处理图片文字",
                    icon = Icons.Default.CameraAlt,
                    iconTint = XcagiTheme.extra.brandBlue,
                    iconBg = MaterialTheme.colorScheme.primaryContainer,
                    showArrow = true,
                    showDivider = true,
                    onClick = { vm.snack("移动端拍照上传正在接入，请先使用电脑端 OCR") },
            )
            WeCell(
                    title = "从相册选择",
                    subtitle = "识别票据、表格截图与文档图片",
                    icon = Icons.Default.PhotoLibrary,
                    iconTint = MaterialTheme.colorScheme.secondary,
                    iconBg = MaterialTheme.colorScheme.secondaryContainer,
                    showArrow = true,
                    showDivider = true,
                    onClick = { vm.snack("移动端相册识别正在接入，请先使用电脑端 OCR") },
            )
            WeCell(
                    title = "批量识别",
                    subtitle = "完整批量处理请使用电脑端",
                    icon = Icons.AutoMirrored.Filled.InsertDriveFile,
                    iconTint = XcagiTheme.extra.warning,
                    iconBg = XcagiTheme.extra.warning.copy(alpha = 0.12f),
                    showArrow = false,
                    showDivider = false,
            )
        }
        Spacer(Modifier.height(16.dp))
        WeSectionCaption("状态")
        WeCellGroup {
            WeCell(
                    title = "企业 OCR",
                    subtitle = "等待移动端上传链路接入",
                    icon = Icons.Default.CloudDone,
                    iconTint = XcagiTheme.extra.success,
                    iconBg = MaterialTheme.colorScheme.secondaryContainer,
                    showArrow = false,
                    showDivider = false,
            )
        }
    }
}
