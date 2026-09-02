import 'dart:async';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_mlkit_barcode_scanning/google_mlkit_barcode_scanning.dart'
    as mlkit;
import 'package:image_picker/image_picker.dart';

import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../platform/android_camera_permission.dart';
import '../../platform/camera_barcode_input.dart';
import '../../policy/mobile_error_policy.dart';
import '../../theme/app_theme.dart';
import '../../widgets/we_ui.dart';

part 'scan_qr_screen_state_camera.part.dart';
part 'scan_qr_screen_state_scan.part.dart';
part 'scan_qr_screen_overlays.part.dart';

class ScanQrScreen extends StatefulWidget {
  const ScanQrScreen({super.key, this.repository, this.enableCamera = true});

  final MobileRepository? repository;
  final bool enableCamera;

  @override
  State<ScanQrScreen> createState() => _ScanQrScreenState();
}

class _ScanQrScreenState extends _ScanQrStateScan {

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final cameraEnabled = widget.enableCamera;
    final scannerReady = cameraEnabled && _permissionGranted && _cameraReady;
    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        children: [
          SafeArea(
            child: Column(
              children: [
                Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 4,
                    vertical: 8,
                  ),
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
                      if (scannerReady && !_scanned)
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
                        icon: const Icon(
                          Icons.photo_library,
                          color: Colors.white,
                        ),
                        tooltip: '从相册选择',
                      ),
                    ],
                  ),
                ),
                Expanded(
                  child: Stack(
                    alignment: Alignment.center,
                    children: [
                      if (cameraEnabled &&
                          scannerReady &&
                          _cameraController != null)
                        Positioned.fill(
                          child: FittedBox(
                            fit: BoxFit.cover,
                            clipBehavior: Clip.hardEdge,
                            child: SizedBox(
                              width: _cameraController!
                                      .value.previewSize?.height ??
                                  MediaQuery.sizeOf(context).width,
                              height:
                                  _cameraController!.value.previewSize?.width ??
                                      MediaQuery.sizeOf(context).height,
                              child: CameraPreview(_cameraController!),
                            ),
                          ),
                        )
                      else if (cameraEnabled &&
                          (_checkingCameraPermission ||
                              _requestingCameraPermission))
                        Center(
                          child: CircularProgressIndicator(color: colors.brand),
                        )
                      else if (cameraEnabled && _cameraError != null)
                        _ScannerFailure(
                          message: _cameraError!,
                          onRetry: _restartScanner,
                          onOpenManual: _showManualInput,
                        )
                      else if (!cameraEnabled)
                        _ScannerUnavailable(
                          onRequestPermission: _requestCameraPermission,
                          onOpenManual: _showManualInput,
                          requesting: _requestingCameraPermission,
                        ),
                      if (scannerReady)
                        const Positioned.fill(child: _ScannerOverlay()),
                      if (cameraEnabled &&
                          !_permissionGranted &&
                          !_checkingCameraPermission)
                        _ScannerUnavailable(
                          onRequestPermission: _requestCameraPermission,
                          onOpenManual: _showManualInput,
                          requesting: _requestingCameraPermission,
                        ),
                      if (cameraEnabled && _pairing)
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
                      if (cameraEnabled && _pickingAlbum)
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
                      if (scannerReady && !_scanned)
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
}
