import SwiftUI
import PhotosUI
@preconcurrency import Vision
import UIKit

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

/// OCR 文字识别(对标 Android ML Kit / 鸿蒙 CoreVisionKit):相册选图 → Vision 识别 → 复制。
struct OcrView: View {
    @StateObject private var vm = OcrViewModel()
    @State private var picked: PhotosPickerItem?

    var body: some View {
        ScrollView {
            VStack(spacing: Theme.Space.lg) {
                PhotosPicker(selection: $picked, matching: .images) {
                    Label("从相册选择图片", systemImage: "photo.on.rectangle.angled")
                        .frame(maxWidth: .infinity).padding(.vertical, Theme.Space.md)
                        .background(Theme.cardBackground).cornerRadius(Theme.Radius.md)
                }
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
        .navigationTitle("OCR 文字识别")
        .navigationBarTitleDisplayMode(.inline)
    }
}
