import SwiftUI

@MainActor
final class CsChatViewModel: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var input = ""
    @Published var info: CsInfo?
    @Published var isSending = false

    func load(_ api: APIClient) async {
        info = try? await api.csInfo()
        if let history = try? await api.csMessages() {
            messages = history.map {
                ChatMessage(role: ($0.role == "user" ? .user : .assistant), text: $0.text ?? "")
            }
        }
    }

    func send(_ api: APIClient) async {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isSending else { return }
        input = ""
        messages.append(ChatMessage(role: .user, text: text))
        isSending = true
        defer { isSending = false }
        do {
            let resp = try await api.csSend(message: text)
            let reply = resp.bestReply
            messages.append(ChatMessage(role: .assistant, text: reply.isEmpty ? "(无回复)" : reply))
        } catch {
            let msg = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            messages.append(ChatMessage(role: .assistant, text: "⚠️ " + msg))
        }
    }
}

/// 专属客服聊天(对标 Android `CsChatScreen`)。
struct CsChatView: View {
    var title: String = "专属客服"
    @EnvironmentObject private var session: SessionManager
    @StateObject private var vm = CsChatViewModel()

    var body: some View {
        VStack(spacing: 0) {
            if vm.messages.isEmpty {
                EmptyStateView(icon: "headphones", title: vm.info?.title ?? title,
                               subtitle: vm.info?.subtitle ?? "在线为您服务")
            } else {
                ChatMessagesView(messages: vm.messages)
            }
            ChatInputBar(text: $vm.input, isBusy: vm.isSending) {
                Task { await vm.send(session.api) }
            }
        }
        .navigationTitle(vm.info?.title ?? title)
        .navigationBarTitleDisplayMode(.inline)
        .task { await vm.load(session.api) }
    }
}
