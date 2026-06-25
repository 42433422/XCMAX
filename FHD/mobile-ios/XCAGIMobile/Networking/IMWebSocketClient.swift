import Foundation

/// IM 实时 WebSocket 客户端(对标 mobile-harmony `ImWebSocketClient.ets` / Android `ImWebSocketClient.kt`)。
///
/// 连接 `/ws/im?session_id=<sid>`(以会话 ID 鉴权,避免客户端自报 user_id)。
/// 含指数退避重连(5s→10s→…→5min 封顶)与 30s 心跳 ping。
/// 接收服务端 `{"type":"message","message":{...}}` 实时推送。
final class IMWebSocketClient: NSObject, @unchecked Sendable {
    enum Status: String { case idle, connecting, open, reconnecting, closed }

    struct Inbound: Decodable {
        var type: String?
        var conversationId: Int?
        var message: InboundMessage?
    }
    struct InboundMessage: Decodable {
        var id: Int?
        var conversationId: Int?
        var senderId: Int?
        var content: String?
        var body: String?
        var createdAt: String?
    }

    private let wsURL: URL?
    private var task: URLSessionWebSocketTask?
    private var session: URLSession!

    private var onMessage: (Inbound) -> Void = { _ in }
    private var onStatus: (Status) -> Void = { _ in }

    private var backoffMs: Int = 5_000
    private let backoffMaxMs = 300_000
    private let heartbeatMs: UInt64 = 30_000
    private var active = false
    private var heartbeatTask: Task<Void, Never>?

    init(baseURL: String, sessionId: String) {
        self.wsURL = IMWebSocketClient.toWsURL(baseURL, sessionId: sessionId)
        super.init()
        self.session = URLSession(configuration: .default)
    }

    func connect(onMessage: @escaping (Inbound) -> Void, onStatus: @escaping (Status) -> Void) {
        self.onMessage = onMessage
        self.onStatus = onStatus
        active = true
        open()
    }

    func disconnect() {
        active = false
        heartbeatTask?.cancel()
        heartbeatTask = nil
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        onStatus(.closed)
    }

    // MARK: - 内部

    private func open() {
        guard active, let url = wsURL else { return }
        onStatus(.connecting)
        let ws = session.webSocketTask(with: url)
        task = ws
        ws.resume()
        onStatus(.open)
        backoffMs = 5_000
        startHeartbeat()
        receiveLoop()
    }

    private func receiveLoop() {
        task?.receive { [weak self] result in
            guard let self else { return }
            switch result {
            case .failure:
                self.stopHeartbeat()
                self.scheduleReconnect()
            case .success(let message):
                switch message {
                case .string(let text):
                    self.handle(text: text)
                case .data(let data):
                    self.handle(text: String(decoding: data, as: UTF8.self))
                @unknown default:
                    break
                }
                self.receiveLoop()
            }
        }
    }

    private func handle(text raw: String) {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty || text == "{\"type\":\"pong\"}" { return }
        guard let data = text.data(using: .utf8) else { return }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        guard let inbound = try? decoder.decode(Inbound.self, from: data) else { return }
        if (inbound.type ?? "") == "message" {
            onMessage(inbound)
        }
    }

    private func startHeartbeat() {
        stopHeartbeat()
        heartbeatTask = Task { [weak self] in
            guard let self else { return }
            while !Task.isCancelled, self.active {
                try? await Task.sleep(nanoseconds: self.heartbeatMs * 1_000_000)
                guard !Task.isCancelled else { break }
                self.task?.send(.string("ping")) { _ in }
            }
        }
    }

    private func stopHeartbeat() {
        heartbeatTask?.cancel()
        heartbeatTask = nil
    }

    private func scheduleReconnect() {
        guard active else { onStatus(.closed); return }
        onStatus(.reconnecting)
        let delay = backoffMs
        backoffMs = min(backoffMs * 2, backoffMaxMs)
        Task { [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(delay) * 1_000_000)
            guard let self, self.active else { return }
            self.open()
        }
    }

    private static func toWsURL(_ baseURL: String, sessionId: String) -> URL? {
        var url = baseURL.trimmingCharacters(in: .whitespaces)
        if url.hasPrefix("https://") {
            url = "wss://" + String(url.dropFirst("https://".count))
        } else if url.hasPrefix("http://") {
            url = "ws://" + String(url.dropFirst("http://".count))
        } else if !url.isEmpty {
            url = "ws://" + url
        } else {
            return nil   // 无有效基址则不连接(不回退到内网/本地开发地址)
        }
        if !url.hasSuffix("/") { url += "/" }
        let encoded = sessionId.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? sessionId
        return URL(string: "\(url)ws/im?session_id=\(encoded)")
    }
}
