package com.xiuci.xcagi.mobile.feature.auth

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Language
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.xiuci.xcagi.mobile.core.ProductSkuConfig

@Composable
fun RegisterScreen(
        onOpenWebForm: () -> Unit,
        onLogin: () -> Unit = {},
) {
    val isEnterprise = ProductSkuConfig.isEnterprise

    Column(
            Modifier.fillMaxSize()
                    .background(MaterialTheme.colorScheme.background)
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 24.dp)
                    .padding(top = 60.dp, bottom = 28.dp),
            verticalArrangement = Arrangement.spacedBy(18.dp),
    ) {
        Text(
                "账号注册",
                fontSize = 24.sp,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onSurface,
        )
        Text(
                if (isEnterprise) "使用网页开户注册表单，和桌面端保持一致。"
                else "使用网页注册表单创建账号。",
                fontSize = 14.sp,
                color = MaterialTheme.colorScheme.outline,
        )

        Surface(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(12.dp),
                color = MaterialTheme.colorScheme.surfaceVariant,
        ) {
            Row(
                    modifier = Modifier.padding(16.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    verticalAlignment = Alignment.Top,
            ) {
                Icon(Icons.Default.Language, contentDescription = null)
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(
                            "网页登录表单",
                            fontWeight = FontWeight.SemiBold,
                            color = MaterialTheme.colorScheme.onSurface,
                    )
                    Text(
                            "打开桌面端注册页填写用户名、邮箱、行业、预算区间、密码和确认密码。提交成功后回到 App 登录并继续启动配置。",
                            fontSize = 13.sp,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            lineHeight = 19.sp,
                    )
                }
            }
        }

        Button(onClick = onOpenWebForm, modifier = Modifier.fillMaxWidth().height(48.dp)) {
            Text("去网页填写注册表单")
        }
        OutlinedButton(onClick = onLogin, modifier = Modifier.fillMaxWidth().height(48.dp)) {
            Text("返回登录")
        }
        Spacer(Modifier.height(8.dp))
    }
}
