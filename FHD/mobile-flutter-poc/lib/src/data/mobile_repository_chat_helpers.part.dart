part of 'mobile_repository.dart';

abstract class _RepoHelpersBase extends _RepoPairingAuthBase {
  _RepoHelpersBase({
    super.client,
    super.imWebSocket,
  });

  Future<int> _loadCurrentUserId() async {
    try {
      return (await loadMe()).user?.id ?? 0;
    } catch (_) {
      return 0;
    }
  }

  List<ConversationItem> fallbackConversations({
    bool adminMode = true,
    bool enterpriseMode = true,
  }) {
    return _sortConversationItems([
      ..._fixedConversationItems(
        showCodex: adminMode,
        showCursor: adminMode,
        showClaude: adminMode,
        showTrae: adminMode,
        showCustomerService: enterpriseMode && !adminMode,
        states: _emptyConversationStates,
      ),
      if (adminMode) ...adminDutyRosterConversationItems(),
    ]);
  }

  Future<String> _relayIdForSuperEmployeeDispatch() async {
    final generation = _client.authGeneration;
    final session = await _client.loadSession();
    final storedRelayId = session.relayDesktopId.trim();
    try {
      final response = await _client.relayDesktops();
      if (!response.success) return storedRelayId;
      final rows = _relayDesktopRows(
        response.data,
      ).where(_relayDesktopIsDispatchable).toList(growable: false);
      // API 正常但账号下尚无 paired 桌面：不要误用 build 注入/历史 relay_id 去排队。
      if (rows.isEmpty) return '';

      // 账号下可能累积大量历史 paired 桌面；只派给近期在线（last_seen≤5min）的执行端，
      // 避免任务进死队列后误回落云端 CLI。
      if (storedRelayId.isNotEmpty) {
        for (final row in rows) {
          if (_stringField(row, 'relay_id') == storedRelayId &&
              _relayDesktopIsFresh(row)) {
            return storedRelayId;
          }
        }
      }

      final freshRows =
          rows.where(_relayDesktopIsFresh).toList(growable: false);
      if (freshRows.isEmpty) {
        throw const MobileRepositoryException(
          '当前没有在线的电脑执行端。请在本机 Mac 打开 XCAGI 并保持桌面云中继运行后再试。',
        );
      }

      freshRows.sort(
        (a, b) => _relayDesktopSortKey(a).compareTo(_relayDesktopSortKey(b)),
      );
      final latest = freshRows.last;
      final latestRelayId = _stringField(latest, 'relay_id');
      if (latestRelayId.isEmpty) return '';
      if (latestRelayId != storedRelayId) {
        await _client.persistRelayBindingMeta(latestRelayId, latest,
            authGeneration: generation);
      }
      return latestRelayId;
    } on MobileRepositoryException {
      rethrow;
    } catch (_) {
      return storedRelayId;
    }
  }

  Future<String> _inflightRelayTask(String conversationId) async {
    final scope = await _offlineScope();
    final store = await openOfflineStore(expectedScope: scope);
    final task = await store?.inflightTaskId(conversationId.trim()) ?? '';
    return scope == await _offlineScope() ? task : '';
  }

  Future<void> _setInflightRelayTask(String conversationId, String taskId,
      {required Future<void> Function() requireScope}) async {
    final id = conversationId.trim();
    if (id.isEmpty) return;
    final scope = await _offlineScope();
    final store = await openOfflineStore(expectedScope: scope);
    await requireScope();
    if (scope != await _offlineScope()) return;
    await store?.setInflightTaskId(id, taskId);
  }

  Future<bool> _clearInflightIfRelayChanged(
    String conversationId,
    String taskId, {
    required Future<void> Function() requireScope,
  }) async {
    final currentRelayId = await _relayIdForSuperEmployeeDispatch();
    await requireScope();
    if (currentRelayId.isEmpty) {
      await _setInflightRelayTask(conversationId, '',
          requireScope: requireScope);
      return true;
    }
    final status = await _client.relayTaskStatus(taskId);
    await requireScope();
    final taskMap = _objectMap(status.data?['task']);
    final current =
        taskMap.isNotEmpty ? taskMap : status.data ?? const <String, Object?>{};
    final taskRelayId = _stringField(current, 'relay_id');
    if (taskRelayId.isEmpty || taskRelayId == currentRelayId) return false;
    await _setInflightRelayTask(conversationId, '', requireScope: requireScope);
    return true;
  }

  Future<List<ChatMessage>> _loadCachedChat(String conversationId) async {
    final id = conversationId.trim();
    if (id.isEmpty) return const [];
    final scope = await _offlineScope();
    final store = await openOfflineStore(expectedScope: scope);
    if (store == null) return const [];
    final rows = await store.cachedMessages(id);
    if (scope != await _offlineScope()) return const [];
    // Legacy JSON/SQLite has no reliable backend owner: retain it on disk,
    // but never import it into a newly authenticated account's scoped cache.
    final messages = rows.map(_chatMessageFromCache).whereType<ChatMessage>().toList();
    final answeredTurns = messages.where((message) => message.role == ChatRole.assistant)
        .map((message) => message.turnId).toSet();
    return messages.expand((message) => [message,
      if (message.role == ChatRole.user && message.turnId.isNotEmpty && !answeredTurns.contains(message.turnId))
        ChatMessage(id: 'turn-${message.turnId}-assistant', conversationId: id,
            role: ChatRole.assistant, body: '原任务回执待核对，请读取原任务状态，勿重复提交。',
            timeText: message.timeText, turnId: message.turnId, status: ChatDeliveryStatus.pending)
    ]).toList();
  }

  Future<void> _requireChatScope(int generation, String base) async {
    final currentBase = await _client.resolveSessionBaseUrl();
    if (generation != _client.authGeneration || base != currentBase) {
      throw const MobileRepositoryException('账号或服务端已切换，请重新发送');
    }
  }

  Future<void> _cacheChatMessage(
    String conversationId, {
    required ChatRole role,
    required String body,
    String turnId = '',
    ChatDeliveryStatus status = ChatDeliveryStatus.sent,
    int? expectedAuthGeneration,
    String? expectedBaseUrl,
  }) async {
    final generation = expectedAuthGeneration ?? _client.authGeneration;
    if (expectedBaseUrl != null) {
      await _requireChatScope(generation, expectedBaseUrl);
    }
    final id = conversationId.trim();
    final text = body.trim();
    if (id.isEmpty || text.isEmpty) return;
    final now = DateTime.now();
    final timestampMs = now.millisecondsSinceEpoch;
    // 微秒 + 角色保证同一毫秒内写入的用户/助手消息不会互相覆盖。
    final messageId = turnId.isEmpty ? 'cache-${now.microsecondsSinceEpoch}-${role.name}' : 'turn-$turnId-${role.name}';
    final preview = _conversationPreviewForRole(role, text);
    final store = await openOfflineStore();
    if (expectedBaseUrl != null) {
      await _requireChatScope(generation, expectedBaseUrl);
    }
    if (generation != _client.authGeneration) return;
    if (store != null) {
      await store.appendMessage(id, {
        'id': messageId,
        'conversation_id': id,
        'role': role.name,
        'body': text,
        'time_text': now.toIso8601String(),
        'ts': timestampMs,
        'has_employee_profile': role == ChatRole.assistant,
        'status': status.name,
        'turn_id': turnId,
      });
      await store.saveConversationState(
        id,
        preview: preview,
        timestampMs: timestampMs,
      );
      return;
    }
  }
}
