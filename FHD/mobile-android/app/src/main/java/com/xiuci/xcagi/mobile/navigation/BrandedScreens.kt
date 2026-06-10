package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.xiuci.xcagi.mobile.R
import com.xiuci.xcagi.mobile.core.ProductSkuConfig
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.AuthScreenLayout
import com.xiuci.xcagi.mobile.ui.components.mobile.ComplianceFooter
import com.xiuci.xcagi.mobile.ui.components.mobile.MobileTokens
import com.xiuci.xcagi.mobile.ui.components.mobile.WeAuthCard
import com.xiuci.xcagi.mobile.ui.components.mobile.WeAuthGreenButton
import com.xiuci.xcagi.mobile.ui.components.mobile.WeAuthInputActionField
import com.xiuci.xcagi.mobile.ui.components.mobile.WeAuthInputField
import com.xiuci.xcagi.mobile.ui.components.mobile.WeAuthTabs
import com.xiuci.xcagi.mobile.ui.components.mobile.WeAvatar
import com.xiuci.xcagi.mobile.ui.components.mobile.WeBlockOutlinedButton
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeInputCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeModeOption
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSectionCaption
import com.xiuci.xcagi.mobile.ui.components.mobile.WeSpacer
import com.xiuci.xcagi.mobile.ui.components.mobile.WeTopBar

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
    val loggedIn by vm.isLoggedIn.collectAsState()
    var pcExpanded by remember { mutableStateOf(fromProfile) }
    var host by remember { mutableStateOf("192.168.1.100") }
    var prefix by remember { mutableStateOf("192.168.1") }
    var cloud by remember { mutableStateOf(true) }
    val scans by vm.scanResults.collectAsState()
    val savedHost by vm.fhdHost.collectAsState()

    LaunchedEffect(savedHost) {
        if (savedHost.isNotBlank()) host = savedHost.substringBefore(':').ifBlank { savedHost }
    }

    Column(
        Modifier
            .fillMaxSize()
            .background(MobileTokens.authPageBg)
            .imePadding(),
    ) {
        if (fromProfile || loggedIn) {
            WeTopBar(title = "连接电脑", onBack = onBack)
        }

        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(vertical = 20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (!fromProfile && !loggedIn) {
                Column(
                    Modifier
                        .fillMaxWidth()
                        .padding(horizontal = MobileTokens.authHorizontalMargin),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    WeAvatar(
                        size = 80.dp,
                        content = {
                            Icon(
                                painter = painterResource(R.mipmap.ic_launcher_foreground),
                                contentDescription = null,
                                modifier = Modifier.size(56.dp),
                                tint = Color.Unspecified,
                            )
                        },
                    )
                    WeSpacer(16.dp)
                    Text(
                        stringResource(R.string.app_name),
                        fontSize = 22.sp,
                        color = MobileTokens.authTextPrimary,
                        textAlign = TextAlign.Center,
                    )
                    Text(
                        "独立客户端，可与电脑协同，也可直接使用云端。",
                        fontSize = 13.sp,
                        color = MobileTokens.authTextMuted,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                }
                WeSpacer(8.dp)
                WeAuthGreenButton(text = "进入云端使用", onClick = onSkipCloud)
                WeBlockOutlinedButton(
                    text = if (pcExpanded) "收起电脑连接" else "连接电脑（可选）",
                    onClick = { pcExpanded = !pcExpanded },
                )
            }

            if (fromProfile || loggedIn || pcExpanded) {
                WeSectionCaption("连接电脑")
                WeAuthCard {
                    WeInputCell(
                        label = "电脑 IP",
                        value = host,
                        onValueChange = { host = it },
                        placeholder = "192.168.1.100",
                    )
                    WeInputCell(
                        label = "网段前缀",
                        value = prefix,
                        onValueChange = { prefix = it },
                        placeholder = "192.168.1",
                        showDivider = false,
                    )
                }
                WeAuthCard {
                    WeCell(
                        title = "云端模式",
                        subtitle = "开启后优先使用云端能力",
                        showDivider = false,
                        trailing = {
                            Switch(cloud, { cloud = it; vm.setMode(it) })
                        },
                    )
                }
                WeSpacer(8.dp)
                WeAuthGreenButton(
                    text = "检测并保存",
                    onClick = {
                        vm.setHost(host)
                        vm.probeHealth(host) {
                            if (it) {
                                vm.setHost(host, markSetup = true)
                                if (fromProfile || loggedIn) onBack?.invoke() else onNext()
                            } else {
                                vm.snack("无法连接", true)
                            }
                        }
                        Unit
                    },
                )
                WeBlockOutlinedButton(text = "扫描局域网", onClick = { vm.scanSubnet(prefix) })
                if (scans.isNotEmpty()) {
                    WeSectionCaption("扫描结果")
                    WeAuthCard {
                        scans.forEachIndexed { index, ip ->
                            WeCell(
                                title = ip,
                                showArrow = true,
                                showDivider = index < scans.lastIndex,
                                onClick = { host = ip; vm.setHost(ip) },
                            )
                        }
                    }
                }
                WeBlockOutlinedButton(text = "扫码配对", onClick = onScan)
                WeBlockOutlinedButton(text = "入网申请", onClick = { vm.lanRequest("Android") })
                if (!fromProfile && !loggedIn && cloud) {
                    WeAuthGreenButton(text = "使用云端并登录", onClick = onNext)
                }
            }
        }
    }
}

@Composable
fun AuthScreen(vm: AppViewModel, onRegister: () -> Unit, onDone: () -> Unit) {
    var tab by remember { mutableStateOf(if (ProductSkuConfig.isEnterprise) 1 else 0) }
    var user by remember { mutableStateOf("") }
    var pass by remember { mutableStateOf("") }
    var phone by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    val appConfig by vm.appConfig.collectAsState()
    val isEnterprise = ProductSkuConfig.isEnterprise
    val accountLabel = if (isEnterprise) "企业账号" else "账号密码"
    val title = if (isEnterprise) "XCAGI 企业版" else "XCAGI 个人版"
    val subtitle = if (isEnterprise) {
        "与企业工作台同一账号，登录即用云端协同能力。"
    } else {
        "与官网 MODstore 同一账号，登录后工作台与云端能力直接可用。"
    }

    AuthScreenLayout(
        title = title,
        subtitle = subtitle,
        logoContent = {
            Icon(
                painter = painterResource(R.mipmap.ic_launcher_foreground),
                contentDescription = null,
                modifier = Modifier.size(58.dp),
                tint = Color.Unspecified,
            )
        },
        footer = {
            ComplianceFooter(appConfig, compact = true, modifier = Modifier.padding(bottom = 12.dp))
        },
        formContent = {
            WeAuthTabs(
                options = listOf(
                    WeModeOption("account", accountLabel),
                    WeModeOption("phone", "手机号"),
                ),
                selectedId = if (tab == 0) "account" else "phone",
                onSelect = { tab = if (it == "account") 0 else 1 },
            )
            Spacer(Modifier.padding(top = 4.dp))
            if (tab == 0) {
                WeAuthInputField(
                    label = "用户名",
                    value = user,
                    onValueChange = { user = it },
                    placeholder = "请输入用户名",
                )
                WeAuthInputField(
                    label = "密码",
                    value = pass,
                    onValueChange = { pass = it },
                    placeholder = "请输入密码",
                    showDivider = false,
                    visualTransformation = PasswordVisualTransformation(),
                )
            } else {
                WeAuthInputField(
                    label = "手机号",
                    value = phone,
                    onValueChange = { phone = it },
                    placeholder = "请输入手机号",
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
                )
                WeAuthInputActionField(
                    label = "验证码",
                    value = code,
                    onValueChange = { code = it },
                    placeholder = "请输入验证码",
                    actionLabel = "获取验证码",
                    onAction = { vm.sendCode(phone) },
                    showDivider = false,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                )
            }
            Spacer(Modifier.padding(bottom = 8.dp))
        },
        actions = {
            if (tab == 0) {
                WeAuthGreenButton(
                    text = "登录",
                    onClick = { vm.loginFhd(user, pass) { if (it) onDone() } },
                )
                if (!isEnterprise) {
                    Text(
                        "个人版注册",
                        fontSize = 14.sp,
                        color = MobileTokens.accent(),
                        textAlign = TextAlign.Center,
                        modifier = Modifier
                            .padding(top = 16.dp)
                            .clickable(onClick = onRegister),
                    )
                }
                Text(
                    "默认直连云端；仅当已连接电脑且电脑在线时，才走电脑端会话。",
                    fontSize = 12.sp,
                    color = MobileTokens.authTextMuted,
                    textAlign = TextAlign.Center,
                    modifier = Modifier
                        .padding(horizontal = MobileTokens.authHorizontalMargin)
                        .padding(top = 12.dp),
                )
            } else {
                WeAuthGreenButton(
                    text = "登录",
                    onClick = { vm.loginPhone(phone, code) { if (it) onDone() } },
                )
            }
        },
    )
}
