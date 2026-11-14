part of 'mobile_repository.dart';

abstract class _RepoChatBase extends _RepoRelayBase {
  _RepoChatBase({
    MobileApiClient? client,
    ImWebSocketClient? imWebSocket,
  }) : super(client: client, imWebSocket: imWebSocket);

  Future<List<ChatMessage>> loadInitialMessages(
    ConversationItem conversation,
  ) async {
    unawaited(flushPendingMessages());
    final cached = await _loadCachedChat(conversation.id);
    if (cached.isNotEmpty) return cached;

    final tool = conversation.type.superTool;
    if (tool == null) return const [];

    final response = await _client.superEmployeeMessages(tool);
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('超级员工消息加载失败'));
    }
    final messages = response.data ?? const <SuperEmployeeMessage>[];
    return messages
        .map((message) => message.toChatMessage(conversation.id))
        .toList(growable: false);
  }

  Future<ChatMessage> sendMessage({
    required ConversationItem conversation,
    required String body,
  }) async {
    final tool = conversation.type.superTool;
    final text = body.trim();
    if (text.isEmpty) {
      throw const MobileRepositoryException('消息不能为空');
    }

    if (tool != null) {
      final reply = await streamMessage(conversation: conversation, body: text);
      return _assistantMessage(conversation.id, reply);
    }

    final employeeRef = _employeeConversationRef(conversation.id);
    if (employeeRef != null) {
      final reply = await _client.streamEmployeeChat(
        message: text,
        employeeId: employeeRef.employeeId,
        modId: employeeRef.modId,
        conversationId: conversation.id,
        userId: await _loadCurrentUserId(),
      );
      return _assistantMessage(conversation.id, reply.ifEmpty('已收到。'));
    }

    final response = await _client.chat(text, sessionId: conversation.id);
    final reply = _assistantReplyFromMap(response).ifEmpty('已收到。');
    return _assistantMessage(conversation.id, reply);
  }

  Future<String> streamMessage({
    required ConversationItem conversation,
    required String body,
    int userId = 0,
    List<ChatMessage> recentMessages = const [],
    bool cacheUserMessage = true,
    void Function(String token)? onToken,
    void Function(RelayTaskProgress progress)? onStatus,
    bool Function()? isCancelled,
  }) async {
    final tool = conversation.type.superTool;
    final text = body.trim();
    if (text.isEmpty) {
      throw const MobileRepositoryException('消息不能为空');
    }

    if (tool != null) {
      if (cacheUserMessage) {
        await _cacheChatMessage(conversation.id,
            role: ChatRole.user, body: text);
      }
      final localBaseUrl = await _superEmployeeLanBaseUrl();
      if (localBaseUrl.isNotEmpty) {
        // 第 1 级：LAN SSE 流式（逐 token 输出，体验最佳）
        try {
          final reply = await _client.streamSuperEmployeeMessage(
            tool,
            text,
            baseUrl: localBaseUrl,
            onToken: (token) {
              if (isCancelled != null && isCancelled()) return;
              onToken?.call(token);
            },
            onStatus: (status) {
              if (isCancelled != null && isCancelled()) return;
              onToken?.call('\n$status\n');
            },
            isCancelled: isCancelled,
          );
          _throwIfCancelled(isCancelled);
          await _cacheChatMessage(
            conversation.id,
            role: ChatRole.assistant,
            body: reply,
          );
          return reply;
        } catch (sseError) {
          _throwIfCancelled(isCancelled);
          // 第 2 级：LAN 直答（一次性返回，SSE 不可用时的同城 fallback）
          try {
            final reply = await _postSuperEmployeeMessage(
              tool,
              text,
              baseUrl: localBaseUrl,
            );
            _throwIfCancelled(isCancelled);
            await _cacheChatMessage(
              conversation.id,
              role: ChatRole.assistant,
              body: reply,
            );
            return reply;
          } catch (e) {
            _throwIfCancelled(isCancelled);
            final sink = onToken;
            if (sink != null) {
              sink('〔局域网连接失败，正在切换到云端中继〕\n');
            }
          }
        }
      }
      final relayKind = relayKindForConversation(conversation.id);
      final relayId = await _relayIdForSuperEmployeeDispatch();
      if (relayKind != null && relayId.isNotEmpty) {
        // 第 3 级：relay 中继轮询（跨网络，状态轮询模拟流式）
        final reply = await _streamRelaySuperEmployeeTask(
          relayId: relayId,
          relayKind: relayKind,
          conversationId: conversation.id,
          message: text,
          onToken: onToken,
          onStatus: onStatus,
          isCancelled: isCancelled,
        );
        _throwIfCancelled(isCancelled);
        if (reply.trim().isNotEmpty) {
          await _cacheChatMessage(
            conversation.id,
            role: ChatRole.assistant,
            body: reply,
          );
        }
        return reply.ifEmpty('已收到，我会继续处理。');
      }
      final reply = await _postSuperEmployeeMessage(tool, text);
      _throwIfCancelled(isCancelled);
      await _cacheChatMessage(
        conversation.id,
        role: ChatRole.assistant,
        body: reply,
      );
      return reply;
    }

    final employeeRef = _employeeConversationRef(conversation.id);
    if (employeeRef != null) {
      if (cacheUserMessage) {
        await _cacheChatMessage(conversation.id,
            role: ChatRole.user, body: text);
      }
      final effectiveUserId = userId > 0 ? userId : await _loadCurrentUserId();
      final reply = await _client.streamEmployeeChat(
        message: text,
        employeeId: employeeRef.employeeId,
        modId: employeeRef.modId,
        conversationId: conversation.id,
        userId: effectiveUserId,
        onToken: onToken,
      );
      _throwIfCancelled(isCancelled);
      await _cacheChatMessage(
        conversation.id,
        role: ChatRole.assistant,
        body: reply,
      );
      return reply;
    }

    if (cacheUserMessage) {
      await _cacheChatMessage(conversation.id, role: ChatRole.user, body: text);
    }
    final effectiveUserId = userId > 0 ? userId : await _loadCurrentUserId();
    final reply = await _client.streamChat(
      text,
      sessionId: conversation.id,
      userId: effectiveUserId,
      recentMessages: _recentChatContext(recentMessages),
      onToken: onToken,
    );
    _throwIfCancelled(isCancelled);
    await _cacheChatMessage(
      conversation.id,
      role: ChatRole.assistant,
      body: reply,
    );
    return reply;
  }

  Future<bool> hasInflightRelay(String conversationId) async {
    return _inflightRelayTask(conversationId).then((value) => value.isNotEmpty);
  }

  Future<String?> resumeRelayTask({
    required String conversationId,
    void Function(String token)? onToken,
    void Function(RelayTaskProgress progress)? onStatus,
    bool Function()? isCancelled,
  }) async {
    final taskId = await _inflightRelayTask(conversationId);
    if (taskId.isEmpty) return null;
    if (await _clearInflightIfRelayChanged(conversationId, taskId)) {
      return null;
    }
    final kind = relayKindForConversation(conversationId);
    final toolLabel = toolLabelForRelayKind(kind ?? 'codex.invoke');
    onStatus?.call(
      RelayTaskProgress(
        taskId: taskId,
        status: 'resuming',
        toolLabel: toolLabel,
      ),
    );
    onToken?.call('思考中...');
    final reply = await _pollRelayTask(
      taskId: taskId,
      toolLabel: toolLabel,
      conversationId: conversationId,
      onToken: onToken,
      onStatus: onStatus,
      isCancelled: isCancelled,
    );
    _throwIfCancelled(isCancelled);
    if (reply.trim().isNotEmpty) {
      await _cacheChatMessage(
        conversationId,
        role: ChatRole.assistant,
        body: reply,
      );
    }
    return reply;
  }

  Future<void> deleteCachedChatMessage({
    required String conversationId,
    required ChatMessage message,
  }) async {
    final generation = _client.authGeneration;
    final id = conversationId.trim();
    if (id.isEmpty) return;
    final targetTs = message.cacheTimestampMs;
    if (targetTs <= 0) return;
    final store = await openOfflineStore();
    if (store != null) {
      await store.removeMessageByTimestamp(id, targetTs);
      return;
    }
    final session = await _client.loadSession();
    final rows = [
      ...(session.cachedChatMessages[id] ?? const <Map<String, Object?>>[]),
    ];
    if (rows.isEmpty) return;

    final index = rows.indexWhere(
      (row) => _cachedChatTimestampMs(row) == targetTs,
    );
    if (index < 0) return;
    rows.removeAt(index);

    final cache = Map<String, List<Map<String, Object?>>>.of(
      session.cachedChatMessages,
    );
    if (rows.isEmpty) {
      cache.remove(id);
    } else {
      cache[id] = rows;
    }
    await _client.saveSession(session.copyWith(cachedChatMessages: cache),
        authGeneration: generation);
  }

  // ── 离线待发送队列 ──────────────────────────────────────────

  bool _flushingOutbox = false;

  /// 断网时把消息写入 SQLite 队列；返回 0 表示离线库不可用或内容为空。
  Future<int> enqueuePendingMessage({
    required ConversationItem conversation,
    required String body,
  }) async {
    final store = await openOfflineStore();
    if (store == null) return 0;
    return store.enqueueMessage(
      conversationId: conversation.id,
      conversationType: conversation.type,
      title: conversation.title,
      body: body,
      authGeneration: _client.authGeneration,
    );
  }

  Future<int> pendingMessageCount() async {
    final store = await openOfflineStore();
    if (store == null) return 0;
    return store.pendingMessageCount();
  }

  /// 手动重发或重连成功后，清掉同一内容的排队记录，避免重复发送。
  Future<void> removeQueuedMessage(String conversationId, String body) async {
    final store = await openOfflineStore();
    await store?.removePendingByBody(conversationId, body);
  }

  /// 依次重放待发送消息；跨账号的旧队列直接丢弃，避免串号。
  Future<int> flushPendingMessages() async {
    if (_flushingOutbox) return 0;
    final store = await openOfflineStore();
    if (store == null) return 0;
    _flushingOutbox = true;
    var sent = 0;
    try {
      final pending = await store.pendingMessages(limit: 5);
      for (final item in pending) {
        if (item.authGeneration != _client.authGeneration) {
          await store.markSent(item.id);
          continue;
        }
        await store.markSending(item.id);
        try {
          await streamMessage(
            conversation: ConversationItem(
              id: item.conversationId,
              type: item.conversationType,
              title: item.title,
              subtitle: '',
              timestampText: '',
            ),
            body: item.body,
            cacheUserMessage: false,
          );
          await store.markSent(item.id);
          sent++;
        } catch (error) {
          await store.markFailed(item.id, error.toString());
        }
      }
    } finally {
      _flushingOutbox = false;
    }
    return sent;
  }
}
