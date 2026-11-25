part of 'chat_screen.dart';

// 消息发送、流式回复与远端消息同步链路。
abstract class _ChatStateMessaging extends _ChatStateHelpers {
  Future<void> _loadRemoteMessages() async {
    final repository = _repository;
    if (repository == null || _chatInvalidated) return;
    final epoch = _chatEpoch;
    final generation = _chatGeneration;

    try {
      final remoteMessages = await repository.loadInitialMessages(
        widget.conversation,
      );
      if (!mounted || _chatInvalidated || epoch != _chatEpoch ||
          generation != repository.client.authGeneration) return;
      if (remoteMessages.isNotEmpty && !_sending) {
        setState(() => _messages = remoteMessages);
        _syncFlyerChat();
      }
    } catch (error) {
      if (error is MobileApiException &&
          (error.statusCode == 401 || error.statusCode == 403)) {
        _revokeChatView();
        return;
      }
      // Keep a scoped, read-only cached view on transport failure.
    }
    if (!_chatInvalidated && _chatForeground) {
      await _resumeInflightRelayIfNeeded();
      await _resumePendingChatTurnsIfNeeded();
    }
  }

  void _revokeChatView() {
    if (!mounted || _chatInvalidated) return;
    _streamTokenBatcher.clear();
    _chatInvalidated = true;
    _chatEpoch++;
    _draftTimer?.cancel();
    setState(() {
      _messages.clear();
      _attachments.clear();
      _failedAttachments.clear();
      _recoveredAttachmentNames.clear();
      _sending = false;
      _activeAssistantId = null;
      _controller.clear();
    });
    _syncFlyerChat();
  }

  /// Read only the original turn receipt; never replay an uncertain POST.
  Future<void> _resumePendingChatTurnsIfNeeded() async {
    if (_resumingPendingChat || _sending || _chatInvalidated ||
        !_chatForeground) return;
    _resumingPendingChat = true;
    try {
      final pending = _messages.where((message) =>
          message.role == ChatRole.assistant &&
          message.turnId.isNotEmpty &&
          const [
            ChatDeliveryStatus.pending,
            ChatDeliveryStatus.sending,
            ChatDeliveryStatus.queued,
          ].contains(message.status)).toList(growable: false);
      for (final message in pending) {
        if (!mounted || _chatInvalidated || !_chatForeground || _sending) break;
        await _readOriginalChatTurn(message);
      }
    } finally {
      _resumingPendingChat = false;
    }
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
    _syncFlyerChat();

    try {
      final reply = await repository.resumeRelayTask(
        conversationId: widget.conversation.id,
        onToken: (token) {
          if (!mounted) return;
          if (_stopRequested || _activeAssistantId != assistantId) return;
          _queueStreamToken(assistantId, token);
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
          body: '（${mobileErrorText(error)}）',
          status: ChatDeliveryStatus.failed,
        );
        _activeRelayProgress = null;
      });
    } finally {
      _streamTokenBatcher.clearFor(assistantId);
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
    if (_chatInvalidated || !_chatForeground ||
        _repository?.client.authGeneration != _chatGeneration) return;
    if (_recoveredAttachmentNames.isNotEmpty) {
      _showMessage('请重新选择或移除上次的附件后再发送');
      return;
    }
    if (text.isEmpty ||
        _sending ||
        _uploading ||
        _failedAttachments.isNotEmpty) {
      return;
    }
    _lastSentAttachments = List.of(_attachments);
    final quoted = _replyTo;
    _replyTo = null;
    final now = DateTime.now().microsecondsSinceEpoch;
    final assistantId = 'assistant-$now';
    final outgoing =
        quoted == null ? text : '引用「${_take(quoted.body, 200)}」\n\n$text';
    final turnId = 'mobile-$now-${Random.secure().nextInt(1 << 32).toRadixString(16)}';
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
        turnId: turnId,
      );
      final assistantMessage = ChatMessage(
        id: assistantId,
        conversationId: widget.conversation.id,
        role: ChatRole.assistant,
        body: '',
        timeText: '刚刚',
        hasEmployeeProfile: _employeeProfile != null,
        status: ChatDeliveryStatus.sending,
        turnId: turnId,
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
          turnId: assistantMessage.turnId,
        ),
      ]);
    });
    _syncFlyerChat();
    _controller.clear();

    await _streamAssistantReply(
      assistantId: assistantId,
      outgoing: outgoing,
      recentMessages: recentMessages,
      attachments: _lastSentAttachments,
      idempotencyKey: turnId,
    );
  }

  Future<void> _streamAssistantReply({
    required String assistantId,
    required String outgoing,
    required List<ChatMessage> recentMessages,
    List<MobileChatAttachment> attachments = const [],
    String idempotencyKey = '',
    bool resumeOnly = false,
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
      final reply = attachments.isNotEmpty
          ? await repository.streamAttachedMessage(
              conversation: widget.conversation,
              body: outgoing,
              attachments: attachments,
              idempotencyKey: idempotencyKey,
              resumeOnly: resumeOnly,
              recentMessages: recentMessages,
              onToken: (token) {
                if (mounted &&
                    !_stopRequested &&
                    _activeAssistantId == assistantId) {
                  _queueStreamToken(assistantId, token);
                }
              })
          : await repository.streamMessage(
              conversation: widget.conversation,
              body: outgoing,
              userId: _userId,
              idempotencyKey: idempotencyKey,
              resumeOnly: resumeOnly,
              cacheUserMessage: !resumeOnly,
              recentMessages: recentMessages,
              onToken: (token) {
                if (!mounted) return;
                if (_stopRequested || _activeAssistantId != assistantId) return;
                _queueStreamToken(assistantId, token);
              },
              onStatus: (progress) {
                if (!mounted) return;
                if (_stopRequested || _activeAssistantId != assistantId) return;
                setState(() => _activeRelayProgress = progress);
              },
              isCancelled: () =>
                  _stopRequested || _activeAssistantId != assistantId,
            );
      if (!mounted) return;
      if (_stopRequested || _activeAssistantId != assistantId) return;
      await repository.removeQueuedMessage(widget.conversation.id, outgoing, idempotencyKey: idempotencyKey);
      setState(() {
        _replaceMessage(
          assistantId,
          body: reply,
          status: ChatDeliveryStatus.sent,
        );
        _activeRelayProgress = null;
        _attachments.removeWhere(attachments.contains);
      });
    } catch (error) {
      if (!mounted) return;
      if (_stopRequested || _activeAssistantId != assistantId) return;
      if (error is MobileApiException &&
          (error.statusCode == 401 || error.statusCode == 403)) {
        _revokeChatView();
        return;
      }
      final pending = error is MobileApiException && error.errorCode == 'CHAT_RECEIPT_PENDING';
      final offline = !pending && isOfflineError(error);
      final queuedId = offline && !resumeOnly && attachments.isEmpty
          ? await repository.enqueuePendingMessage(
              conversation: widget.conversation,
              body: outgoing,
              idempotencyKey: idempotencyKey,
            )
          : 0;
      if (!mounted) return;
      setState(() {
        _replaceMessage(
          assistantId,
          body: queuedId > 0
              ? '网络不可用，消息已加入待发送队列，恢复连接后会自动发送。'
              : mobileProductErrorMessage(
                  mobileErrorText(error),
                  '当前离线同步不可用，请连接电脑或稍后重试。',
                ),
          status: queuedId > 0
              ? ChatDeliveryStatus.queued
              : (pending || (resumeOnly && offline))
                  ? ChatDeliveryStatus.pending : ChatDeliveryStatus.failed,
        );
        _activeRelayProgress = null;
      });
    } finally {
      _streamTokenBatcher.clearFor(assistantId);
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
    _streamTokenBatcher.clear();
    setState(() {
      _messages.clear();
      _attachments.clear();
      _failedAttachments.clear();
      _recoveredAttachmentNames.clear();
      _lastSentAttachments = const [];
      _showToolPanel = false;
      _replyTo = null;
    });
    _syncFlyerChat();
    _controller.clear();
  }

  void _stopChat() {
    final assistantId = _activeAssistantId;
    if (assistantId == null) return;
    _streamTokenBatcher.flushFor(assistantId);
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
        status: ChatDeliveryStatus.pending,
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

  Future<void> _readOriginalChatTurn(ChatMessage message) async {
    if (_sending) return;
    if (message.turnId.isEmpty && widget.conversation.type.superTool == null) {
      setState(() => _replaceMessage(message.id,
          body: '这条历史消息缺少原任务标识，请在任务工作区核对结果，勿重复提交。',
          status: ChatDeliveryStatus.pending));
      return;
    }
    final assistantId = message.id;
    setState(() {
      _replaceMessage(assistantId, body: '正在核对原任务回执…', status: ChatDeliveryStatus.sending);
      _sending = true;
      _showToolPanel = false;
      _activeAssistantId = assistantId;
      _stopRequested = false;
    });
    await _streamAssistantReply(
      assistantId: assistantId,
      outgoing: '',
      recentMessages: const [],
      idempotencyKey: message.turnId,
      resumeOnly: true,
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
    _syncFlyerChat();
    _repository
        ?.deleteCachedChatMessage(
          conversationId: widget.conversation.id,
          message: removed,
        )
        .catchError((_) {});
  }
}
