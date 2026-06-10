package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.R
import com.xiuci.xcagi.mobile.core.ProductSkuConfig
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.components.mobile.ComplianceFooter
import com.xiuci.xcagi.mobile.ui.components.mobile.WeAvatar
import com.xiuci.xcagi.mobile.ui.components.mobile.WeBlockOutlinedButton
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeCellGroup
import com.xiuci.xcagi.mobile.ui.components.mobile.WeInputCell
import com.xiuci.xcagi.mobile.ui.components.mobile.WeModeCapsule
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
            .background(MaterialTheme.colorScheme.background),
    ) {
        if (fromProfile || loggedIn) {
            WeTopBar(title = "连接电脑", onBack = onBack)
        }

        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(vertical = 16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (!fromProfile && !loggedIn) {
                Column(
                    Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 24.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    WeAvatar(
                        size = 72.dp,
                        content = {
                            Icon(
                                painter = painterResource(R.mipmap.ic_launcher_foreground),
                                contentDescription = null,
                                modifier = Modifier.size(52.dp),
                                tint = Color.Unspecified,
                            )
                        },
                    )
                    WeSpacer(16.dp)
                    Text(
                        stringResource(R.string.app_name),
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        "独立客户端，可与电脑协同，也可直接使用云端。",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                }
                WeSpacer(8.dp)
                AuthPrimaryButton(text = "进入云端使用", onClick = onSkipCloud)
                WeBlockOutlinedButton(
                    text = if (pcExpanded) "收起电脑连接" else "连接电脑（可选）",
                    onClick = { pcExpanded = !pcExpanded },
                )
            }

            if (fromProfile || loggedIn || pcExpanded) {
                WeSectionCaption("连接电脑")
                WeCellGroup {
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
                WeCellGroup {
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
                AuthPrimaryButton(
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
                    WeCellGroup {
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
                    AuthPrimaryButton(text = "使用云端并登录", onClick = onNext)
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

    Column(
        Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background),
    ) {
        Column(
            Modifier
                .weight(1f)
                .verticalScroll(rememberScrollState())
                .padding(top = 48.dp, bottom = 16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            WeAvatar(
                size = 80.dp,
                content = {
                    Icon(
                        painter = painterResource(R.mipmap.ic_launcher_foreground),
                        contentDescription = null,
                        modifier = Modifier.size(60.dp),
                        tint = Color.Unspecified,
                    )
                },
            )
            WeSpacer(20.dp)
            Text(
                title,
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onBackground,
            )
            Text(
                stringResource(R.string.company_name),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 4.dp),
            )
            Text(
                subtitle,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(horizontal = 32.dp, vertical = 12.dp),
            )

            WeModeCapsule(
                options = listOf(
                    WeModeOption("account", accountLabel),
                    WeModeOption("phone", "手机号"),
                ),
                selectedId = if (tab == 0) "account" else "phone",
                onSelect = { tab = if (it == "account") 0 else 1 },
                modifier = Modifier.padding(horizontal = 16.dp),
            )

            WeSpacer(16.dp)

            WeCellGroup {
                if (tab == 0) {
                    WeInputCell(
                        label = "用户名",
                        value = user,
                        onValueChange = { user = it },
                        placeholder = "请输入用户名",
                    )
                    WeInputCell(
                        label = "密码",
                        value = pass,
                        onValueChange = { pass = it },
                        placeholder = "请输入密码",
                        showDivider = false,
                        visualTransformation = PasswordVisualTransformation(),
                    )
                } else {
                    WeInputCell(
                        label = "手机号",
                        value = phone,
                        onValueChange = { phone = it },
                        placeholder = "请输入手机号",
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
                    )
                    AuthCodeInputRow(
                        value = code,
                        onValueChange = { code = it },
                        onSend = { vm.sendCode(phone) },
                    )
                }
            }

            if (tab == 0) {
                Text(
                    "默认直连云端；仅当已连接电脑且电脑在线时，才走电脑端会话。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 32.dp, vertical = 8.dp),
                )
            }

            WeSpacer(20.dp)

            if (tab == 0) {
                AuthPrimaryButton(
                    text = "登录",
                    onClick = { vm.loginFhd(user, pass) { if (it) onDone() } },
                )
                if (!isEnterprise) {
                    TextButton(
                        onClick = onRegister,
                        modifier = Modifier.padding(top = 4.dp),
                    ) {
                        Text(
                            "还没有账号？立即注册",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.secondary,
                        )
                    }
                }
            } else {
                AuthPrimaryButton(
                    text = "登录",
                    onClick = { vm.loginPhone(phone, code) { if (it) onDone() } },
                )
            }
        }

        ComplianceFooter(appConfig, Modifier.padding(bottom = 12.dp))
    }
}

@Composable
private fun AuthPrimaryButton(
    text: String,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    Button(
        onClick = onClick,
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
            .height(50.dp),
        shape = androidx.compose.foundation.shape.RoundedCornerShape(10.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = MaterialTheme.colorScheme.secondary,
            contentColor = MaterialTheme.colorScheme.onSecondary,
        ),
    ) {
        Text(text, style = MaterialTheme.typography.bodyLarge)
    }
}

@Composable
private fun AuthCodeInputRow(
    value: String,
    onValueChange: (String) -> Unit,
    onSend: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            "验证码",
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.width(80.dp),
        )
        OutlinedTextField(
            value = value,
            onValueChange = onValueChange,
            modifier = Modifier.weight(1f),
            placeholder = {
                Text(
                    "请输入验证码",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            colors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = Color.Transparent,
                unfocusedBorderColor = Color.Transparent,
                errorBorderColor = Color.Transparent,
                disabledBorderColor = Color.Transparent,
            ),
            textStyle = MaterialTheme.typography.bodyMedium,
        )
        TextButton(
            onClick = onSend,
            contentPadding = PaddingValues(horizontal = 4.dp),
        ) {
            Text(
                "获取验证码",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.secondary,
            )
        }
    }
}
