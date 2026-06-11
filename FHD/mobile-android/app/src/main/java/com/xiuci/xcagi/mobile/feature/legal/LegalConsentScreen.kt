package com.xiuci.xcagi.mobile.feature.legal

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.xiuci.xcagi.mobile.R
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileTokens

@Composable
fun LegalConsentScreen(
    vm: AppViewModel,
    onAccepted: () -> Unit,
    onAbout: () -> Unit,
) {
    val config by vm.appConfig.collectAsState()
    var checked by remember { mutableStateOf(false) }
    val ctx = LocalContext.current
    val privacyUrl = config?.privacy_url?.takeIf { it.isNotBlank() } ?: "https://xiu-ci.com/legal/privacy"
    val termsUrl = config?.terms_url?.takeIf { it.isNotBlank() } ?: "https://xiu-ci.com/legal/terms"

    Box(
        Modifier
            .fillMaxSize()
            .background(MobileTokens.brandBlue),
    ) {
        Column(
            Modifier
                .fillMaxSize()
                .padding(horizontal = 32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Spacer(Modifier.weight(1f))

            // Logo
            Box(
                Modifier
                    .size(88.dp)
                    .clip(RoundedCornerShape(20.dp))
                    .background(Color.White.copy(alpha = 0.15f)),
                contentAlignment = Alignment.Center,
            ) {
                Image(
                    painter = painterResource(R.mipmap.ic_launcher_foreground),
                    contentDescription = null,
                    modifier = Modifier.size(64.dp),
                    contentScale = ContentScale.Fit,
                )
            }

            Spacer(Modifier.height(20.dp))

            Text(
                "XCAGI",
                fontSize = 28.sp,
                fontWeight = FontWeight.Bold,
                color = Color.White,
                letterSpacing = 2.sp,
            )

            Spacer(Modifier.height(6.dp))

            Text(
                "企业智能工作平台",
                fontSize = 14.sp,
                color = Color.White.copy(alpha = 0.7f),
            )

            Spacer(Modifier.weight(1f))

            // 协议勾选
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 8.dp)
                    .clip(RoundedCornerShape(8.dp))
                    .clickable { checked = !checked },
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.Center,
            ) {
                Box(
                    Modifier
                        .size(18.dp)
                        .clip(RoundedCornerShape(4.dp))
                        .background(if (checked) Color.White else Color.White.copy(alpha = 0.2f)),
                    contentAlignment = Alignment.Center,
                ) {
                    if (checked) {
                        Icon(
                            Icons.Default.Check,
                            contentDescription = null,
                            modifier = Modifier.size(14.dp),
                            tint = MobileTokens.brandBlue,
                        )
                    }
                }
                Spacer(Modifier.size(8.dp))
                Text(
                    buildAnnotatedString {
                        withStyle(SpanStyle(color = Color.White.copy(alpha = 0.6f), fontSize = 12.sp)) {
                            append("我已阅读并同意")
                        }
                        withStyle(SpanStyle(color = Color.White, fontSize = 12.sp, textDecoration = TextDecoration.Underline)) {
                            append("《用户协议》")
                        }
                        withStyle(SpanStyle(color = Color.White.copy(alpha = 0.6f), fontSize = 12.sp)) {
                            append("和")
                        }
                        withStyle(SpanStyle(color = Color.White, fontSize = 12.sp, textDecoration = TextDecoration.Underline)) {
                            append("《隐私政策》")
                        }
                    },
                )
            }

            Spacer(Modifier.height(16.dp))

            // 进入按钮
            Box(
                Modifier
                    .fillMaxWidth()
                    .height(48.dp)
                    .clip(RoundedCornerShape(24.dp))
                    .background(if (checked) Color.White else Color.White.copy(alpha = 0.2f))
                    .clickable(enabled = checked) { vm.acceptLegal(onAccepted) },
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    if (checked) "进入 XCAGI" else "请先同意协议",
                    fontSize = 16.sp,
                    fontWeight = FontWeight.Medium,
                    color = if (checked) MobileTokens.brandBlue else Color.White.copy(alpha = 0.5f),
                )
            }

            Spacer(Modifier.height(32.dp))
        }
    }
}
