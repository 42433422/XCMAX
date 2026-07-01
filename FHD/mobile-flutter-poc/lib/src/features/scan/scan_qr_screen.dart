import 'package:flutter/material.dart';
import 'package:google_mlkit_barcode_scanning/google_mlkit_barcode_scanning.dart'
    as mlkit;
import 'package:image_picker/image_picker.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../policy/android_error_policy.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';

class ScanQrScreen extends StatefulWidget {
  const ScanQrScreen({
    super.key,
    this.repository,
    this.enableCamera = true,
  });

  final MobileRepository? repository;
  final bool enableCamera;

  @override
  State<ScanQrScreen> createState() => _ScanQrScreenState();
}

class _ScanQrScreenState extends State<ScanQrScreen> {
  late final MobileRepository _repository;
  late final MobileScannerController _scannerController;
  late final ImagePicker _imagePicker;
  late final mlkit.BarcodeScanner _albumScanner;
  var _flashOn = false;
  var _scanned = false;
  var _pairing = false;
  var _pickingAlbum = false;
  var _showSuccess = false;

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _scannerController = MobileScannerController(
      formats: const [BarcodeFormat.qrCode],
      facing: CameraFacing.back,
    );
    _imagePicker = ImagePicker();
    _albumScanner = mlkit.BarcodeScanner(
      formats: [mlkit.BarcodeFormat.qrCode],
    );
  }

  @override
  void dispose() {
    _scannerController.dispose();
    _albumScanner.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        children: [
          SafeArea(
            child: Column(
              children: [
                Padding(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 4, vertical: 8),
                  child: Row(
                    children: [
                      IconButton(
                        onPressed: () => Navigator.of(context).maybePop(),
                        icon: const Icon(Icons.arrow_back, color: Colors.white),
                        tooltip: '返回',
                      ),
                      const Text(
                        '扫一扫',
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 17,
                          height: 1.29,
                          fontWeight: FontWeight.w500,
                          letterSpacing: 0,
                        ),
                      ),
                      const Spacer(),
                      if (widget.enableCamera && !_scanned)
                        IconButton(
                          onPressed: _toggleTorch,
                          icon: Icon(
                            _flashOn ? Icons.flash_on : Icons.flash_off,
                            color: Colors.white,
                          ),
                          tooltip: _flashOn ? '关闭闪光灯' : '打开闪光灯',
                        ),
                      IconButton(
                        onPressed: _pickingAlbum ? null : _pickAlbum,
                        icon: const Icon(Icons.photo_library,
                            color: Colors.white),
                        tooltip: '从相册选择',
                      ),
                    ],
                  ),
                ),
                Expanded(
                  child: Stack(
                    alignment: Alignment.center,
                    children: [
                      if (widget.enableCamera)
                        MobileScanner(
                          controller: _scannerController,
                          fit: BoxFit.cover,
                          onDetect: _onDetect,
                          errorBuilder: (context, error) {
                            return _ScannerUnavailable(
                                onOpenManual: _showManualInput);
                          },
                        )
                      else
                        Container(color: Colors.black),
                      const Positioned.fill(child: _ScannerOverlay()),
                      if (_pairing)
                        Positioned.fill(
                          child: Container(
                            color: Colors.black.withValues(alpha: 0.38),
                            child: Center(
                              child: CircularProgressIndicator(
                                color: colors.brand,
                              ),
                            ),
                          ),
                        ),
                      if (_pickingAlbum)
                        Positioned.fill(
                          child: Container(
                            color: Colors.black.withValues(alpha: 0.38),
                            child: Center(
                              child: CircularProgressIndicator(
                                color: colors.brand,
                              ),
                            ),
                          ),
                        ),
                      Positioned(
                        bottom: 42,
                        left: 32,
                        right: 32,
                        child: Column(
                          children: [
                            Text(
                              '将电脑端显示的配对二维码放入框内，即可自动扫描',
                              textAlign: TextAlign.center,
                              style: TextStyle(
                                color: Colors.white.withValues(alpha: 0.6),
                                fontSize: 13,
                                height: 1.31,
                                letterSpacing: 0,
                              ),
                            ),
                            const SizedBox(height: 12),
                            TextButton(
                              onPressed: _showManualInput,
                              child: Text(
                                '输入设备码',
                                style: TextStyle(
                                  color: colors.brand,
                                  fontSize: 14,
                                  height: 1.36,
                                  fontWeight: FontWeight.w500,
                                  letterSpacing: 0,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          if (_showSuccess)
            Positioned.fill(
              child: _PairingSuccessOverlay(
                onDismiss: () {
                  if (!mounted) return;
                  setState(() => _showSuccess = false);
                  Navigator.of(context).maybePop();
                },
              ),
            ),
        ],
      ),
    );
  }

  Future<void> _toggleTorch() async {
    setState(() => _flashOn = !_flashOn);
    try {
      await _scannerController.toggleTorch();
    } catch (_) {
      if (mounted) setState(() => _flashOn = !_flashOn);
    }
  }

  void _onDetect(BarcodeCapture capture) {
    if (_scanned || _pairing) return;
    final raw = capture.barcodes
        .map((barcode) => barcode.rawValue?.trim() ?? '')
        .firstWhere((value) => value.isNotEmpty, orElse: () => '');
    if (raw.isEmpty) return;
    _handleScanResult(raw);
  }

  void _handleScanResult(String raw) {
    final authPayload = parseAuthQrPayload(raw);
    if (authPayload != null) {
      setState(() => _scanned = true);
      _showAuthQrConfirm(authPayload);
      return;
    }
    _submitPairing(raw);
  }

  Future<void> _pickAlbum() async {
    if (_pairing || _pickingAlbum) return;
    setState(() => _pickingAlbum = true);
    try {
      final image = await _imagePicker.pickImage(source: ImageSource.gallery);
      if (!mounted) return;
      if (image == null) {
        setState(() => _pickingAlbum = false);
        return;
      }
      final inputImage = mlkit.InputImage.fromFilePath(image.path);
      final barcodes = await _albumScanner.processImage(inputImage);
      if (!mounted) return;
      final raw = barcodes
          .map((barcode) => barcode.rawValue?.trim() ?? '')
          .firstWhere((value) => value.isNotEmpty, orElse: () => '');
      setState(() => _pickingAlbum = false);
      if (raw.isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('未识别到二维码')),
        );
        return;
      }
      _handleScanResult(raw);
    } catch (error) {
      if (!mounted) return;
      setState(() => _pickingAlbum = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('相册扫码失败：$error')),
      );
    }
  }

  void _showManualInput() {
    final controller = TextEditingController();
    var submitted = false;

    void submit(BuildContext sheetContext) {
      if (submitted) return;
      final code = controller.text.trim();
      if (code.isEmpty) return;
      submitted = true;
      Navigator.of(sheetContext).pop();
      _handleScanResult(code);
    }

    final colors = AppTheme.colors(context);
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: colors.surface,
      builder: (sheetContext) {
        final sheetColors = AppTheme.colors(sheetContext);
        return StatefulBuilder(
          builder: (sheetContext, setSheetState) {
            void onChanged(String raw) {
              final filtered = raw.replaceAll(RegExp(r'\D'), '');
              final next =
                  filtered.length > 6 ? filtered.substring(0, 6) : filtered;
              if (controller.text != next) {
                controller.value = TextEditingValue(
                  text: next,
                  selection: TextSelection.collapsed(offset: next.length),
                );
              }
              setSheetState(() {});
              if (next.length == 6) submit(sheetContext);
            }

            return Padding(
              padding: EdgeInsets.only(
                left: 20,
                right: 20,
                top: 16,
                bottom: MediaQuery.of(sheetContext).viewInsets.bottom + 16,
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    '输入设备码',
                    style: TextStyle(
                      color: sheetColors.textPrimary,
                      fontSize: 18,
                      height: 1.33,
                      fontWeight: FontWeight.w700,
                      letterSpacing: 0,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    '请输入电脑端显示的 6 位设备码',
                    style: TextStyle(
                      color: sheetColors.textSecondary,
                      fontSize: 13,
                      height: 1.31,
                      letterSpacing: 0,
                    ),
                  ),
                  const SizedBox(height: 20),
                  _PairingCodeInput(
                    controller: controller,
                    onChanged: onChanged,
                  ),
                  const SizedBox(height: 16),
                  WeBlockButton(
                    text: '连接',
                    onPressed: () => submit(sheetContext),
                    enabled: controller.text.trim().isNotEmpty,
                  ),
                ],
              ),
            );
          },
        );
      },
    ).whenComplete(controller.dispose);
  }

  void _showAuthQrConfirm(AuthQrPayload payload) {
    final usernameController = TextEditingController();
    final passwordController = TextEditingController();
    final targetLabel = payload.accountKind == 'admin' ? '管理端' : '企业端';
    final rootContext = context;
    final colors = AppTheme.colors(rootContext);
    showModalBottomSheet<void>(
      context: rootContext,
      isScrollControlled: true,
      backgroundColor: colors.surface,
      builder: (sheetContext) {
        final sheetColors = AppTheme.colors(sheetContext);
        var submitting = false;
        return StatefulBuilder(
          builder: (sheetContext, setSheetState) {
            Future<void> submit() async {
              if (submitting) return;
              setSheetState(() => submitting = true);
              try {
                await _repository.confirmAuthQr(
                  qrId: payload.qrId,
                  username: usernameController.text,
                  password: passwordController.text,
                  accountKind: payload.accountKind,
                );
                if (!mounted || !sheetContext.mounted) return;
                Navigator.of(sheetContext).pop();
                ScaffoldMessenger.of(rootContext).showSnackBar(
                  const SnackBar(content: Text('已确认登录')),
                );
                Navigator.of(rootContext).maybePop();
              } catch (error) {
                if (!sheetContext.mounted) return;
                setSheetState(() => submitting = false);
                ScaffoldMessenger.of(sheetContext).showSnackBar(
                  SnackBar(
                    content: Text(
                      androidProductErrorMessage(
                        error.toString(),
                        '扫码登录失败，请重试',
                      ),
                    ),
                  ),
                );
              }
            }

            return Padding(
              padding: EdgeInsets.only(
                left: 20,
                right: 20,
                top: 16,
                bottom: MediaQuery.of(context).viewInsets.bottom + 20,
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Center(
                    child: Text(
                      '确认$targetLabel扫码登录',
                      style: TextStyle(
                        color: sheetColors.textPrimary,
                        fontSize: 18,
                        height: 1.33,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 0,
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  TextField(
                    controller: usernameController,
                    textInputAction: TextInputAction.next,
                    decoration: InputDecoration(
                      hintText:
                          payload.accountKind == 'admin' ? '管理员账号' : '企业账号',
                      filled: true,
                      fillColor: sheetColors.surfaceHigh,
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(8),
                      ),
                    ),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: passwordController,
                    obscureText: true,
                    onSubmitted: (_) => submit(),
                    decoration: InputDecoration(
                      hintText: '密码',
                      filled: true,
                      fillColor: sheetColors.surfaceHigh,
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(8),
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  WeBlockButton(
                    text: submitting ? '确认中…' : '确认登录',
                    onPressed: submit,
                    enabled: !submitting,
                  ),
                ],
              ),
            );
          },
        );
      },
    ).whenComplete(() {
      usernameController.dispose();
      passwordController.dispose();
      if (mounted && !_pairing) {
        setState(() => _scanned = false);
        _scannerController.start().ignore();
      }
    });
  }

  Future<void> _submitPairing(String raw) async {
    final text = raw.trim();
    if (text.isEmpty || _pairing) return;
    setState(() {
      _pairing = true;
      _scanned = true;
    });
    try {
      await _scannerController.stop();
    } catch (_) {}
    try {
      await _repository.exchangePairingCode(text);
      if (!mounted) return;
      setState(() {
        _pairing = false;
        _showSuccess = true;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _pairing = false;
        _scanned = false;
      });
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            androidProductErrorMessage(
              error.toString(),
              '设备配对失败，请刷新二维码或输入设备码',
            ),
          ),
        ),
      );
      if (widget.enableCamera) {
        _scannerController.start().ignore();
      }
    }
  }
}

class _PairingSuccessOverlay extends StatefulWidget {
  const _PairingSuccessOverlay({required this.onDismiss});

  final VoidCallback onDismiss;

  @override
  State<_PairingSuccessOverlay> createState() => _PairingSuccessOverlayState();
}

class _PairingSuccessOverlayState extends State<_PairingSuccessOverlay> {
  @override
  void initState() {
    super.initState();
    Future<void>.delayed(const Duration(milliseconds: 1600), () {
      if (mounted) widget.onDismiss();
    });
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return ColoredBox(
      color: Colors.black.withValues(alpha: 0.82),
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TweenAnimationBuilder<double>(
              tween: Tween(begin: 0.72, end: 1),
              duration: const Duration(milliseconds: 420),
              curve: Curves.easeOutBack,
              builder: (context, scale, child) {
                return Transform.scale(scale: scale, child: child);
              },
              child: Container(
                width: 88,
                height: 88,
                decoration: BoxDecoration(
                  color: colors.brand,
                  shape: BoxShape.circle,
                ),
                alignment: Alignment.center,
                child: const CustomPaint(
                  size: Size(44, 44),
                  painter: _CheckPainter(),
                ),
              ),
            ),
            const SizedBox(height: 24),
            const Text(
              '配对成功',
              style: TextStyle(
                color: Colors.white,
                fontSize: 28,
                height: 1.21,
                fontWeight: FontWeight.w700,
                letterSpacing: 0,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              '手机与电脑已连接',
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.6),
                fontSize: 14,
                height: 1.36,
                letterSpacing: 0,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _CheckPainter extends CustomPainter {
  const _CheckPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final path = Path()
      ..moveTo(size.width * 0.2, size.height * 0.52)
      ..lineTo(size.width * 0.42, size.height * 0.72)
      ..lineTo(size.width * 0.8, size.height * 0.28);
    final paint = Paint()
      ..color = Colors.white
      ..style = PaintingStyle.stroke
      ..strokeWidth = size.width * 0.08
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    canvas.drawPath(path, paint);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

class _PairingCodeInput extends StatelessWidget {
  const _PairingCodeInput({
    required this.controller,
    required this.onChanged,
  });

  final TextEditingController controller;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        const gap = 10.0;
        final boxWidth = ((constraints.maxWidth - gap * 5) / 6).clamp(38, 46);
        return Stack(
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                for (var index = 0; index < 6; index++) ...[
                  _PairingDigitBox(
                    digit: controller.text.length > index
                        ? controller.text[index]
                        : '',
                    focused: index == controller.text.length && index < 6,
                    width: boxWidth.toDouble(),
                  ),
                  if (index != 5) const SizedBox(width: gap),
                ],
              ],
            ),
            Positioned.fill(
              child: Opacity(
                opacity: 0.01,
                child: TextField(
                  autofocus: true,
                  controller: controller,
                  keyboardType: TextInputType.number,
                  maxLength: 6,
                  onChanged: onChanged,
                  decoration: const InputDecoration(
                    counterText: '',
                    border: InputBorder.none,
                  ),
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}

class _PairingDigitBox extends StatelessWidget {
  const _PairingDigitBox({
    required this.digit,
    required this.focused,
    required this.width,
  });

  final String digit;
  final bool focused;
  final double width;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      width: width,
      height: 54,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: colors.surfaceHigh,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: focused ? colors.brand : colors.divider,
          width: focused ? 1.8 : 0.7,
        ),
      ),
      child: Text(
        digit,
        style: TextStyle(
          color: digit.isEmpty ? Colors.transparent : colors.textPrimary,
          fontSize: 40,
          height: 1.2,
          fontWeight: FontWeight.w700,
          letterSpacing: 0,
        ),
      ),
    );
  }
}

class _ScannerUnavailable extends StatelessWidget {
  const _ScannerUnavailable({required this.onOpenManual});

  final VoidCallback onOpenManual;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      color: Colors.black,
      alignment: Alignment.center,
      padding: const EdgeInsets.symmetric(horizontal: 32),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            '需要相机权限以扫描配对二维码',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: Colors.white.withValues(alpha: 0.8),
              fontSize: 15,
              height: 1.4,
              letterSpacing: 0,
            ),
          ),
          const SizedBox(height: 20),
          TextButton(
            onPressed: onOpenManual,
            child: Text(
              '输入设备码',
              style: TextStyle(color: colors.brand),
            ),
          ),
        ],
      ),
    );
  }
}

class _ScannerOverlay extends StatefulWidget {
  const _ScannerOverlay();

  @override
  State<_ScannerOverlay> createState() => _ScannerOverlayState();
}

class _ScannerOverlayState extends State<_ScannerOverlay>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2500),
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, _) {
        return CustomPaint(
          painter: _ScannerOverlayPainter(
            progress: _controller.value,
            accent: colors.brand,
          ),
          child: const SizedBox.expand(),
        );
      },
    );
  }
}

class _ScannerOverlayPainter extends CustomPainter {
  const _ScannerOverlayPainter({
    required this.progress,
    required this.accent,
  });

  final double progress;
  final Color accent;

  @override
  void paint(Canvas canvas, Size size) {
    const frameSize = 220.0;
    const strokeWidth = 2.5;
    final side = (size.width - frameSize) / 2;
    final top = (size.height - frameSize) / 2;
    final frame = Rect.fromLTWH(side, top, frameSize, frameSize);
    final maskPaint = Paint()..color = Colors.black.withValues(alpha: 0.55);

    canvas.drawRect(Rect.fromLTWH(0, 0, size.width, top), maskPaint);
    canvas.drawRect(
      Rect.fromLTWH(0, frame.bottom, size.width, top),
      maskPaint,
    );
    canvas.drawRect(Rect.fromLTWH(0, top, side, frameSize), maskPaint);
    canvas.drawRect(
      Rect.fromLTWH(frame.right, top, side, frameSize),
      maskPaint,
    );

    final cornerPaint = Paint()
      ..color = Colors.white
      ..style = PaintingStyle.stroke
      ..strokeWidth = strokeWidth
      ..strokeCap = StrokeCap.round;
    const cornerLength = frameSize * 0.13;
    final corners = <List<Offset>>[
      [frame.topLeft, Offset(frame.left + cornerLength, frame.top)],
      [frame.topLeft, Offset(frame.left, frame.top + cornerLength)],
      [frame.topRight, Offset(frame.right - cornerLength, frame.top)],
      [frame.topRight, Offset(frame.right, frame.top + cornerLength)],
      [frame.bottomLeft, Offset(frame.left + cornerLength, frame.bottom)],
      [frame.bottomLeft, Offset(frame.left, frame.bottom - cornerLength)],
      [frame.bottomRight, Offset(frame.right - cornerLength, frame.bottom)],
      [frame.bottomRight, Offset(frame.right, frame.bottom - cornerLength)],
    ];
    for (final line in corners) {
      canvas.drawLine(line[0], line[1], cornerPaint);
    }

    final lineY = frame.top + progress * frameSize;
    final glowPaint = Paint()..color = accent.withValues(alpha: 0.08);
    canvas.drawRect(
      Rect.fromLTWH(
          frame.left, lineY - frameSize * 0.15, frameSize, frameSize * 0.3),
      glowPaint,
    );
    final scanPaint = Paint()
      ..color = accent.withValues(alpha: 0.7)
      ..strokeWidth = strokeWidth * 1.5;
    canvas.drawLine(
      Offset(frame.left, lineY),
      Offset(frame.right, lineY),
      scanPaint,
    );
  }

  @override
  bool shouldRepaint(covariant _ScannerOverlayPainter oldDelegate) {
    return oldDelegate.progress != progress || oldDelegate.accent != accent;
  }
}
