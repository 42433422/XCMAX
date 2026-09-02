// part 文件：扫码页扫码与配对交互状态（_ScanQrStateScan）。

part of 'scan_qr_screen.dart';

abstract class _ScanQrStateScan extends _ScanQrStateCamera {
  void _handleScanResult(String raw) {
    if (_scanned || _pairing) return;
    HapticFeedback.mediumImpact();
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
      final barcodes = await _barcodeScanner.processImage(inputImage);
      if (!mounted) return;
      final raw = barcodes
          .map((barcode) => barcode.rawValue?.trim() ?? '')
          .firstWhere((value) => value.isNotEmpty, orElse: () => '');
      setState(() => _pickingAlbum = false);
      if (raw.isEmpty) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('未识别到二维码')));
        return;
      }
      _handleScanResult(raw);
    } catch (error) {
      if (!mounted) return;
      setState(() => _pickingAlbum = false);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('相册扫码失败：$error')));
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
                    '请确保手机与电脑在同一 WiFi，输入管理端显示的 6 位局域网配对码',
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
    final targetLabel = mobileAuthQrTargetLabel(payload.accountKind);
    final usernameHint = mobileAuthQrUsernameHint(payload.accountKind);
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
                ScaffoldMessenger.of(
                  rootContext,
                ).showSnackBar(const SnackBar(content: Text('已确认登录')));
                Navigator.of(rootContext).maybePop();
              } catch (error) {
                if (!sheetContext.mounted) return;
                setSheetState(() => submitting = false);
                ScaffoldMessenger.of(sheetContext).showSnackBar(
                  SnackBar(
                    content: Text(
                      mobileProductErrorMessage(error.toString(), '扫码登录失败，请重试'),
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
                      hintText: usernameHint,
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
                    text: submitting ? '确认中…' : '确认$targetLabel登录',
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
        unawaited(_resumeCameraStream());
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
    await _stopCameraStream();
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
            mobileProductErrorMessage(error.toString(), '设备配对失败，请刷新二维码或输入设备码'),
          ),
        ),
      );
      if (widget.enableCamera) {
        unawaited(_resumeCameraStream());
      }
    }
  }
}
