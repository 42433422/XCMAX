package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.xiuci.xcagi.mobile.R
import com.xiuci.xcagi.mobile.core.ProductSkuConfig
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.WeAuthOtpField
import com.xiuci.xcagi.mobile.ui.components.mobile.WeAvatar
import com.xiuci.xcagi.mobile.ui.components.mobile.WeTopBar
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme
import kotlinx.coroutines.delay

// ─────────────────────────────────────────────────────────────────────────────
// ConnectScreen  ─  连接电脑页（白底+Logo+按钮，飞书风格）
// ─────────────────────────────────────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ConnectScreen(
        vm: AppViewModel,
        fromProfile: Boolean,
        onNext: () -> Unit,
        onScan: () -> Unit,
        onSkipCloud: () -> Unit,
        onBack: (() -> Unit)? = null,
) {
        Column(
                Modifier.fillMaxSize().background(Color.White).imePadding(),
        ) {
                WeTopBar(title = "Agent 远程控制", onBack = onBack)

                Column(
                        Modifier.fillMaxSize()
                                .verticalScroll(rememberScrollState())
                                .padding(vertical = 40.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(16.dp),
                ) {
                        Icon(
                                painter = painterResource(R.mipmap.ic_launcher_foreground),
                                contentDescription = null,
                                modifier = Modifier.size(72.dp),
                                tint = Color.Unspecified,
                        )
                        Text(
                                "Agent 远程控制",
                                fontSize = MaterialTheme.typography.headlineSmall.fontSize,
                                fontWeight = FontWeight.SemiBold,
                                color = MaterialTheme.colorScheme.onSurface,
                        )
                        Text(
                                "绑定电脑后，手机可远程操控电脑执行任务、运行命令，如同你的 AI Agent 助手。",
                                fontSize = MaterialTheme.typography.bodySmall.fontSize,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                textAlign = TextAlign.Center,
                                modifier = Modifier.padding(horizontal = 40.dp),
                        )
                        Spacer(Modifier.height(8.dp))
                        LoginPrimaryButton(text = "扫描绑定", onClick = onScan)
                        LoginSecondaryButton(
                                text = "返回",
                                onClick = { onBack?.invoke() ?: onSkipCloud() }
                        )
                }
        }
}

// ─────────────────────────────────────────────────────────────────────────────
// AuthScreen  ─  登录页（精确复刻截图：白底+Logo+无Tab+输入框+眼睛+灰色按钮+勾选）
// ─────────────────────────────────────────────────────────────────────────────

private enum class AuthLoginMode {
        PASSWORD,
        PHONE,
}

@Composable
fun AuthScreen(vm: AppViewModel, onRegister: () -> Unit, onDone: () -> Unit) {
        var loginMode by remember { mutableStateOf(AuthLoginMode.PASSWORD) }
        var user by remember { mutableStateOf("") }
        var pass by remember { mutableStateOf("") }
        var phone by remember { mutableStateOf("") }
        var otpCode by remember { mutableStateOf("") }
        var passwordVisible by remember { mutableStateOf(false) }
        var agreed by remember { mutableStateOf(true) }
        var loggingIn by remember { mutableStateOf(false) }
        var adminMode by remember { mutableStateOf(false) }
        var rememberPass by remember { mutableStateOf(false) }
        var autoLogin by remember { mutableStateOf(false) }
        var loginError by remember { mutableStateOf<String?>(null) }
        var codeCooldown by remember { mutableStateOf(0) }
        var sendingCode by remember { mutableStateOf(false) }
        val appConfig by vm.appConfig.collectAsState()
        val ctx = androidx.compose.ui.platform.LocalContext.current
        val sessionStore = com.xiuci.xcagi.mobile.core.datastore.SessionStore(ctx)

        // 从持久化存储恢复已保存的账号密码和选项状态
        androidx.compose.runtime.LaunchedEffect(Unit) {
                user = sessionStore.savedUsername()
                pass = sessionStore.savedPassword()
                rememberPass = sessionStore.isRememberPass()
                autoLogin = sessionStore.isAutoLogin()
        }
        val isEnterprise = ProductSkuConfig.isEnterprise
        val title = if (isEnterprise) "XCAGI 企业版" else "XCAGI 个人版"
        val subtitle =
                if (isEnterprise) {
                        "智能协同，助力企业经营"
                } else {
                        "与官网 MODstore 同一账号，登录后可同步能力。"
                }

        Column(
                Modifier.fillMaxSize()
                        .background(Color.White)
                        .imePadding()
                        .verticalScroll(rememberScrollState()),
                horizontalAlignment = Alignment.CenterHorizontally,
        ) {
                // ── Logo + 标题区（截图对齐） ──
                Spacer(Modifier.height(60.dp))
                WeAvatar(
                        size = 96.dp,
                        content = {
                                Icon(
                                        painter = painterResource(R.mipmap.ic_launcher_foreground),
                                        contentDescription = null,
                                        modifier = Modifier.size(68.dp),
                                        tint = Color.Unspecified,
                                )
                        },
                )
                Spacer(Modifier.height(20.dp))
                Text(
                        title,
                        fontSize = 22.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = MaterialTheme.colorScheme.onSurface,
                        textAlign = TextAlign.Center,
                )
                Spacer(Modifier.height(6.dp))
                Text(
                        subtitle,
                        fontSize = MaterialTheme.typography.labelMedium.fontSize,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.Center,
                )
                Spacer(Modifier.height(24.dp))

                // ── 密码 / 手机号登录切换 ──
                Row(
                        Modifier.fillMaxWidth().padding(horizontal = 24.dp),
                        horizontalArrangement = Arrangement.spacedBy(24.dp),
                ) {
                        LoginTab(
                                label = "密码登录",
                                selected = loginMode == AuthLoginMode.PASSWORD,
                                onClick = { loginMode = AuthLoginMode.PASSWORD },
                        )
                        LoginTab(
                                label = "手机号登录",
                                selected = loginMode == AuthLoginMode.PHONE,
                                onClick = { loginMode = AuthLoginMode.PHONE },
                        )
                }
                Spacer(Modifier.height(20.dp))

                androidx.compose.runtime.LaunchedEffect(codeCooldown) {
                        if (codeCooldown > 0) {
                                delay(1000)
                                codeCooldown -= 1
                        }
                }

                // ── 管理员切换（企业版） ──
                if (isEnterprise && loginMode == AuthLoginMode.PASSWORD) {
                        Text(
                                if (adminMode) "切换为市场账号" else "管理员账号登录",
                                fontSize = MaterialTheme.typography.labelMedium.fontSize,
                                fontWeight = FontWeight.Medium,
                                color = XcagiTheme.extra.brandBlue,
                                textAlign = TextAlign.Center,
                                modifier = Modifier.clickable { adminMode = !adminMode },
                        )
                        Spacer(Modifier.height(20.dp))
                }

                // ── 输入框 ──
                if (loginMode == AuthLoginMode.PASSWORD) {
                        LoginInputBox(
                                value = user,
                                onValueChange = { user = it },
                                placeholder =
                                        when {
                                                adminMode -> "管理员账号"
                                                isEnterprise -> "市场账号或邮箱"
                                                else -> "请输入用户名"
                                        },
                        )
                        Spacer(Modifier.height(14.dp))
                        LoginPasswordBox(
                                value = pass,
                                onValueChange = { pass = it },
                                visible = passwordVisible,
                                onToggleVisibility = { passwordVisible = !passwordVisible },
                        )
                } else {
                        LoginInputBox(
                                value = phone,
                                onValueChange = { phone = it.filter { ch -> ch.isDigit() }.take(11) },
                                placeholder = "请输入手机号",
                        )
                        Spacer(Modifier.height(8.dp))
                        WeAuthOtpField(
                                actionLabel =
                                        when {
                                                sendingCode -> "发送中…"
                                                codeCooldown > 0 -> "${codeCooldown}s 后重发"
                                                else -> "获取验证码"
                                        },
                                onAction = {
                                        if (phone.length != 11 || codeCooldown > 0 || sendingCode) return@WeAuthOtpField
                                        sendingCode = true
                                        loginError = null
                                        vm.sendCode(phone) {
                                                sendingCode = false
                                                codeCooldown = 60
                                        }
                                },
                                value = otpCode,
                                onValueChange = { otpCode = it.filter { ch -> ch.isDigit() }.take(6) },
                                actionEnabled = phone.length == 11 && codeCooldown == 0 && !sendingCode,
                        )
                }

                Spacer(Modifier.height(28.dp))

                // ── 登录错误提示 ──
                if (loginError != null) {
                        Text(
                                loginError!!,
                                fontSize = MaterialTheme.typography.labelMedium.fontSize,
                                color = MaterialTheme.colorScheme.error,
                                modifier = Modifier.padding(horizontal = 24.dp),
                        )
                        Spacer(Modifier.height(8.dp))
                }

                // ── 登录按钮 ──
                val canLogin =
                        when (loginMode) {
                                AuthLoginMode.PASSWORD ->
                                        user.isNotBlank() && pass.isNotBlank() && agreed && !loggingIn
                                AuthLoginMode.PHONE ->
                                        phone.length == 11 && otpCode.length >= 4 && agreed && !loggingIn
                        }
                Box(
                        Modifier.fillMaxWidth()
                                .padding(horizontal = 24.dp)
                                .height(48.dp)
                                .clip(RoundedCornerShape(24.dp))
                                .background(
                                        if (canLogin) XcagiTheme.extra.brandBlue
                                        else MaterialTheme.colorScheme.outlineVariant
                                )
                                .clickable(enabled = canLogin) {
                                        loggingIn = true
                                        loginError = null
                                        when (loginMode) {
                                                AuthLoginMode.PASSWORD ->
                                                        vm.loginFhd(
                                                                user,
                                                                pass,
                                                                adminMode,
                                                                rememberPass,
                                                                autoLogin
                                                        ) {
                                                                loggingIn = false
                                                                if (it) onDone()
                                                                else loginError = "用户名或密码错误"
                                                        }
                                                AuthLoginMode.PHONE ->
                                                        vm.loginPhone(phone, otpCode) {
                                                                loggingIn = false
                                                                if (it) onDone()
                                                                else loginError = "验证码错误或已过期"
                                                        }
                                        }
                                },
                        contentAlignment = Alignment.Center,
                ) {
                        Text(
                                if (loggingIn) "登录中…" else "登录",
                                fontSize = MaterialTheme.typography.bodyLarge.fontSize,
                                fontWeight = FontWeight.Medium,
                                color = if (canLogin) Color.White else MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                }

                // ── 记住密码 / 免登录（密码模式） ──
                if (loginMode == AuthLoginMode.PASSWORD) {
                        Spacer(Modifier.height(14.dp))
                        Row(
                                Modifier.fillMaxWidth().padding(horizontal = 24.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.End,
                        ) {
                                LoginCheckbox(
                                        checked = rememberPass,
                                        onToggle = { rememberPass = !rememberPass },
                                        label = "记住密码"
                                )
                                Spacer(Modifier.width(20.dp))
                                LoginCheckbox(
                                        checked = autoLogin,
                                        onToggle = { autoLogin = !autoLogin },
                                        label = "免登录"
                                )
                        }
                }

                if (!isEnterprise && loginMode == AuthLoginMode.PASSWORD) {
                        Spacer(Modifier.height(12.dp))
                        Text(
                                "个人版注册",
                                fontSize = MaterialTheme.typography.bodySmall.fontSize,
                                fontWeight = FontWeight.Medium,
                                color = XcagiTheme.extra.brandBlue,
                                modifier = Modifier.clickable(onClick = onRegister),
                        )
                }

                Spacer(Modifier.weight(1f))

                // ── 协议勾选（截图：蓝色勾选框+文字） ──
                Row(
                        Modifier.fillMaxWidth().padding(horizontal = 32.dp, vertical = 16.dp),
                        verticalAlignment = Alignment.CenterVertically,
                ) {
                        Box(
                                Modifier.size(20.dp)
                                        .clip(MaterialTheme.shapes.extraSmall)
                                        .background(
                                                if (agreed) XcagiTheme.extra.brandBlue
                                                else MaterialTheme.colorScheme.outlineVariant
                                        )
                                        .border(
                                                if (!agreed) 0.5.dp else 0.dp,
                                                MaterialTheme.colorScheme.outlineVariant,
                                                MaterialTheme.shapes.extraSmall,
                                        )
                                        .clickable { agreed = !agreed },
                                contentAlignment = Alignment.Center,
                        ) {
                                if (agreed) {
                                        Icon(
                                                androidx.compose.material.icons.Icons.Default.Check,
                                                contentDescription = null,
                                                modifier = Modifier.size(14.dp),
                                                tint = Color.White,
                                        )
                                }
                        }
                        Spacer(Modifier.width(8.dp))
                        Text(
                                "已阅读并同意 ",
                                fontSize = MaterialTheme.typography.labelSmall.fontSize,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Text(
                                "服务协议",
                                fontSize = MaterialTheme.typography.labelSmall.fontSize,
                                fontWeight = FontWeight.Medium,
                                color = XcagiTheme.extra.brandBlue,
                                modifier =
                                        Modifier.clickable {
                                                val url =
                                                        appConfig?.terms_url?.takeIf {
                                                                it.isNotBlank()
                                                        }
                                                                ?: "https://xiu-ci.com/legal/terms"
                                                ctx.startActivity(
                                                        android.content.Intent(
                                                                android.content.Intent.ACTION_VIEW,
                                                                android.net.Uri.parse(url)
                                                        )
                                                )
                                        },
                        )
                        Text(
                                " 和 ",
                                fontSize = MaterialTheme.typography.labelSmall.fontSize,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Text(
                                "隐私政策",
                                fontSize = MaterialTheme.typography.labelSmall.fontSize,
                                fontWeight = FontWeight.Medium,
                                color = XcagiTheme.extra.brandBlue,
                                modifier =
                                        Modifier.clickable {
                                                val url =
                                                        appConfig?.privacy_url?.takeIf {
                                                                it.isNotBlank()
                                                        }
                                                                ?: "https://xiu-ci.com/legal/privacy"
                                                ctx.startActivity(
                                                        android.content.Intent(
                                                                android.content.Intent.ACTION_VIEW,
                                                                android.net.Uri.parse(url)
                                                        )
                                                )
                                        },
                        )
                }
                Spacer(Modifier.height(8.dp))
        }
}

// ─────────────────────────────────────────────────────────────────────────────
// 截图风格输入框组件
// ─────────────────────────────────────────────────────────────────────────────

/** 普通输入框（placeholder在内部，浅灰底+细边框） */
@Composable
private fun LoginInputBox(
        value: String,
        onValueChange: (String) -> Unit,
        placeholder: String,
) {
        val focusRequester = remember { FocusRequester() }
        var isFocused by remember { mutableStateOf(false) }
        Box(
                Modifier.fillMaxWidth()
                        .padding(horizontal = 24.dp)
                        .height(48.dp)
                        .clip(MaterialTheme.shapes.small)
                        .background(Color.White)
                        .border(
                                BorderStroke(
                                        1.dp,
                                        if (isFocused) XcagiTheme.extra.brandBlue
                                        else MaterialTheme.colorScheme.outlineVariant
                                ),
                                MaterialTheme.shapes.small
                        )
                        .padding(horizontal = 16.dp),
                contentAlignment = Alignment.CenterStart,
        ) {
                if (value.isEmpty()) {
                        Text(placeholder, fontSize = MaterialTheme.typography.bodyMedium.fontSize, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                BasicTextField(
                        value = value,
                        onValueChange = onValueChange,
                        modifier =
                                Modifier.fillMaxWidth()
                                        .focusRequester(focusRequester)
                                        .onFocusChanged { isFocused = it.isFocused },
                        singleLine = true,
                        textStyle =
                                MaterialTheme.typography.bodyLarge.copy(
                                        color = MaterialTheme.colorScheme.onSurface,
                                        fontSize = MaterialTheme.typography.bodyMedium.fontSize,
                                ),
                )
        }
}

/** 密码输入框（右侧眼睛图标） */
@Composable
private fun LoginPasswordBox(
        value: String,
        onValueChange: (String) -> Unit,
        visible: Boolean,
        onToggleVisibility: () -> Unit,
) {
        val focusRequester = remember { FocusRequester() }
        var isFocused by remember { mutableStateOf(false) }
        Box(
                Modifier.fillMaxWidth().padding(horizontal = 24.dp),
        ) {
                Box(
                        Modifier.fillMaxWidth()
                                .height(48.dp)
                                .clip(MaterialTheme.shapes.small)
                                .background(Color.White)
                                .border(
                                        BorderStroke(
                                                1.dp,
                                                if (isFocused) XcagiTheme.extra.brandBlue
                                                else MaterialTheme.colorScheme.outlineVariant
                                        ),
                                        MaterialTheme.shapes.small
                                )
                                .padding(start = 16.dp, end = 44.dp),
                        contentAlignment = Alignment.CenterStart,
                ) {
                        if (value.isEmpty()) {
                                Text("密码", fontSize = MaterialTheme.typography.bodyMedium.fontSize, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        BasicTextField(
                                value = value,
                                onValueChange = onValueChange,
                                modifier =
                                        Modifier.fillMaxWidth()
                                                .focusRequester(focusRequester)
                                                .onFocusChanged { isFocused = it.isFocused },
                                singleLine = true,
                                visualTransformation =
                                        if (visible) VisualTransformation.None
                                        else PasswordVisualTransformation(),
                                keyboardOptions =
                                        KeyboardOptions(keyboardType = KeyboardType.Password),
                                textStyle =
                                        MaterialTheme.typography.bodyLarge.copy(
                                                color = MaterialTheme.colorScheme.onSurface,
                                                fontSize = MaterialTheme.typography.bodyMedium.fontSize,
                                        ),
                        )
                }
                // 右侧眼睛图标（绝对定位在Box内）
                Icon(
                        if (visible) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                        contentDescription = if (visible) "隐藏密码" else "显示密码",
                        modifier =
                                Modifier.size(22.dp)
                                        .align(Alignment.CenterEnd)
                                        .padding(end = 12.dp)
                                        .clickable(onClick = onToggleVisibility),
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
        }
}

// ─────────────────────────────────────────────────────────────────────────────
// 登录页专用小组件
// ─────────────────────────────────────────────────────────────────────────────

@Composable
private fun LoginTab(
        label: String,
        selected: Boolean,
        onClick: () -> Unit,
        modifier: Modifier = Modifier,
) {
        Column(
                modifier.clickable(onClick = onClick).padding(vertical = 8.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
        ) {
                Text(
                        label,
                        fontSize = MaterialTheme.typography.bodyLarge.fontSize,
                        fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
                        color =
                                if (selected) MaterialTheme.colorScheme.onSurface
                                else MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(8.dp))
                Box(
                        Modifier.fillMaxWidth()
                                .height(2.5.dp)
                                .clip(RoundedCornerShape(1.25.dp))
                                .background(
                                        if (selected) XcagiTheme.extra.brandBlue else Color.Transparent
                                ),
                )
        }
}

@Composable
private fun LoginInputField(
        label: String,
        value: String,
        onValueChange: (String) -> Unit,
        modifier: Modifier = Modifier,
        placeholder: String = "",
        visualTransformation: VisualTransformation = VisualTransformation.None,
        keyboardOptions: KeyboardOptions = KeyboardOptions.Default,
) {
        Column(modifier.padding(horizontal = 24.dp)) {
                Text(
                        label,
                        fontSize = MaterialTheme.typography.labelMedium.fontSize,
                        fontWeight = FontWeight.Medium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(bottom = 6.dp),
                )
                Box(
                        Modifier.fillMaxWidth()
                                .height(48.dp)
                                .clip(MaterialTheme.shapes.small)
                                .background(MaterialTheme.colorScheme.surfaceVariant)
                                .border(0.5.dp, MaterialTheme.colorScheme.outlineVariant, MaterialTheme.shapes.small)
                                .padding(horizontal = 14.dp),
                        contentAlignment = Alignment.CenterStart,
                ) {
                        if (value.isEmpty() && placeholder.isNotBlank()) {
                                Text(
                                        placeholder,
                                        fontSize = MaterialTheme.typography.bodyMedium.fontSize,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                        }
                        BasicTextField(
                                value = value,
                                onValueChange = onValueChange,
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true,
                                visualTransformation = visualTransformation,
                                keyboardOptions = keyboardOptions,
                                textStyle =
                                        MaterialTheme.typography.bodyLarge.copy(
                                                color = MaterialTheme.colorScheme.onSurface
                                        ),
                        )
                }
        }
}

@Composable
private fun LoginPrimaryButton(
        text: String,
        onClick: () -> Unit,
        modifier: Modifier = Modifier,
        enabled: Boolean = true,
) {
        Box(
                modifier.fillMaxWidth()
                        .padding(horizontal = 24.dp)
                        .height(48.dp)
                        .clip(MaterialTheme.shapes.small)
                        .background(
                                if (enabled) XcagiTheme.extra.brandBlue
                                else XcagiTheme.extra.brandBlue.copy(alpha = 0.4f)
                        )
                        .clickable(enabled = enabled, onClick = onClick),
                contentAlignment = Alignment.Center,
        ) {
                Text(
                        text,
                        fontSize = MaterialTheme.typography.bodyLarge.fontSize,
                        fontWeight = FontWeight.Medium,
                        color = Color.White,
                )
        }
}

@Composable
private fun LoginSecondaryButton(
        text: String,
        onClick: () -> Unit,
        modifier: Modifier = Modifier,
) {
        Box(
                modifier.fillMaxWidth()
                        .padding(horizontal = 24.dp)
                        .height(48.dp)
                        .clip(MaterialTheme.shapes.small)
                        .border(0.5.dp, MaterialTheme.colorScheme.outlineVariant, MaterialTheme.shapes.small)
                        .background(Color.White)
                        .clickable(onClick = onClick),
                contentAlignment = Alignment.Center,
        ) {
                Text(
                        text,
                        fontSize = MaterialTheme.typography.bodyMedium.fontSize,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
        }
}

@Composable
private fun LoginCard(
        modifier: Modifier = Modifier,
        content: @Composable ColumnScope.() -> Unit,
) {
        androidx.compose.material3.Surface(
                modifier = modifier.fillMaxWidth().padding(horizontal = 24.dp),
                shape = MaterialTheme.shapes.medium,
                color = Color.White,
                tonalElevation = 0.dp,
                shadowElevation = 0.dp,
        ) { Column(content = content) }
}

@Composable
private fun LoginCheckbox(
        checked: Boolean,
        onToggle: () -> Unit,
        label: String,
) {
        Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.clickable(onClick = onToggle),
        ) {
                Box(
                        Modifier.size(18.dp)
                                .clip(RoundedCornerShape(3.dp))
                                .background(
                                        if (checked) XcagiTheme.extra.brandBlue
                                        else MaterialTheme.colorScheme.outlineVariant
                                )
                                .border(
                                        if (!checked) 0.5.dp else 0.dp,
                                        MaterialTheme.colorScheme.outlineVariant,
                                        RoundedCornerShape(3.dp),
                                ),
                        contentAlignment = Alignment.Center,
                ) {
                        if (checked) {
                                Icon(
                                        Icons.Default.Check,
                                        contentDescription = null,
                                        modifier = Modifier.size(12.dp),
                                        tint = Color.White,
                                )
                        }
                }
                Spacer(Modifier.width(6.dp))
                Text(
                        label,
                        fontSize = MaterialTheme.typography.labelMedium.fontSize,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
        }
}
