package com.xiuci.xcagi.mobile.feature.about

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.xiuci.xcagi.mobile.BuildConfig
import com.xiuci.xcagi.mobile.R
import com.xiuci.xcagi.mobile.core.model.AppConfigResponse
import com.xiuci.xcagi.mobile.ui.components.mobile.ComplianceFooter
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeScreen
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSectionCaption

@Composable
fun AboutScreen(
        onBack: () -> Unit,
        appConfig: AppConfigResponse? = null,
        onCheckUpdate: () -> Unit = {}
) {
    val ctx = LocalContext.current
    WeScreen(title = "关于", onBack = onBack) {
        Column(
                Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Spacer(Modifier.height(32.dp))
            Image(
                    painter = painterResource(R.mipmap.ic_launcher_foreground),
                    contentDescription = null,
                    modifier = Modifier.size(72.dp),
                    contentScale = ContentScale.Fit,
            )
            Spacer(Modifier.height(12.dp))
            Text(
                    "XCAGI",
                    fontSize = 20.sp,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSurface
            )
            Text(
                    "v${BuildConfig.VERSION_NAME}",
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.outline
            )
        }
        Spacer(Modifier.height(24.dp))
        WeSectionCaption("信息")
        WeCellGroup {
            WeCell(
                    title = "公司",
                    subtitle = stringResource(R.string.company_name),
                    showArrow = false,
                    showDivider = true,
            )
            WeCell(
                    title = "官网",
                    subtitle = stringResource(R.string.brand_url),
                    showArrow = true,
                    showDivider = true,
                    onClick = {
                        ctx.startActivity(
                                Intent(Intent.ACTION_VIEW, Uri.parse("https://xiu-ci.com"))
                        )
                    },
            )
            WeCell(
                    title = "检查更新",
                    subtitle = "v${BuildConfig.VERSION_NAME}",
                    showArrow = true,
                    showDivider = false,
                    onClick = onCheckUpdate,
            )
        }
        Spacer(Modifier.height(16.dp))
        ComplianceFooter(appConfig)
    }
}
