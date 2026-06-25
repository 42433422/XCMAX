import SwiftUI
import PhotosUI
import Vision
import UIKit
import AVFoundation

@MainActor
final class OcrViewModel: ObservableObject {
    @Published var image: UIImage?
    @Published var recognizedText = ""
    @Published var recognizing = false
    @Published var error: String?

    func handlePicked(_ item: PhotosPickerItem?) async {
        guard let item else { return }
        error = nil
        recognizedText = ""
        do {
            guard let data = try await item.loadTransferable(type: Data.self),
                  let ui = UIImage(data: data) else {
                error = "无法读取所选图片"; return
            }
            image = ui
            await recognize(ui)
        } catch {
            self.error = error.localizedDescription
        }
    }

    func handleCaptured(_ ui: UIImage) async {
        error = nil
        recognizedText = ""
        image = ui
        await recognize(ui)
    }

    private func recognize(_ ui: UIImage) async {
        guard let cg = ui.cgImage else { error = "图片格式不支持"; return }
        recognizing = true
        defer { recognizing = false }
        let text: String = await withCheckedContinuation { continuation in
            let request = VNRecognizeTextRequest { req, _ in
                let lines = (req.results as? [VNRecognizedTextObservation] ?? [])
                    .compactMap { $0.topCandidates(1).first?.string }
                continuation.resume(returning: lines.joined(separator: "\n"))
            }
            request.recognitionLevel = .accurate
            request.usesLanguageCorrection = true
            request.recognitionLanguages = ["zh-Hans", "en-US"]
            let handler = VNImageRequestHandler(cgImage: cg, orientation: .up, options: [:])
            DispatchQueue.global(qos: .userInitiated).async {
                do { try handler.perform([request]) }
                catch { continuation.resume(returning: "") }
            }
        }
        recognizedText = text
        if text.isEmpty { error = "未识别到文字" }
    }

    func copy() {
        UIPasteboard.general.string = recognizedText
    }
}

/// OCR 文字识别(对标 Android `OcrScreen` 入口 + 鸿蒙 CoreVisionKit)。
/// 拍照 / 相册 → 本机 Vision 识别 → 复制。Android 列拍照与相册两入口,iOS 用 on-device Vision 真实落地。
struct OcrView: View {
    @StateObject private var vm = OcrViewModel()
    @State private var picked: PhotosPickerItem?
    @State private var showCamera = false

    var body: some View {
        ScrollView {
            VStack(spacing: Theme.Space.lg) {
                // ── 入口(对标 Android「拍照识别 / 从相册选择」) ──
                VStack(spacing: 0) {
                    Button { presentCamera() } label: {
                        entryRow(icon: "camera.fill", tint: Theme.brand,
                                 title: "拍照识别", subtitle: "拍摄票据、表格或文档实时识别文字")
                    }
                    Divider().padding(.leading, 56)
                    PhotosPicker(selection: $picked, matching: .images) {
                        entryRow(icon: "photo.on.rectangle.angled", tint: .orange,
                                 title: "从相册选择", subtitle: "识别票据、表格截图与文档图片")
                    }
                }
                .background(Theme.cardBackground)
                .cornerRadius(Theme.Radius.md)
                .onChange(of: picked) { item in
                    Task { await vm.handlePicked(item) }
                }

                if let img = vm.image {
                    Image(uiImage: img).resizable().scaledToFit()
                        .frame(maxHeight: 220).cornerRadius(Theme.Radius.md)
                }

                if vm.recognizing { LoadingView(title: "识别中…").frame(height: 120) }

                if let e = vm.error { Text(e).font(.footnote).foregroundColor(.orange) }

                if !vm.recognizedText.isEmpty {
                    VStack(alignment: .leading, spacing: Theme.Space.sm) {
                        HStack {
                            Text("识别结果").font(.headline)
                            Spacer()
                            Button { vm.copy() } label: { Label("复制", systemImage: "doc.on.doc") }
                                .font(.footnote)
                        }
                        Text(vm.recognizedText)
                            .font(.callout).textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding().background(Theme.cardBackground).cornerRadius(Theme.Radius.md)
                    }
                }
            }
            .padding(Theme.Space.lg)
        }
        .navigationTitle("拍照识别")
        .navigationBarTitleDisplayMode(.inline)
        .sheet(isPresented: $showCamera) {
            CameraCaptureView { ui in
                showCamera = false
                if let ui { Task { await vm.handleCaptured(ui) } }
            }
            .ignoresSafeArea()
        }
    }

    private func entryRow(icon: String, tint: Color, title: String, subtitle: String) -> some View {
        HStack(spacing: Theme.Space.md) {
            Image(systemName: icon)
                .font(.system(size: 18)).foregroundColor(tint)
                .frame(width: 36, height: 36)
                .background(tint.opacity(0.12)).clipShape(RoundedRectangle(cornerRadius: Theme.Radius.sm))
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.body).foregroundColor(.primary)
                Text(subtitle).font(.caption).foregroundColor(.secondary)
            }
            Spacer()
            Image(systemName: "chevron.right").font(.caption).foregroundColor(.secondary.opacity(0.6))
        }
        .padding(.horizontal, Theme.Space.lg)
        .padding(.vertical, Theme.Space.md)
        .contentShape(Rectangle())
    }

    private func presentCamera() {
        // 无相机(模拟器)直接提示走相册。
        guard UIImagePickerController.isSourceTypeAvailable(.camera) else {
            vm.error = "当前设备不支持拍照,请改用「从相册选择」"
            return
        }
        Task {
            let status = AVCaptureDevice.authorizationStatus(for: .video)
            switch status {
            case .authorized: showCamera = true
            case .notDetermined:
                let granted = await AVCaptureDevice.requestAccess(for: .video)
                if granted { showCamera = true } else { vm.error = "需要相机权限以拍照识别" }
            default: vm.error = "需要相机权限,请在「设置 → 隐私 → 相机」中开启"
            }
        }
    }
}

/// 相机拍照采集(对标 Android 拍照入口);用 `UIImagePickerController` 取单张照片。
private struct CameraCaptureView: UIViewControllerRepresentable {
    var onResult: (UIImage?) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onResult: onResult) }

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = .camera
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ uiViewController: UIImagePickerController, context: Context) {}

    final class Coordinator: NSObject, UINavigationControllerDelegate, UIImagePickerControllerDelegate {
        let onResult: (UIImage?) -> Void
        init(onResult: @escaping (UIImage?) -> Void) { self.onResult = onResult }

        func imagePickerController(_ picker: UIImagePickerController,
                                   didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            onResult(info[.originalImage] as? UIImage)
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
            onResult(nil)
        }
    }
}
