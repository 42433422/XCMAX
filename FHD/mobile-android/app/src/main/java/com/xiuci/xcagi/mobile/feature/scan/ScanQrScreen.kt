@file:OptIn(androidx.camera.core.ExperimentalGetImage::class)

package com.xiuci.xcagi.mobile.feature.scan

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.VibrationEffect
import android.os.Vibrator
import android.provider.MediaStore
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.FlashOff
import androidx.compose.material.icons.filled.FlashOn
import androidx.compose.material.icons.filled.PhotoLibrary
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.common.InputImage
import com.xiuci.xcagi.mobile.core.network.PairingQrCodec
import com.xiuci.xcagi.mobile.ui.AppViewModel
import com.xiuci.xcagi.mobile.ui.theme.XcagiTheme
import kotlinx.coroutines.delay
import java.util.concurrent.Executors

// ─────────────────────────────────────────────────────────────────────────────
// ScanQrScreen  ─  大厂级扫码页面（微信/支付宝风格）
// 特性：取景框+四角边框+扫描线动画+蒙层+闪光灯+相册选图+震动反馈+手动输入弹窗
// ─────────────────────────────────────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class, ExperimentalGetImage::class)
@Composable
fun ScanQrScreen(vm: AppViewModel, onBack: () -> Unit) {
        val ctx = LocalContext.current
        val lifecycleOwner = LocalLifecycleOwner.current
        val vibrator = remember {
                ctx.getSystemService(android.content.Context.VIBRATOR_SERVICE) as? Vibrator
        }
        val scope = rememberCoroutineScope()

        // ── 状态 ──
        var hasCamera by remember {
                mutableStateOf(
                        ContextCompat.checkSelfPermission(ctx, Manifest.permission.CAMERA) ==
                                PackageManager.PERMISSION_GRANTED,
                )
        }
        var scanned by remember { mutableStateOf(false) }
        var flashOn by remember { mutableStateOf(false) }
        var showManualInput by remember { mutableStateOf(false) }
        var showSuccess by remember { mutableStateOf(false) }
        var nonce by remember { mutableStateOf("") }
        var authQrId by remember { mutableStateOf("") }
        var authAccountKind by remember { mutableStateOf("") }
        var authUsername by remember { mutableStateOf("") }
        var authPassword by remember { mutableStateOf("") }

        // ── 权限请求 ──
        val permissionLauncher =
                rememberLauncherForActivityResult(
                        ActivityResultContracts.RequestPermission(),
                ) { granted -> hasCamera = granted }

        // ── 相册选图 ──
        val pickImageLauncher =
                rememberLauncherForActivityResult(
                        ActivityResultContracts.StartActivityForResult(),
                ) { result ->
                        result.data?.data?.let { uri ->
                                tryScanFromUri(
                                        uri,
                                        ctx,
                                        onResult = { raw ->
                                                handleScanResult(
                                                        raw,
                                                        vm,
                                                        onBack,
                                                        nonceState = { nonce = it },
                                                        authQrIdState = { authQrId = it },
                                                        authAccountKindState = { authAccountKind = it },
                                                        scannedState = { scanned = it },
								onSuccess = { showSuccess = true },
                                                )
                                        }
                                )
                        }
                }

        // ── 震动反馈 ──
        fun vibrateSuccess() {
                vibrator?.vibrate(
                        VibrationEffect.createOneShot(80, VibrationEffect.DEFAULT_AMPLITUDE)
                )
        }

        Column(Modifier.fillMaxSize().background(Color.Black)) {
                // ── 顶栏：黑色半透明背景 ──
                Row(
                        Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                ) {
                        IconButton(onClick = onBack) {
                                Icon(
                                        Icons.AutoMirrored.Filled.ArrowBack,
                                        contentDescription = "返回",
                                        tint = Color.White,
                                )
                        }
                        Text(
                                "扫一扫",
                                color = Color.White,
                                fontSize = MaterialTheme.typography.titleMedium.fontSize,
                                fontWeight = FontWeight.Medium,
                        )
                        Spacer(Modifier.weight(1f))
                        // 闪光灯按钮
                        if (hasCamera && !scanned) {
                                IconButton(
                                        onClick = { flashOn = !flashOn },
                                ) {
                                        Icon(
                                                if (flashOn) Icons.Default.FlashOn
                                                else Icons.Default.FlashOff,
                                                contentDescription =
                                                        if (flashOn) "关闭闪光灯" else "打开闪光灯",
                                                tint = Color.White,
                                        )
                                }
                        }
                        // 相册按钮
                        IconButton(
                                onClick = {
                                        val intent =
                                                Intent(Intent.ACTION_PICK).apply {
                                                        type = "image/*"
                                                }
                                        pickImageLauncher.launch(intent)
                                },
                        ) {
                                Icon(
                                        Icons.Default.PhotoLibrary,
                                        contentDescription = "从相册选择",
                                        tint = Color.White,
                                )
                        }
                }

                // ── 相机预览区域（含取景框） ──
                Box(Modifier.weight(1f)) {
                        if (hasCamera) {
                                AndroidView(
                                        factory = { PreviewView(it) },
                                        modifier = Modifier.fillMaxSize(),
                                ) { previewView ->
                                        val cameraProviderFuture =
                                                ProcessCameraProvider.getInstance(ctx)
                                        cameraProviderFuture.addListener(
                                                {
                                                        val cameraProvider =
                                                                cameraProviderFuture.get()
                                                        val preview =
                                                                Preview.Builder().build().also {
                                                                        it.surfaceProvider =
                                                                                previewView
                                                                                        .surfaceProvider
                                                                }
                                                        val analyzer =
                                                                ImageAnalysis.Builder()
                                                                        .build()
                                                                        .also { analysis ->
                                                                                analysis
                                                                                        .setAnalyzer(
                                                                                                Executors
                                                                                                        .newSingleThreadExecutor()
                                                                                        ) {
                                                                                                imageProxy
                                                                                                ->
                                                                                                if (scanned
                                                                                                ) {
                                                                                                        imageProxy
                                                                                                                .close()
                                                                                                        return@setAnalyzer
                                                                                                }
                                                                                                @Suppress("UnsafeOptInUsageError")
                                                                                                val mediaImage =
                                                                                                        imageProxy
                                                                                                                .image
                                                                                                if (mediaImage !=
                                                                                                                null
                                                                                                ) {
                                                                                                        val image =
                                                                                                                InputImage
                                                                                                                        .fromMediaImage(
                                                                                                                                mediaImage,
                                                                                                                                imageProxy
                                                                                                                                        .imageInfo
                                                                                                                                        .rotationDegrees,
                                                                                                                        )
                                                                                                        BarcodeScanning
                                                                                                                .getClient()
                                                                                                                .process(
                                                                                                                        image
                                                                                                                )
                                                                                                                .addOnSuccessListener {
                                                                                                                        barcodes
                                                                                                                        ->
                                                                                                                        val raw =
                                                                                                                                barcodes.firstOrNull()
                                                                                                                                        ?.rawValue
                                                                                                                        if (!raw.isNullOrBlank()
                                                                                                                        ) {
                                                                                                                                scanned =
                                                                                                                                        true
                                                                                                                                vibrateSuccess()
                                                                                                                                handleScanResult(
                                                                                                                                        raw,
                                                                                                                                        vm,
                                                                                                                                        onBack,
                                                                                                                                        nonceState = {
                                                                                                                                                nonce =
                                                                                                                                                        it
                                                                                                                                        },
                                                                                                                                        authQrIdState = {
                                                                                                                                                authQrId =
                                                                                                                                                        it
                                                                                                                                        },
                                                                                                                                        authAccountKindState = {
                                                                                                                                                authAccountKind =
                                                                                                                                                        it
                                                                                                                                        },
                                                                                                                                        scannedState = {
                                                                                                                                                scanned =
                                                                                                                                                        it
                                                                                                                                        },
													onSuccess = { showSuccess = true },
                                                                                                                                )
                                                                                                                        }
                                                                                                                }
                                                                                                                .addOnCompleteListener {
                                                                                                                        imageProxy
                                                                                                                                .close()
                                                                                                                }
                                                                                                } else {
                                                                                                        imageProxy
                                                                                                                .close()
                                                                                                }
                                                                                        }
                                                                        }
                                                        cameraProvider.unbindAll()
                                                        val camera =
                                                                cameraProvider.bindToLifecycle(
                                                                        lifecycleOwner,
                                                                        CameraSelector
                                                                                .DEFAULT_BACK_CAMERA,
                                                                        preview,
                                                                        analyzer,
                                                                )
                                                        // 闪光灯控制
                                                        camera.cameraControl.enableTorch(flashOn)
                                                },
                                                ContextCompat.getMainExecutor(ctx)
                                        )
                                }

                                // ── 取景框覆盖层：蒙层 + 四角边框 + 扫描线 ──
                                ScannerOverlay()
                        } else {
                                // 无权限状态
                                Column(
                                        Modifier.fillMaxSize(),
                                        horizontalAlignment = Alignment.CenterHorizontally,
                                        verticalArrangement = Arrangement.Center,
                                ) {
                                        Text(
                                                "需要相机权限以扫描配对二维码",
                                                color = Color.White.copy(alpha = 0.8f),
                                                fontSize = MaterialTheme.typography.bodyMedium.fontSize,
                                                textAlign = TextAlign.Center,
                                                modifier = Modifier.padding(horizontal = 32.dp),
                                        )
                                        Spacer(Modifier.height(20.dp))
                                        TextButton(
                                                onClick = {
                                                        permissionLauncher.launch(
                                                                Manifest.permission.CAMERA
                                                        )
                                                },
                                        ) { Text("授予相机权限", color = XcagiTheme.extra.brandBlue) }
                                        Spacer(Modifier.height(12.dp))
                                        TextButton(
                                                onClick = { showManualInput = true },
                                        ) {
                                                Text(
                                                        "手动输入配对码",
                                                        color = Color.White.copy(alpha = 0.7f)
                                                )
                                        }
                                }
                        }
                }

                // ── 底部提示文字 + 配对码快捷入口 ──
                if (hasCamera && !scanned) {
                        Column(
                                Modifier.fillMaxWidth(),
                                horizontalAlignment = Alignment.CenterHorizontally,
                        ) {
                                Text(
                                        "将电脑端显示的配对二维码放入框内，即可自动扫描",
                                        color = Color.White.copy(alpha = 0.6f),
                                        fontSize = MaterialTheme.typography.labelMedium.fontSize,
                                        textAlign = TextAlign.Center,
                                )
                                Spacer(Modifier.height(12.dp))
                                // v2: 快捷输入6位配对码入口（对标微信/钉钉）
                                TextButton(
                                        onClick = { showManualInput = true },
                                ) {
                                        Text(
                                                "手动输入配对码",
                                                color = XcagiTheme.extra.brandBlue,
                                                fontSize = MaterialTheme.typography.bodySmall.fontSize,
                                                fontWeight = FontWeight.Medium,
                                        )
                                }
                                Spacer(Modifier.height(8.dp))
                        }
                }
        }

        // ── 手动输入底部弹窗（v2: 配对码优先 + nonce 兼容） ──
        if (showManualInput) {
                ModalBottomSheet(
                        onDismissRequest = { showManualInput = false },
                        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
                        containerColor = MaterialTheme.colorScheme.surface,
                ) {
                        Column(
                                Modifier.fillMaxWidth()
                                        .padding(horizontal = 20.dp, vertical = 16.dp),
                                horizontalAlignment = Alignment.CenterHorizontally,
                        ) {
                                Text(
                                        "输入配对码",
                                        fontSize = MaterialTheme.typography.titleLarge.fontSize,
                                        fontWeight = FontWeight.Bold,
                                        color = MaterialTheme.colorScheme.onSurface,
                                )
                                Spacer(Modifier.height(6.dp))
                                Text(
                                        "请输入电脑端显示的6位数字配对码",
                                        fontSize = MaterialTheme.typography.labelMedium.fontSize,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                                Spacer(Modifier.height(20.dp))

                                // ── OTP 风格 6 位配对码输入框 ──
                                PairingCodeInput(
                                        value = nonce,
                                        onValueChange = { newValue ->
                                                // 只允许数字，最多6位
                                                val filtered = newValue.filter { it.isDigit() }.take(6)
                                                nonce = filtered
                                                // 满六位自动提交（对标微信/钉钉）
                                                if (filtered.length == 6) {
                                                        vm.exchangeQr(filtered) { ok ->
                                                                if (ok) {
                                                                        vm.completeSetup()
                                                                        showManualInput = false
                                                                        showSuccess = true
                                                                }
                                                        }
                                                }
                                        },
                                        onSubmit = {
                                                if (nonce.length == 6) {
                                                        vm.exchangeQr(nonce) { ok ->
                                                                if (ok) {
                                                                        vm.completeSetup()
                                                                        showManualInput = false
                                                                        showSuccess = true
                                                                }
                                                        }
                                                }
                                        },
                                )

                                Spacer(Modifier.height(16.dp))

                                // 配对按钮
                                com.xiuci.xcagi.mobile.ui.components.mobile.WeGreenButton(
                                        text = "连接",
                                        onClick = {
                                                if (nonce.length == 6) {
                                                        vm.exchangeQr(nonce) { ok ->
                                                                if (ok) {
                                                                        vm.completeSetup()
                                                                        showManualInput = false
                                                                        showSuccess = true
                                                                }
                                                        }
                                                } else if (nonce.isNotBlank()) {
                                                        // fallback: 非6位数字当 nonce 处理
                                                        vm.exchangeQr(nonce) { ok ->
                                                                if (ok) {
                                                                        vm.completeSetup()
                                                                        showManualInput = false
                                                                        showSuccess = true
                                                                }
                                                        }
                                                }
                                        },
                                        modifier = Modifier.fillMaxWidth(),
                                )

                                Spacer(Modifier.height(12.dp))

                                // Auth QR 模式（企业版扫码登录）
                                if (authQrId.isNotBlank()) {
                                        val authTargetLabel =
                                                if (authAccountKind == "admin") "管理端" else "企业端"
                                        Spacer(Modifier.height(4.dp))
                                        Text(
                                                "确认${authTargetLabel}扫码登录",
                                                style = MaterialTheme.typography.titleSmall,
                                                fontWeight = FontWeight.SemiBold,
                                                color = MaterialTheme.colorScheme.onSurface,
                                                modifier = Modifier.fillMaxWidth(),
                                        )
                                        Spacer(Modifier.height(8.dp))
                                        androidx.compose.foundation.text.BasicTextField(
                                                value = authUsername,
                                                onValueChange = { authUsername = it },
                                                modifier =
                                                        Modifier.fillMaxWidth()
                                                                .height(44.dp)
                                                                .clip(MaterialTheme.shapes.small)
                                                                .background(MaterialTheme.colorScheme.surfaceVariant)
                                                                .border(
                                                                        0.5.dp,
                                                                        MaterialTheme.colorScheme.outlineVariant,
                                                                        MaterialTheme.shapes.small
                                                                )
                                                                .padding(horizontal = 14.dp),
                                                textStyle =
                                                        MaterialTheme.typography.bodyMedium.copy(
                                                                color = MaterialTheme.colorScheme.onSurface,
                                                        ),
                                                singleLine = true,
                                                decorationBox = { inner ->
                                                        Box(
                                                                Modifier.fillMaxSize(),
                                                                contentAlignment =
                                                                        Alignment.CenterStart
                                                        ) {
                                                                if (authUsername.isEmpty()) {
                                                                        Text(
                                                                                if (authAccountKind == "admin") "管理员账号" else "企业账号",
                                                                                color =
                                                                                        MaterialTheme.colorScheme.onSurfaceVariant
                                                                        )
                                                                }
                                                                inner()
                                                        }
                                                },
                                        )
                                        Spacer(Modifier.height(10.dp))
                                        androidx.compose.foundation.text.BasicTextField(
                                                value = authPassword,
                                                onValueChange = { authPassword = it },
                                                modifier =
                                                        Modifier.fillMaxWidth()
                                                                .height(44.dp)
                                                                .clip(MaterialTheme.shapes.small)
                                                                .background(MaterialTheme.colorScheme.surfaceVariant)
                                                                .border(
                                                                        0.5.dp,
                                                                        MaterialTheme.colorScheme.outlineVariant,
                                                                        MaterialTheme.shapes.small
                                                                )
                                                                .padding(horizontal = 14.dp),
                                                textStyle =
                                                        MaterialTheme.typography.bodyMedium.copy(
                                                                color = MaterialTheme.colorScheme.onSurface
                                                ),
                                                singleLine = true,
                                                visualTransformation = PasswordVisualTransformation(),
                                                decorationBox = { inner ->
                                                        Box(
                                                                Modifier.fillMaxSize(),
                                                                contentAlignment =
                                                                        Alignment.CenterStart
                                                        ) {
                                                                if (authPassword.isEmpty()) {
                                                                        Text(
                                                                                "密码",
                                                                                color =
                                                                                        MaterialTheme.colorScheme.onSurfaceVariant
                                                                        )
                                                                }
                                                                inner()
                                                        }
                                                },
                                        )
                                        Spacer(Modifier.height(8.dp))
                                        com.xiuci.xcagi.mobile.ui.components.mobile.WeGreenButton(
                                                text = "确认${authTargetLabel}登录",
                                                onClick = {
                                                        vm.confirmAuthQr(
                                                                authQrId,
                                                                authUsername,
                                                                authPassword,
                                                                authAccountKind,
                                                        ) {
                                                                if (it) {
                                                                        showManualInput = false
                                                                        showSuccess = true
                                                                }
                                                        }
                                                },
                                                modifier = Modifier.fillMaxWidth(),
                                                enabled =
                                                        authUsername.isNotBlank() &&
                                                                authPassword.isNotBlank(),
                                        )
                                }

                                Spacer(Modifier.height(16.dp))
                        }
                }
        }

	// ── 配对成功动画覆盖层（微信/钉钉风格） ──
	if (showSuccess) {
		PairingSuccessOverlay(onDismiss = {
			showSuccess = false
			onBack()
		})
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// PairingSuccessOverlay  ─  配对成功全屏动画（微信/钉钉风格）
// ✓ 打勾动画 + 光晕扩散 + "配对成功" 文字 + 1.5s 后自动返回
// ─────────────────────────────────────────────────────────────────────────────

@Composable
private fun PairingSuccessOverlay(onDismiss: () -> Unit) {
	val scale by animateFloatAsState(
		targetValue = 1f,
		animationSpec = spring(dampingRatio = 0.6f, stiffness = 300f),
		label = "successScale",
	)
	val alpha by animateFloatAsState(
		targetValue = 1f,
		animationSpec = tween(400),
		label = "successAlpha",
	)

	LaunchedEffect(Unit) {
		delay(1600)
		onDismiss()
	}

	Box(
		modifier = Modifier
			.fillMaxSize()
			.background(Color.Black.copy(alpha = 0.82f)),
		contentAlignment = Alignment.Center,
	) {
		Column(horizontalAlignment = Alignment.CenterHorizontally) {
			// ✓ 圆形背景 + 打勾
		Box(
			modifier = Modifier
				.size(88.dp)
				.graphicsLayer(scaleX = scale, scaleY = scale, alpha = alpha)
				.background(XcagiTheme.extra.brandBlue, shape = CircleShape),
			contentAlignment = Alignment.Center,
		) {
			Canvas(modifier = Modifier.size(44.dp)) {
			val w = size.width
			val h = size.height
			// ✓ 勾的路径
			val checkPath = Path().apply {
				moveTo(w * 0.2f, h * 0.52f)
				lineTo(w * 0.42f, h * 0.72f)
				lineTo(w * 0.8f, h * 0.28f)
			}
			drawPath(
				path = checkPath,
				color = Color.White,
				style = Stroke(
					width = w * 0.08f,
					cap = StrokeCap.Round,
					join = StrokeJoin.Round,
				),
			)
		}
		}

		Spacer(Modifier.height(24.dp))

		Text(
			"配对成功",
			color = Color.White,
			fontSize = MaterialTheme.typography.headlineMedium.fontSize,
			fontWeight = FontWeight.Bold,
		)

		Spacer(Modifier.height(8.dp))

		Text(
			"手机与电脑已连接",
			color = Color.White.copy(alpha = 0.6f),
			fontSize = MaterialTheme.typography.bodySmall.fontSize,
		)
		}
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// ScannerOverlay  ─  扫描取景框覆盖层（微信风格）
// 四角边框 + 半透明蒙层 + 动态扫描线
// ─────────────────────────────────────────────────────────────────────────────

@Composable
private fun ScannerOverlay() {
        val frameSize = 220.dp
        val strokeWidth = 2.5.dp
        val brandBlue = XcagiTheme.extra.brandBlue

        // 扫描线动画：上下循环移动
        val infiniteTransition = rememberInfiniteTransition(label = "scanLine")
        val scanLineY by infiniteTransition.animateFloat(
                        initialValue = 0f,
                        targetValue = 1f,
                        animationSpec =
                                infiniteRepeatable(
                                        animation = tween(2500, easing = LinearEasing),
                                        repeatMode = RepeatMode.Restart,
                                ),
                        label = "scanLineY",
                )

        // 用 BoxWithConstraints 获取实际可用空间，精确计算蒙层
        androidx.compose.foundation.layout.BoxWithConstraints(Modifier.fillMaxSize()) {
                val containerW = maxWidth
                val containerH = maxHeight
                val maskTop = (containerH - frameSize) / 2
                val maskSide = (containerW - frameSize) / 2

                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        Canvas(modifier = Modifier.size(frameSize)) {
                                val w = size.width
                                val h = size.height
                                val cl = w * 0.13f // corner length ratio
                                val sw = strokeWidth.toPx()

                                // ── 四角边框（L型，每角两段） ──
                                drawContext.canvas.apply {
                                        // 左上
                                        drawRoundRect(
                                                Color.White,
                                                Offset(0f, 0f),
                                                Size(cl, sw),
                                                CornerRadius(sw / 2)
                                        )
                                        drawRoundRect(
                                                Color.White,
                                                Offset(0f, 0f),
                                                Size(sw, cl),
                                                CornerRadius(sw / 2)
                                        )
                                        // 右上
                                        drawRoundRect(
                                                Color.White,
                                                Offset(w - cl, 0f),
                                                Size(cl, sw),
                                                CornerRadius(sw / 2)
                                        )
                                        drawRoundRect(
                                                Color.White,
                                                Offset(w - sw, 0f),
                                                Size(sw, cl),
                                                CornerRadius(sw / 2)
                                        )
                                        // 左下
                                        drawRoundRect(
                                                Color.White,
                                                Offset(0f, h - sw),
                                                Size(cl, sw),
                                                CornerRadius(sw / 2)
                                        )
                                        drawRoundRect(
                                                Color.White,
                                                Offset(0f, h - cl),
                                                Size(sw, cl),
                                                CornerRadius(sw / 2)
                                        )
                                        // 右下
                                        drawRoundRect(
                                                Color.White,
                                                Offset(w - cl, h - sw),
                                                Size(cl, sw),
                                                CornerRadius(sw / 2)
                                        )
                                        drawRoundRect(
                                                Color.White,
                                                Offset(w - sw, h - cl),
                                                Size(sw, cl),
                                                CornerRadius(sw / 2)
                                        )
                                }

                                // ── 扫描线（品牌蓝色水平线 + 光晕，上下移动） ──
                                val lineY = scanLineY * h
                                drawLine(
                                        color = brandBlue.copy(alpha = 0.7f),
                                        start = Offset(0f, lineY),
                                        end = Offset(w, lineY),
                                        strokeWidth = sw * 1.5f,
                                )
                                // 扫描线上方渐变光晕
                                drawRect(
                                        color = brandBlue.copy(alpha = 0.08f),
                                        topLeft = Offset(0f, lineY - h * 0.15f),
                                        size = Size(w, h * 0.3f),
                                )
                        }
                }

                // ── 四周半透明蒙层（4 个矩形精确遮挡取景框外区域） ──
                val maskColor = Color.Black.copy(alpha = 0.55f)
                // 上蒙层
                Box(
                        Modifier.fillMaxWidth()
                                .height(maskTop.coerceAtLeast(0.dp))
                                .background(maskColor),
                )
                // 下蒙层
                Box(
                        Modifier.fillMaxWidth()
                                .align(Alignment.BottomCenter)
                                .height(maskTop.coerceAtLeast(0.dp))
                                .background(maskColor),
                )
                // 左蒙层
                Box(
                        Modifier.align(Alignment.CenterStart)
                                .width(maskSide.coerceAtLeast(0.dp))
                                .fillMaxHeight()
                                .background(maskColor),
                )
                // 右蒙层
                Box(
                        Modifier.align(Alignment.CenterEnd)
                                .width(maskSide.coerceAtLeast(0.dp))
                                .fillMaxHeight()
                                .background(maskColor),
                )
        }
}

// ─────────────────────────────────────────────────────────────────────────────
// PairingCodeInput  ─  OTP 风格 6 位配对码输入框（对标微信/钉钉配对体验）
// 6 个独立方格 + 自动聚焦 + 数字键盘 + 提交回调
// ─────────────────────────────────────────────────────────────────────────────

@Composable
private fun PairingCodeInput(
        value: String,
        onValueChange: (String) -> Unit,
        onSubmit: () -> Unit,
) {
        val digitCount = 6
        Row(
                horizontalArrangement = Arrangement.spacedBy(10.dp, Alignment.CenterHorizontally),
                modifier = Modifier.fillMaxWidth(),
        ) {
                repeat(digitCount) { index ->
                        val isFocused = index == value.length && value.length < digitCount
                        val char = value.getOrNull(index)?.toString() ?: ""
                        Box(
                                modifier = Modifier
                                        .size(width = 46.dp, height = 54.dp)
                                        .clip(MaterialTheme.shapes.small)
                                        .background(MaterialTheme.colorScheme.surfaceVariant)
                                        .border(
                                                width = if (isFocused) 1.8.dp else 0.7.dp,
                                                color = if (isFocused) XcagiTheme.extra.brandBlue else MaterialTheme.colorScheme.outlineVariant,
                                                shape = MaterialTheme.shapes.small,
                                        ),
                                contentAlignment = Alignment.Center,
                        ) {
                                Text(
                                        text = char,
                                        fontSize = MaterialTheme.typography.displayMedium.fontSize,
                                        fontWeight = FontWeight.Bold,
                                        color = if (char.isNotBlank()) MaterialTheme.colorScheme.onSurface else Color.Transparent,
                                )
                        }
                }
        }

        // 隐藏的输入框（用于接收键盘输入）
        androidx.compose.foundation.text.BasicTextField(
                value = value,
                onValueChange = onValueChange,
                modifier = Modifier.height(1.dp), // 隐藏但保持焦点
                textStyle = androidx.compose.ui.text.TextStyle(fontSize = 1.sp, color = Color.Transparent),
                singleLine = true,
                keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                        keyboardType = androidx.compose.ui.text.input.KeyboardType.Number,
                        imeAction = androidx.compose.ui.text.input.ImeAction.Done,
                ),
                keyboardActions = androidx.compose.foundation.text.KeyboardActions(
                        onDone = { onSubmit() },
                ),
        )
}

// ─────────────────────────────────────────────────────────────────────────────
// 业务逻辑：处理扫描结果
// ─────────────────────────────────────────────────────────────────────────────

private fun handleScanResult(
        raw: String,
        vm: AppViewModel,
        onBack: () -> Unit,
        nonceState: (String) -> Unit,
        authQrIdState: (String) -> Unit,
        authAccountKindState: (String) -> Unit,
        scannedState: (Boolean) -> Unit,
        onSuccess: () -> Unit,
) {
        val authMatch = Regex("(?:[?&])qr_id=([^&]+)").find(raw)
        when {
                raw.contains("auth-qr") && authMatch != null -> {
                        authQrIdState(decodeQrValue(authMatch.groupValues[1]))
                        authAccountKindState(authQrParam(raw, "account_kind").orEmpty())
                        // auth-qr 模式需要用户输入账号密码，不自动返回
                }
                else -> {
                        val parsed = PairingQrCodec.parse(raw)
                        if (parsed != null) {
                                nonceState(parsed.nonce)
                        } else {
                                nonceState(raw)
                        }
                        vm.exchangeQr(raw) { ok ->
                                if (ok) {
                                        vm.completeSetup()
                                        onSuccess()
                                } else {
                                        scannedState(false)
                                }
                        }
                }
        }
}

private fun authQrParam(raw: String, key: String): String? =
        Regex("(?:[?&])${Regex.escape(key)}=([^&]+)")
                .find(raw)
                ?.groupValues
                ?.getOrNull(1)
                ?.let(::decodeQrValue)
                ?.trim()
                ?.lowercase()
                ?.takeIf { it.isNotBlank() }

private fun decodeQrValue(value: String): String =
        runCatching { java.net.URLDecoder.decode(value, "UTF-8") }.getOrElse { value }

private fun tryScanFromUri(
        uri: android.net.Uri,
        ctx: android.content.Context,
        onResult: (String) -> Unit,
) {
        try {
                val bitmap = MediaStore.Images.Media.getBitmap(ctx.contentResolver, uri)
                val image = InputImage.fromBitmap(bitmap, 0)
                BarcodeScanning.getClient()
                        .process(image)
                        .addOnSuccessListener { barcodes ->
                                val raw = barcodes.firstOrNull()?.rawValue
                                if (!raw.isNullOrBlank()) {
                                        onResult(raw)
                                }
                        }
                        .addOnFailureListener { /* 静默 */}
        } catch (_: Exception) {
                /* 静默 */
        }
}
