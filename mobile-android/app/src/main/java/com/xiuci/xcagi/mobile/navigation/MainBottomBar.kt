package com.xiuci.xcagi.mobile.navigation

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.filled.Dashboard
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Lan
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Task
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.core.ProductSkuConfig

private data class BottomNavEntry(
    val route: String,
    val icon: ImageVector,
    val label: String,
)

@Composable
fun XcagiMainBottomBar(
    currentRoute: String?,
    onNavigate: (String) -> Unit,
) {
    val entries =
        buildList {
            add(BottomNavEntry(Routes.CHAT, Icons.AutoMirrored.Filled.Chat, "对话"))
            add(BottomNavEntry(Routes.HOME_HUB, Icons.Default.Home, "首页"))
            add(BottomNavEntry(Routes.WORKBENCH, Icons.Default.Dashboard, "能力"))
            if (ProductSkuConfig.showsEnterpriseNav) {
                add(BottomNavEntry(Routes.APPROVAL, Icons.Default.Task, "审批"))
                add(BottomNavEntry(Routes.ERP, Icons.Default.Lan, "业务"))
            }
            add(BottomNavEntry(Routes.PROFILE, Icons.Default.Person, "我的"))
        }

    NavigationBar(
        containerColor = MaterialTheme.colorScheme.surface,
        tonalElevation = 0.dp,
    ) {
        entries.forEach { entry ->
            val selected = currentRoute == entry.route
            NavigationBarItem(
                selected = selected,
                onClick = { onNavigate(entry.route) },
                icon = { Icon(entry.icon, contentDescription = entry.label) },
                label = { Text(entry.label) },
                alwaysShowLabel = true,
                colors =
                    NavigationBarItemDefaults.colors(
                        selectedIconColor = MaterialTheme.colorScheme.primary,
                        selectedTextColor = MaterialTheme.colorScheme.primary,
                        unselectedIconColor = MaterialTheme.colorScheme.onSurfaceVariant,
                        unselectedTextColor = MaterialTheme.colorScheme.onSurfaceVariant,
                        indicatorColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.08f),
                    ),
            )
        }
    }
}
