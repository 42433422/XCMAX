// part 文件：扫码页相机状态基类（_ScanQrStateCamera）。

part of 'scan_qr_screen.dart';

abstract class _ScanQrStateCamera extends State<ScanQrScreen>
    with WidgetsBindingObserver {
  late final MobileRepository _repository;
  CameraController? _cameraController;
  late final ImagePicker _imagePicker;
  late final mlkit.BarcodeScanner _barcodeScanner;
  final AndroidCameraPermission _cameraPermission =
      const AndroidCameraPermission();
  var _flashOn = false;
  var _scanned = false;
  var _pairing = false;
  var _pickingAlbum = false;
  var _showSuccess = false;
  var _permissionGranted = false;
  var _checkingCameraPermission = true;
  var _requestingCameraPermission = false;
  var _bootstrappingScanner = false;
  var _cameraReady = false;
  var _processingFrame = false;
  String? _cameraError;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _imagePicker = ImagePicker();
    _barcodeScanner = mlkit.BarcodeScanner(
      formats: [mlkit.BarcodeFormat.qrCode],
    );
    if (widget.enableCamera) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        unawaited(_bootstrapScanner(requestPermission: false));
      });
    } else {
      _checkingCameraPermission = false;
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (!widget.enableCamera) return;
    if (state == AppLifecycleState.inactive ||
        state == AppLifecycleState.paused) {
      unawaited(_stopCameraStream());
      return;
    }
    if (state == AppLifecycleState.resumed) {
      unawaited(_bootstrapScanner(requestPermission: false));
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    unawaited(_disposeCameraController());
    _barcodeScanner.close();
    super.dispose();
  }

  Future<void> _disposeCameraController() async {
    final controller = _cameraController;
    _cameraController = null;
    if (controller == null) return;
    try {
      if (controller.value.isStreamingImages) {
        await controller.stopImageStream();
      }
    } catch (_) {}
    await controller.dispose();
  }

  Future<void> _toggleTorch() async {
    final controller = _cameraController;
    if (controller == null || !controller.value.isInitialized) return;
    final next = !_flashOn;
    setState(() => _flashOn = next);
    try {
      await controller.setFlashMode(next ? FlashMode.torch : FlashMode.off);
    } catch (_) {
      if (mounted) setState(() => _flashOn = !next);
    }
  }

  Future<void> _bootstrapScanner({required bool requestPermission}) async {
    if (!widget.enableCamera || _bootstrappingScanner) return;
    _bootstrappingScanner = true;
    if (mounted) {
      setState(() {
        _requestingCameraPermission = requestPermission;
        if (!requestPermission) {
          _checkingCameraPermission = true;
        }
        _cameraError = null;
      });
    }

    var granted = await _cameraPermission.isGranted();
    if (!granted && requestPermission) {
      granted = await _cameraPermission.ensureGranted();
    }

    if (!mounted) return;
    setState(() {
      _permissionGranted = granted;
      _checkingCameraPermission = false;
      _requestingCameraPermission = false;
      _bootstrappingScanner = false;
    });

    if (!granted) return;
    await _initializeCamera();
  }

  Future<void> _initializeCamera() async {
    if (!widget.enableCamera || !mounted) return;
    try {
      await _disposeCameraController();
      final cameras = await availableCameras();
      if (!mounted) return;
      if (cameras.isEmpty) {
        setState(() {
          _cameraReady = false;
          _cameraError = '未找到可用相机';
        });
        return;
      }
      final description = cameras.firstWhere(
        (camera) => camera.lensDirection == CameraLensDirection.back,
        orElse: () => cameras.first,
      );
      final controller = CameraController(
        description,
        ResolutionPreset.medium,
        enableAudio: false,
        imageFormatGroup: ImageFormatGroup.yuv420,
      );
      _cameraController = controller;
      await controller.initialize();
      if (!mounted) return;
      await controller.startImageStream(_processCameraFrame);
      if (!mounted) return;
      setState(() {
        _cameraReady = true;
        _cameraError = null;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _cameraReady = false;
        _cameraError = error.toString();
      });
    }
  }

  Future<void> _stopCameraStream() async {
    final controller = _cameraController;
    if (controller == null || !controller.value.isStreamingImages) return;
    try {
      await controller.stopImageStream();
    } catch (_) {}
    if (mounted) {
      setState(() => _cameraReady = false);
    }
  }

  Future<void> _restartScanner() async {
    if (!widget.enableCamera) return;
    await _bootstrapScanner(requestPermission: false);
  }

  Future<void> _requestCameraPermission() async {
    if (!widget.enableCamera || _requestingCameraPermission) return;
    await _bootstrapScanner(requestPermission: true);
  }

  Future<void> _processCameraFrame(CameraImage image) async {
    if (_scanned || _pairing || _processingFrame) return;
    final controller = _cameraController;
    if (controller == null || !controller.value.isInitialized) return;
    _processingFrame = true;
    try {
      final inputImage = inputImageFromCameraFrame(image, controller);
      if (inputImage == null) return;
      final barcodes = await _barcodeScanner.processImage(inputImage);
      final raw = barcodes
          .map((barcode) => barcode.rawValue?.trim() ?? '')
          .firstWhere((value) => value.isNotEmpty, orElse: () => '');
      if (raw.isEmpty || !mounted || _scanned || _pairing) return;
      await _stopCameraStream();
      if (!mounted) return;
      _handleScanResult(raw);
    } catch (_) {
    } finally {
      _processingFrame = false;
    }
  }

  Future<void> _resumeCameraStream() async {
    final controller = _cameraController;
    if (controller == null || !controller.value.isInitialized) {
      await _initializeCamera();
      return;
    }
    if (controller.value.isStreamingImages) {
      if (mounted) setState(() => _cameraReady = true);
      return;
    }
    try {
      await controller.startImageStream(_processCameraFrame);
      if (mounted) setState(() => _cameraReady = true);
    } catch (error) {
      if (!mounted) return;
      setState(() => _cameraError = error.toString());
    }
  }
}
