part of 'mobile_repository.dart';

abstract class _RepoChatBase extends _RepoRelayBase {
  _RepoChatBase({
    super.client,
    super.imWebSocket,
  });

  Future<String> streamAttachedMessage({
    required ConversationItem conversation,
    required String body,
    required List<MobileChatAttachment> attachments,
    required String idempotencyKey,
    bool resumeOnly = false,
    List<ChatMessage> recentMessages = const [],
    void Function(String)? onToken,
  }) async {
    if (conversation.type != ConversationType.pinnedAssistant) {
      throw const MobileRepositoryException('请在小C对话中处理附件');
    }
    final generation = _client.authGeneration;
    final base = await _client.resolveSessionBaseUrl();
    await _requireChatScope(generation, base);
    Future<void> cache(ChatRole role, String text, {ChatDeliveryStatus status = ChatDeliveryStatus.sent}) =>
        _cacheChatMessage(conversation.id, role: role, body: text,
            turnId: idempotencyKey, status: status,
            expectedAuthGeneration: generation, expectedBaseUrl: base);
    if (!resumeOnly) await cache(ChatRole.user, body);
    late final String reply;
    try {
      reply = await _client.streamAttachmentChat(body,
          conversationId: conversation.id,
          attachments: attachments,
          idempotencyKey: idempotencyKey,
          resumeOnly: resumeOnly,
          recentMessages: _recentChatContext(recentMessages),
          onToken: onToken);
    } on MobileApiException catch (error) {
      if (error.errorCode == 'CHAT_RECEIPT_PENDING') {
        await cache(ChatRole.assistant, error.message, status: ChatDeliveryStatus.pending);
      }
      rethrow;
    }
    await cache(ChatRole.assistant, reply);
    await _requireChatScope(generation, base);
    return reply;
  }

  Future<Map<String, Object?>> loadChatComposerDraft(
      String conversationId) async {
    final scope = await _offlineScope();
    final store = await openOfflineStore(expectedScope: scope);
    if (store == null || scope != await _offlineScope()) return const {};
    final draft = await store.readChatDraft(conversationId);
    return scope == await _offlineScope() ? draft : const {};
  }

  Future<void> saveChatComposerDraft(String conversationId, String text,
      {List<String> attachmentNames = const []}) async {
    final scope = await _offlineScope();
    final store = await openOfflineStore(expectedScope: scope);
    if (store == null || scope != await _offlineScope()) return;
    await store.saveChatDraft(conversationId, text,
        attachmentNames: attachmentNames);
  }

  Future<List<ChatMessage>> loadInitialMessages(
    ConversationItem conversation,
  ) async {
    final generation = _client.authGeneration;
    final base = await _client.resolveSessionBaseUrl();
    unawaited(flushPendingMessages());
    final cached = await _loadCachedChat(conversation.id);
    await _requireChatScope(generation, base);
    if (cached.isNotEmpty) return cached;

    final tool = conversation.type.superTool;
    if (tool == null) return const [];

    final response = await _client.superEmployeeMessages(tool);
    await _requireChatScope(generation, base);
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
    final reply = await streamMessage(conversation: conversation, body: body);
    return _assistantMessage(conversation.id, reply);
  }

  Future<String> streamMessage({
    required ConversationItem conversation,
    required String body,
    int userId = 0,
    String idempotencyKey = '',
    bool resumeOnly = false,
    List<ChatMessage> recentMessages = const [],
    bool cacheUserMessage = true,
    void Function(String token)? onToken,
    void Function(RelayTaskProgress progress)? onStatus,
    bool Function()? isCancelled,
  }) async {
    final generation = _client.authGeneration;
    final base = await _client.resolveSessionBaseUrl();
    if (idempotencyKey.trim().isEmpty && !resumeOnly) {
      idempotencyKey = 'mobile-${DateTime.now().microsecondsSinceEpoch}-${Random.secure().nextInt(1 << 32).toRadixString(16)}';
    }
    Future<void> requireScope() => _requireChatScope(generation, base);
    Future<void> cache(ChatRole role, String body, {ChatDeliveryStatus status = ChatDeliveryStatus.sent}) async {
      await _cacheChatMessage(conversation.id,
          role: role,
          body: body,
          turnId: idempotencyKey,
          status: status,
          expectedAuthGeneration: generation,
          expectedBaseUrl: base);
      await requireScope();
    }

    await requireScope();
    final tool = conversation.type.superTool;
    final text = body.trim();
    if (text.isEmpty && !resumeOnly) {
      throw const MobileRepositoryException('消息不能为空');
    }

    if (tool != null) {
      // A caller retrying the same turn without resumeOnly is still a retry.
      // Read the persisted original channel rather than replace its claim.
      final dispatch = idempotencyKey.isEmpty
          ? const <String, Object?>{}
          : await _turnDispatch(conversation.id, idempotencyKey);
      await requireScope();
      if (resumeOnly || dispatch.isNotEmpty) {
        if (dispatch.isNotEmpty) {
          final reply = dispatch['channel'] == 'relay'
              ? await _readRelayTurn(conversationId: conversation.id, dispatch: dispatch,
                  requireScope: requireScope, onToken: onToken, onStatus: onStatus,
                  isCancelled: isCancelled)
              : await _client.readSuperEmployeeTurn(tool: tool, conversationId: conversation.id,
                  idempotencyKey: idempotencyKey, baseUrl: '${dispatch['base_url']}',
                  expectedConnectionBase: '${dispatch['connection_base']}');
          await cache(ChatRole.assistant, reply);
          return reply;
        }
        if (idempotencyKey.isNotEmpty) {
          throw MobileApiException(statusCode: 409, errorCode: 'CHAT_RECEIPT_PENDING',
              message: '当前账号或连接没有这条原任务的派发记录，请恢复原连接后核对，未重新派发。',
              body: {'turn_id': idempotencyKey, 'execution_state': 'unknown', 'requires_reconciliation': true});
        }
        final reply = await resumeRelayTask(conversationId: conversation.id,
            onToken: onToken, onStatus: onStatus, isCancelled: isCancelled);
        if (reply != null) return reply;
        throw MobileApiException(statusCode: 409, errorCode: 'CHAT_RECEIPT_PENDING',
            message: '原任务回执待核对，请在任务工作区查看；未重新派发。',
            body: {'turn_id': idempotencyKey, 'execution_state': 'unknown', 'requires_reconciliation': true});
      }
      if (cacheUserMessage) {
        await cache(ChatRole.user, text);
      }
      final localBaseUrl = await _superEmployeeLanBaseUrl();
      await requireScope();
      if (localBaseUrl.isNotEmpty) {
        await _saveTurnDispatch(conversation.id, idempotencyKey, channel: 'super',
            baseUrl: localBaseUrl, requireScope: requireScope);
        // 第 1 级：LAN SSE 流式（逐 token 输出，体验最佳）
        try {
          final reply = await _client.streamSuperEmployeeMessage(
            tool,
            text,
            baseUrl: localBaseUrl,
            idempotencyKey: idempotencyKey,
            conversationId: conversation.id,
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
          await cache(ChatRole.assistant, reply);
          return reply;
        } catch (sseError) {
          _throwIfCancelled(isCancelled);
          await requireScope();
          // Only a missing SSE route proves that no task was dispatched.
          if (sseError is MobileApiException &&
              [404, 405].contains(sseError.statusCode)) {
            final reply = await _postSuperEmployeeMessage(
              tool,
              text,
              baseUrl: localBaseUrl,
              conversationId: conversation.id,
              idempotencyKey: idempotencyKey,
            );
            _throwIfCancelled(isCancelled);
            await cache(ChatRole.assistant, reply);
            return reply;
          }
          // Even a raw socket error cannot prove the server did not accept
          // the POST. Failing over to relay would create a second execution.
          // Read the stable original turn on the original LAN backend only.
          if (sseError is SocketException) {
            final reply = await _client.readSuperEmployeeTurn(
              tool: tool,
              conversationId: conversation.id,
              idempotencyKey: idempotencyKey,
              baseUrl: localBaseUrl,
              expectedConnectionBase: base,
            );
            _throwIfCancelled(isCancelled);
            await cache(ChatRole.assistant, reply);
            return reply;
          }
          rethrow;
        }
      }
      final relayKind = relayKindForConversation(conversation.id);
      final relayId = await _relayIdForSuperEmployeeDispatch();
      await requireScope();
      if (relayKind != null && relayId.isNotEmpty) {
        final dispatch = await _saveTurnDispatch(conversation.id, idempotencyKey,
            channel: 'relay', baseUrl: base, relayId: relayId, requireScope: requireScope);
        // 第 3 级：relay 中继轮询（跨网络，状态轮询模拟流式）
        final reply = await _streamRelaySuperEmployeeTask(
          relayId: relayId,
          relayKind: relayKind,
          conversationId: conversation.id,
          message: text,
          dispatch: dispatch,
          onToken: onToken,
          onStatus: onStatus,
          isCancelled: isCancelled,
          requireScope: requireScope,
        );
        _throwIfCancelled(isCancelled);
        if (reply.trim().isNotEmpty) {
          await cache(ChatRole.assistant, reply);
        }
        await requireScope();
        return reply.ifEmpty('已收到，我会继续处理。');
      }
      await _saveTurnDispatch(conversation.id, idempotencyKey, channel: 'super',
          baseUrl: base, requireScope: requireScope);
      final reply = await _postSuperEmployeeMessage(tool, text, baseUrl: base,
          conversationId: conversation.id, idempotencyKey: idempotencyKey);
      _throwIfCancelled(isCancelled);
      await cache(ChatRole.assistant, reply);
      return reply;
    }

    if (cacheUserMessage && !resumeOnly) {
      await cache(ChatRole.user, text);
    }
    final employeeRef = _employeeConversationRef(conversation.id);
    final effectiveUserId = userId > 0 ? userId : await _loadCurrentUserId();
    await requireScope();
    late final String reply;
    try {
      reply = employeeRef != null
          ? await _client.streamEmployeeChat(message: text,
              employeeId: employeeRef.employeeId, modId: employeeRef.modId,
              conversationId: conversation.id, userId: effectiveUserId,
              idempotencyKey: idempotencyKey, resumeOnly: resumeOnly, onToken: onToken)
          : await _client.streamChat(text, sessionId: conversation.id,
              userId: effectiveUserId, idempotencyKey: idempotencyKey,
              resumeOnly: resumeOnly, recentMessages: _recentChatContext(recentMessages),
              onToken: onToken);
    } on MobileApiException catch (error) {
      if (error.errorCode == 'CHAT_RECEIPT_PENDING') {
        await cache(ChatRole.assistant, error.message, status: ChatDeliveryStatus.pending);
      }
      rethrow;
    }
    _throwIfCancelled(isCancelled);
    await cache(ChatRole.assistant, reply);
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
    final generation = _client.authGeneration;
    final base = await _client.resolveSessionBaseUrl();
    Future<void> requireScope() => _requireChatScope(generation, base);
    await requireScope();
    final taskId = await _inflightRelayTask(conversationId);
    await requireScope();
    if (taskId.isEmpty) return null;
    if (await _clearInflightIfRelayChanged(conversationId, taskId,
        requireScope: requireScope)) {
      return null;
    }
    await requireScope();
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
      requireScope: requireScope,
    );
    _throwIfCancelled(isCancelled);
    if (reply.trim().isNotEmpty) {
      await _cacheChatMessage(
        conversationId,
        role: ChatRole.assistant,
        body: reply,
        expectedAuthGeneration: generation,
        expectedBaseUrl: base,
      );
    }
    await requireScope();
    return reply;
  }

  Future<void> deleteCachedChatMessage({
    required String conversationId,
    required ChatMessage message,
  }) async {
    final scope = await _offlineScope();
    final id = conversationId.trim();
    if (id.isEmpty) return;
    final targetTs = message.cacheTimestampMs;
    if (targetTs <= 0) return;
    final store = await openOfflineStore(expectedScope: scope);
    if (scope != await _offlineScope()) return;
    await store?.removeMessageByTimestamp(id, targetTs);
  }

  // ── 离线待发送队列 ──────────────────────────────────────────

  bool _flushingOutbox = false;

  /// 断网时把消息写入 SQLite 队列；返回 0 表示离线库不可用或内容为空。
  Future<int> enqueuePendingMessage({
    required ConversationItem conversation,
    required String body,
    String idempotencyKey = '',
  }) async {
    final scope = await _offlineScope();
    final generation = _client.authGeneration;
    final store = await openOfflineStore(expectedScope: scope);
    if (store == null || scope != await _offlineScope()) return 0;
    return store.enqueueMessage(
      conversationId: conversation.id,
      conversationType: conversation.type,
      title: conversation.title,
      body: body,
      authGeneration: generation,
      idempotencyKey: idempotencyKey,
      // This call site runs only after a send threw; a timeout cannot prove
      // the POST was never committed. Resume by receipt GET, never resend.
      requiresReconciliation: true,
    );
  }

  Future<int> pendingMessageCount() async {
    final store = await openOfflineStore();
    if (store == null) return 0;
    return store.pendingMessageCount();
  }

  /// 手动重发或重连成功后，清掉同一内容的排队记录，避免重复发送。
  Future<void> removeQueuedMessage(String conversationId, String body, {String idempotencyKey = ''}) async {
    final store = await openOfflineStore();
    if (idempotencyKey.isNotEmpty) {
      await store?.removePendingByTurn(conversationId, idempotencyKey);
    } else {
      await store?.removePendingByBody(conversationId, body);
    }
  }

  /// 只读核对已持久化的原任务；旧版 pending 不能证明尚未派发。
  Future<int> flushPendingMessages() async {
    if (_flushingOutbox) return 0;
    _flushingOutbox = true;
    var sent = 0;
    try {
      final scope = await _offlineScope();
      final store = await openOfflineStore(expectedScope: scope);
      if (store == null || scope != await _offlineScope()) return 0;
      final pending = await store.pendingMessages(
          limit: 5, authGeneration: _client.authGeneration);
      for (final item in pending) {
        if (scope != await _offlineScope()) break;
        if (item.authGeneration != _client.authGeneration) {
          // Credentials changed; retain the unknown original outcome until
          // the owner can reconcile it against the original authorized scope.
          continue;
        }
        // Do not promote an unknown result to another write attempt.
        await store.markReconciliationRequired(item.id);
        if (scope != await _offlineScope()) break;
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
            idempotencyKey: item.idempotencyKey,
            // Legacy pending rows may have been downgraded after a lost POST.
            // No persisted row proves that the server never received it.
            resumeOnly: true,
            cacheUserMessage: false,
          );
          await store.markSent(item.id);
          sent++;
        } catch (error) {
          await store.markFailed(item.id, error.toString(),
              // Once dispatch was attempted, a socket error or timeout cannot
              // establish that the server did not commit the original turn.
              requiresReconciliation: true,
              terminal: error is MobileApiException && error.errorCode == 'CHAT_RECEIPT_TERMINAL');
        }
      }
    } finally {
      _flushingOutbox = false;
    }
    return sent;
  }
}
