part of 'chat_screen.dart';

// _ChatScreenState 的最底层基类：持有全部状态字段与消息编辑/分支解析等低层方法。
abstract class _ChatStateHelpers extends State<ChatScreen> {
  late List<ChatMessage> _messages;
  final _controller = TextEditingController();
  var _loadingRemoteMessages = false;
  var _showToolPanel = false;
  var _sending = false;
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
    );
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
    );
  }

  void _removeMessage(String messageId) {
    _messages = [..._messages]
      ..removeWhere((message) => message.id == messageId);
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
