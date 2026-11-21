part of 'mobile_repository.dart';

abstract class _RepoRelayBase extends _RepoHelpersBase {
  _RepoRelayBase({
    super.client,
    super.imWebSocket,
  });

  Future<String> runGitOperation({
    required String branch,
    required String op,
  }) async {
    final cleanBranch = branch.trim();
    final cleanOp = op.trim();
    if (cleanBranch.isEmpty) {
      throw const MobileRepositoryException('缺少分支名');
    }
    if (!const {
      'git.merge',
      'git.diff',
      'git.discard',
      'git.diff.structured',
      'git.log',
      'git.cancel',
    }.contains(cleanOp)) {
      throw MobileRepositoryException('未知 git 操作：$cleanOp');
    }

    final relayId = await _relayIdForSuperEmployeeDispatch();
    if (relayId.isEmpty) {
      throw MobileRepositoryException('未绑定电脑工具，无法执行 $cleanOp');
    }

    final created = await _client.relayCreateTask(
      relayId: relayId,
      kind: cleanOp,
      payload: {
        'branch': cleanBranch,
        'context': _superEmployeeRelayContext(),
      },
    );
    if (!created.success) {
      throw MobileRepositoryException(created.message.ifEmpty('操作创建失败'));
    }
    final task = _objectMap(created.data?['task']);
    final taskId = _stringField(task, 'task_id');
    if (taskId.isEmpty) {
      throw const MobileRepositoryException('操作缺少 task_id');
    }

    var lastStatus = '';
    for (var attempt = 0; attempt < 150; attempt += 1) {
      await Future<void>.delayed(const Duration(seconds: 2));
      final status = await _client.relayTaskStatus(taskId);
      final taskMap = _objectMap(status.data?['task']);
      final current = taskMap.isNotEmpty
          ? taskMap
          : status.data ?? const <String, Object?>{};
      final currentStatus = _stringField(current, 'status');
      lastStatus = currentStatus.ifEmpty(lastStatus);
      if (currentStatus == 'done' || currentStatus == 'completed') {
        return _relayTaskResultText(current).ifEmpty('电脑工具已完成任务。');
      }
      if (const {'failed', 'blocked', 'cancelled'}.contains(currentStatus)) {
        throw MobileRepositoryException(
          _relayTaskResultText(current).ifEmpty('电脑工具执行失败'),
        );
      }
    }
    throw MobileRepositoryException(
      lastStatus.isEmpty
          ? '电脑工具暂未回写结果，任务仍在后台运行，可稍后回到此会话查看。'
          : '电脑工具仍处于 $lastStatus，任务仍在后台运行，可稍后回到此会话查看。',
    );
  }

  /// 结构化 diff：返回 {files, base, branch, total_additions, total_deletions}。
  Future<Map<String, Object?>> runGitDiffStructured({
    required String branch,
  }) async {
    final relayId = await _relayIdForSuperEmployeeDispatch();
    if (relayId.isEmpty) {
      throw const MobileRepositoryException('未绑定电脑工具，无法查看改动');
    }
    final created = await _client.relayCreateTask(
      relayId: relayId,
      kind: 'git.diff.structured',
      payload: {
        'branch': branch.trim(),
        'context': _superEmployeeRelayContext(),
      },
    );
    if (!created.success) {
      throw MobileRepositoryException(created.message.ifEmpty('操作创建失败'));
    }
    final task = _objectMap(created.data?['task']);
    final taskId = _stringField(task, 'task_id');
    if (taskId.isEmpty) {
      throw const MobileRepositoryException('操作缺少 task_id');
    }
    for (var attempt = 0; attempt < 150; attempt += 1) {
      await Future<void>.delayed(const Duration(seconds: 2));
      final status = await _client.relayTaskStatus(taskId);
      final taskMap = _objectMap(status.data?['task']);
      final current = taskMap.isNotEmpty
          ? taskMap
          : status.data ?? const <String, Object?>{};
      final currentStatus = _stringField(current, 'status');
      if (currentStatus == 'done' || currentStatus == 'completed') {
        final result = _objectMap(current['result']);
        final structured = _objectMap(result['structured']);
        if (structured.isNotEmpty) return structured;
        return {
          'files': <Map<String, Object?>>[],
          'base': '',
          'branch': branch.trim(),
        };
      }
      if (const {'failed', 'blocked', 'cancelled'}.contains(currentStatus)) {
        throw MobileRepositoryException(
          _relayTaskResultText(current).ifEmpty('查看改动失败'),
        );
      }
    }
    throw const MobileRepositoryException('查看改动超时，请稍后重试');
  }

  /// 分支 commit 列表：返回 {commits, base, branch}。
  Future<Map<String, Object?>> runGitLog({
    required String branch,
    int limit = 10,
  }) async {
    final relayId = await _relayIdForSuperEmployeeDispatch();
    if (relayId.isEmpty) {
      throw const MobileRepositoryException('未绑定电脑工具，无法查看提交');
    }
    final created = await _client.relayCreateTask(
      relayId: relayId,
      kind: 'git.log',
      payload: {
        'branch': branch.trim(),
        'limit': limit,
        'context': _superEmployeeRelayContext(),
      },
    );
    if (!created.success) {
      throw MobileRepositoryException(created.message.ifEmpty('操作创建失败'));
    }
    final task = _objectMap(created.data?['task']);
    final taskId = _stringField(task, 'task_id');
    if (taskId.isEmpty) {
      throw const MobileRepositoryException('操作缺少 task_id');
    }
    for (var attempt = 0; attempt < 150; attempt += 1) {
      await Future<void>.delayed(const Duration(seconds: 2));
      final status = await _client.relayTaskStatus(taskId);
      final taskMap = _objectMap(status.data?['task']);
      final current = taskMap.isNotEmpty
          ? taskMap
          : status.data ?? const <String, Object?>{};
      final currentStatus = _stringField(current, 'status');
      if (currentStatus == 'done' || currentStatus == 'completed') {
        final result = _objectMap(current['result']);
        final commits = result['commits'];
        return {
          'commits': commits is List ? commits : <Map<String, Object?>>[],
          'base': _stringField(result, 'base'),
          'branch': _stringField(result, 'branch').ifEmpty(branch.trim()),
        };
      }
      if (const {'failed', 'blocked', 'cancelled'}.contains(currentStatus)) {
        throw MobileRepositoryException(
          _relayTaskResultText(current).ifEmpty('查看提交失败'),
        );
      }
    }
    throw const MobileRepositoryException('查看提交超时，请稍后重试');
  }

  /// 取消正在执行的 relay 任务。
  Future<bool> cancelRelayTask(String taskId) async {
    if (taskId.trim().isEmpty) return false;
    final response = await _client.relayCancelTask(taskId.trim());
    if (!response.success) return false;
    final task = _objectMap(response.data?['task']);
    return _stringField(task, 'status') == 'cancelled';
  }

  /// 从 relay task result 读取工具调用记录（dev-loop 时间线）。
  Future<List<Map<String, Object?>>> loadToolCalls(String taskId) async {
    if (taskId.trim().isEmpty) return const <Map<String, Object?>>[];
    final status = await _client.relayTaskStatus(taskId.trim());
    final taskMap = _objectMap(status.data?['task']);
    if (taskMap.isEmpty) return const <Map<String, Object?>>[];
    final result = _objectMap(taskMap['result']);
    final codex = _objectMap(result['codex']);
    final raw = codex['tool_calls'] ?? result['tool_calls'];
    if (raw is! List) return const <Map<String, Object?>>[];
    return raw
        .whereType<Map<String, Object?>>()
        .map((e) => Map<String, Object?>.from(e))
        .toList(growable: false);
  }

  /// 从 assistant 消息正文解析 dev-loop 工具调用记录。
  /// 与后端 `_extract_tool_calls` 的正则保持一致，避免无 task_id 时无法回顾。
  List<Map<String, Object?>> parseToolCallsFromBody(
    String body, {
    String toolLabel = '超级员工',
  }) {
    final text = body.trim();
    if (text.isEmpty || !text.contains('闭环结果')) {
      return const <Map<String, Object?>>[];
    }
    final calls = <Map<String, Object?>>[];
    final branchMatch = RegExp(r'分支[：:]\s*(\S+)').firstMatch(text);
    if (branchMatch != null) {
      final branch = branchMatch.group(1) ?? '';
      calls.add({
        'action': 'create_branch',
        'icon': 'branch',
        'label': '创建分支 $branch',
        'detail': branch,
      });
    }
    final verifyMatch = RegExp(
      r'验证[：:]\s*(通过|未通过)[（(]([^)）]*)',
    ).firstMatch(text);
    if (verifyMatch != null) {
      final ok = verifyMatch.group(1) == '通过';
      final detail = verifyMatch.group(2) ?? '';
      calls.add({
        'action': 'verify',
        'icon': 'check',
        'label': '验证${ok ? '通过' : '未通过'}',
        'detail': detail.length > 200 ? detail.substring(0, 200) : detail,
        'success': ok,
      });
    }
    final pushMatch = RegExp(r'推送[：:]\s*(.+?)(?:\n|$)').firstMatch(text);
    if (pushMatch != null) {
      final raw = (pushMatch.group(1) ?? '').trim();
      final pushText = raw.length > 200 ? raw.substring(0, 200) : raw;
      calls.add({
        'action': 'push',
        'icon': 'upload',
        'label': '推送分支',
        'detail': pushText,
        'success': pushText.contains('成功') || pushText.contains('已推送'),
      });
    }
    if (calls.isNotEmpty) {
      calls.insert(0, {
        'action': 'cli_run',
        'icon': 'terminal',
        'label': '$toolLabel CLI 执行',
        'detail': '调用无头 agent 修改代码',
      });
    }
    return calls;
  }

  Future<String> _postSuperEmployeeMessage(
    String tool,
    String text, {
    String baseUrl = '',
  }) async {
    late final MobileEnvelope<Map<String, Object?>> response;
    try {
      response = await _client.postSuperEmployeeMessage(tool, text, baseUrl: baseUrl);
    } catch (error) {
      if (error is MobileApiException && error.statusCode >= 400 && error.statusCode < 500) rethrow;
      throw const MobileApiException(statusCode: 409, errorCode: 'CHAT_RECEIPT_PENDING',
          message: '原任务结果待核对，请在任务工作区读取原回执，勿重复提交。',
          body: {'execution_state': 'unknown', 'requires_reconciliation': true});
    }
    chatReceiptText({...response.raw, ...?response.data}, '', '');
    if (!response.success) {
      throw MobileRepositoryException(response.message.ifEmpty('超级员工回复失败'));
    }
    return _assistantReplyFromMap(
      response.data ?? response.raw,
    ).ifEmpty('已收到，我会继续处理。');
  }

  Future<String> _superEmployeeLanBaseUrl() async {
    final session = await _client.loadSession();
    if (session.serverMode.trim().toLowerCase() != 'lan') {
      return '';
    }
    final localBase = session.localBaseUrl.trim();
    if (localBase.isNotEmpty) return _ensureTrailingSlash(localBase);
    final host = session.fhdHost.trim();
    if (host.isEmpty) return '';
    // 后端 loopback 监听 17500 时手机不可达，需改用 vite proxy 端口 5011。
    return MobileServerRouter(
      fhdHost: host,
      mode: MobileServerMode.lan,
    ).lanReachableBaseUrl();
  }

  Future<String> _streamRelaySuperEmployeeTask({
    required String relayId,
    required String relayKind,
    required String conversationId,
    required String message,
    required Future<void> Function() requireScope,
    void Function(String token)? onToken,
    void Function(RelayTaskProgress progress)? onStatus,
    bool Function()? isCancelled,
  }) async {
    await requireScope();
    late final MobileEnvelope<Map<String, Object?>> created;
    try {
      created = await _client.relayCreateTask(relayId: relayId, kind: relayKind,
        payload: {'message': message,
          'context': _superEmployeeRelayContext(conversationId: conversationId)});
    } catch (error) {
      if (error is MobileApiException && error.statusCode >= 400 && error.statusCode < 500) rethrow;
      throw const MobileApiException(statusCode: 409, errorCode: 'CHAT_RECEIPT_PENDING',
          message: '原中继任务是否受理尚待核对，请在任务工作区查看，勿重复提交。',
          body: {'execution_state': 'unknown', 'requires_reconciliation': true});
    }
    await requireScope();
    if (!created.success) {
      throw MobileApiException(statusCode: 409, errorCode: 'CHAT_RECEIPT_PENDING',
          message: created.message.ifEmpty('原中继任务受理回执未确认，请核对后再操作。'),
          body: {'execution_state': 'unknown', 'requires_reconciliation': true});
    }
    final task = _objectMap(created.data?['task']);
    final taskId = _stringField(task, 'task_id');
    if (taskId.isEmpty) {
      throw const MobileApiException(statusCode: 409, errorCode: 'CHAT_RECEIPT_PENDING',
          message: '中继受理回执缺少原任务标识，请核对原任务，勿重复提交。',
          body: {'execution_state': 'unknown', 'requires_reconciliation': true});
    }
    await _setInflightRelayTask(conversationId, taskId,
        requireScope: requireScope);
    await requireScope();
    final toolLabel = toolLabelForRelayKind(relayKind);
    onStatus?.call(
      RelayTaskProgress(taskId: taskId, status: 'queued', toolLabel: toolLabel),
    );
    onToken?.call('思考中...');
    return _pollRelayTask(
      taskId: taskId,
      toolLabel: toolLabel,
      conversationId: conversationId,
      onToken: onToken,
      onStatus: onStatus,
      isCancelled: isCancelled,
      requireScope: requireScope,
    );
  }

  Future<String> _pollRelayTask({
    required String taskId,
    required String toolLabel,
    required String conversationId,
    required Future<void> Function() requireScope,
    void Function(String token)? onToken,
    void Function(RelayTaskProgress progress)? onStatus,
    bool Function()? isCancelled,
  }) async {
    var lastStatus = '';
    for (var attempt = 0; attempt < 150; attempt += 1) {
      _throwIfCancelled(isCancelled);
      await Future<void>.delayed(const Duration(seconds: 2));
      await requireScope();
      _throwIfCancelled(isCancelled);
      late final MobileEnvelope<Map<String, Object?>> status;
      try {
        status = await _relayTaskStatusWithBackoff(
          taskId,
          isCancelled: isCancelled,
          requireScope: requireScope,
        );
      } catch (error) {
        if (error is MobileApiException && [401, 403].contains(error.statusCode)) rethrow;
        throw MobileApiException(statusCode: 409, errorCode: 'CHAT_RECEIPT_PENDING',
            message: '原中继任务回执暂不可读，请核对原任务，勿重复提交。',
            body: {'task_id': taskId, 'execution_state': 'unknown', 'requires_reconciliation': true});
      }
      await requireScope();
      final taskMap = _objectMap(status.data?['task']);
      final current = taskMap.isNotEmpty
          ? taskMap
          : status.data ?? const <String, Object?>{};
      final currentStatus = _stringField(current, 'status');
      if (!status.success || (_stringField(current, 'task_id').isNotEmpty && _stringField(current, 'task_id') != taskId)) {
        throw MobileApiException(statusCode: 409, errorCode: 'CHAT_RECEIPT_PENDING',
            message: '原中继任务回执未确认，请核对原任务，勿重复提交。',
            body: {'task_id': taskId, 'execution_state': 'unknown', 'requires_reconciliation': true});
      }
      _throwIfCancelled(isCancelled);
      if (currentStatus.isNotEmpty && currentStatus != lastStatus) {
        onStatus?.call(
          RelayTaskProgress(
            taskId: taskId,
            status: currentStatus,
            toolLabel: toolLabel,
          ),
        );
        switch (currentStatus) {
          case 'running':
          case 'assigned':
            onToken?.call('\n电脑工具正在运行 $toolLabel。');
            break;
          case 'queued':
            onToken?.call('\n任务仍在服务器队列中。');
            break;
        }
        lastStatus = currentStatus;
      }
      if (currentStatus == 'done' || currentStatus == 'completed') {
        final result = _objectMap(current['result']);
        final reply = chatReceiptText({...result, 'execution_state': result['execution_state'] ?? result['agent_status'] ?? result['run_status'] ?? result['status'] ?? 'completed'}, taskId,
            _relayTaskResultText(current).ifEmpty('电脑工具已完成任务。'));
        await _setInflightRelayTask(conversationId, '',
            requireScope: requireScope);
        await requireScope();
        onStatus?.call(
          RelayTaskProgress(
            taskId: taskId,
            status: 'completed',
            toolLabel: toolLabel,
          ),
        );
        return reply;
      }
      if (const {'failed', 'cancelled', 'rejected'}.contains(currentStatus)) {
        await _setInflightRelayTask(conversationId, '',
            requireScope: requireScope);
        await requireScope();
        onStatus?.call(
          RelayTaskProgress(
            taskId: taskId,
            status: currentStatus,
            toolLabel: toolLabel,
          ),
        );
        throw MobileApiException(statusCode: 409, errorCode: 'CHAT_RECEIPT_TERMINAL',
            message: _relayTaskResultText(current).ifEmpty(currentStatus == 'cancelled' ? '原任务已取消' : '电脑工具执行失败'),
            body: {'task_id': taskId, 'execution_state': currentStatus});
      }
      if (!const {'queued', 'pending', 'running', 'assigned', 'planning', 'retrying'}.contains(currentStatus)) {
        throw MobileApiException(statusCode: 409, errorCode: 'CHAT_RECEIPT_PENDING',
            message: _relayTaskResultText(current).ifEmpty('原任务尚未完成，请在任务工作区查看进度或确认请求。'),
            body: {'task_id': taskId, 'execution_state': currentStatus.isEmpty ? 'unknown' : currentStatus});
      }
    }
    throw MobileApiException(statusCode: 409, errorCode: 'CHAT_RECEIPT_PENDING',
        message: '电脑工具暂未回写结果，请稍后读取原任务状态，勿重复提交。',
        body: {'task_id': taskId, 'execution_state': lastStatus.isEmpty ? 'unknown' : lastStatus});
  }

  /// 429 是服务端正常限流：按 Retry-After 等待后重试同一任务，不当作失败。
  Future<MobileEnvelope<Map<String, Object?>>> _relayTaskStatusWithBackoff(
    String taskId, {
    required Future<void> Function() requireScope,
    bool Function()? isCancelled,
  }) async {
    while (true) {
      _throwIfCancelled(isCancelled);
      await requireScope();
      try {
        return await _client.relayTaskStatus(taskId);
      } on MobileApiException catch (error) {
        if (error.statusCode != 429) rethrow;
        await Future<void>.delayed(
          Duration(seconds: error.retryAfterSeconds ?? 5),
        );
      }
    }
  }
}
