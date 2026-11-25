part of 'chat_screen.dart';

// _ChatScreenState 的最底层基类：持有全部状态字段与消息编辑/分支解析等低层方法。
abstract class _ChatStateHelpers extends State<ChatScreen> {
  String get _flyerMeId => 'me';

  late List<ChatMessage> _messages;

  /// 没有缓存时间戳的消息（本地新建/测试注入）首次渲染时固定 createdAt，
  /// 避免每次同步都换时间导致 flutter_chat_ui 的动画列表重排断言。
  final _flyerCreatedAt = <String, DateTime>{};
  late final InMemoryChatController _flyerChatController =
      InMemoryChatController();
  final _controller = TextEditingController();
  var _showToolPanel = false;
  var _sending = false;
  var _uploading = false;
  String? _attachmentScope;
  StreamSubscription<MobileSessionData>? _attachmentSessionSubscription;
  final _attachments = <MobileChatAttachment>[];
  final _failedAttachments = <XFile>[];
  // An old upload receipt is not a reusable capability after restart.
  final _recoveredAttachmentNames = <String>[];
  Timer? _draftTimer;
  bool _restoringDraft = false;
  bool _draftTouched = false;
  bool _chatInvalidated = false;
  int _chatGeneration = 0;
  List<MobileChatAttachment> _lastSentAttachments = const [];
  var _runningGitOp = false;
  String? _selectedGitBranch;
  ChatMessage? _replyTo;
  String? _activeAssistantId;
  var _stopRequested = false;
  var _resumeInflightStarted = false;
  String _userAvatarSource = '';
  int _userId = 0;
  MobileRepository? _repository;
  late final _EmployeeConversationRef? _employeeRef;
  AiEmployeeProfile? _employeeProfile;
  RelayTaskProgress? _activeRelayProgress;
  bool _cancellingRelay = false;

  Future<void> _restoreChatDraft() async {
    final repository = _repository;
    if (repository == null) return;
    final generation = _chatGeneration;
    try {
      final draft = await repository.loadChatComposerDraft(widget.conversation.id);
      if (!mounted || _chatInvalidated || _draftTouched ||
          generation != repository.client.authGeneration) return;
      final text = draft['text'] is String ? draft['text'] as String : '';
      final rawNames = draft['attachment_names'];
      final names = rawNames is List
          ? rawNames.whereType<String>().take(4).toList()
          : <String>[];
      _restoringDraft = true;
      try {
        if (_controller.text.isEmpty && text.isNotEmpty) {
          _controller.value = TextEditingValue(
              text: text, selection: TextSelection.collapsed(offset: text.length));
        }
        if (names.isNotEmpty) {
          setState(() => _recoveredAttachmentNames.addAll(names));
        }
      } finally {
        _restoringDraft = false;
      }
    } catch (_) {
      // A corrupt or inaccessible local draft cannot grant execution rights.
    }
  }

  void _scheduleChatDraftSave() {
    if (_restoringDraft || _chatInvalidated) return;
    _draftTouched = true;
    _draftTimer?.cancel();
    _draftTimer = Timer(const Duration(milliseconds: 300),
        _persistChatDraftSnapshot);
  }

  void _persistChatDraftSnapshot() {
    final repository = _repository;
    if (repository == null || _chatInvalidated) return;
    final text = _controller.text;
    final attachmentNames = <String>[
      ..._attachments.map((attachment) => attachment.name),
      ..._failedAttachments.map((file) => file.name),
      ..._recoveredAttachmentNames,
    ].toSet().take(4).toList(growable: false);
    unawaited(repository.saveChatComposerDraft(widget.conversation.id, text,
        attachmentNames: attachmentNames).catchError((_) {}));
  }

  String get _resolvedTitle {
    final employee = _employeeProfile;
    if (employee != null) return employee.name;
    final conversationId = widget.conversation.id;
    if (isCodexConversation(conversationId)) return '超级员工-Codex';
    if (isCursorConversation(conversationId)) return '超级员工-Cursor';
    if (isClaudeConversation(conversationId)) return '超级员工-Claude';
    if (isTraeConversation(conversationId)) return '超级员工-Trae';
    return widget.conversation.title;
  }

  void _showMessage(String message) {
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  // ── Flyer Chat 适配层 ──────────────────────────────────────

  /// 把本地消息同步到 flutter_chat_ui 的控制器。
  void _syncFlyerChat() {
    final messages = _messages.map(_toFlyerMessage).toList(growable: false);
    unawaited(_flyerChatController.setMessages(messages));
  }

  /// 没有缓存时间戳的消息（本地新建/测试注入）首次渲染时固定 createdAt，
  /// 避免每次同步都换时间导致 flutter_chat_ui 的动画列表重排断言。
  Message _toFlyerMessage(ChatMessage message) {
    final createdMs = message.cacheTimestampMs > 0
        ? message.cacheTimestampMs
        : _flyerCreatedAt
            .putIfAbsent(message.id, DateTime.now)
            .millisecondsSinceEpoch;
    return TextMessage(
      id: message.id,
      authorId:
          message.role == ChatRole.user ? _flyerMeId : widget.conversation.id,
      createdAt: DateTime.fromMillisecondsSinceEpoch(createdMs),
      text: message.body,
      status: switch (message.status) {
        ChatDeliveryStatus.sent => MessageStatus.sent,
        ChatDeliveryStatus.pending => MessageStatus.sent,
        ChatDeliveryStatus.sending => MessageStatus.sending,
        ChatDeliveryStatus.queued => MessageStatus.sending,
        ChatDeliveryStatus.failed => MessageStatus.error,
      },
    );
  }

  Future<User?> _resolveFlyerUser(UserID userId) async {
    if (userId == _flyerMeId) {
      return User(id: _flyerMeId, name: '我');
    }
    return User(
      id: userId,
      name: _resolvedTitle,
      imageSource: _employeeProfile?.avatarUrl,
    );
  }

  void _insertVoiceText(String text) {
    final recognized = text.trim();
    if (recognized.isEmpty) return;
    final current = _controller.text.trim();
    _controller.text = current.isEmpty ? recognized : '$current $recognized';
    _controller.selection = TextSelection.collapsed(
      offset: _controller.text.length,
    );
  }

  void _replaceMessageBody(String messageId, String body) {
    setState(() => _replaceMessage(messageId, body: body));
  }

  void _appendMessageBody(String messageId, String token) {
    final index = _messages.indexWhere((message) => message.id == messageId);
    if (index < 0) return;
    final current = _messages[index];
    _messages[index] = ChatMessage(
      id: current.id,
      conversationId: current.conversationId,
      role: current.role,
      body: '${current.body}$token',
      timeText: '刚刚',
      senderName: current.senderName,
      senderAvatarUrl: current.senderAvatarUrl,
      hasEmployeeProfile: current.hasEmployeeProfile,
      status: current.status,
      quote: current.quote,
      cacheTimestampMs: current.cacheTimestampMs,
      turnId: current.turnId,
    );
    _syncFlyerChat();
  }

  void _replaceMessage(
    String messageId, {
    required String body,
    ChatDeliveryStatus? status,
  }) {
    final index = _messages.indexWhere((message) => message.id == messageId);
    if (index < 0) return;
    final current = _messages[index];
    _messages[index] = ChatMessage(
      id: current.id,
      conversationId: current.conversationId,
      role: current.role,
      body: body,
      timeText: '刚刚',
      senderName: current.senderName,
      senderAvatarUrl: current.senderAvatarUrl,
      hasEmployeeProfile: current.hasEmployeeProfile,
      status: status ?? current.status,
      quote: current.quote,
      cacheTimestampMs: current.cacheTimestampMs,
      turnId: current.turnId,
    );
    _syncFlyerChat();
  }

  void _removeMessage(String messageId) {
    _messages = [..._messages]
      ..removeWhere((message) => message.id == messageId);
    _syncFlyerChat();
  }

  List<Map<String, Object?>> _collectRecentToolCalls() {
    final repository = _repository;
    if (repository == null) return const <Map<String, Object?>>[];
    for (final message in _messages.reversed) {
      if (message.role != ChatRole.assistant) continue;
      if (!message.body.contains('闭环结果')) continue;
      final calls = repository.parseToolCallsFromBody(
        message.body,
        toolLabel: _resolvedTitle,
      );
      if (calls.isNotEmpty) return calls;
    }
    return const <Map<String, Object?>>[];
  }

  /// 计算某条 assistant 消息的 dev-loop 工具调用记录，供气泡内嵌 mini timeline 使用。
  List<Map<String, Object?>> _toolCallsFor(ChatMessage message) {
    final repository = _repository;
    if (repository == null) return const <Map<String, Object?>>[];
    if (message.role != ChatRole.assistant) {
      return const <Map<String, Object?>>[];
    }
    if (!message.body.contains('闭环结果')) return const <Map<String, Object?>>[];
    return repository.parseToolCallsFromBody(
      message.body,
      toolLabel: _resolvedTitle,
    );
  }

  List<String> _activeGitBranches() {
    final active = <String>{};
    final pattern = RegExp(r'(super-employee/[\w./-]+)');
    for (final message in _messages) {
      if (message.role != ChatRole.assistant) continue;
      for (final match in pattern.allMatches(message.body)) {
        active.add(match.group(1)!);
      }
      if (message.body.contains('✅ 已合并') || message.body.contains('已丢弃分支')) {
        final disposed = pattern
            .allMatches(message.body)
            .map((match) => match.group(1)!)
            .toSet();
        if (disposed.isEmpty) {
          active.clear();
        } else {
          active.removeAll(disposed);
        }
      }
    }
    return active.toList(growable: false);
  }

  String? _currentGitBranch(List<String> branches) {
    if (branches.isEmpty) return null;
    final selected = _selectedGitBranch;
    if (selected != null && branches.contains(selected)) return selected;
    return branches.last;
  }

  bool _showAvatarAt(int index) {
    final message = _messages[index];
    if (message.role == ChatRole.user) return true;
    if (index == 0) return true;
    return _messages[index - 1].role != message.role;
  }
}
