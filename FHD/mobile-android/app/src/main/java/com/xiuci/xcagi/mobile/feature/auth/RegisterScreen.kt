package com.xiuci.xcagi.mobile.feature.auth

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme

@Composable
fun RegisterScreen(vm: AppViewModel, onBack: () -> Unit) {
    var u by remember { mutableStateOf("") }
    var p by remember { mutableStateOf("") }
    var e by remember { mutableStateOf("") }
    var agreed by remember { mutableStateOf(false) }
    val canSubmit = u.isNotBlank() && p.isNotBlank() && e.isNotBlank() && agreed

    Column(
            Modifier.fillMaxSize()
                    .background(Color.White)
                    .padding(horizontal = 24.dp)
                    .padding(top = 60.dp),
    ) {
        Text(
                "创建账号",
                fontSize = 24.sp,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onSurface,
        )
        Spacer(Modifier.height(6.dp))
        Text(
                "注册 XCAGI 企业平台账号",
                fontSize = 14.sp,
                color = MaterialTheme.colorScheme.outline,
        )
        Spacer(Modifier.height(32.dp))

        // 用户名
        OutlinedTextField(
                value = u,
                onValueChange = { u = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("用户名") },
                singleLine = true,
                shape = RoundedCornerShape(8.dp),
        )
        Spacer(Modifier.height(12.dp))

        // 密码
        OutlinedTextField(
                value = p,
                onValueChange = { p = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("密码") },
                singleLine = true,
                shape = RoundedCornerShape(8.dp),
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
        )
        Spacer(Modifier.height(12.dp))

        // 邮箱
        OutlinedTextField(
                value = e,
                onValueChange = { e = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("邮箱") },
                singleLine = true,
                shape = RoundedCornerShape(8.dp),
        )
        Spacer(Modifier.height(24.dp))

        // 协议勾选
        Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.clip(RoundedCornerShape(4.dp)).clickable { agreed = !agreed },
        ) {
            Box(
                    Modifier.size(16.dp)
                            .clip(RoundedCornerShape(3.dp))
                            .background(
                                    if (agreed) XcagiTheme.extra.brandBlue else MaterialTheme.colorScheme.outlineVariant
                            ),
                    contentAlignment = Alignment.Center,
            ) {
                if (agreed)
                        Icon(Icons.Default.Check, null, Modifier.size(12.dp), tint = Color.White)
            }
            Spacer(Modifier.size(6.dp))
            Text(
                    buildAnnotatedString {
                        withStyle(SpanStyle(color = MaterialTheme.colorScheme.outline, fontSize = 12.sp)) {
                            append("我已阅读并同意")
                        }
                        withStyle(
                                SpanStyle(
                                        color = XcagiTheme.extra.brandBlue,
                                        fontSize = 12.sp,
                                        textDecoration = TextDecoration.Underline
                                )
                        ) { append("《用户协议》") }
                        withStyle(SpanStyle(color = MaterialTheme.colorScheme.outline, fontSize = 12.sp)) {
                            append("和")
                        }
                        withStyle(
                                SpanStyle(
                                        color = XcagiTheme.extra.brandBlue,
                                        fontSize = 12.sp,
                                        textDecoration = TextDecoration.Underline
                                )
                        ) { append("《隐私政策》") }
                    }
            )
        }
        Spacer(Modifier.height(24.dp))

        // 注册按钮
        Box(
                Modifier.fillMaxWidth()
                        .height(48.dp)
                        .clip(RoundedCornerShape(24.dp))
                        .background(if (canSubmit) XcagiTheme.extra.brandBlue else MaterialTheme.colorScheme.outlineVariant)
                        .clickable(enabled = canSubmit) {
                            vm.register(u, p, e) { if (it) onBack() }
                        },
                contentAlignment = Alignment.Center,
        ) { Text("注册", fontSize = 16.sp, fontWeight = FontWeight.Medium, color = Color.White) }
    }
}
