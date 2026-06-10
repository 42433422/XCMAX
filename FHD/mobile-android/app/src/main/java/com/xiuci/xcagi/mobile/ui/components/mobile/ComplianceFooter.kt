package com.xiuci.xcagi.mobile.ui.components.mobile

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.xiuci.xcagi.mobile.R
import com.xiuci.xcagi.mobile.core.model.AppConfigResponse

@Composable
fun ComplianceFooter(
    config: AppConfigResponse?,
    modifier: Modifier = Modifier,
    compact: Boolean = false,
) {
    val ctx = LocalContext.current
    val beianUrl = config?.app_filing_beian_url?.takeIf { it.isNotBlank() }
        ?: "https://beian.miit.gov.cn/"
    val filingApproved = config?.app_filing_approved != false
    val appFiling = config?.app_filing_number?.takeIf { it.isNotBlank() }
        ?: stringResource(R.string.app_filing_number)
    val websiteIcp = config?.icp_number?.takeIf { it.isNotBlank() }
        ?: stringResource(R.string.website_icp)
    val openBeian = {
        ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(beianUrl)))
    }

    if (compact) {
        Column(
            modifier = modifier
                .fillMaxWidth()
                .padding(horizontal = MobileTokens.authHorizontalMargin),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            if (filingApproved) {
                Text(
                    "APP 备案 $appFiling",
                    fontSize = 11.sp,
                    color = MobileTokens.authPlaceholder,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.clickable(onClick = openBeian),
                )
            }
            Text(
                "网站 ICP $websiteIcp",
                fontSize = 11.sp,
                color = MobileTokens.authPlaceholder,
                textAlign = TextAlign.Center,
                modifier = Modifier.clickable(onClick = openBeian),
            )
            if (config?.ok == true && config.app_filing_approved == false) {
                Text(
                    stringResource(R.string.app_filing_pending),
                    fontSize = 11.sp,
                    color = MobileTokens.authPlaceholder,
                    textAlign = TextAlign.Center,
                )
            }
        }
        return
    }

    WeSpacer(12.dp)
    WeCellGroup(modifier) {
        if (filingApproved) {
            WeCell(
                title = "APP 备案",
                value = appFiling,
                subtitle = stringResource(R.string.app_filing_subtitle),
                showArrow = true,
                showDivider = true,
                onClick = openBeian,
            )
        }
        WeCell(
            title = "网站 ICP",
            value = websiteIcp,
            showArrow = true,
            showDivider = false,
            onClick = openBeian,
        )
    }
    if (config?.ok == true && config.app_filing_approved == false) {
        Text(
            stringResource(R.string.app_filing_pending),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 8.dp),
        )
    }
}
