import SwiftUI

@MainActor
final class ChatViewModel: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var input = ""
    @Published var isStreaming = false

    let sessionId: String

    init(sessionId: String) { self.sessionId = sessionId }

    /// 发送一条消息:优先 SSE 逐字流,失败回退一次性 `api/ai/chat`(对标 Android SSE→HTTP 回退)。
    func send(using session: SessionManager) async {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isStreaming else { return }
        input = ""
        messages.append(ChatMessage(role: .user, text: text))
        messages.append(ChatMessage(role: .assistant, text: ""))
        let idx = messages.count - 1
        isStreaming = true
        defer { isStreaming = false }

        var accumulated = ""
        do {
            for try await chunk in session.makeSSEClient().stream(message: text) {
                switch chunk {
                case .token(let t):
                    accumulated += t
                    messages[idx].text = accumulated
                case .done(let reply):
                    if !reply.isEmpty { messages[idx].text = reply }
                }
            }
        } catch {
            // SSE 失败 → 回退一次性对话
            await fallback(text: text, idx: idx, session: session,
                           streamError: (error as? LocalizedError)?.errorDescription)
            return
        }
        if messages[idx].text.isEmpty {
            await fallback(text: text, idx: idx, session: session, streamError: nil)
        }
    }

    private func fallback(text: String, idx: Int, session: SessionManager, streamError: String?) async {
        do {
            let resp = try await session.api.chat(message: text, sessionId: sessionId)
            let reply = resp.bestReply
            messages[idx].text = reply.isEmpty ? "(无回复)" : reply
        } catch {
            let msg = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            messages[idx].text = "⚠️ " + (streamError ?? msg)
        }
    }
}

/// SSE 流式对话页(对标 Android `ChatScreen` / 鸿蒙 SSE 对话)。
struct ChatView: View {
    let title: String
    let sessionId: String

    @EnvironmentObject private var session: SessionManager
    @StateObject private var vm: ChatViewModel

    init(title: String, sessionId: String) {
        self.title = title
        self.sessionId = sessionId
        _vm = StateObject(wrappedValue: ChatViewModel(sessionId: sessionId))
    }

    var body: some View {
        VStack(spacing: 0) {
            if vm.messages.isEmpty {
                EmptyStateView(icon: "sparkles", title: "和 \(title) 开始对话吧", subtitle: "支持逐字流式回复")
            } else {
                ChatMessagesView(messages: vm.messages)
            }
            ChatInputBar(text: $vm.input, isBusy: vm.isStreaming) {
                Task { await vm.send(using: session) }
            }
        }
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
    }
}
