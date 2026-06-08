package com.xiuci.xcagi.mobile.ui.components.mobile

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

@Composable
fun MobileStatusChip(status: String, modifier: Modifier = Modifier) {
    val normalized = status.lowercase()
    val (label, bg, fg) = when {
        normalized.contains("pending") || normalized.contains("待") -> Triple("待处理", MobileTokens.pending(), Color.White)
        normalized.contains("approved") || normalized.contains("通过") -> Triple("已通过", MobileTokens.success(), Color.White)
        normalized.contains("reject") || normalized.contains("驳回") -> Triple("已驳回", MobileTokens.danger(), Color.White)
        normalized.contains("withdraw") -> Triple("已撤回", MobileTokens.warning(), Color.White)
        status.isBlank() -> Triple("—", MaterialTheme.colorScheme.surfaceVariant, MaterialTheme.colorScheme.onSurfaceVariant)
        else -> Triple(status, MaterialTheme.colorScheme.secondaryContainer, MaterialTheme.colorScheme.onSecondaryContainer)
    }
    Text(
        label,
        modifier = modifier
            .background(bg.copy(alpha = 0.92f), MobileTokens.cornerChip)
            .padding(horizontal = 10.dp, vertical = 4.dp),
        style = MaterialTheme.typography.labelSmall,
        color = fg,
    )
}
