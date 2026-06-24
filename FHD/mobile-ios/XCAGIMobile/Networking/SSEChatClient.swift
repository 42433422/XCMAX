import Foundation

/// SSE 流式对话客户端(对标 mobile-harmony `SseChatClient.ets` / Android `SseChatClient.kt`)。
///
/// 用 `URLSession.bytes` 逐行读取 `text/event-stream`,解析 `data: {json}` 帧,
/// 按 `type` 分发 token/done/error。端点:POST `/api/ai/chat/stream`。
/// 以 `AsyncThrowingStream` 顺序产出,消费方(@MainActor VM)按序更新 UI,不会乱序。
final class SSEChatClient: @unchecked Sendable {
    private let baseURL: String
    private let accessToken: String
    private let session: URLSession

    init(baseURL: String, accessToken: String = "") {
        self.baseURL = APIClient.normalize(baseURL)
        self.accessToken = accessToken
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 60
        config.timeoutIntervalForResource = 120
        self.session = URLSession(configuration: config)
    }

    enum Chunk {
        case token(String)
        case done(String)   // 最终完整回复
    }

    func stream(message: String) -> AsyncThrowingStream<Chunk, Error> {
        AsyncThrowingStream { continuation in
            let work = Task {
                do {
                    guard let url = URL(string: resolve(APIEndpoints.aiChatStream)) else {
                        continuation.finish(throwing: APIError.invalidURL); return
                    }
                    var req = URLRequest(url: url)
                    req.httpMethod = HTTPMethod.post.rawValue
                    req.setValue("application/json", forHTTPHeaderField: "Content-Type")
                    req.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                    if !accessToken.isEmpty {
                        req.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
                    }
                    req.httpBody = try JSONSerialization.data(withJSONObject: ["message": message])

                    let (bytes, response) = try await session.bytes(for: req)
                    let status = (response as? HTTPURLResponse)?.statusCode ?? 0
                    if status >= 400 {
                        continuation.finish(throwing: APIError.http(status: status, message: "")); return
                    }

                    for try await line in bytes.lines {
                        if Task.isCancelled { break }
                        let trimmed = line.trimmingCharacters(in: .whitespaces)
                        guard trimmed.hasPrefix("data:") else { continue }
                        let json = String(trimmed.dropFirst(5)).trimmingCharacters(in: .whitespaces)
                        if json.isEmpty || json == "[DONE]" { continue }
                        guard let event = Self.decode(json) else { continue }
                        switch event.type ?? "" {
                        case "token":
                            continuation.yield(.token(event.text ?? ""))
                        case "done":
                            continuation.yield(.done(Self.extractReply(event.result)))
                        case "error":
                            continuation.finish(throwing: APIError.business(event.message ?? "流式对话失败"))
                            return
                        default:
                            continue
                        }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: APIError.transport(error.localizedDescription))
                }
            }
            continuation.onTermination = { _ in work.cancel() }
        }
    }

    // MARK: - 帧解析

    private struct SSEEvent: Decodable {
        var type: String?
        var text: String?
        var message: String?
        var result: SSEResult?
    }
    private struct SSEResult: Decodable {
        var response: String?
        var reply: String?
        var message: String?
        var data: SSEResultData?
    }
    private struct SSEResultData: Decodable {
        var reply: String?
        var content: String?
        var message: String?
    }

    private static func decode(_ json: String) -> SSEEvent? {
        guard let data = json.data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode(SSEEvent.self, from: data)
    }

    private static func extractReply(_ result: SSEResult?) -> String {
        guard let result else { return "" }
        if let r = result.reply, !r.isEmpty { return r }
        if let r = result.response, !r.isEmpty { return r }
        if let r = result.data?.reply, !r.isEmpty { return r }
        if let r = result.data?.content, !r.isEmpty { return r }
        if let r = result.message, !r.isEmpty { return r }
        return ""
    }

    private func resolve(_ path: String) -> String {
        let cleaned = path.hasPrefix("/") ? String(path.dropFirst()) : path
        return baseURL + cleaned
    }
}
