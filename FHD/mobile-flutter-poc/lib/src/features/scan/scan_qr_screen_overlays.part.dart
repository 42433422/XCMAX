// part 文件：扫码页配对成功浮层与扫描框覆盖层组件。

part of 'scan_qr_screen.dart';

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
  const _PairingCodeInput({required this.controller, required this.onChanged});

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

class _ScannerFailure extends StatelessWidget {
  const _ScannerFailure({
    required this.message,
    required this.onRetry,
    required this.onOpenManual,
  });

  final String message;
  final VoidCallback onRetry;
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
            message.isEmpty ? '相机启动失败' : message,
            textAlign: TextAlign.center,
            style: TextStyle(
              color: Colors.white.withValues(alpha: 0.8),
              fontSize: 15,
              height: 1.4,
            ),
          ),
          const SizedBox(height: 20),
          TextButton(
            onPressed: onRetry,
            child: Text('重试', style: TextStyle(color: colors.brand)),
          ),
          const SizedBox(height: 12),
          TextButton(
            onPressed: onOpenManual,
            child: Text(
              '输入设备码',
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.7),
                fontSize: 14,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ScannerUnavailable extends StatelessWidget {
  const _ScannerUnavailable({
    required this.onRequestPermission,
    required this.onOpenManual,
    this.requesting = false,
  });

  final VoidCallback onRequestPermission;
  final VoidCallback onOpenManual;
  final bool requesting;

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
            onPressed: requesting ? null : onRequestPermission,
            child: requesting
                ? SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: colors.brand,
                    ),
                  )
                : Text('授予相机权限', style: TextStyle(color: colors.brand)),
          ),
          const SizedBox(height: 12),
          TextButton(
            onPressed: onOpenManual,
            child: Text(
              '输入设备码',
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.7),
                fontSize: 14,
                height: 1.36,
                fontWeight: FontWeight.w500,
                letterSpacing: 0,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

String mobileAuthQrTargetLabel(String accountKind) {
  return accountKind.trim().toLowerCase() == 'admin' ? '管理端' : '企业端';
}

String mobileAuthQrUsernameHint(String accountKind) {
  return accountKind.trim().toLowerCase() == 'admin' ? '管理员账号' : '企业账号';
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
  const _ScannerOverlayPainter({required this.progress, required this.accent});

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
    canvas.drawRect(Rect.fromLTWH(0, frame.bottom, size.width, top), maskPaint);
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
        frame.left,
        lineY - frameSize * 0.15,
        frameSize,
        frameSize * 0.3,
      ),
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
