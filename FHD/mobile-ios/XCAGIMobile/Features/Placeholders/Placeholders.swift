import SwiftUI

// 诚实占位页(对标 PARITY_MATRIX 中标注「待真机 / 后续」的能力)。
// 这些能力依赖原生设备框架(相机/VisionKit/APNs/WebView),需在真机分阶段补齐;
// 此处以可编译的占位呈现,而非假装已完成。

struct ScanQrPlaceholderView: View {
    var body: some View {
        WorkInProgressView(
            title: "扫一扫",
            note: "二维码扫描将接入 AVFoundation `AVCaptureMetadataOutput`(对标安卓 CameraX / 鸿蒙 ScanKit)。需真机相机权限验证。"
        )
    }
}

struct OcrPlaceholderView: View {
    var body: some View {
        WorkInProgressView(
            title: "OCR 文字识别",
            note: "文字识别将接入 Vision `VNRecognizeTextRequest` + PhotosUI 选图(对标安卓 ML Kit / 鸿蒙 CoreVisionKit)。需真机验证识别效果。"
        )
    }
}

struct NotificationPlaceholderView: View {
    var body: some View {
        WorkInProgressView(
            title: "通知中心",
            note: "推送将接入 APNs(UNUserNotificationCenter + device token 注册到 /devices/register)。需 Apple Push 证书与真机验证。"
        )
    }
}

struct MarketPlaceholderView: View {
    var body: some View {
        WorkInProgressView(
            title: "应用市场",
            note: "MOD 市场详情走 WKWebView 注入登录态(对标安卓 ModWebView / 鸿蒙 ArkWeb)。列表数据已可用 /mods,详情承载页后续接入。"
        )
    }
}

struct ImMessengerPlaceholderView: View {
    var body: some View {
        WorkInProgressView(
            title: "即时通讯 IM",
            note: "IM 实时收发的 WebSocket 客户端(IMWebSocketClient)已就绪(含退避重连 + 心跳);会话 UI 与历史拉取后续接入,需真机验证实时性。"
        )
    }
}
