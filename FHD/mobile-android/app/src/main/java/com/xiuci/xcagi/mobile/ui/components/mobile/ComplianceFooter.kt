package com.xiuci.xcagi.mobile.ui.components.mobile

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
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
    val filingApproved = config?.app_filing_approved != false
    val appFiling = config?.app_filing_number?.takeIf { it.isNotBlank() }
        ?: stringResource(R.string.app_filing_number)

    if (compact) {
        Column(
            modifier = modifier
                .fillMaxWidth()
                .padding(horizontal = MobileTokens.authHorizontalMargin, vertical = 8.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            if (filingApproved) {
                Text(
                    appFiling,
                    fontSize = 11.sp,
                    color = MobileTokens.textTertiary,
                    textAlign = TextAlign.Center,
                )
            }
            if (config?.ok == true && config.app_filing_approved == false) {
                Text(
                    stringResource(R.string.app_filing_pending),
                    fontSize = 11.sp,
                    color = MobileTokens.textTertiary,
                    textAlign = TextAlign.Center,
                )
            }
        }
        return
    }

    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        if (filingApproved) {
            Text(
                appFiling,
                fontSize = 11.sp,
                color = MobileTokens.textTertiary,
                textAlign = TextAlign.Center,
            )
        }
        if (config?.ok == true && config.app_filing_approved == false) {
            Text(
                stringResource(R.string.app_filing_pending),
                fontSize = 11.sp,
                color = MobileTokens.textTertiary,
                textAlign = TextAlign.Center,
            )
        }
    }
}
