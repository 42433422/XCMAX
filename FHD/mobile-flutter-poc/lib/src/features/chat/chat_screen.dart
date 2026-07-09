import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../api/mobile_models.dart' show MobileMeData;
import '../../data/ai_employee_profile.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../models/conversation.dart';
import '../../policy/android_error_policy.dart';
import '../../policy/avatar_policy.dart';
import '../../platform/android_record_audio_permission.dart';
import '../../theme/app_theme.dart';
import '../../theme/message_avatar_layout.dart';
import '../../widgets/app_avatar.dart';
import '../../widgets/we_ui.dart';
import '../contacts/employee_profile_screen.dart';
import '../contacts/fixed_partner_profile_screen.dart';
import '../devtools/branch_detail_screen.dart';
import '../devtools/diff_viewer_screen.dart';
import '../devtools/timeline_screen.dart';
import '../tools/ocr_screen.dart';
import '../voice/voice_input_sheet.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({
    super.key,
    required this.conversation,
    required this.initialMessages,
    this.repository,
  });

  final ConversationItem conversation;
  final List<ChatMessage> initialMessages;
  final MobileRepository? repository;

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
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
  String _workspaceLabel = '';
  String _workspaceId = '';

  @override
  void initState() {
    super.initState();
    _messages = [...widget.initialMessages];
    _repository = widget.repository ?? MobileRepositoryScope.maybeRead(context);
    _employeeRef = _parseEmployeeConversationRef(widget.conversation.id);
    // 进会话一律从可发送状态开始，避免上次僵死锁残留。
    _sending = false;
    _activeAssistantId = null;
    _stopRequested = false;
    _activeRelayProgress = null;
    _loadRemoteMessages();
    _loadUserAvatar();
    _loadEmployeeProfile();
    _loadSelectedWorkspace();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final activeGitBranches = _activeGitBranches();
    final activeGitBranch = _currentGitBranch(activeGitBranches);
    final employeeProfile = _employeeProfile;
    return Scaffold(
      backgroundColor: colors.page,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            WeTopBar(
              title: _workspaceLabel.isNotEmpty &&
                      widget.conversation.type.superTool != null
                  ? '$_resolvedTitle · $_workspaceLabel'
                  : _resolvedTitle,
              height: 48,
              showBack: true,
              onBack: () => Navigator.of(context).maybePop(),
              actions: [
                if (widget.conversation.type.superTool != null)
                  IconButton(
                    onPressed: _pickWorkspace,
                    icon: const Icon(Icons.folder_open_outlined, size: 22),
                    tooltip: '选择项目',
                    color: colors.textPrimary,
                  ),
                IconButton(
                  onPressed: () => _showMessage('视频通话功能即将上线'),
                  icon: const Icon(Icons.videocam_outlined, size: 22),
                  tooltip: '视频',
                  color: colors.textPrimary,
                ),
                IconButton(
                  onPressed: _openProfileOrTools,
                  icon: const Icon(Icons.more_horiz, size: 22),
                  tooltip: '更多',
                  color: colors.textPrimary,
                ),
              ],
            ),
            if (_loadingRemoteMessages)
              LinearProgressIndicator(
                minHeight: 2,
                color: colors.brand,
                backgroundColor: colors.surfaceHigh,
              ),
            Expanded(
              child: _messages.isEmpty
                  ? const SizedBox.expand()
                  : ListView.builder(
                      reverse: true,
                      padding: const EdgeInsets.fromLTRB(14, 4, 14, 20),
                      itemBuilder: (context, index) {
                        final originalIndex = _messages.length - index - 1;
                        final message = _messages[originalIndex];
                        final isActiveRelay = _sending &&
                            _activeAssistantId == message.id &&
                            _activeRelayProgress != null;
                        final toolCalls = _toolCallsFor(message);
                        return MessageBubble(
                          message: message,
                          conversation: widget.conversation,
                          showAvatar: _showAvatarAt(originalIndex),
                          userAvatarUrl: _userAvatarSource,
                          aiAvatarUrl: employeeProfile?.avatarUrl,
                          aiContentDescription: _resolvedTitle,
                          hasEmployeeProfile: employeeProfile != null,
                          relayProgress:
                              isActiveRelay ? _activeRelayProgress : null,
                          cancellingRelay: _cancellingRelay,
                          onReply: () => setState(() => _replyTo = message),
                          onDelete: () => _deleteMessageAt(originalIndex),
                          onResend: message.status == ChatDeliveryStatus.failed
                              ? _resendLastChat
                              : null,
                          toolCalls: toolCalls,
                          onShowTimeline: toolCalls.isEmpty
                              ? null
                              : () => _openTimelineForMessage(message),
                        );
                      },
                      itemCount: _messages.length,
                    ),
            ),
            _Composer(
              key: ValueKey('chat-composer-busy-$_sending'),
              controller: _controller,
              onSend: _send,
              onStop: _stopChat,
              busy: _sending,
              topContent: _composerTopContent(
                activeGitBranches,
                activeGitBranch,
              ),
              showTools: _showToolPanel,
              onToggleTools: () =>
                  setState(() => _showToolPanel = !_showToolPanel),
              onVoice: _startVoiceInput,
              toolActions: _toolActions(),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _loadRemoteMessages() async {
    final repository = _repository;
    if (repository == null) return;

    setState(() => _loadingRemoteMessages = true);
    try {
      final remoteMessages = await repository.loadInitialMessages(
        widget.conversation,
      );
      if (!mounted) return;
      if (remoteMessages.isEmpty) return;
      setState(() {
        // 始终合并，禁止整表覆盖：发送中/本地临时气泡必须保留。
        final byId = <String, ChatMessage>{
          for (final m in remoteMessages) m.id: m,
        };
        for (final local in _messages) {
          final keepLocal = local.id.startsWith('local-') ||
              local.id.startsWith('assistant-') ||
              local.id.startsWith('git-') ||
              local.status == ChatDeliveryStatus.sending ||
              _sending ||
              _activeAssistantId == local.id;
          if (keepLocal || !byId.containsKey(local.id)) {
            byId[local.id] = local;
          }
        }
        _messages = byId.values.toList(growable: true);
      });
    } catch (_) {
      // Keep the Android-like empty state when auth/network is unavailable.
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

    // 恢复旧中继时不要占用 _sending：否则发送键变「停止」或点发送直接 return，
    // 用户会感觉「除了 Trae 都发不出去」。恢复失败/超时由 repository 清 inflight。
    final assistantId =
        'assistant-resume-${DateTime.now().microsecondsSinceEpoch}';
    setState(() {
      _showToolPanel = false;
      // 不抢占 _activeAssistantId / _sending：用户新发送应优先。
      _messages.add(
        ChatMessage(
          id: assistantId,
          conversationId: widget.conversation.id,
          role: ChatRole.assistant,
          body: '正在检查未完成的电脑任务…',
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
          if (!mounted || _stopRequested || _sending) return;
          setState(() => _appendMessageBody(assistantId, token));
        },
        onStatus: (progress) {
          if (!mounted || _stopRequested || _sending) return;
          setState(() => _activeRelayProgress = progress);
        },
        isCancelled: () => _stopRequested || _sending || !mounted,
      );
      if (!mounted) return;
      if (_sending || _stopRequested) {
        setState(() => _removeMessage(assistantId));
        return;
      }
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
      if (_sending || _stopRequested) {
        setState(() => _removeMessage(assistantId));
        return;
      }
      setState(() {
        _replaceMessage(
          assistantId,
          body: '（上次电脑任务已结束：$error）',
          status: ChatDeliveryStatus.failed,
        );
        _activeRelayProgress = null;
      });
    } finally {
      if (mounted) {
        setState(() {
          if (_activeAssistantId == assistantId) {
            _activeAssistantId = null;
          }
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
      // Keep the Android-like chat surface usable while modInfos refresh fails.
    }
  }

  Future<void> _loadSelectedWorkspace() async {
    if (widget.conversation.type.superTool == null) return;
    final repository = _repository;
    if (repository == null) return;
    try {
      final options = await repository.listFactoryWorkspaces();
      final label = await repository.selectedWorkspaceLabel();
      final session = await repository.client.loadSession();
      if (!mounted) return;
      final id = session.selectedWorkspaceId.trim().isEmpty
          ? (options.isNotEmpty ? options.first.id : 'xcmax')
          : session.selectedWorkspaceId.trim();
      setState(() {
        _workspaceId = id;
        _workspaceLabel = label;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _workspaceId = 'xcmax';
        _workspaceLabel = 'XCMAX 主项目';
      });
    }
  }

  Future<void> _pickWorkspace() async {
    final repository = _repository;
    if (repository == null) return;
    final options = await repository.listFactoryWorkspaces();
    if (!mounted) return;
    if (options.isEmpty) {
      _showMessage('暂无可用项目');
      return;
    }
    final colors = AppTheme.colors(context);
    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: colors.surface,
      builder: (context) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.only(bottom: 18),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(18, 16, 18, 10),
                  child: Text(
                    '选择派工项目',
                    style: TextStyle(
                      color: colors.textPrimary,
                      fontSize: 17,
                      height: 1.29,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                Divider(height: 0.5, thickness: 0.5, color: colors.divider),
                for (final option in options)
                  ListTile(
                    title: Text(
                      option.label.isNotEmpty ? option.label : option.id,
                      style: TextStyle(color: colors.textPrimary),
                    ),
                    subtitle: option.root.isNotEmpty
                        ? Text(
                            option.root,
                            style: TextStyle(color: colors.textSecondary),
                          )
                        : null,
                    trailing: option.id == _workspaceId
                        ? Icon(Icons.check, color: colors.brand)
                        : null,
                    onTap: () async {
                      Navigator.of(context).pop();
                      await repository.setSelectedWorkspaceId(option.id);
                      if (!mounted) return;
                      setState(() {
                        _workspaceId = option.id;
                        _workspaceLabel =
                            option.label.isNotEmpty ? option.label : option.id;
                      });
                    },
                  ),
              ],
            ),
          ),
        );
      },
    );
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

  void _unlockSending({String? onlyAssistantId}) {
    if (!mounted) {
      _sending = false;
      if (onlyAssistantId == null || _activeAssistantId == onlyAssistantId) {
        _activeAssistantId = null;
      }
      _activeRelayProgress = null;
      return;
    }
    setState(() {
      _sending = false;
      if (onlyAssistantId == null || _activeAssistantId == onlyAssistantId) {
        _activeAssistantId = null;
      }
      _activeRelayProgress = null;
      _cancellingRelay = false;
    });
  }

  Future<void> _send([String? overrideText]) async {
    final text = (overrideText ?? _controller.text).trim();
    if (text.isEmpty) return;
    // 僵死锁：_sending=true 但没有活跃助手气泡时，按钮仍可能显示「发送」，
    // 点发送只会 toast。直接解锁后继续发，避免 Cursor 等会话永久卡死。
    if (_sending && _activeAssistantId == null) {
      _unlockSending();
    } else if (_sending) {
      _showMessage('当前仍有任务在进行，请先点「停止」再发送');
      return;
    }
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
        body: '正在连接…',
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

    // 看门狗：异常路径漏清 _sending 时自动解锁（90s，避免永久无法再发）。
    Future<void>.delayed(const Duration(seconds: 90), () {
      if (!mounted) return;
      if (_sending && _activeAssistantId == assistantId) {
        _unlockSending(onlyAssistantId: assistantId);
        _showMessage('发送超时已解锁，可重试');
      }
    });

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
      });
      _unlockSending(onlyAssistantId: assistantId);
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
          body: androidProductErrorMessage(
            error.toString(),
            '当前离线同步不可用，请连接电脑或稍后重试。',
          ),
          status: ChatDeliveryStatus.failed,
        );
        _activeRelayProgress = null;
      });
    } finally {
      // 无论 _activeAssistantId 是否被中途清空，本轮发送结束都必须释放锁。
      if (_sending &&
          (_activeAssistantId == null || _activeAssistantId == assistantId)) {
        _unlockSending(onlyAssistantId: assistantId);
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
    final progress = _activeRelayProgress;
    // 即使没有 assistantId，也必须清 _sending，否则会出现「按钮是发送、点了却提示先停止」。
    if (assistantId == null) {
      setState(() {
        _stopRequested = true;
        _sending = false;
        _activeRelayProgress = null;
        _cancellingRelay = false;
      });
      if (progress != null && progress.taskId.isNotEmpty) {
        _cancelRelayTask(progress.taskId);
      }
      return;
    }
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

  void _showMessage(String message) {
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
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

  Future<void> _startVoiceInput() async {
    setState(() => _showToolPanel = false);
    final granted = await const AndroidRecordAudioPermission().ensureGranted();
    if (!mounted) return;
    if (!granted) {
      _showMessage('需要麦克风权限才能使用语音输入');
      return;
    }
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: AppTheme.colors(context).surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(
          top: Radius.circular(VoiceInputDesign.sheetTopCornerRadius),
        ),
      ),
      clipBehavior: Clip.antiAlias,
      builder: (context) => VoiceInputSheet(onResult: _insertVoiceText),
    );
  }

  void _openProfileOrTools() {
    final fixedKind =
        FixedPartnerProfileSpec.kindForConversation(widget.conversation);
    if (fixedKind != null) {
      Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => FixedPartnerProfileScreen(
            kind: fixedKind,
            repositoryConversation: widget.conversation,
            repository: _repository,
          ),
        ),
      );
      return;
    }

    final employee =
        _employeeProfile ?? _employeePlaceholderFromRef(_employeeRef);
    if (employee != null) {
      Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => AiEmployeeProfileScreen(
            employee: employee,
            repository: _repository,
          ),
        ),
      );
      return;
    }

    setState(() => _showToolPanel = !_showToolPanel);
  }

  void _sendTaskDispatch() {
    final task = _controller.text.trim();
    if (task.isEmpty) {
      setState(() => _showToolPanel = false);
      _showMessage('先输入要派发的任务');
      return;
    }
    _send('帮我安排并完成这个任务：$task');
  }

  void _sendAcceptanceFollowUp() {
    _send('回访一下最近一次任务的进度和验收结论。');
  }

  void _sendProblemFix() {
    final task = _controller.text.trim();
    if (task.isEmpty) {
      setState(() => _showToolPanel = false);
      _showMessage('先输入要修复的问题');
      return;
    }
    _send(task.startsWith('修复') ? task : '修复：$task');
  }

  Future<void> _runGitOperation(String branch, String op) async {
    if (_runningGitOp) return;
    final repository = widget.repository;
    if (repository == null) {
      _showMessage('未绑定电脑工具，无法执行 $op');
      return;
    }
    final messageId = 'git-${DateTime.now().microsecondsSinceEpoch}';
    setState(() {
      _runningGitOp = true;
      _showToolPanel = false;
      _messages.add(
        ChatMessage(
          id: messageId,
          conversationId: widget.conversation.id,
          role: ChatRole.assistant,
          body: '执行中…',
          timeText: '刚刚',
          hasEmployeeProfile: _employeeProfile != null,
        ),
      );
    });
    try {
      final result = await repository.runGitOperation(branch: branch, op: op);
      if (!mounted) return;
      _replaceMessageBody(
          messageId, result.trim().isEmpty ? '电脑工具已完成任务。' : result);
    } catch (error) {
      if (!mounted) return;
      _replaceMessageBody(messageId, '（$error）');
    } finally {
      if (mounted) setState(() => _runningGitOp = false);
    }
  }

  void _replaceMessageBody(String messageId, String body) {
    setState(() => _replaceMessage(messageId, body: body));
  }

  void _appendMessageBody(String messageId, String token) {
    final index = _messages.indexWhere((message) => message.id == messageId);
    if (index < 0) {
      // 远程历史覆盖后气泡可能丢失：补回助手气泡，避免「停止」却无内容。
      _messages.add(
        ChatMessage(
          id: messageId,
          conversationId: widget.conversation.id,
          role: ChatRole.assistant,
          body: token,
          timeText: '刚刚',
          hasEmployeeProfile: _employeeProfile != null,
          status: ChatDeliveryStatus.sending,
        ),
      );
      return;
    }
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
    if (index < 0) {
      _messages.add(
        ChatMessage(
          id: messageId,
          conversationId: widget.conversation.id,
          role: ChatRole.assistant,
          body: body,
          timeText: '刚刚',
          hasEmployeeProfile: _employeeProfile != null,
          status: status ?? ChatDeliveryStatus.sent,
        ),
      );
      return;
    }
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

  List<_ChatToolAction> _toolActions() {
    final isSuperEmployee = widget.conversation.type.superTool != null;
    final activeGitBranches = _activeGitBranches();
    final baseActions = _baseToolActions();
    if (isSuperEmployee && activeGitBranches.isNotEmpty) {
      final branch =
          _currentGitBranch(activeGitBranches) ?? activeGitBranches.last;
      return [
        _ChatToolAction(
          icon: Icons.difference,
          title: '查看 diff',
          subtitle: '逐行检查分支改动',
          onTap: () => _openDiffViewer(branch),
        ),
        _ChatToolAction(
          icon: Icons.account_tree,
          title: '分支与审批',
          subtitle: '查看提交并合并/丢弃',
          onTap: () => _openBranchDetail(branch),
        ),
        _ChatToolAction(
          icon: Icons.timeline,
          title: '执行回顾',
          subtitle: '查看工具调用时间线',
          onTap: () => _openTimeline(),
        ),
        ..._sharedToolActions(),
      ];
    }
    if (isSuperEmployee) {
      // 与 Android 对齐：无活跃分支时保留新建对话/OCR/语音，并额外提供执行回顾。
      return [
        ...baseActions,
        _ChatToolAction(
          icon: Icons.bolt_outlined,
          title: '测试发送 ping',
          subtitle: '绕过输入框直接发一条 ping',
          onTap: () {
            setState(() => _showToolPanel = false);
            // 若上次发送僵死，先解锁再测，避免只 toast「请先停止」。
            if (_sending) _unlockSending();
            _send('ping');
          },
        ),
        _ChatToolAction(
          icon: Icons.folder_open_outlined,
          title: '选择项目',
          subtitle: _workspaceLabel.isNotEmpty
              ? '当前：$_workspaceLabel'
              : '切换派工 Workspace',
          onTap: () {
            setState(() => _showToolPanel = false);
            _pickWorkspace();
          },
        ),
        _ChatToolAction(
          icon: Icons.timeline,
          title: '执行回顾',
          subtitle: '查看工具调用时间线',
          onTap: () => _openTimeline(),
        ),
        ..._sharedToolActions(),
      ];
    }
    return [
      ...baseActions,
      ..._sharedToolActions(),
    ];
  }

  List<_ChatToolAction> _baseToolActions() {
    return [
      _ChatToolAction(
        icon: Icons.refresh,
        title: '新建对话',
        subtitle: '清空当前上下文',
        onTap: _clearChat,
      ),
      _ChatToolAction(
        icon: Icons.qr_code_scanner,
        title: 'OCR 识别',
        subtitle: '拍照提取文字',
        onTap: () {
          setState(() => _showToolPanel = false);
          Navigator.of(
            context,
          ).push(MaterialPageRoute(builder: (_) => const OcrScreen()));
        },
      ),
      _ChatToolAction(
        icon: Icons.mic,
        title: '语音输入',
        subtitle: '手机语音转文字',
        onTap: _startVoiceInput,
      ),
    ];
  }

  void _openDiffViewer(String branch) {
    final repository = _repository;
    if (repository == null) return;
    setState(() => _showToolPanel = false);
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => DiffViewerScreen(
          branch: branch,
          repository: repository,
        ),
      ),
    );
  }

  void _openBranchDetail(String branch) {
    final repository = _repository;
    if (repository == null) return;
    setState(() => _showToolPanel = false);
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => BranchDetailScreen(
          branch: branch,
          repository: repository,
        ),
      ),
    );
  }

  void _openTimeline() {
    final repository = _repository;
    if (repository == null) return;
    setState(() => _showToolPanel = false);
    final toolLabel = _resolvedTitle;
    final calls = _collectRecentToolCalls();
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => TimelineScreen(
          repository: repository,
          taskId: '',
          toolLabel: toolLabel,
          initialCalls: calls,
        ),
      ),
    );
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
    if (message.role != ChatRole.assistant) return const <Map<String, Object?>>[];
    if (!message.body.contains('闭环结果')) return const <Map<String, Object?>>[];
    return repository.parseToolCallsFromBody(
      message.body,
      toolLabel: _resolvedTitle,
    );
  }

  void _openTimelineForMessage(ChatMessage message) {
    final repository = _repository;
    if (repository == null) return;
    final calls = _toolCallsFor(message);
    if (calls.isEmpty) return;
    setState(() => _showToolPanel = false);
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => TimelineScreen(
          repository: repository,
          taskId: '',
          toolLabel: _resolvedTitle,
          initialCalls: calls,
        ),
      ),
    );
  }

  List<_ChatToolAction> _sharedToolActions() {
    return [
      _ChatToolAction(
        icon: Icons.group,
        title: '任务派工',
        subtitle: '先讨论再执行',
        onTap: _sendTaskDispatch,
      ),
      _ChatToolAction(
        icon: Icons.check,
        title: '验收回访',
        subtitle: '要结论和证据',
        onTap: _sendAcceptanceFollowUp,
      ),
      _ChatToolAction(
        icon: Icons.auto_awesome,
        title: '问题修复',
        subtitle: '定位根因并验证',
        onTap: _sendProblemFix,
      ),
      if (widget.conversation.type.superTool != null)
        _ChatToolAction(
          icon: Icons.system_update_alt,
          title: '发布 APK 到局域网',
          subtitle: '本机打包并自动装到手机',
          onTap: _sendLanApkPublish,
        ),
    ];
  }

  void _sendLanApkPublish() {
    setState(() => _showToolPanel = false);
    if (_sending) _unlockSending();
    _send(
      '请在本机执行：bash FHD/scripts/dev/lan-mobile-apk-publish.sh\n'
      '要求：versionName 保持 10.0.0，versionCode 用时间戳；'
      '产物写入 FHD/data/lan-releases/enterprise/ 并更新 manifest.json。\n'
      '脚本默认会识别无线 adb（adb connect 手机IP:5555）并自动 install -r，'
      '无需 USB、无需我再点「检查更新」。完成后回复 versionCode、设备 serial、安装结果。',
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

  Widget? _composerTopContent(List<String> branches, String? branch) {
    final gitBar = _gitActionBar(branches, branch);
    final reply = _replyTo;
    if (gitBar == null && reply == null) return null;
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (reply != null)
          _ReplyPreviewBar(
            message: reply,
            onCancel: () => setState(() => _replyTo = null),
          ),
        if (gitBar != null) gitBar,
      ],
    );
  }

  Widget? _gitActionBar(List<String> branches, String? branch) {
    final isSuperEmployee = widget.conversation.type.superTool != null;
    if (!isSuperEmployee || branch == null) return null;
    return _ChatGitActionBar(
      branch: branch,
      branches: branches,
      running: _runningGitOp,
      onSelectBranch: branches.length > 1
          ? () => _showGitBranchPicker(branches: branches, current: branch)
          : null,
      onDiff: () => _runGitOperation(branch, 'git.diff'),
      onMerge: () => _runGitOperation(branch, 'git.merge'),
      onDiscard: () => _runGitOperation(branch, 'git.discard'),
    );
  }

  void _showGitBranchPicker({
    required List<String> branches,
    required String current,
  }) {
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: AppTheme.colors(context).surface,
      builder: (context) {
        final colors = AppTheme.colors(context);
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.only(bottom: 18),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(18, 16, 18, 10),
                  child: Text(
                    '选择开发任务分支',
                    style: TextStyle(
                      color: colors.textPrimary,
                      fontSize: 17,
                      height: 1.29,
                      fontWeight: FontWeight.w600,
                      letterSpacing: 0,
                    ),
                  ),
                ),
                Divider(height: 0.5, thickness: 0.5, color: colors.divider),
                for (final branch in branches)
                  ListTile(
                    title: Text(
                      _shortGitBranchLabel(branch),
                      style: TextStyle(color: colors.textPrimary),
                    ),
                    subtitle: Text(
                      branch,
                      style: TextStyle(color: colors.textSecondary),
                    ),
                    trailing: branch == current
                        ? Icon(Icons.check, color: colors.brand)
                        : null,
                    onTap: () {
                      Navigator.of(context).pop();
                      setState(() => _selectedGitBranch = branch);
                    },
                  ),
              ],
            ),
          ),
        );
      },
    );
  }
}

String _formatBubbleTimeText(String rawText) {
  final raw = rawText.trim();
  if (raw.isEmpty) return '';

  DateTime? parsed;
  final numeric = int.tryParse(raw);
  if (numeric != null && numeric > 0) {
    final millis = numeric <= 9999999999 ? numeric * 1000 : numeric;
    parsed = DateTime.fromMillisecondsSinceEpoch(millis);
  } else {
    parsed = DateTime.tryParse(raw)?.toLocal();
  }
  if (parsed == null) return raw;

  final now = DateTime.now();
  final sameDay = now.year == parsed.year &&
      now.month == parsed.month &&
      now.day == parsed.day;
  final hour = parsed.hour.toString().padLeft(2, '0');
  final minute = parsed.minute.toString().padLeft(2, '0');
  if (sameDay) return '$hour:$minute';
  return '${parsed.month}/${parsed.day} $hour:$minute';
}

class MessageBubble extends StatelessWidget {
  const MessageBubble({
    super.key,
    required this.message,
    required this.conversation,
    required this.showAvatar,
    required this.userAvatarUrl,
    required this.aiAvatarUrl,
    required this.aiContentDescription,
    required this.hasEmployeeProfile,
    required this.onReply,
    required this.onDelete,
    this.onResend,
    this.relayProgress,
    this.cancellingRelay = false,
    this.toolCalls = const <Map<String, Object?>>[],
    this.onShowTimeline,
  });

  final ChatMessage message;
  final ConversationItem conversation;
  final bool showAvatar;
  final String userAvatarUrl;
  final String? aiAvatarUrl;
  final String aiContentDescription;
  final bool hasEmployeeProfile;
  final VoidCallback onReply;
  final VoidCallback onDelete;
  final VoidCallback? onResend;
  final RelayTaskProgress? relayProgress;
  final bool cancellingRelay;
  final List<Map<String, Object?>> toolCalls;
  final VoidCallback? onShowTimeline;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    if (message.role == ChatRole.system) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Center(
          child: Text(
            message.body,
            style: TextStyle(color: colors.textSecondary, fontSize: 12),
          ),
        ),
      );
    }

    final isUser = message.role == ChatRole.user;
    final fallback = isUser
        ? AppAvatarFallback.user
        : chatAvatarFallback(
            conversationId: conversation.id,
            hasEmployeeProfile: hasEmployeeProfile,
          );
    final fixedAssistantAvatar = conversation.type.usesPinnedAvatar;
    final avatar = AppAvatar(
      imageSource: isUser
          ? userAvatarUrl
          : fixedAssistantAvatar
              ? null
              : aiAvatarUrl,
      fallback: fallback,
      size: MessageAvatarLayout.bubbleAvatarSize,
      borderRadius: MessageAvatarLayout.bubbleAvatarRadius,
      contentDescription: isUser ? '我' : aiContentDescription,
    );
    final bubbleColor = isUser ? colors.chatUserBubble : colors.surface;
    final textColor = isUser ? colors.chatUserBubbleText : colors.textPrimary;
    final visibleBody = message.status == ChatDeliveryStatus.sending
        ? '${message.body}\u200B▌'
        : message.body;
    final quote = message.quote?.trim() ?? '';
    final timeText = _formatBubbleTimeText(message.timeText);
    final showTimestamp =
        message.status != ChatDeliveryStatus.sending && timeText.isNotEmpty;

    return Padding(
      padding: EdgeInsets.only(
        top: showAvatar
            ? MessageAvatarLayout.bubbleTopPaddingWithAvatar
            : MessageAvatarLayout.bubbleTopPaddingWithoutAvatar,
        bottom: MessageAvatarLayout.bubbleTopPaddingWithoutAvatar,
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment:
            isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
        children: [
          if (!isUser) ...[
            if (showAvatar) ...[
              avatar,
              const SizedBox(width: MessageAvatarLayout.bubbleAvatarGap),
            ] else
              const SizedBox(
                  width: MessageAvatarLayout.bubbleAvatarReservedWidth),
          ],
          Flexible(
            child: Column(
              crossAxisAlignment:
                  isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start,
              children: [
                _MessageActionMenu(
                  text: message.body,
                  onReply: onReply,
                  onDelete: onDelete,
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 260),
                    child: Material(
                      key: ValueKey('chat_bubble_${message.id}'),
                      color: bubbleColor,
                      elevation: 1,
                      shadowColor: Colors.black.withValues(alpha: 0.08),
                      borderRadius: BorderRadius.only(
                        topLeft: Radius.circular(isUser ? 12 : 4),
                        topRight: Radius.circular(isUser ? 4 : 12),
                        bottomLeft: const Radius.circular(12),
                        bottomRight: const Radius.circular(12),
                      ),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 10,
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            if (quote.isNotEmpty) ...[
                              Container(
                                constraints:
                                    const BoxConstraints(maxWidth: 236),
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 8,
                                  vertical: 6,
                                ),
                                decoration: BoxDecoration(
                                  color: (isUser
                                          ? Colors.white
                                          : colors.textPrimary)
                                      .withValues(alpha: 0.06),
                                  borderRadius: BorderRadius.circular(6),
                                ),
                                child: Text(
                                  quote,
                                  maxLines: 2,
                                  overflow: TextOverflow.ellipsis,
                                  style: TextStyle(
                                    color: isUser
                                        ? colors.chatUserBubbleText
                                            .withValues(alpha: 0.8)
                                        : colors.textSecondary,
                                    fontSize: 12,
                                    height: 1.33,
                                    letterSpacing: 0,
                                  ),
                                ),
                              ),
                              const SizedBox(height: 6),
                            ],
                            if (relayProgress != null) ...[
                              _RelayProgressCard(
                                progress: relayProgress!,
                                cancelling: cancellingRelay,
                              ),
                              const SizedBox(height: 8),
                            ],
                            Text(
                              visibleBody,
                              style: TextStyle(
                                color: textColor,
                                fontSize: 15,
                                height: 1.4,
                                letterSpacing: 0,
                              ),
                            ),
                            if (toolCalls.isNotEmpty && onShowTimeline != null) ...[
                              const SizedBox(height: 10),
                              _MiniTimeline(
                                calls: toolCalls,
                                onTap: onShowTimeline!,
                              ),
                            ],
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
                if (message.status == ChatDeliveryStatus.failed ||
                    showTimestamp)
                  Padding(
                    padding: const EdgeInsets.only(top: 3, left: 4, right: 4),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        if (message.status == ChatDeliveryStatus.failed) ...[
                          Text(
                            '发送失败',
                            style: TextStyle(
                              color: colors.danger,
                              fontSize: 11,
                              height: 1.27,
                              fontWeight: FontWeight.w500,
                              letterSpacing: 0,
                            ),
                          ),
                          if (onResend != null) ...[
                            const SizedBox(width: 8),
                            GestureDetector(
                              onTap: onResend,
                              child: Text(
                                '重发',
                                style: TextStyle(
                                  color: colors.brand,
                                  fontSize: 11,
                                  height: 1.27,
                                  fontWeight: FontWeight.w500,
                                  letterSpacing: 0,
                                ),
                              ),
                            ),
                          ],
                        ] else
                          Text(
                            timeText,
                            style: TextStyle(
                              color: colors.textSecondary,
                              fontSize: 11,
                              height: 1.27,
                              fontWeight: FontWeight.w500,
                              letterSpacing: 0,
                            ),
                          ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
          if (isUser) ...[
            if (showAvatar) ...[
              const SizedBox(width: MessageAvatarLayout.bubbleAvatarGap),
              avatar,
            ] else
              const SizedBox(
                  width: MessageAvatarLayout.bubbleAvatarReservedWidth),
          ],
        ],
      ),
    );
  }
}

/// Assistant 气泡底部嵌入的 dev-loop mini timeline：4 图标水平排列 + 连接线，
/// 点击跳转 TimelineScreen 查看完整调用详情。
class _MiniTimeline extends StatelessWidget {
  const _MiniTimeline({required this.calls, required this.onTap});

  final List<Map<String, Object?>> calls;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        decoration: BoxDecoration(
          color: colors.surfaceHigh.withValues(alpha: 0.5),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(
            color: colors.divider.withValues(alpha: 0.6),
            width: 0.5,
          ),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Text(
              '闭环',
              style: TextStyle(
                color: colors.textSecondary,
                fontSize: 10,
                fontWeight: FontWeight.w600,
                letterSpacing: 0.5,
              ),
            ),
            const SizedBox(width: 8),
            Expanded(child: _buildNodes(colors)),
            const SizedBox(width: 6),
            Icon(
              Icons.chevron_right,
              size: 14,
              color: colors.textTertiary,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildNodes(XcagiThemeColors colors) {
    final children = <Widget>[];
    for (var i = 0; i < calls.length; i++) {
      final call = calls[i];
      children.add(_MiniTimelineNode(call: call, colors: colors));
      if (i < calls.length - 1) {
        children.add(
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(top: 10.5, left: 2, right: 2),
              child: _MiniTimelineConnector(
                colors: colors,
                success: _callSuccess(call),
              ),
            ),
          ),
        );
      }
    }
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: children,
    );
  }

  /// 已完成的步骤（success 为 null）按成功处理；只有显式 success=false 才视为失败。
  bool _callSuccess(Map<String, Object?> call) {
    final v = call['success'];
    if (v is bool) return v;
    return true;
  }
}

class _MiniTimelineNode extends StatelessWidget {
  const _MiniTimelineNode({required this.call, required this.colors});

  final Map<String, Object?> call;
  final XcagiThemeColors colors;

  @override
  Widget build(BuildContext context) {
    final icon = _iconFor(call['icon'] ?? '');
    final success = call['success'] != false;
    final color = success ? colors.success : colors.danger;
    final label = _shortLabel(call['label'] as String? ?? '');
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 22,
          height: 22,
          decoration: BoxDecoration(
            color: color.withValues(alpha: 0.12),
            shape: BoxShape.circle,
          ),
          child: Icon(icon, size: 13, color: color),
        ),
        const SizedBox(height: 3),
        SizedBox(
          width: 22,
          child: Text(
            label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            textAlign: TextAlign.center,
            style: TextStyle(
              color: colors.textSecondary,
              fontSize: 9,
              height: 1.0,
              fontWeight: FontWeight.w500,
              letterSpacing: 0,
            ),
          ),
        ),
      ],
    );
  }

  String _shortLabel(String raw) {
    if (raw.isEmpty) return raw;
    if (raw.startsWith('创建分支')) return '分支';
    if (raw.startsWith('验证')) return '验证';
    if (raw.startsWith('推送')) return '推送';
    if (raw.contains('CLI')) return 'CLI';
    if (raw.contains('执行')) return '执行';
    if (raw.length <= 2) return raw;
    return raw.substring(0, 2);
  }

  IconData _iconFor(Object? icon) {
    switch (icon) {
      case 'branch':
        return Icons.call_split;
      case 'check':
        return Icons.check_circle_outline;
      case 'upload':
        return Icons.cloud_upload_outlined;
      case 'terminal':
      default:
        return Icons.terminal;
    }
  }
}

class _MiniTimelineConnector extends StatelessWidget {
  const _MiniTimelineConnector({required this.colors, required this.success});

  final XcagiThemeColors colors;
  final bool success;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 1,
      color: success
          ? colors.success.withValues(alpha: 0.5)
          : colors.divider.withValues(alpha: 0.7),
    );
  }
}

class _MessageActionMenu extends StatelessWidget {
  const _MessageActionMenu({
    required this.text,
    required this.onReply,
    required this.onDelete,
    required this.child,
  });

  final String text;
  final VoidCallback onReply;
  final VoidCallback onDelete;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      behavior: HitTestBehavior.translucent,
      onLongPressStart: (details) async {
        if (text.trim().isEmpty) return;
        final selected = await showMenu<String>(
          context: context,
          position: RelativeRect.fromLTRB(
            details.globalPosition.dx,
            details.globalPosition.dy,
            details.globalPosition.dx,
            details.globalPosition.dy,
          ),
          items: const [
            PopupMenuItem(value: 'copy', child: Text('复制')),
            PopupMenuItem(value: 'reply', child: Text('引用')),
            PopupMenuItem(value: 'delete', child: Text('删除')),
          ],
        );
        if (!context.mounted) return;
        switch (selected) {
          case 'copy':
            await Clipboard.setData(ClipboardData(text: text));
            if (!context.mounted) return;
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('已复制')),
            );
            break;
          case 'reply':
            onReply();
            break;
          case 'delete':
            onDelete();
            break;
        }
      },
      child: child,
    );
  }
}

/// 长任务（relay dev-loop）内嵌进度卡：步骤列表 + 进度条。
/// 取消统一走底部「停止」，气泡内不再放「中断」。
class _RelayProgressCard extends StatelessWidget {
  const _RelayProgressCard({
    required this.progress,
    required this.cancelling,
  });

  final RelayTaskProgress progress;
  final bool cancelling;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final steps = _stepsForStatus(progress.status);
    final activeIndex = _activeIndexForStatus(progress.status);
    return Container(
      constraints: const BoxConstraints(maxWidth: 236),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: colors.page,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: colors.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              SizedBox(
                width: 14,
                height: 14,
                child: cancelling
                    ? CircularProgressIndicator(
                        strokeWidth: 2,
                        valueColor: AlwaysStoppedAnimation(colors.danger),
                      )
                    : (progress.status == 'completed'
                        ? Icon(Icons.check_circle,
                            size: 14, color: colors.success)
                        : SizedBox(
                            width: 14,
                            height: 14,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              valueColor:
                                  AlwaysStoppedAnimation(colors.brand),
                            ),
                          )),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  _titleForStatus(progress.status),
                  style: TextStyle(
                    color: colors.textPrimary,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          for (var i = 0; i < steps.length; i++) ...[
            _StepRow(
              label: steps[i],
              state: _stepState(i, activeIndex, progress.status),
              isLast: i == steps.length - 1,
            ),
          ],
        ],
      ),
    );
  }

  String _titleForStatus(String status) {
    switch (status) {
      case 'queued':
        return '${progress.toolLabel} 任务排队中';
      case 'running':
      case 'assigned':
        return '${progress.toolLabel} 正在执行';
      case 'resuming':
        return '${progress.toolLabel} 恢复中';
      case 'completed':
        return '${progress.toolLabel} 已完成';
      case 'failed':
        return '${progress.toolLabel} 执行失败';
      case 'blocked':
        return '${progress.toolLabel} 已阻塞';
      case 'cancelled':
        return '${progress.toolLabel} 已取消';
      default:
        return progress.toolLabel;
    }
  }

  List<String> _stepsForStatus(String status) {
    return const ['创建任务', '排队等待', '电脑执行', '回写结果'];
  }

  int _activeIndexForStatus(String status) {
    switch (status) {
      case 'queued':
        return 1;
      case 'running':
      case 'assigned':
        return 2;
      case 'completed':
        return 4;
      case 'failed':
      case 'blocked':
      case 'cancelled':
        return -1;
      default:
        return 0;
    }
  }

  _StepState _stepState(int index, int activeIndex, String status) {
    if (status == 'failed' || status == 'blocked' || status == 'cancelled') {
      if (index == activeIndex - 1 || index == activeIndex) {
        return _StepState.failed;
      }
    }
    if (index < activeIndex) return _StepState.done;
    if (index == activeIndex) return _StepState.active;
    return _StepState.pending;
  }
}

enum _StepState { pending, active, done, failed }

class _StepRow extends StatelessWidget {
  const _StepRow({
    required this.label,
    required this.state,
    required this.isLast,
  });

  final String label;
  final _StepState state;
  final bool isLast;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final iconColor = switch (state) {
      _StepState.done => colors.success,
      _StepState.active => colors.brand,
      _StepState.failed => colors.danger,
      _StepState.pending => colors.textTertiary,
    };
    final labelColor = switch (state) {
      _StepState.done => colors.textSecondary,
      _StepState.active => colors.textPrimary,
      _StepState.failed => colors.danger,
      _StepState.pending => colors.textTertiary,
    };
    return Row(
      children: [
        SizedBox(
          width: 16,
          child: Column(
            children: [
              if (state == _StepState.active)
                SizedBox(
                  width: 10,
                  height: 10,
                  child: CircularProgressIndicator(
                    strokeWidth: 1.5,
                    valueColor: AlwaysStoppedAnimation(iconColor),
                  ),
                )
              else
                Icon(
                  state == _StepState.done
                      ? Icons.check_circle
                      : state == _StepState.failed
                          ? Icons.cancel
                          : Icons.radio_button_unchecked,
                  size: 12,
                  color: iconColor,
                ),
              if (!isLast)
                Container(
                  width: 1,
                  height: 8,
                  color: colors.divider,
                ),
            ],
          ),
        ),
        const SizedBox(width: 6),
        Text(
          label,
          style: TextStyle(
            color: labelColor,
            fontSize: 11,
            fontWeight: state == _StepState.active
                ? FontWeight.w600
                : FontWeight.w400,
          ),
        ),
      ],
    );
  }
}

class _ReplyPreviewBar extends StatelessWidget {
  const _ReplyPreviewBar({
    required this.message,
    required this.onCancel,
  });

  final ChatMessage message;
  final VoidCallback onCancel;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final sender = message.role == ChatRole.user ? '我' : '对方';
    return Container(
      color: colors.surface,
      padding: const EdgeInsets.fromLTRB(12, 6, 8, 6),
      child: Row(
        children: [
          Container(
            width: 3,
            height: 28,
            decoration: BoxDecoration(
              color: colors.brand,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              '引用 $sender：${message.body}',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: colors.textSecondary,
                fontSize: 13,
                height: 1.31,
                letterSpacing: 0,
              ),
            ),
          ),
          IconButton(
            onPressed: onCancel,
            icon: const Icon(Icons.close, size: 18),
            color: colors.textSecondary,
            tooltip: '取消引用',
            constraints: const BoxConstraints.tightFor(width: 32, height: 32),
            padding: EdgeInsets.zero,
          ),
        ],
      ),
    );
  }
}

class _Composer extends StatelessWidget {
  const _Composer({
    super.key,
    required this.controller,
    required this.onSend,
    required this.onStop,
    required this.busy,
    this.topContent,
    required this.showTools,
    required this.onToggleTools,
    required this.onVoice,
    required this.toolActions,
  });

  final TextEditingController controller;
  final VoidCallback onSend;
  final VoidCallback onStop;
  final bool busy;
  final Widget? topContent;
  final bool showTools;
  final VoidCallback onToggleTools;
  final VoidCallback onVoice;
  final List<_ChatToolAction> toolActions;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final textTheme = theme.textTheme;
    return SafeArea(
      top: false,
      child: Container(
        key: const ValueKey('chat_composer_surface'),
        decoration: BoxDecoration(
          color: colors.surface,
          border: Border(
            top: BorderSide(color: colorScheme.outlineVariant, width: 0.5),
          ),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (topContent != null) topContent!,
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
              child: Row(
                children: [
                  _ComposerIconButton(
                    icon: Icons.mic,
                    onPressed: onVoice,
                    tooltip: '语音',
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Container(
                      height: 38,
                      decoration: BoxDecoration(
                        color: colors.surface,
                        borderRadius: BorderRadius.circular(10),
                      ),
                      alignment: Alignment.center,
                      child: TextField(
                        controller: controller,
                        maxLines: 1,
                        style: textTheme.bodyMedium?.copyWith(
                          color: colors.textPrimary,
                          fontSize: 15,
                        ),
                        decoration: InputDecoration(
                          isDense: true,
                          hintText: '发消息',
                          hintStyle: textTheme.bodyMedium?.copyWith(
                            color: colors.textSecondary,
                            fontSize: 15,
                          ),
                          border: InputBorder.none,
                          contentPadding:
                              const EdgeInsets.symmetric(horizontal: 12),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 6),
                  _ComposerIconButton(
                    icon: Icons.add,
                    iconSize: 26,
                    selected: showTools,
                    onPressed: onToggleTools,
                    tooltip: '更多工具',
                  ),
                  ListenableBuilder(
                    listenable: controller,
                    builder: (context, _) {
                      // parent 已用 busy key 重建；这里再听输入，保证打字时出现发送键。
                      final canSend =
                          controller.text.trim().isNotEmpty && !busy;
                      if (!canSend && !busy) return const SizedBox.shrink();
                      return Padding(
                        padding: const EdgeInsets.only(left: 6),
                        child: _SendPill(
                          canStop: busy,
                          onSend: onSend,
                          onStop: onStop,
                        ),
                      );
                    },
                  ),
                ],
              ),
            ),
            if (showTools && toolActions.isNotEmpty)
              _ChatToolCardPanel(actions: toolActions),
          ],
        ),
      ),
    );
  }
}

class _ComposerIconButton extends StatelessWidget {
  const _ComposerIconButton({
    required this.icon,
    required this.onPressed,
    required this.tooltip,
    this.iconSize = 22,
    this.selected = false,
  });

  final IconData icon;
  final VoidCallback? onPressed;
  final String tooltip;
  final double iconSize;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return SizedBox(
      width: 38,
      height: 38,
      child: IconButton(
        onPressed: onPressed,
        padding: EdgeInsets.zero,
        icon: Icon(icon, size: iconSize),
        color: selected ? colors.brand : colors.textPrimary,
        tooltip: tooltip,
      ),
    );
  }
}

class _ChatGitActionBar extends StatelessWidget {
  const _ChatGitActionBar({
    required this.branch,
    required this.branches,
    required this.running,
    required this.onSelectBranch,
    required this.onDiff,
    required this.onMerge,
    required this.onDiscard,
  });

  final String branch;
  final List<String> branches;
  final bool running;
  final VoidCallback? onSelectBranch;
  final VoidCallback onDiff;
  final VoidCallback onMerge;
  final VoidCallback onDiscard;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final selectable = onSelectBranch != null && branches.length > 1;
    final suffix = _shortGitBranchLabel(branch);
    return Padding(
      padding: const EdgeInsets.fromLTRB(10, 8, 10, 2),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          InkWell(
            borderRadius: BorderRadius.circular(8),
            onTap: selectable ? onSelectBranch : null,
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    Icons.call_merge,
                    size: 13,
                    color: colors.textSecondary,
                  ),
                  const SizedBox(width: 4),
                  Flexible(
                    child: Text(
                      selectable
                          ? '开发任务分支 · $suffix（点此切换）'
                          : '开发任务分支 · $suffix',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        color: colors.textSecondary,
                        fontSize: 11,
                        height: 1.27,
                        letterSpacing: 0,
                      ),
                    ),
                  ),
                  if (selectable)
                    Icon(
                      Icons.chevron_right,
                      size: 16,
                      color: colors.textSecondary,
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 6),
          Row(
            children: [
              _GitActionChip(
                label: '查看 diff',
                icon: Icons.difference,
                color: colors.textPrimary,
                onTap: running ? null : onDiff,
              ),
              const SizedBox(width: 8),
              _GitActionChip(
                label: '合并到主干',
                icon: Icons.call_merge,
                color: colors.brand,
                filled: true,
                onTap: running ? null : onMerge,
              ),
              const SizedBox(width: 8),
              _GitActionChip(
                label: '丢弃',
                icon: Icons.delete_outline,
                color: colors.danger,
                onTap: running ? null : onDiscard,
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _GitActionChip extends StatelessWidget {
  const _GitActionChip({
    required this.label,
    required this.icon,
    required this.color,
    required this.onTap,
    this.filled = false,
  });

  final String label;
  final IconData icon;
  final Color color;
  final VoidCallback? onTap;
  final bool filled;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final enabled = onTap != null;
    final effective = enabled ? color : color.withValues(alpha: 0.45);
    return InkWell(
      borderRadius: BorderRadius.circular(8),
      onTap: onTap,
      child: Container(
        height: 32,
        padding: const EdgeInsets.symmetric(horizontal: 10),
        decoration: BoxDecoration(
          color: filled
              ? color.withValues(alpha: enabled ? 0.12 : 0.06)
              : colors.surfaceHigh.withValues(alpha: enabled ? 0.5 : 0.3),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 15, color: effective),
            const SizedBox(width: 5),
            Text(
              label,
              style: TextStyle(
                color: effective,
                fontSize: 12,
                height: 1.33,
                fontWeight: filled ? FontWeight.w600 : FontWeight.w500,
                letterSpacing: 0,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _EmployeeConversationRef {
  const _EmployeeConversationRef({
    required this.modId,
    required this.employeeId,
  });

  final String modId;
  final String employeeId;
}

_EmployeeConversationRef? _parseEmployeeConversationRef(
    String? conversationId) {
  final raw = conversationId?.trim() ?? '';
  if (!raw.startsWith('employee:')) return null;
  final parts = raw.split(':');
  if (parts.length != 3) return null;
  final modId = parts[1].trim();
  final employeeId = parts[2].trim();
  if (modId.isEmpty || employeeId.isEmpty) return null;
  return _EmployeeConversationRef(modId: modId, employeeId: employeeId);
}

AiEmployeeProfile? _findEmployeeProfile(
  List<AiEmployeeProfile> employees,
  _EmployeeConversationRef ref,
) {
  for (final employee in employees) {
    if (employee.modId == ref.modId && employee.employeeId == ref.employeeId) {
      return employee;
    }
  }
  return null;
}

AiEmployeeProfile? _employeePlaceholderFromRef(_EmployeeConversationRef? ref) {
  if (ref == null) return null;
  return AiEmployeeProfile(
    modId: ref.modId,
    modName: ref.modId,
    modDescription: '',
    modVersion: '',
    modAuthor: '',
    industryName: '',
    employeeId: ref.employeeId,
    name: ref.employeeId,
    title: ref.employeeId,
    summary: '稍后刷新或从企业端同步数据',
    apiBasePath: '',
    phoneChannel: '',
    workflowPlaceholder: false,
    profileSource: 'conversation-ref',
    marketConnected: false,
    marketPkgId: '',
    marketVersion: '',
    marketAuthor: '',
    marketMaterialCategory: '',
    marketLicenseScope: '',
    marketSecurityLevel: '',
  );
}

String _shortGitBranchLabel(String branch) {
  final clean = branch.trim();
  final index = clean.lastIndexOf('/');
  if (index < 0 || index == clean.length - 1) return clean;
  return clean.substring(index + 1);
}

String _take(String value, int maxLength) {
  final text = value.trim();
  if (text.length <= maxLength) return text;
  return text.substring(0, maxLength);
}

class _ChatToolAction {
  const _ChatToolAction({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;
}

class _ChatToolCardPanel extends StatelessWidget {
  const _ChatToolCardPanel({required this.actions});

  final List<_ChatToolAction> actions;

  @override
  Widget build(BuildContext context) {
    const columns = 4;
    final rows = <List<_ChatToolAction>>[];
    for (var start = 0; start < actions.length; start += columns) {
      final end = (start + columns).clamp(0, actions.length);
      rows.add(actions.sublist(start, end));
    }

    return Padding(
      key: const ValueKey('chat_tool_card_panel'),
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 20),
      child: Column(
        children: [
          for (var rowIndex = 0; rowIndex < rows.length; rowIndex++) ...[
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (var index = 0; index < columns; index++) ...[
                  Expanded(
                    child: index < rows[rowIndex].length
                        ? _ChatToolCard(action: rows[rowIndex][index])
                        : const SizedBox(height: 92),
                  ),
                  if (index != columns - 1) const SizedBox(width: 12),
                ],
              ],
            ),
            if (rowIndex != rows.length - 1) const SizedBox(height: 18),
          ],
        ],
      ),
    );
  }
}

class _ChatToolCard extends StatelessWidget {
  const _ChatToolCard({required this.action});

  final _ChatToolAction action;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    return SizedBox(
      key: ValueKey('chat_tool_card_${action.title}'),
      height: 92,
      child: Material(
        color: Colors.transparent,
        borderRadius: BorderRadius.circular(8),
        child: InkWell(
          onTap: action.onTap,
          borderRadius: BorderRadius.circular(8),
          child: Padding(
            padding: const EdgeInsets.only(top: 1),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                Container(
                  key: ValueKey('chat_tool_icon_box_${action.title}'),
                  width: 62,
                  height: 62,
                  decoration: BoxDecoration(
                    color: colors.surfaceHigh.withValues(alpha: 0.62),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  alignment: Alignment.center,
                  child: Icon(
                    action.icon,
                    size: 27,
                    color: colors.textPrimary,
                    semanticLabel: action.title,
                  ),
                ),
                const SizedBox(height: 8),
                ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 82),
                  child: Text(
                    action.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    textAlign: TextAlign.center,
                    style: textTheme.labelMedium?.copyWith(
                      color: colors.textSecondary,
                      fontSize: 13,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _SendPill extends StatelessWidget {
  const _SendPill({
    required this.canStop,
    required this.onSend,
    required this.onStop,
  });

  final bool canStop;
  final VoidCallback onSend;
  final VoidCallback onStop;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    return Material(
      color:
          canStop ? Theme.of(context).colorScheme.errorContainer : colors.brand,
      borderRadius: BorderRadius.circular(8),
      child: InkWell(
        onTap: canStop ? onStop : onSend,
        borderRadius: BorderRadius.circular(8),
        child: SizedBox(
          height: 38,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 17),
            child: Center(
              child: Text(
                canStop ? '停止' : '发送',
                style: textTheme.labelLarge?.copyWith(
                  color: canStop ? colors.danger : Colors.white,
                  fontSize: 15,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
