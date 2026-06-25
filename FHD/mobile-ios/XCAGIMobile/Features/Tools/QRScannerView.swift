import SwiftUI
import UIKit
import AVFoundation
import PhotosUI
import CoreImage

/// 相机二维码扫描(对标 Android CameraX / 鸿蒙 ScanKit)。
/// 用 `AVCaptureMetadataOutput` 识别 QR,识别到即回调一次并停止。
/// 支持外部通过 `torchOn` 切换闪光灯(对标 Android `camera.cameraControl.enableTorch`)。
struct QRScannerView: UIViewControllerRepresentable {
    var torchOn: Bool = false
    var onFound: (String) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onFound: onFound) }

    func makeUIViewController(context: Context) -> ScannerViewController {
        let vc = ScannerViewController()
        vc.coordinator = context.coordinator
        return vc
    }

    func updateUIViewController(_ uiViewController: ScannerViewController, context: Context) {
        uiViewController.setTorch(torchOn)
    }

    final class Coordinator: NSObject, AVCaptureMetadataOutputObjectsDelegate {
        let onFound: (String) -> Void
        private var handled = false
        init(onFound: @escaping (String) -> Void) { self.onFound = onFound }

        func metadataOutput(_ output: AVCaptureMetadataOutput,
                            didOutput metadataObjects: [AVMetadataObject],
                            from connection: AVCaptureConnection) {
            guard !handled,
                  let obj = metadataObjects.first as? AVMetadataMachineReadableCodeObject,
                  let value = obj.stringValue else { return }
            handled = true
            // 识别成功震动反馈(对标 Android vibrateSuccess)。
            UINotificationFeedbackGenerator().notificationOccurred(.success)
            onFound(value)
        }
    }
}

/// 承载 AVCaptureSession 的 UIKit 控制器。
final class ScannerViewController: UIViewController {
    weak var coordinator: QRScannerView.Coordinator?
    private let session = AVCaptureSession()
    private var preview: AVCaptureVideoPreviewLayer?
    private var device: AVCaptureDevice?

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        configureSession()
    }

    private func configureSession() {
        guard let device = AVCaptureDevice.default(for: .video),
              let input = try? AVCaptureDeviceInput(device: device),
              session.canAddInput(input) else { return }
        self.device = device
        session.addInput(input)

        let output = AVCaptureMetadataOutput()
        guard session.canAddOutput(output) else { return }
        session.addOutput(output)
        output.setMetadataObjectsDelegate(coordinator, queue: .main)
        output.metadataObjectTypes = [.qr]

        let layer = AVCaptureVideoPreviewLayer(session: session)
        layer.videoGravity = .resizeAspectFill
        layer.frame = view.bounds
        view.layer.addSublayer(layer)
        preview = layer
    }

    /// 切换手电筒(对标 Android `enableTorch`)。
    func setTorch(_ on: Bool) {
        guard let device, device.hasTorch, device.isTorchAvailable else { return }
        do {
            try device.lockForConfiguration()
            device.torchMode = on ? .on : .off
            device.unlockForConfiguration()
        } catch { /* 静默 */ }
    }

    override func viewWillAppear(_ animated: Bool) {
        super.viewWillAppear(animated)
        if !session.isRunning {
            DispatchQueue.global(qos: .userInitiated).async { [weak self] in self?.session.startRunning() }
        }
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        if session.isRunning {
            DispatchQueue.global(qos: .userInitiated).async { [weak self] in self?.session.stopRunning() }
        }
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        preview?.frame = view.bounds
    }
}

// MARK: - 扫一扫页(对标 Android ScanQrScreen)

/// 扫一扫页:相机取景框 + 扫描线动画 + 蒙层 + 闪光灯 + 相册选图 + 震动 + 6 位设备码手动输入兜底。
/// 多格式解析走 `PairingQrCodec`;分发统一走 `session.applyPairingQr`(对标 Android `vm.exchangeQr` + 分发)。
struct ScanQrView: View {
    @EnvironmentObject private var session: SessionManager
    @Environment(\.dismiss) private var dismiss

    @State private var scanned = false
    @State private var permissionDenied = false
    @State private var flashOn = false
    @State private var showManualInput = false
    @State private var showSuccess = false
    @State private var deviceCode = ""
    @State private var applying = false
    @State private var pickerItem: PhotosPickerItem?

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            if permissionDenied {
                noPermissionView
            } else {
                cameraView
            }

            if showSuccess {
                PairingSuccessOverlay { showSuccess = false; dismiss() }
            }
        }
        .navigationTitle("扫一扫")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItemGroup(placement: .navigationBarTrailing) {
                if !permissionDenied && !scanned {
                    Button { flashOn.toggle() } label: {
                        Image(systemName: flashOn ? "bolt.fill" : "bolt.slash")
                    }
                }
                PhotosPicker(selection: $pickerItem, matching: .images) {
                    Image(systemName: "photo.on.rectangle")
                }
            }
        }
        .onChange(of: pickerItem) { item in
            Task { await scanFromLibrary(item) }
        }
        .sheet(isPresented: $showManualInput) { manualInputSheet }
        .task { await checkPermission() }
    }

    // ── 相机预览 + 取景框覆盖层 ──
    private var cameraView: some View {
        ZStack {
            QRScannerView(torchOn: flashOn) { value in handleScan(value) }
                .ignoresSafeArea()

            ScannerOverlay()

            VStack {
                Spacer()
                if !scanned {
                    Text("将电脑端显示的配对二维码放入框内,即可自动扫描")
                        .font(.footnote)
                        .foregroundColor(.white.opacity(0.7))
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, Theme.Space.xl)
                    Button("输入设备码") { showManualInput = true }
                        .font(.subheadline.weight(.medium))
                        .foregroundColor(Theme.brand)
                        .padding(.top, Theme.Space.md)
                }
                if applying {
                    ProgressView().tint(.white).padding(.top, Theme.Space.md)
                }
                if let err = session.lastError {
                    Text(err).font(.footnote).foregroundColor(.red)
                        .padding(.top, Theme.Space.sm)
                }
                Spacer().frame(height: Theme.Space.xl)
            }
            .padding(.bottom, Theme.Space.xl)
        }
    }

    // ── 无相机权限:授权 + 设备码兜底(对标 Android 无权限分支) ──
    private var noPermissionView: some View {
        VStack(spacing: Theme.Space.lg) {
            Image(systemName: "camera.fill").font(.system(size: 44)).foregroundColor(.white.opacity(0.5))
            Text("需要相机权限以扫描配对二维码")
                .font(.body).foregroundColor(.white.opacity(0.8))
                .multilineTextAlignment(.center).padding(.horizontal, Theme.Space.xl)
            Button("授予相机权限") { openSettings() }
                .font(.body.weight(.medium)).foregroundColor(Theme.brand)
            Button("输入设备码") { showManualInput = true }
                .font(.subheadline).foregroundColor(.white.opacity(0.7))
        }
    }

    // ── 手动输入设备码弹窗(OTP 风格 6 位 + 满 6 位自动提交,对标 Android ModalBottomSheet) ──
    private var manualInputSheet: some View {
        VStack(spacing: Theme.Space.lg) {
            Capsule().fill(Color.secondary.opacity(0.3)).frame(width: 36, height: 5).padding(.top, Theme.Space.sm)
            Text("输入设备码").font(.title2.bold())
            Text("请输入电脑端显示的 6 位设备码")
                .font(.footnote).foregroundColor(.secondary)

            PairingCodeInput(value: $deviceCode) { submitDeviceCode() }
                .padding(.vertical, Theme.Space.sm)

            Button {
                submitDeviceCode()
            } label: {
                Text(applying ? "连接中…" : "连接")
                    .frame(maxWidth: .infinity).padding(.vertical, Theme.Space.sm)
            }
            .buttonStyle(.borderedProminent)
            .disabled(deviceCode.isEmpty || applying)

            if let err = session.lastError {
                Text(err).font(.footnote).foregroundColor(.red)
            }
            Spacer()
        }
        .padding(Theme.Space.xl)
        .presentationDetents([.height(360)])
        .onChange(of: deviceCode) { newValue in
            // 满 6 位自动提交(对标微信/钉钉)。
            if newValue.count == 6 { submitDeviceCode() }
        }
    }

    // MARK: 行为

    private func handleScan(_ raw: String) {
        guard !scanned else { return }
        scanned = true
        applyCode(raw)
    }

    private func submitDeviceCode() {
        guard !deviceCode.isEmpty, !applying else { return }
        applyCode(deviceCode)
    }

    /// 统一分发:多格式解析 + 配对(对标 Android `vm.exchangeQr` → 分发)。
    private func applyCode(_ raw: String) {
        applying = true
        session.lastError = nil
        Task {
            await session.applyPairingQr(raw)
            applying = false
            if session.lastError == nil {
                showManualInput = false
                UINotificationFeedbackGenerator().notificationOccurred(.success)
                showSuccess = true
            } else {
                // 失败时允许继续扫描 / 重新输入。
                scanned = false
            }
        }
    }

    /// 相册选图识别 QR(对标 Android `tryScanFromUri` + ML Kit)。
    private func scanFromLibrary(_ item: PhotosPickerItem?) async {
        guard let item else { return }
        guard let data = try? await item.loadTransferable(type: Data.self),
              let ui = UIImage(data: data),
              let raw = Self.detectQR(in: ui) else {
            session.lastError = "未在所选图片中识别到二维码"
            return
        }
        handleScan(raw)
    }

    /// 用 CoreImage `CIDetector` 在静态图片中识别 QR(对标 Android `InputImage.fromBitmap`)。
    static func detectQR(in image: UIImage) -> String? {
        guard let cg = image.cgImage else { return nil }
        let ci = CIImage(cgImage: cg)
        let detector = CIDetector(ofType: CIDetectorTypeQRCode,
                                  context: nil,
                                  options: [CIDetectorAccuracy: CIDetectorAccuracyHigh])
        let features = detector?.features(in: ci) ?? []
        for case let qr as CIQRCodeFeature in features {
            if let msg = qr.messageString, !msg.isEmpty { return msg }
        }
        return nil
    }

    private func checkPermission() async {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized: permissionDenied = false
        case .notDetermined:
            let granted = await AVCaptureDevice.requestAccess(for: .video)
            permissionDenied = !granted
        default: permissionDenied = true
        }
    }

    private func openSettings() {
        guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
        UIApplication.shared.open(url)
    }
}

// MARK: - 取景框覆盖层(微信风格:四角边框 + 蒙层 + 扫描线动画)

private struct ScannerOverlay: View {
    private let frameSize: CGFloat = 240
    @State private var lineOffset: CGFloat = 0

    var body: some View {
        GeometryReader { geo in
            ZStack {
                // 半透明蒙层 + 镂空取景框
                Color.black.opacity(0.55)
                    .mask {
                        Rectangle()
                            .overlay {
                                RoundedRectangle(cornerRadius: Theme.Radius.md)
                                    .frame(width: frameSize, height: frameSize)
                                    .blendMode(.destinationOut)
                            }
                            .compositingGroup()
                    }

                // 四角 L 型边框 + 扫描线
                ZStack {
                    CornerFrame()
                        .stroke(Color.white, style: StrokeStyle(lineWidth: 3, lineCap: .round, lineJoin: .round))
                        .frame(width: frameSize, height: frameSize)

                    Rectangle()
                        .fill(
                            LinearGradient(colors: [Theme.brand.opacity(0), Theme.brand.opacity(0.8), Theme.brand.opacity(0)],
                                           startPoint: .leading, endPoint: .trailing)
                        )
                        .frame(width: frameSize - 8, height: 2)
                        .offset(y: lineOffset)
                }
                .frame(width: frameSize, height: frameSize)
            }
            .frame(width: geo.size.width, height: geo.size.height)
            .onAppear {
                lineOffset = -frameSize / 2 + 6
                withAnimation(.linear(duration: 2.2).repeatForever(autoreverses: true)) {
                    lineOffset = frameSize / 2 - 6
                }
            }
        }
        .ignoresSafeArea()
    }
}

/// 四角 L 型取景边框(对标 Android `ScannerOverlay` 的四角 drawRoundRect)。
private struct CornerFrame: Shape {
    func path(in rect: CGRect) -> Path {
        var p = Path()
        let len = min(rect.width, rect.height) * 0.16
        let maxX = rect.maxX, maxY = rect.maxY
        // 左上
        p.move(to: CGPoint(x: 0, y: len)); p.addLine(to: .zero); p.addLine(to: CGPoint(x: len, y: 0))
        // 右上
        p.move(to: CGPoint(x: maxX - len, y: 0)); p.addLine(to: CGPoint(x: maxX, y: 0)); p.addLine(to: CGPoint(x: maxX, y: len))
        // 右下
        p.move(to: CGPoint(x: maxX, y: maxY - len)); p.addLine(to: CGPoint(x: maxX, y: maxY)); p.addLine(to: CGPoint(x: maxX - len, y: maxY))
        // 左下
        p.move(to: CGPoint(x: len, y: maxY)); p.addLine(to: CGPoint(x: 0, y: maxY)); p.addLine(to: CGPoint(x: 0, y: maxY - len))
        return p
    }
}

// MARK: - OTP 风格 6 位设备码输入(对标 Android PairingCodeInput)

private struct PairingCodeInput: View {
    @Binding var value: String
    var onSubmit: () -> Void
    @FocusState private var focused: Bool
    private let count = 6

    var body: some View {
        ZStack {
            HStack(spacing: Theme.Space.sm) {
                ForEach(0..<count, id: \.self) { index in
                    let char = index < value.count ? String(Array(value)[index]) : ""
                    let isActive = index == value.count
                    Text(char)
                        .font(.title.bold())
                        .frame(width: 44, height: 54)
                        .background(Theme.cardBackground)
                        .overlay(
                            RoundedRectangle(cornerRadius: Theme.Radius.sm)
                                .stroke(isActive ? Theme.brand : Color.secondary.opacity(0.3),
                                        lineWidth: isActive ? 1.8 : 0.7)
                        )
                        .cornerRadius(Theme.Radius.sm)
                }
            }

            // 承接输入的透明输入框
            TextField("", text: $value)
                .keyboardType(.numberPad)
                .focused($focused)
                .foregroundColor(.clear)
                .accentColor(.clear)
                .onChange(of: value) { newValue in
                    let filtered = String(newValue.filter(\.isNumber).prefix(count))
                    if filtered != newValue { value = filtered }
                }
                .submitLabel(.done)
                .onSubmit(onSubmit)
        }
        .contentShape(Rectangle())
        .onTapGesture { focused = true }
        .onAppear { focused = true }
    }
}

// MARK: - 配对成功全屏动画(对标 Android PairingSuccessOverlay)

private struct PairingSuccessOverlay: View {
    var onDismiss: () -> Void
    @State private var scale: CGFloat = 0.4
    @State private var opacity: Double = 0

    var body: some View {
        ZStack {
            Color.black.opacity(0.82).ignoresSafeArea()
            VStack(spacing: Theme.Space.lg) {
                ZStack {
                    Circle().fill(Theme.brand).frame(width: 88, height: 88)
                    Image(systemName: "checkmark")
                        .font(.system(size: 40, weight: .bold))
                        .foregroundColor(.white)
                }
                .scaleEffect(scale)
                .opacity(opacity)

                Text("配对成功").font(.title.bold()).foregroundColor(.white)
                Text("手机与电脑已连接").font(.footnote).foregroundColor(.white.opacity(0.6))
            }
        }
        .onAppear {
            withAnimation(.spring(response: 0.4, dampingFraction: 0.6)) { scale = 1; opacity = 1 }
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.6) { onDismiss() }
        }
    }
}
