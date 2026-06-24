import SwiftUI

/// 单条聊天气泡。
struct ChatBubble: View {
    let message: ChatMessage

    private var isUser: Bool { message.role == .user }

    var body: some View {
        HStack(alignment: .top, spacing: Theme.Space.sm) {
            if isUser { Spacer(minLength: 40) }
            if !isUser { AvatarView(text: "AI", size: 32) }

            Text(message.text.isEmpty ? "…" : message.text)
                .textSelection(.enabled)
                .padding(.horizontal, Theme.Space.md)
                .padding(.vertical, Theme.Space.sm)
                .foregroundColor(isUser ? .white : .primary)
                .background(isUser ? Theme.brand : Theme.cardBackground)
                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.md, style: .continuous))

            if !isUser { Spacer(minLength: 40) }
        }
        .id(message.id)
    }
}

/// 可自动滚到底的消息列表。
struct ChatMessagesView: View {
    let messages: [ChatMessage]

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: Theme.Space.md) {
                    ForEach(messages) { ChatBubble(message: $0) }
                }
                .padding(Theme.Space.md)
            }
            .onChange(of: messages.last?.text) { _ in
                if let last = messages.last {
                    withAnimation(.easeOut(duration: 0.15)) {
                        proxy.scrollTo(last.id, anchor: .bottom)
                    }
                }
            }
            .onChange(of: messages.count) { _ in
                if let last = messages.last { proxy.scrollTo(last.id, anchor: .bottom) }
            }
        }
    }
}

/// 底部输入条。
struct ChatInputBar: View {
    @Binding var text: String
    var isBusy: Bool
    var onSend: () -> Void

    private var canSend: Bool {
        !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !isBusy
    }

    var body: some View {
        HStack(spacing: Theme.Space.sm) {
            TextField("输入消息…", text: $text, axis: .vertical)
                .lineLimit(1...4)
                .padding(.horizontal, Theme.Space.md)
                .padding(.vertical, Theme.Space.sm)
                .background(Theme.cardBackground)
                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.lg, style: .continuous))

            Button(action: onSend) {
                Image(systemName: isBusy ? "ellipsis" : "arrow.up.circle.fill")
                    .font(.system(size: 30))
                    .foregroundColor(canSend ? Theme.brand : .secondary)
            }
            .disabled(!canSend)
        }
        .padding(Theme.Space.sm)
        .background(.bar)
    }
}
