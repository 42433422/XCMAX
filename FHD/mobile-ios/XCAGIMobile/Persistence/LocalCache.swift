import Foundation

/// 聊天 / IM 本地持久化(对标 Android Room `ChatCacheEntity` + `ConversationListStateEntity`)。
///
/// 按 `sessionId` 存取消息数组,以及会话列表的「最后预览 + 时间戳」用于微信风格副标题。
/// 实现用 UserDefaults(JSON 编码),无第三方依赖;线程安全由内部串行队列保证。
///
/// 用法:
/// - 缓存一条消息:`LocalCache.shared.appendMessage(.init(role: "user", text: "你好"), sessionId: "default")`
/// - 读历史:`let history = LocalCache.shared.messages(sessionId: "default")`
/// - 观察会话列表:`LocalCache.shared.conversationStates()`
final class LocalCache: @unchecked Sendable {
    static let shared = LocalCache()

    /// 一条持久化的聊天消息(角色 + 文本 + 时间戳)。
    struct CachedMessage: Codable, Hashable, Identifiable {
        var id: String
        var role: String          // user / assistant / system / cs
        var text: String
        var timestamp: Double     // 毫秒

        init(id: String = UUID().uuidString, role: String, text: String, timestamp: Double = Date().timeIntervalSince1970 * 1000) {
            self.id = id
            self.role = role.isEmpty ? "user" : role
            self.text = text
            self.timestamp = timestamp
        }
    }

    /// 会话列表条目状态(最后消息时间 + 预览),对标 Android ConversationListStateEntity。
    struct ConversationState: Codable, Hashable {
        var conversationId: String
        var lastMessageAt: Double
        var lastMessagePreview: String
    }

    private let defaults = UserDefaults.standard
    private let queue = DispatchQueue(label: "com.xiuci.xcagi.localcache", attributes: .concurrent)

    private let messagePrefix = "chat_cache."          // + sessionId
    private let conversationStateKey = "conversation_list_state"
    private let maxMessagesPerSession = 500

    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    private init() {}

    // MARK: - 消息读写(按 sessionId)

    /// 读取某会话的全部缓存消息(按时间升序)。无缓存返回空数组。
    func messages(sessionId: String) -> [CachedMessage] {
        let key = messageKey(sessionId)
        return queue.sync {
            guard let data = defaults.data(forKey: key),
                  let list = try? decoder.decode([CachedMessage].self, from: data) else { return [] }
            return list
        }
    }

    /// 整体覆盖写入某会话的消息数组(超过上限保留最近 N 条)。
    func setMessages(_ messages: [CachedMessage], sessionId: String) {
        let key = messageKey(sessionId)
        let trimmed = messages.suffix(maxMessagesPerSession)
        queue.async(flags: .barrier) {
            if let data = try? self.encoder.encode(Array(trimmed)) {
                self.defaults.set(data, forKey: key)
            }
        }
    }

    /// 追加一条消息到某会话,并刷新会话列表预览。
    func appendMessage(_ message: CachedMessage, sessionId: String) {
        let key = messageKey(sessionId)
        queue.async(flags: .barrier) {
            var list: [CachedMessage] = []
            if let data = self.defaults.data(forKey: key),
               let decoded = try? self.decoder.decode([CachedMessage].self, from: data) {
                list = decoded
            }
            list.append(message)
            if list.count > self.maxMessagesPerSession {
                list = Array(list.suffix(self.maxMessagesPerSession))
            }
            if let data = try? self.encoder.encode(list) {
                self.defaults.set(data, forKey: key)
            }
            self.markConversationActivityLocked(
                conversationId: sessionId,
                timestamp: message.timestamp,
                preview: Self.formatPreview(role: message.role, text: message.text)
            )
        }
    }

    /// 便捷:缓存一条 role/text 消息(供 ChatView / CsChatView / IM 复用)。
    func cache(role: String, text: String, sessionId: String) {
        appendMessage(CachedMessage(role: role, text: text), sessionId: sessionId)
    }

    /// 清空某会话的消息(不影响会话列表状态)。
    func clearMessages(sessionId: String) {
        queue.async(flags: .barrier) {
            self.defaults.removeObject(forKey: self.messageKey(sessionId))
        }
    }

    // MARK: - 会话列表状态(最后预览 + 时间戳)

    /// 读取全部会话列表状态(key=conversationId)。
    func conversationStates() -> [String: ConversationState] {
        queue.sync {
            guard let data = defaults.data(forKey: conversationStateKey),
                  let map = try? decoder.decode([String: ConversationState].self, from: data) else { return [:] }
            return map
        }
    }

    /// 标记某会话的活动(更新时间戳 + 预览),仅当时间更新或预览非空时写入。
    func markConversationActivity(conversationId: String,
                                  timestamp: Double = Date().timeIntervalSince1970 * 1000,
                                  preview: String = "") {
        queue.async(flags: .barrier) {
            self.markConversationActivityLocked(conversationId: conversationId, timestamp: timestamp, preview: preview)
        }
    }

    // MARK: - 全量清理(登出用)

    /// 清空所有聊天缓存与会话状态(对标 Android logout 时清 chatDao 等)。
    func clearAll() {
        queue.async(flags: .barrier) {
            for key in self.defaults.dictionaryRepresentation().keys where key.hasPrefix(self.messagePrefix) {
                self.defaults.removeObject(forKey: key)
            }
            self.defaults.removeObject(forKey: self.conversationStateKey)
        }
    }

    // MARK: - 内部

    /// 必须在 barrier 块内调用(假定已持有写锁)。
    private func markConversationActivityLocked(conversationId: String, timestamp: Double, preview: String) {
        guard !conversationId.isEmpty, timestamp > 0 else { return }
        var map: [String: ConversationState] = [:]
        if let data = defaults.data(forKey: conversationStateKey),
           let decoded = try? decoder.decode([String: ConversationState].self, from: data) {
            map = decoded
        }
        let normalizedPreview = preview.trimmingCharacters(in: .whitespacesAndNewlines)
        let existing = map[conversationId]
        if let existing {
            let newPreview = normalizedPreview.isEmpty ? existing.lastMessagePreview : normalizedPreview
            // 有新预览强制刷新;否则仅在更新时间时更新。
            if !normalizedPreview.isEmpty || timestamp > existing.lastMessageAt {
                map[conversationId] = ConversationState(
                    conversationId: conversationId,
                    lastMessageAt: max(timestamp, existing.lastMessageAt),
                    lastMessagePreview: newPreview
                )
            }
        } else {
            map[conversationId] = ConversationState(
                conversationId: conversationId,
                lastMessageAt: timestamp,
                lastMessagePreview: normalizedPreview
            )
        }
        if let data = try? encoder.encode(map) {
            defaults.set(data, forKey: conversationStateKey)
        }
    }

    private func messageKey(_ sessionId: String) -> String {
        messagePrefix + (sessionId.isEmpty ? "default" : sessionId)
    }

    /// 会话列表副标题预览:user 消息加「我:」前缀,折叠换行(对标 Android formatMessagePreview)。
    static func formatPreview(role: String, text: String) -> String {
        let normalized = text
            .replacingOccurrences(of: "\n", with: " ")
            .replacingOccurrences(of: "\r", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if normalized.isEmpty { return "" }
        return role.trimmingCharacters(in: .whitespaces).lowercased() == "user" ? "我: \(normalized)" : normalized
    }
}
