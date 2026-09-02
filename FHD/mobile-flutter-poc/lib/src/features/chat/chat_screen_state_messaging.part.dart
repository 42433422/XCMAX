part of 'chat_screen.dart';

// 消息发送、流式回复与远端消息同步链路。
abstract class _ChatStateMessaging extends _ChatStateHelpers {
  Future<void> _loadRemoteMessages() async {
    final repository = _repository;
    if (repository == null) return;

    setState(() => _loadingRemoteMessages = true);
    try {
      final remoteMessages = await repository.loadInitialMessages(
        widget.conversation,
      );
      if (!mounted) return;
      if (remoteMessages.isNotEmpty) {
        setState(() => _messages = remoteMessages);
      }
    } catch (_) {
      // Keep the mobile empty state when auth/network is unavailable.
    } finally {
      if (mounted) setState(() => _loadingRemoteMessages = false);
    }
    await _resumeInflightRelayIfNeeded();
  }

  Future<void> _resumeInflightRelayIfNeeded() async {
    if (_resumeInflightStarted) return;
    if (widget.conversation.type.superTool == null) return;
    final repository = _repository;
    if (repository == null) return;
    _resumeInflightStarted = true;

    final hasInflight = await repository.hasInflightRelay(
      widget.conversation.id,
    );
    if (!mounted || !hasInflight) return;

    final assistantId =
        'assistant-resume-${DateTime.now().microsecondsSinceEpoch}';
    setState(() {
      _sending = true;
      _showToolPanel = false;
      _activeAssistantId = assistantId;
      _stopRequested = false;
      _messages.add(
        ChatMessage(
          id: assistantId,
          conversationId: widget.conversation.id,
          role: ChatRole.assistant,
          body: '',
          timeText: '刚刚',
          hasEmployeeProfile: true,
          status: ChatDeliveryStatus.sending,
        ),
      );
    });

    try {
      final reply = await repository.resumeRelayTask(
        conversationId: widget.conversation.id,
        onToken: (token) {
          if (!mounted) return;
          if (_stopRequested || _activeAssistantId != assistantId) return;
          setState(() => _appendMessageBody(assistantId, token));
        },
        onStatus: (progress) {
          if (!mounted) return;
          if (_stopRequested || _activeAssistantId != assistantId) return;
          setState(() => _activeRelayProgress = progress);
        },
        isCancelled: () => _stopRequested || _activeAssistantId != assistantId,
      );
      if (!mounted) return;
      if (_stopRequested || _activeAssistantId != assistantId) return;
      if (reply == null) {
        setState(() => _removeMessage(assistantId));
      } else {
        setState(() {
          _replaceMessage(
            assistantId,
            body: reply,
            status: ChatDeliveryStatus.sent,
          );
          _activeRelayProgress = null;
        });
      }
    } catch (error) {
      if (!mounted) return;
      if (_stopRequested || _activeAssistantId != assistantId) return;
      setState(() {
        _replaceMessage(
          assistantId,
          body: '（$error）',
          status: ChatDeliveryStatus.failed,
        );
        _activeRelayProgress = null;
      });
    } finally {
      if (mounted && _activeAssistantId == assistantId) {
        setState(() {
          _sending = false;
          _activeAssistantId = null;
          _activeRelayProgress = null;
          _cancellingRelay = false;
        });
      }
    }
  }

  Future<void> _loadUserAvatar() async {
    final repository = _repository;
    if (repository == null) return;

    try {
      final me = await repository.loadMe();
      if (!mounted) return;
      setState(() {
        _userAvatarSource = me.avatarSource;
        _userId = me.user?.id ?? 0;
      });
    } catch (_) {
      if (!mounted) return;
      final fallback = MobileMeData.adminFallback();
      setState(() {
        _userAvatarSource = fallback.avatarSource;
        _userId = fallback.user?.id ?? 0;
      });
    }
  }

  Future<void> _loadEmployeeProfile() async {
    final ref = _employeeRef;
    final repository = _repository;
    if (ref == null || repository == null) return;

    try {
      final employees = await repository.loadAiEmployees();
      if (!mounted) return;
      setState(() {
        _employeeProfile = _findEmployeeProfile(employees, ref);
      });
    } catch (_) {
      // Keep the Flutter chat surface usable while modInfos refresh fails.
    }
  }

  Future<void> _send([String? overrideText]) async {
    final text = (overrideText ?? _controller.text).trim();
    if (text.isEmpty || _sending) return;
    final quoted = _replyTo;
    _replyTo = null;
    final now = DateTime.now().microsecondsSinceEpoch;
    final assistantId = 'assistant-$now';
    final outgoing =
        quoted == null ? text : '引用「${_take(quoted.body, 200)}」\n\n$text';
    late List<ChatMessage> recentMessages;
    setState(() {
      _sending = true;
      _showToolPanel = false;
      _activeAssistantId = assistantId;
      _stopRequested = false;
      final userMessage = ChatMessage(
        id: 'local-$now',
        conversationId: widget.conversation.id,
        role: ChatRole.user,
        body: text,
        timeText: '刚刚',
        quote: quoted == null ? null : _take(quoted.body, 120),
      );
      final assistantMessage = ChatMessage(
        id: assistantId,
        conversationId: widget.conversation.id,
        role: ChatRole.assistant,
        body: '',
        timeText: '刚刚',
        hasEmployeeProfile: _employeeProfile != null,
        status: ChatDeliveryStatus.sending,
      );
      recentMessages = [..._messages, userMessage];
      _messages.addAll([
        userMessage,
        ChatMessage(
          id: assistantMessage.id,
          conversationId: assistantMessage.conversationId,
          role: assistantMessage.role,
          body: assistantMessage.body,
          timeText: '刚刚',
          senderName: assistantMessage.senderName,
          senderAvatarUrl: assistantMessage.senderAvatarUrl,
          hasEmployeeProfile: assistantMessage.hasEmployeeProfile,
          status: assistantMessage.status,
        ),
      ]);
    });
    _controller.clear();

    await _streamAssistantReply(
      assistantId: assistantId,
      outgoing: outgoing,
      recentMessages: recentMessages,
    );
  }

  Future<void> _streamAssistantReply({
    required String assistantId,
    required String outgoing,
    required List<ChatMessage> recentMessages,
  }) async {
    final repository = _repository;
    if (repository == null) {
      setState(() {
        _replaceMessage(
          assistantId,
          body: '当前离线同步不可用，请连接电脑或稍后重试。',
          status: ChatDeliveryStatus.failed,
        );
        _sending = false;
        _activeAssistantId = null;
      });
      return;
    }

    try {
      final reply = await repository.streamMessage(
        conversation: widget.conversation,
        body: outgoing,
        userId: _userId,
        recentMessages: recentMessages,
        onToken: (token) {
          if (!mounted) return;
          if (_stopRequested || _activeAssistantId != assistantId) return;
          setState(() => _appendMessageBody(assistantId, token));
        },
        onStatus: (progress) {
          if (!mounted) return;
          if (_stopRequested || _activeAssistantId != assistantId) return;
          setState(() => _activeRelayProgress = progress);
        },
        isCancelled: () => _stopRequested || _activeAssistantId != assistantId,
      );
      if (!mounted) return;
      if (_stopRequested || _activeAssistantId != assistantId) return;
      setState(() {
        _replaceMessage(
          assistantId,
          body: reply,
          status: ChatDeliveryStatus.sent,
        );
        _activeRelayProgress = null;
      });
    } catch (error) {
      if (!mounted) return;
      if (_stopRequested || _activeAssistantId != assistantId) return;
      setState(() {
        _replaceMessage(
          assistantId,
          body: mobileProductErrorMessage(
            error.toString(),
            '当前离线同步不可用，请连接电脑或稍后重试。',
          ),
          status: ChatDeliveryStatus.failed,
        );
        _activeRelayProgress = null;
      });
    } finally {
      if (mounted && _activeAssistantId == assistantId) {
        setState(() {
          _sending = false;
          _activeAssistantId = null;
          _activeRelayProgress = null;
          _cancellingRelay = false;
        });
      }
    }
  }

  void _clearChat() {
    setState(() {
      _messages.clear();
      _showToolPanel = false;
      _replyTo = null;
    });
    _controller.clear();
  }

  void _stopChat() {
    final assistantId = _activeAssistantId;
    if (assistantId == null) return;
    final progress = _activeRelayProgress;
    setState(() {
      _stopRequested = true;
      _replaceMessage(
        assistantId,
        body: _messages
            .firstWhere(
              (message) => message.id == assistantId,
              orElse: () => ChatMessage(
                id: assistantId,
                conversationId: widget.conversation.id,
                role: ChatRole.assistant,
                body: '',
                timeText: '刚刚',
              ),
            )
            .body,
        status: ChatDeliveryStatus.sent,
      );
      _sending = false;
      _activeAssistantId = null;
      _activeRelayProgress = null;
    });
    if (progress != null && progress.taskId.isNotEmpty) {
      _cancelRelayTask(progress.taskId);
    }
  }

  Future<void> _cancelRelayTask(String taskId) async {
    final repository = _repository;
    if (repository == null || taskId.isEmpty) return;
    setState(() => _cancellingRelay = true);
    try {
      await repository.cancelRelayTask(taskId);
    } catch (_) {
      // 静默失败：本地已经停止展示，远端任务稍后自然完成或超时
    } finally {
      if (mounted) setState(() => _cancellingRelay = false);
    }
  }

  Future<void> _resendLastChat() async {
    if (_sending) return;
    ChatMessage? lastUser;
    for (final message in _messages.reversed) {
      if (message.role == ChatRole.user) {
        lastUser = message;
        break;
      }
    }
    if (lastUser == null) return;

    final now = DateTime.now().microsecondsSinceEpoch;
    final assistantId = 'assistant-resend-$now';
    late List<ChatMessage> recentMessages;
    setState(() {
      final trimmed = [..._messages];
      if (trimmed.isNotEmpty && trimmed.last.role == ChatRole.assistant) {
        trimmed.removeLast();
      }
      final assistantMessage = ChatMessage(
        id: assistantId,
        conversationId: widget.conversation.id,
        role: ChatRole.assistant,
        body: '',
        timeText: '刚刚',
        hasEmployeeProfile: true,
        status: ChatDeliveryStatus.sending,
      );
      recentMessages = trimmed;
      _messages = [...trimmed, assistantMessage];
      _sending = true;
      _showToolPanel = false;
      _activeAssistantId = assistantId;
      _stopRequested = false;
    });

    final quote = lastUser.quote?.trim() ?? '';
    final outgoing = quote.isEmpty
        ? lastUser.body
        : '引用「${_take(quote, 200)}」\n\n${lastUser.body}';
    await _streamAssistantReply(
      assistantId: assistantId,
      outgoing: outgoing,
      recentMessages: recentMessages,
    );
  }

  void _deleteMessageAt(int index) {
    if (index < 0 || index >= _messages.length) return;
    late final ChatMessage removed;
    setState(() {
      removed = _messages[index];
      _messages = [..._messages]..removeAt(index);
      if (_replyTo?.id == removed.id) _replyTo = null;
    });
    _repository
        ?.deleteCachedChatMessage(
          conversationId: widget.conversation.id,
          message: removed,
        )
        .catchError((_) {});
  }
}
