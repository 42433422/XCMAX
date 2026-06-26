package com.xiuci.xcagi.mobile.navigation

import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.xiuci.xcagi.mobile.ui.theme.Spacing

internal data class XcagiComposerToolAction(
    val label: String,
    val subtitle: String,
    val icon: ImageVector,
    val onClick: () -> Unit,
)

@Composable
internal fun XcagiComposerMoreButton(
    expanded: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    tint: Color = MaterialTheme.colorScheme.onSurface,
) {
    IconButton(onClick = onClick, modifier = modifier.size(38.dp)) {
        Icon(
            if (expanded) Icons.Default.Close else Icons.Default.Add,
            contentDescription = "更多",
            tint = tint,
            modifier = Modifier.size(26.dp),
        )
    }
}

@Composable
internal fun XcagiComposerToolPanel(
    actions: List<XcagiComposerToolAction>,
    modifier: Modifier = Modifier,
) {
    if (actions.isEmpty()) return
    Column(
        modifier
            .fillMaxWidth()
            .animateContentSize()
            .padding(start = Spacing.lg, end = Spacing.lg, top = Spacing.md, bottom = Spacing.xxl),
    ) {
        val rows = actions.chunked(4)
        rows.forEachIndexed { rowIndex, row ->
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(Spacing.md),
            ) {
                row.forEach { action ->
                    XcagiComposerToolCard(action, Modifier.weight(1f))
                }
                repeat(4 - row.size) {
                    Spacer(Modifier.weight(1f))
                }
            }
            if (rowIndex < rows.lastIndex) Spacer(Modifier.height(Spacing.lg))
        }
    }
}

@Composable
private fun XcagiComposerToolCard(action: XcagiComposerToolAction, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier.clickable(onClick = action.onClick),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            Modifier
                .size(64.dp)
                .clip(RoundedCornerShape(16.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.62f)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                action.icon,
                contentDescription = action.label,
                tint = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.size(28.dp),
            )
        }
        Spacer(Modifier.height(7.dp))
        Text(
            action.label,
            style = MaterialTheme.typography.labelMedium.copy(fontSize = 13.sp),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}
