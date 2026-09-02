part of 'mobile_repository.dart';

abstract class _RepoHelpersBase extends _RepoPairingAuthBase {
  _RepoHelpersBase({
    MobileApiClient? client,
    ImWebSocketClient? imWebSocket,
  }) : super(client: client, imWebSocket: imWebSocket);

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
        showCodex: enterpriseMode || adminMode,
        showCursor: enterpriseMode || adminMode,
        showClaude: enterpriseMode || adminMode,
        showTrae: enterpriseMode || adminMode,
        showCustomerService: enterpriseMode && !adminMode,
        states: _emptyConversationStates,
      ),
      if (adminMode) ...adminDutyRosterConversationItems(),
    ]);
  }

  Future<String> _relayIdForSuperEmployeeDispatch() async {
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
        await _client.persistRelayBindingMeta(latestRelayId, latest);
      }
      return latestRelayId;
    } on MobileRepositoryException {
      rethrow;
    } catch (_) {
      return storedRelayId;
    }
  }

  Future<String> _inflightRelayTask(String conversationId) async {
    final session = await _client.loadSession();
    return session.inflightRelayTasks[conversationId.trim()]?.trim() ?? '';
  }

  Future<void> _setInflightRelayTask(
    String conversationId,
    String taskId,
  ) async {
    final id = conversationId.trim();
    if (id.isEmpty) return;
    final session = await _client.loadSession();
    final tasks = Map<String, String>.of(session.inflightRelayTasks);
    final cleanTaskId = taskId.trim();
    if (cleanTaskId.isEmpty) {
      tasks.remove(id);
    } else {
      tasks[id] = cleanTaskId;
    }
    await _client.saveSession(session.copyWith(inflightRelayTasks: tasks));
  }

  Future<bool> _clearInflightIfRelayChanged(
    String conversationId,
    String taskId,
  ) async {
    final currentRelayId = await _relayIdForSuperEmployeeDispatch();
    if (currentRelayId.isEmpty) {
      await _setInflightRelayTask(conversationId, '');
      return true;
    }
    final status = await _client.relayTaskStatus(taskId);
    final taskMap = _objectMap(status.data?['task']);
    final current =
        taskMap.isNotEmpty ? taskMap : status.data ?? const <String, Object?>{};
    final taskRelayId = _stringField(current, 'relay_id');
    if (taskRelayId.isEmpty || taskRelayId == currentRelayId) return false;
    await _setInflightRelayTask(conversationId, '');
    return true;
  }

  Future<List<ChatMessage>> _loadCachedChat(String conversationId) async {
    final session = await _client.loadSession();
    final rows = session.cachedChatMessages[conversationId.trim()];
    if (rows == null || rows.isEmpty) return const [];
    return rows.map(_chatMessageFromCache).whereType<ChatMessage>().toList();
  }

  Future<void> _cacheChatMessage(
    String conversationId, {
    required ChatRole role,
    required String body,
  }) async {
    final id = conversationId.trim();
    final text = body.trim();
    if (id.isEmpty || text.isEmpty) return;
    final session = await _client.loadSession();
    final cache = Map<String, List<Map<String, Object?>>>.of(
      session.cachedChatMessages,
    );
    final rows = [...(cache[id] ?? const <Map<String, Object?>>[])];
    final now = DateTime.now();
    final timestampMs = now.millisecondsSinceEpoch;
    rows.add({
      'id': 'cache-$timestampMs',
      'conversation_id': id,
      'role': role.name,
      'body': text,
      'time_text': now.toIso8601String(),
      'ts': timestampMs,
      'has_employee_profile': role == ChatRole.assistant,
      'status': ChatDeliveryStatus.sent.name,
    });
    cache[id] = rows.length > 80
        ? rows.sublist(rows.length - 80).toList(growable: false)
        : rows;
    final states = Map<String, Map<String, Object?>>.of(
      session.conversationListStates,
    );
    states[id] = _ConversationListState(
      preview: _conversationPreviewForRole(role, text),
      timestampMs: timestampMs,
    ).toJson();
    await _client.saveSession(
      session.copyWith(
        cachedChatMessages: cache,
        conversationListStates: states,
      ),
    );
  }
}
