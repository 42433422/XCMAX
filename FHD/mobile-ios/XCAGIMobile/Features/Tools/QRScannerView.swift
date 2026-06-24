import SwiftUI
import UIKit
import AVFoundation

/// 相机二维码扫描(对标 Android CameraX / 鸿蒙 ScanKit)。
/// 用 `AVCaptureMetadataOutput` 识别 QR,识别到即回调一次并停止。
struct QRScannerView: UIViewControllerRepresentable {
    var onFound: (String) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onFound: onFound) }

    func makeUIViewController(context: Context) -> ScannerViewController {
        let vc = ScannerViewController()
        vc.coordinator = context.coordinator
        return vc
    }

    func updateUIViewController(_ uiViewController: ScannerViewController, context: Context) {}

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
            onFound(value)
        }
    }
}

/// 承载 AVCaptureSession 的 UIKit 控制器。
final class ScannerViewController: UIViewController {
    weak var coordinator: QRScannerView.Coordinator?
    private let session = AVCaptureSession()
    private var preview: AVCaptureVideoPreviewLayer?

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        configureSession()
    }

    private func configureSession() {
        guard let device = AVCaptureDevice.default(for: .video),
              let input = try? AVCaptureDeviceInput(device: device),
              session.canAddInput(input) else { return }
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

/// 扫一扫页:扫码 → 展示结果 → 可用作桌面绑定码连接(对标 Android `ScanQrScreen`)。
struct ScanQrView: View {
    @EnvironmentObject private var session: SessionManager
    @State private var scanned: String?
    @State private var permissionDenied = false
    @State private var applying = false

    var body: some View {
        ZStack {
            if permissionDenied {
                ErrorStateView(message: "未获得相机权限。请在「设置 → 隐私 → 相机」中开启。")
            } else if let code = scanned {
                resultView(code)
            } else {
                QRScannerView { value in scanned = value }
                    .ignoresSafeArea()
                VStack {
                    Spacer()
                    Text("将二维码放入取景框")
                        .font(.footnote).foregroundColor(.white)
                        .padding(.horizontal, Theme.Space.lg).padding(.vertical, Theme.Space.sm)
                        .background(.black.opacity(0.5)).clipShape(Capsule())
                        .padding(.bottom, Theme.Space.xl)
                }
            }
        }
        .navigationTitle("扫一扫")
        .navigationBarTitleDisplayMode(.inline)
        .task { await checkPermission() }
    }

    private func resultView(_ code: String) -> some View {
        VStack(spacing: Theme.Space.lg) {
            Image(systemName: "qrcode.viewfinder").font(.system(size: 48)).foregroundColor(Theme.brand)
            Text("扫描结果").font(.headline)
            Text(code).font(.callout.monospaced()).multilineTextAlignment(.center)
                .padding().background(Theme.cardBackground).cornerRadius(Theme.Radius.md)
            if let err = session.lastError { Text(err).font(.footnote).foregroundColor(.red) }
            Button {
                applying = true
                Task { await session.applyPairing(code: code); applying = false }
            } label: {
                Text(applying ? "连接中…" : "用作桌面绑定码连接")
                    .frame(maxWidth: .infinity).padding(.vertical, Theme.Space.sm)
            }
            .buttonStyle(.borderedProminent).disabled(applying)
            Button("重新扫描") { scanned = nil }.font(.footnote)
            Spacer()
        }
        .padding(Theme.Space.xl)
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
}
