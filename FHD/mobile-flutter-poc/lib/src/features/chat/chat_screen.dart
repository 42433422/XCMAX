import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../api/mobile_models.dart' show MobileMeData;
import '../../data/ai_employee_profile.dart';
import '../../data/assistant_assets.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../models/conversation.dart';
import '../../policy/android_error_policy.dart';
import '../../policy/avatar_policy.dart';
import '../../policy/pinned_ids.dart';
import '../../platform/android_record_audio_permission.dart';
import '../../platform/assistant_native_bridge.dart';
import '../../platform/external_url_launcher.dart';
import '../../theme/app_theme.dart';
import '../../theme/message_avatar_layout.dart';
import '../../widgets/app_avatar.dart';
import '../../widgets/super_employee_run_capsule.dart';
import '../../widgets/we_ui.dart';
import '../contacts/employee_profile_screen.dart';
import '../contacts/fixed_partner_profile_screen.dart';
import '../devtools/branch_detail_screen.dart';
import '../devtools/diff_viewer_screen.dart';
import '../devtools/execution_review_screen.dart';
import '../devtools/timeline_screen.dart';
import '../meeting/meeting_minutes_screen.dart';
import '../assistant/assistant_file_screen.dart';
import '../assistant/assistant_memory_screen.dart';
import '../assistant/assistant_visuals.dart';
import '../assistant/assistant_voice_screen.dart';
import '../tools/ocr_screen.dart';
import '../voice/voice_input_sheet.dart';

enum _AssistantMode { quick, online, deep, execute }

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
  final _composerFocusNode = FocusNode();
  var _assistantMode = _AssistantMode.quick;
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
  List<RelayRunSummary> _activeRuns = const [];
  Timer? _activeRunsTimer;
  AssistantEmployeeAvailability? _employeeAvailability;
  final _assistantNativeBridge = const AssistantNativeBridge();

  @override
  void initState() {
    super.initState();
    _messages = [...widget.initialMessages];
    _repository = widget.repository ?? MobileRepositoryScope.maybeRead(context);
    _employeeRef = _parseEmployeeConversationRef(widget.conversation.id);
    _loadRemoteMessages();
    _loadUserAvatar();
    _loadEmployeeProfile();
    _refreshActiveRuns();
    _refreshAssistantAvailability();
    _activeRunsTimer = Timer.periodic(
      const Duration(seconds: 4),
      (_) => _refreshActiveRuns(),
    );
  }

  @override
  void dispose() {
    _activeRunsTimer?.cancel();
    _composerFocusNode.dispose();
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final activeGitBranches = _activeGitBranches();
    final activeGitBranch = _currentGitBranch(activeGitBranches);
    final employeeProfile = _employeeProfile;
    final isAssistant = widget.conversation.id == PinnedIds.assistant;
    final topActions = <Widget>[
      IconButton(
        onPressed: isAssistant
            ? _openVoiceConversation
            : () => _showMessage('视频通话功能即将上线'),
        icon: Icon(
          isAssistant ? Icons.graphic_eq_rounded : Icons.videocam_outlined,
          size: 22,
        ),
        tooltip: isAssistant ? '语音对话' : '视频',
        color: colors.textPrimary,
      ),
      IconButton(
        onPressed: _openProfileOrTools,
        icon: const Icon(Icons.more_horiz_rounded, size: 23),
        tooltip: '更多',
        color: colors.textPrimary,
      ),
    ];
    return Scaffold(
      backgroundColor: isAssistant ? Colors.transparent : colors.page,
      body: AssistantBackdrop(
        enabled: isAssistant,
        child: SafeArea(
          bottom: false,
          child: Column(
            children: [
              if (isAssistant)
                AssistantTopBar(
                  title: _resolvedTitle,
                  onBack: () => Navigator.of(context).maybePop(),
                  actions: topActions,
                )
              else
                WeTopBar(
                  title: _resolvedTitle,
                  height: 48,
                  showBack: true,
                  onBack: () => Navigator.of(context).maybePop(),
                  actions: topActions,
                ),
              if (_loadingRemoteMessages)
                LinearProgressIndicator(
                  minHeight: 2,
                  color: colors.brand,
                  backgroundColor: colors.surfaceHigh,
                ),
              if (widget.conversation.type.superTool != null)
                SuperEmployeeRunCapsule(
                  runs: _activeRuns,
                  onTap: () => _openExecutionReview(allThreads: true),
                ),
              Expanded(
                child: _messages.isEmpty
                    ? isAssistant
                        ? _AssistantWelcome(
                            onQuickQuestion: () =>
                                _selectAssistantMode(_AssistantMode.quick),
                            onDeepAnalysis: () =>
                                _selectAssistantMode(_AssistantMode.deep),
                            onExecuteTask: () =>
                                _selectAssistantMode(_AssistantMode.execute),
                            onMeetingMinutes: _openMeetingMinutes,
                            onlineEmployees: _employeeAvailability
                                    ?.onlineConversationIds.length ??
                                0,
                          )
                        : const SizedBox.expand()
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
                            onReply: () => setState(() => _replyTo = message),
                            onDelete: () => _deleteMessageAt(originalIndex),
                            onResend:
                                message.status == ChatDeliveryStatus.failed
                                    ? _resendLastChat
                                    : null,
                            toolCalls: toolCalls,
                            onShowTimeline: toolCalls.isEmpty
                                ? null
                                : () => _openTimelineForMessage(message),
                            onSpeak: message.role == ChatRole.assistant &&
                                    message.status == ChatDeliveryStatus.sent
                                ? () => _speakMessage(message.body)
                                : null,
                          );
                        },
                        itemCount: _messages.length,
                      ),
              ),
              _Composer(
                controller: _controller,
                focusNode: _composerFocusNode,
                onSend: _send,
                onStop: _stopChat,
                busy: _sending,
                topContent: isAssistant
                    ? _AssistantModeBar(
                        selected: _assistantMode,
                        onSelected: _selectAssistantMode,
                      )
                    : _composerTopContent(
                        activeGitBranches,
                        activeGitBranch,
                      ),
                showTools: _showToolPanel,
                onToggleTools: () =>
                    setState(() => _showToolPanel = !_showToolPanel),
                onVoice: _startVoiceInput,
                toolActions: _toolActions(),
                assistantStyle: isAssistant,
              ),
            ],
          ),
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
      if (remoteMessages.isNotEmpty) {
        // Repository responses may intentionally be fixed-length. The chat
        // surface appends optimistic user/assistant bubbles on send, so always
        // keep its local transcript growable.
        setState(() => _messages = List<ChatMessage>.of(remoteMessages));
      }
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
          unawaited(_refreshActiveRuns());
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

  Future<void> _send([String? overrideText]) async {
    final text = (overrideText ?? _controller.text).trim();
    if (text.isEmpty || _sending) return;
    final isAssistant = widget.conversation.id == PinnedIds.assistant;
    final dispatchConversation =
        isAssistant && _assistantMode == _AssistantMode.execute
            ? await _resolveAssistantExecutionConversation(text)
            : null;
    if (!mounted) return;
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
        body: dispatchConversation == null
            ? _assistantMode == _AssistantMode.online
                ? '正在联网搜索并核对来源…'
                : ''
            : '正在交给 ${dispatchConversation.title}…',
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
      dispatchConversation: dispatchConversation,
    );
  }

  Future<void> _streamAssistantReply({
    required String assistantId,
    required String outgoing,
    required List<ChatMessage> recentMessages,
    ConversationItem? dispatchConversation,
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
      void onToken(String token) {
        if (!mounted) return;
        if (_stopRequested || _activeAssistantId != assistantId) return;
        setState(() => _appendMessageBody(assistantId, token));
      }

      void onStatus(RelayTaskProgress progress) {
        if (!mounted) return;
        if (_stopRequested || _activeAssistantId != assistantId) return;
        setState(() => _activeRelayProgress = progress);
        unawaited(_refreshActiveRuns());
      }

      bool isCancelled() => _stopRequested || _activeAssistantId != assistantId;

      late final String reply;
      var sources = const <ChatSource>[];
      if (widget.conversation.id == PinnedIds.assistant &&
          dispatchConversation == null) {
        if (_assistantMode == _AssistantMode.online) {
          final searched = await repository.searchAssistantMessage(
            body: outgoing,
            userId: _userId,
            recentMessages: recentMessages,
          );
          reply = searched.answer;
          sources = searched.sources;
          if (sources.isEmpty && searched.warning.isNotEmpty) {
            sources = [
              ChatSource(
                title: '联网搜索提示',
                url: '',
                snippet: searched.warning,
              ),
            ];
          }
        } else {
          reply = await repository.streamAssistantMessage(
            body: outgoing,
            deepAnalysis: _assistantMode == _AssistantMode.deep,
            userId: _userId,
            recentMessages: recentMessages,
            onToken: onToken,
            isCancelled: isCancelled,
          );
        }
      } else {
        reply = await repository.streamMessage(
          conversation: dispatchConversation ?? widget.conversation,
          body: outgoing,
          userId: _userId,
          recentMessages: recentMessages,
          onToken: onToken,
          onStatus: onStatus,
          isCancelled: isCancelled,
        );
      }
      if (dispatchConversation != null &&
          widget.conversation.id == PinnedIds.assistant) {
        await repository.cacheAssistantExchange(
          userMessage: outgoing,
          assistantMessage: reply,
        );
      }
      if (!mounted) return;
      if (_stopRequested || _activeAssistantId != assistantId) return;
      setState(() {
        _replaceMessage(
          assistantId,
          body: reply,
          status: ChatDeliveryStatus.sent,
          sources: sources,
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
      if (mounted && _activeAssistantId == assistantId) {
        setState(() {
          _sending = false;
          _activeAssistantId = null;
          _activeRelayProgress = null;
        });
      }
    }
  }

  void _selectAssistantMode(_AssistantMode mode) {
    setState(() {
      _assistantMode = mode;
      _showToolPanel = false;
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _composerFocusNode.requestFocus();
    });
  }

  ConversationItem _assistantExecutionConversation(String message) {
    final text = message.toLowerCase();
    if (text.contains('claude') ||
        text.contains('分析') ||
        text.contains('方案') ||
        text.contains('文档') ||
        text.contains('总结')) {
      return const ConversationItem(
        id: PinnedIds.claude,
        type: ConversationType.pinnedClaude,
        title: '超级员工-Claude',
        subtitle: '',
        timestampText: '',
      );
    }
    if (text.contains('cursor') ||
        text.contains('界面') ||
        text.contains('前端') ||
        text.contains('ui')) {
      return const ConversationItem(
        id: PinnedIds.cursor,
        type: ConversationType.pinnedCursor,
        title: '超级员工-Cursor',
        subtitle: '',
        timestampText: '',
      );
    }
    if (text.contains('trae') || text.contains('ide') || text.contains('补位')) {
      return const ConversationItem(
        id: PinnedIds.trae,
        type: ConversationType.pinnedTrae,
        title: '超级员工-Trae',
        subtitle: '',
        timestampText: '',
      );
    }
    return const ConversationItem(
      id: PinnedIds.codex,
      type: ConversationType.pinnedCodex,
      title: '超级员工-Codex',
      subtitle: '',
      timestampText: '',
    );
  }

  Future<ConversationItem> _resolveAssistantExecutionConversation(
    String message,
  ) async {
    final preferred = _assistantExecutionConversation(message);
    final lower = message.toLowerCase();
    final explicitlyNamed =
        const ['codex', 'claude', 'cursor', 'trae'].any(lower.contains);
    if (explicitlyNamed) return preferred;
    var availability = _employeeAvailability;
    if (availability == null) {
      try {
        availability = await _repository?.loadAssistantEmployeeAvailability();
        if (mounted && availability != null) {
          setState(() => _employeeAvailability = availability);
        }
      } catch (_) {
        return preferred;
      }
    }
    if (availability == null || !availability.hasAny) return preferred;
    if (availability.isOnline(preferred.id)) return preferred;
    for (final id in const [
      PinnedIds.trae,
      PinnedIds.cursor,
      PinnedIds.claude,
      PinnedIds.codex,
    ]) {
      if (availability.isOnline(id)) return _executionConversationForId(id);
    }
    return preferred;
  }

  ConversationItem _executionConversationForId(String id) => switch (id) {
        PinnedIds.claude => const ConversationItem(
            id: PinnedIds.claude,
            type: ConversationType.pinnedClaude,
            title: '超级员工-Claude',
            subtitle: '',
            timestampText: '',
          ),
        PinnedIds.cursor => const ConversationItem(
            id: PinnedIds.cursor,
            type: ConversationType.pinnedCursor,
            title: '超级员工-Cursor',
            subtitle: '',
            timestampText: '',
          ),
        PinnedIds.trae => const ConversationItem(
            id: PinnedIds.trae,
            type: ConversationType.pinnedTrae,
            title: '超级员工-Trae',
            subtitle: '',
            timestampText: '',
          ),
        _ => const ConversationItem(
            id: PinnedIds.codex,
            type: ConversationType.pinnedCodex,
            title: '超级员工-Codex',
            subtitle: '',
            timestampText: '',
          ),
      };

  Future<void> _openAssistantConversationManager() async {
    final repository = _repository;
    if (repository == null || _sending) return;
    setState(() => _showToolPanel = false);
    final threads = await repository.loadAssistantConversations();
    final activeId = await repository.activeSuperEmployeeThreadId(
      PinnedIds.assistant,
    );
    if (!mounted) return;
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.only(bottom: 16),
          children: [
            ListTile(
              key: const ValueKey('assistant_new_conversation'),
              leading: const Icon(Icons.add_comment_outlined),
              title: const Text('新建对话'),
              subtitle: const Text('保留历史，开始一段独立上下文'),
              onTap: () {
                Navigator.of(sheetContext).pop();
                _startNewAssistantConversation();
              },
            ),
            if (threads.isNotEmpty) const Divider(height: 1),
            for (final thread in threads)
              ListTile(
                leading: Icon(
                  thread.threadId == activeId ||
                          (thread.threadId == 'legacy' && activeId.isEmpty)
                      ? Icons.radio_button_checked
                      : Icons.chat_bubble_outline,
                ),
                title: Text(thread.title),
                subtitle: Text(
                  thread.status == 'active' ? '当前对话' : '历史对话',
                ),
                onTap: () {
                  Navigator.of(sheetContext).pop();
                  _switchAssistantConversation(thread.threadId);
                },
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _startNewAssistantConversation() async {
    final repository = _repository;
    if (repository == null || _sending) return;
    await repository.startNewAssistantConversation();
    if (!mounted) return;
    setState(() {
      _messages = [];
      _replyTo = null;
      _activeRelayProgress = null;
      _assistantMode = _AssistantMode.quick;
    });
    _controller.clear();
    _showMessage('已新建一段独立的小C对话');
  }

  Future<void> _switchAssistantConversation(String threadId) async {
    final repository = _repository;
    if (repository == null || _sending) return;
    final messages = await repository.switchAssistantConversation(threadId);
    if (!mounted) return;
    setState(() {
      _messages = List<ChatMessage>.of(messages);
      _replyTo = null;
      _activeRelayProgress = null;
      _assistantMode = _AssistantMode.quick;
    });
    _controller.clear();
  }

  Future<void> _openMeetingMinutes() async {
    final repository = _repository;
    if (repository == null) {
      _showMessage('当前离线同步不可用，无法整理会议纪要');
      return;
    }
    setState(() => _showToolPanel = false);
    final result = await Navigator.of(context).push<MeetingMinutesResult>(
      MaterialPageRoute(
        builder: (_) => MeetingMinutesScreen(repository: repository),
      ),
    );
    if (!mounted || result == null) return;
    final now = DateTime.now().microsecondsSinceEpoch;
    final userText = '生成会议纪要：${result.title}';
    const assistantText = '会议纪要 Word 已生成，并已打开系统保存/分享面板。';
    setState(() {
      _messages.addAll([
        ChatMessage(
          id: 'meeting-user-$now',
          conversationId: widget.conversation.id,
          role: ChatRole.user,
          body: userText,
          timeText: '刚刚',
        ),
        ChatMessage(
          id: 'meeting-assistant-$now',
          conversationId: widget.conversation.id,
          role: ChatRole.assistant,
          body: '$assistantText\n${result.summary}',
          timeText: '刚刚',
          hasEmployeeProfile: true,
        ),
      ]);
    });
    await repository.cacheAssistantExchange(
      userMessage: userText,
      assistantMessage: '$assistantText\n${result.summary}',
    );
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
    try {
      final acknowledged = await repository.cancelRelayTask(taskId);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            acknowledged ? '电脑已确认停止任务' : '只能停止等待，电脑任务可能继续',
          ),
        ),
      );
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('只能停止等待，电脑任务可能继续')),
      );
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

  Future<void> _refreshAssistantAvailability() async {
    if (widget.conversation.id != PinnedIds.assistant) return;
    final repository = _repository;
    if (repository == null) return;
    try {
      final availability = await repository.loadAssistantEmployeeAvailability();
      if (mounted) setState(() => _employeeAvailability = availability);
    } catch (_) {
      // Conversation and search remain usable without a paired execution host.
    }
  }

  Future<void> _openVoiceConversation() async {
    final repository = _repository;
    if (repository == null) {
      _showMessage('当前没有可用的服务器连接');
      return;
    }
    setState(() => _showToolPanel = false);
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => AssistantVoiceScreen(repository: repository),
      ),
    );
    if (mounted) await _loadRemoteMessages();
  }

  Future<void> _openAssistantMemory() async {
    final repository = _repository;
    if (repository == null) {
      _showMessage('当前没有可用的记忆服务');
      return;
    }
    setState(() => _showToolPanel = false);
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => AssistantMemoryScreen(repository: repository),
      ),
    );
  }

  Future<void> _openAssistantFiles() async {
    final repository = _repository;
    if (repository == null) {
      _showMessage('当前没有可用的文件服务');
      return;
    }
    setState(() => _showToolPanel = false);
    final result = await Navigator.of(context).push<AssistantFileAnalysis>(
      MaterialPageRoute(
        builder: (_) => AssistantFileScreen(repository: repository),
      ),
    );
    if (result == null || !mounted) return;
    await _recordAssistantArtifact(
      userText: '分析文件：${result.filename}',
      assistantText: result.summary,
    );
  }

  Future<void> _openAssistantOcr() async {
    final repository = _repository;
    if (repository == null) return;
    setState(() => _showToolPanel = false);
    final text = await Navigator.of(context).push<String>(
      MaterialPageRoute(builder: (_) => OcrScreen(repository: repository)),
    );
    if (text == null || text.trim().isEmpty || !mounted) return;
    await _recordAssistantArtifact(
      userText: '识别图片文字',
      assistantText: text.trim(),
    );
  }

  Future<void> _recordAssistantArtifact({
    required String userText,
    required String assistantText,
  }) async {
    final now = DateTime.now().microsecondsSinceEpoch;
    setState(() {
      _messages.addAll([
        ChatMessage(
          id: 'artifact-user-$now',
          conversationId: widget.conversation.id,
          role: ChatRole.user,
          body: userText,
          timeText: '刚刚',
        ),
        ChatMessage(
          id: 'artifact-assistant-$now',
          conversationId: widget.conversation.id,
          role: ChatRole.assistant,
          body: assistantText,
          timeText: '刚刚',
          hasEmployeeProfile: true,
        ),
      ]);
    });
    await _repository?.cacheAssistantExchange(
      userMessage: userText,
      assistantMessage: assistantText,
    );
  }

  Future<void> _speakMessage(String text) async {
    final clean = text.trim();
    if (clean.isEmpty) return;
    try {
      await _assistantNativeBridge.stopSpeech();
      final audio = await _repository?.synthesizeAssistantSpeech(clean);
      if (audio != null && audio.isNotEmpty) {
        await _assistantNativeBridge.playBase64Audio(audio);
      } else {
        await _assistantNativeBridge.speakText(clean);
      }
    } catch (_) {
      try {
        await _assistantNativeBridge.speakText(clean);
      } catch (error) {
        if (mounted) _showMessage('朗读失败：$error');
      }
    }
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
    if (widget.conversation.id == PinnedIds.assistant) {
      _assistantMode = _AssistantMode.execute;
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
    if (widget.conversation.id == PinnedIds.assistant) {
      _assistantMode = _AssistantMode.execute;
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
      sources: current.sources,
    );
  }

  void _replaceMessage(
    String messageId, {
    required String body,
    ChatDeliveryStatus? status,
    List<ChatSource>? sources,
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
      sources: sources ?? current.sources,
    );
  }

  void _removeMessage(String messageId) {
    _messages = [..._messages]
      ..removeWhere((message) => message.id == messageId);
  }

  Future<void> _refreshActiveRuns() async {
    final repository = _repository;
    if (repository == null || widget.conversation.type.superTool == null) {
      return;
    }
    try {
      final runs = await repository.loadRelayRuns(activeOnly: true, limit: 20);
      if (!mounted) return;
      setState(() => _activeRuns = runs);
    } catch (_) {
      // Keep the capsule visible with idle states while offline.
    }
  }

  Future<void> _openConversationManager() async {
    final repository = _repository;
    if (repository == null) return;
    setState(() => _showToolPanel = false);
    List<SuperEmployeeThread> threads = const [];
    try {
      threads = await repository.loadSuperEmployeeThreads(widget.conversation);
    } catch (_) {
      // The new-conversation action remains available even if history refresh fails.
    }
    if (!mounted) return;
    final activeId =
        await repository.activeSuperEmployeeThreadId(widget.conversation.id);
    if (!mounted) return;
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.only(bottom: 16),
          children: [
            ListTile(
              key: const ValueKey('super_employee_new_conversation'),
              leading: const Icon(Icons.add_comment_outlined),
              title: const Text('新建对话'),
              subtitle: const Text('创建独立 CLI 会话与工作分支'),
              onTap: () {
                Navigator.of(sheetContext).pop();
                _startNewSuperEmployeeConversation();
              },
            ),
            if (threads.isNotEmpty || activeId.startsWith('local-'))
              const Divider(height: 1),
            if (activeId.startsWith('local-') &&
                !threads.any((thread) => thread.threadId == activeId))
              const ListTile(
                leading: Icon(Icons.radio_button_checked),
                title: Text('当前局域网对话'),
                subtitle: Text('本机持久 CLI 会话'),
              ),
            for (final thread in threads)
              ListTile(
                leading: Icon(
                  thread.threadId == activeId
                      ? Icons.radio_button_checked
                      : Icons.chat_bubble_outline,
                ),
                title: Text(thread.title),
                subtitle: Text(
                  '${thread.sourceLabel} · ${relayRunStatusLabel(thread.status)}'
                  '${thread.branch.isEmpty ? '' : ' · ${thread.branch}'}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                trailing: PopupMenuButton<String>(
                  tooltip: '对话操作',
                  onSelected: (value) {
                    if (value != 'archive') return;
                    Navigator.of(sheetContext).pop();
                    unawaited(_archiveSuperEmployeeConversation(thread));
                  },
                  itemBuilder: (_) => const [
                    PopupMenuItem(
                      value: 'archive',
                      child: Row(
                        children: [
                          Icon(Icons.archive_outlined, size: 19),
                          SizedBox(width: 10),
                          Text('归档对话'),
                        ],
                      ),
                    ),
                  ],
                ),
                onTap: () {
                  Navigator.of(sheetContext).pop();
                  _switchSuperEmployeeConversation(thread.threadId);
                },
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _startNewSuperEmployeeConversation() async {
    final repository = _repository;
    if (repository == null || _sending) return;
    try {
      await repository.startNewSuperEmployeeConversation(widget.conversation);
      if (!mounted) return;
      setState(() {
        _messages = [];
        _replyTo = null;
        _activeRelayProgress = null;
      });
      _controller.clear();
      _showMessage('已创建新的 ${widget.conversation.type.superTool} 对话');
      await _refreshActiveRuns();
    } catch (error) {
      if (mounted) _showMessage(error.toString());
    }
  }

  Future<void> _switchSuperEmployeeConversation(String threadId) async {
    final repository = _repository;
    if (repository == null || _sending) return;
    await repository.switchSuperEmployeeThread(
        widget.conversation.id, threadId);
    final messages = await repository
        .loadActiveSuperEmployeeMessages(widget.conversation.id);
    if (!mounted) return;
    setState(() {
      _messages = List<ChatMessage>.of(messages);
      _replyTo = null;
      _activeRelayProgress = null;
      _resumeInflightStarted = false;
    });
    await _resumeInflightRelayIfNeeded();
  }

  Future<void> _archiveSuperEmployeeConversation(
    SuperEmployeeThread thread,
  ) async {
    final repository = _repository;
    if (repository == null || _sending) return;
    try {
      final activeId = await repository.activeSuperEmployeeThreadId(
        widget.conversation.id,
      );
      await repository.archiveSuperEmployeeThread(
        widget.conversation.id,
        thread.threadId,
      );
      if (!mounted) return;
      if (activeId == thread.threadId) {
        setState(() {
          _messages = [];
          _replyTo = null;
          _activeRelayProgress = null;
          _resumeInflightStarted = false;
        });
      }
      _showMessage('已归档「${thread.title}」');
    } catch (error) {
      if (mounted) _showMessage('归档失败：$error');
    }
  }

  Future<void> _openExecutionReview({bool allThreads = false}) async {
    final repository = _repository;
    if (repository == null) return;
    setState(() => _showToolPanel = false);
    final threadId = allThreads
        ? ''
        : await repository.activeSuperEmployeeThreadId(widget.conversation.id);
    if (!mounted) return;
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ExecutionReviewScreen(
          repository: repository,
          threadId: threadId,
          title: allThreads ? '四员工运行任务' : '$_resolvedTitle · 执行回顾',
        ),
      ),
    );
    await _refreshActiveRuns();
  }

  List<_ChatToolAction> _toolActions() {
    final isSuperEmployee = widget.conversation.type.superTool != null;
    final activeGitBranches = _activeGitBranches();
    if (isSuperEmployee && activeGitBranches.isNotEmpty) {
      final branch =
          _currentGitBranch(activeGitBranches) ?? activeGitBranches.last;
      return [
        _ChatToolAction(
          icon: Icons.add_comment_outlined,
          title: '新建对话',
          subtitle: '新建或切换 CLI 会话',
          onTap: _openConversationManager,
        ),
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
          subtitle: '查看任务、测试与分支证据',
          onTap: _openExecutionReview,
        ),
        ..._sharedToolActions(),
      ];
    }
    if (isSuperEmployee) {
      return [
        _ChatToolAction(
          icon: Icons.add_comment_outlined,
          title: '新建对话',
          subtitle: '新建或切换 CLI 会话',
          onTap: _openConversationManager,
        ),
        _ChatToolAction(
          icon: Icons.timeline,
          title: '执行回顾',
          subtitle: '查看任务、测试与分支证据',
          onTap: _openExecutionReview,
        ),
        ..._sharedToolActions(),
      ];
    }
    if (widget.conversation.id == PinnedIds.assistant) {
      return [
        _ChatToolAction(
          icon: Icons.add_comment_outlined,
          title: '新建对话',
          subtitle: '保留历史并开始新上下文',
          onTap: _openAssistantConversationManager,
        ),
        _ChatToolAction(
          icon: Icons.public,
          title: '联网搜索',
          subtitle: '搜索网页并附来源',
          onTap: () => _selectAssistantMode(_AssistantMode.online),
        ),
        _ChatToolAction(
          icon: Icons.folder_open_outlined,
          title: '文件分析',
          subtitle: 'PDF、Word、Excel、PPT',
          onTap: _openAssistantFiles,
        ),
        _ChatToolAction(
          icon: Icons.record_voice_over_outlined,
          title: '会议纪要',
          subtitle: '录音转写并生成 Word',
          onTap: _openMeetingMinutes,
        ),
        _ChatToolAction(
          icon: Icons.qr_code_scanner,
          title: 'OCR 识别',
          subtitle: '拍照提取文字',
          onTap: _openAssistantOcr,
        ),
        _ChatToolAction(
          icon: Icons.headset_mic_outlined,
          title: '语音对话',
          subtitle: '自然朗读，随时打断',
          onTap: _openVoiceConversation,
        ),
        _ChatToolAction(
          icon: Icons.psychology_outlined,
          title: '长期记忆',
          subtitle: '查看、修改或忘记',
          onTap: _openAssistantMemory,
        ),
        ..._sharedToolActions(),
      ];
    }
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
      ..._sharedToolActions(),
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
    ];
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
    this.toolCalls = const <Map<String, Object?>>[],
    this.onShowTimeline,
    this.onSpeak,
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
  final List<Map<String, Object?>> toolCalls;
  final VoidCallback? onShowTimeline;
  final VoidCallback? onSpeak;

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
    final isSmallCThread = conversation.id == PinnedIds.assistant;
    final isSmallCAssistant = isSmallCThread && !isUser;
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
    final bubbleColor = isUser
        ? colors.chatUserBubble
        : colors.surface.withValues(alpha: isSmallCAssistant ? 0.90 : 1);
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
                    constraints: BoxConstraints(
                      maxWidth: isSmallCThread
                          ? isUser
                              ? MediaQuery.sizeOf(context).width * 0.76
                              : MediaQuery.sizeOf(context).width - 88
                          : 260,
                    ),
                    child: Material(
                      key: ValueKey('chat_bubble_${message.id}'),
                      color: bubbleColor,
                      elevation: isSmallCThread ? 0 : 1,
                      shadowColor: Colors.black.withValues(alpha: 0.08),
                      shape: isSmallCThread
                          ? RoundedRectangleBorder(
                              borderRadius: isUser
                                  ? const BorderRadius.only(
                                      topLeft: Radius.circular(20),
                                      topRight: Radius.circular(7),
                                      bottomLeft: Radius.circular(20),
                                      bottomRight: Radius.circular(20),
                                    )
                                  : BorderRadius.circular(22),
                              side: BorderSide(
                                color: isUser
                                    ? Colors.transparent
                                    : Colors.white.withValues(alpha: 0.82),
                                width: 0.8,
                              ),
                            )
                          : null,
                      borderRadius: isSmallCThread
                          ? null
                          : BorderRadius.only(
                              topLeft: Radius.circular(isUser ? 12 : 4),
                              topRight: Radius.circular(isUser ? 4 : 12),
                              bottomLeft: const Radius.circular(12),
                              bottomRight: const Radius.circular(12),
                            ),
                      child: Padding(
                        padding: EdgeInsets.symmetric(
                          horizontal: isSmallCThread
                              ? isUser
                                  ? 14
                                  : 16
                              : 12,
                          vertical: isSmallCThread
                              ? isUser
                                  ? 11
                                  : 14
                              : 10,
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
                              _RelayProgressCard(progress: relayProgress!),
                              const SizedBox(height: 8),
                            ],
                            if (isSmallCAssistant)
                              _AssistantMessageBody(
                                text: visibleBody,
                                color: textColor,
                              )
                            else
                              Text(
                                visibleBody,
                                style: TextStyle(
                                  color: textColor,
                                  fontSize: 15,
                                  height: 1.4,
                                  letterSpacing: 0,
                                ),
                              ),
                            if (message.sources.isNotEmpty) ...[
                              const SizedBox(height: 10),
                              _SourceCards(sources: message.sources),
                            ],
                            if (toolCalls.isNotEmpty &&
                                onShowTimeline != null) ...[
                              const SizedBox(height: 10),
                              _MiniTimeline(
                                calls: toolCalls,
                                onTap: onShowTimeline!,
                              ),
                            ],
                            if (onSpeak != null) ...[
                              const SizedBox(height: 8),
                              InkWell(
                                onTap: onSpeak,
                                borderRadius: BorderRadius.circular(8),
                                child: Padding(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 2,
                                    vertical: 4,
                                  ),
                                  child: Row(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Icon(
                                        Icons.volume_up_outlined,
                                        size: 16,
                                        color: colors.brand,
                                      ),
                                      const SizedBox(width: 4),
                                      Text(
                                        '朗读',
                                        style: TextStyle(
                                          color: colors.brand,
                                          fontSize: 12,
                                          fontWeight: FontWeight.w600,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
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

class _AssistantMessageBody extends StatelessWidget {
  const _AssistantMessageBody({required this.text, required this.color});

  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final clean = text.trim();
    final baseStyle = TextStyle(
      color: color,
      fontSize: 15,
      height: 1.58,
      letterSpacing: -0.05,
    );
    if (!clean.contains('\n') && !clean.contains('**')) {
      return Text(clean, style: baseStyle);
    }
    final lines = clean.split('\n');
    return SelectionArea(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (var i = 0; i < lines.length; i++)
            _assistantRichLine(
              lines[i],
              baseStyle,
              first: i == 0,
            ),
        ],
      ),
    );
  }
}

Widget _assistantRichLine(
  String raw,
  TextStyle baseStyle, {
  required bool first,
}) {
  final line = raw.trim();
  if (line.isEmpty) return const SizedBox(height: 8);
  final numbered = RegExp(r'^(\d+)[.、]\s*(.*)$').firstMatch(line);
  if (numbered != null) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 7),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 22,
            height: 22,
            margin: const EdgeInsets.only(top: 1),
            decoration: BoxDecoration(
              color: assistantIndigo.withValues(alpha: 0.10),
              shape: BoxShape.circle,
            ),
            alignment: Alignment.center,
            child: Text(
              numbered.group(1)!,
              style: const TextStyle(
                color: assistantIndigo,
                fontSize: 11,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          const SizedBox(width: 9),
          Expanded(
            child: RichText(
              text: TextSpan(
                style: baseStyle,
                children: _assistantInlineSpans(numbered.group(2)!, baseStyle),
              ),
            ),
          ),
        ],
      ),
    );
  }
  final bullet = RegExp(r'^[-•]\s*(.*)$').firstMatch(line);
  if (bullet != null) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Padding(
            padding: EdgeInsets.only(top: 9, left: 3, right: 10),
            child: CircleAvatar(radius: 2.5, backgroundColor: assistantIndigo),
          ),
          Expanded(
            child: RichText(
              text: TextSpan(
                style: baseStyle,
                children: _assistantInlineSpans(bullet.group(1)!, baseStyle),
              ),
            ),
          ),
        ],
      ),
    );
  }
  final isHeading = first ||
      line == '关键依据：' ||
      line == '关键依据' ||
      line == '来源' ||
      (line.length < 18 && line.endsWith('：'));
  return Padding(
    padding: EdgeInsets.only(bottom: isHeading ? 8 : 5),
    child: RichText(
      text: TextSpan(
        style: baseStyle.copyWith(
          fontWeight: isHeading ? FontWeight.w700 : FontWeight.w400,
          fontSize: isHeading ? 15.5 : 15,
          color: isHeading ? baseStyle.color : baseStyle.color,
        ),
        children: _assistantInlineSpans(line, baseStyle),
      ),
    ),
  );
}

List<InlineSpan> _assistantInlineSpans(String text, TextStyle baseStyle) {
  final matches = RegExp(r'\*\*(.+?)\*\*').allMatches(text).toList();
  if (matches.isEmpty) return [TextSpan(text: text)];
  final spans = <InlineSpan>[];
  var cursor = 0;
  for (final match in matches) {
    if (match.start > cursor) {
      spans.add(TextSpan(text: text.substring(cursor, match.start)));
    }
    spans.add(
      TextSpan(
        text: match.group(1),
        style: baseStyle.copyWith(fontWeight: FontWeight.w700),
      ),
    );
    cursor = match.end;
  }
  if (cursor < text.length) spans.add(TextSpan(text: text.substring(cursor)));
  return spans;
}

class _SourceCards extends StatelessWidget {
  const _SourceCards({required this.sources});

  final List<ChatSource> sources;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final visible = sources.take(5).toList(growable: false);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            const Icon(Icons.travel_explore_rounded,
                size: 15, color: assistantIndigo),
            const SizedBox(width: 6),
            Text(
              '来源',
              style: TextStyle(
                color: colors.textPrimary,
                fontSize: 12,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(width: 5),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: assistantIndigo.withValues(alpha: 0.09),
                borderRadius: BorderRadius.circular(999),
              ),
              child: Text(
                '${visible.length}',
                style: const TextStyle(
                  color: assistantIndigo,
                  fontSize: 9.5,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            const Spacer(),
            Text(
              '点击查看原文',
              style: TextStyle(color: colors.textSecondary, fontSize: 10.5),
            ),
          ],
        ),
        const SizedBox(height: 9),
        SizedBox(
          height: 116,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            clipBehavior: Clip.none,
            itemCount: visible.length,
            separatorBuilder: (_, __) => const SizedBox(width: 8),
            itemBuilder: (context, index) {
              final source = visible[index];
              final host = Uri.tryParse(source.url)
                      ?.host
                      .replaceFirst(RegExp(r'^www\.'), '') ??
                  '';
              return SizedBox(
                width: 218,
                child: Material(
                  color: colors.surfaceHigh.withValues(alpha: 0.48),
                  borderRadius: BorderRadius.circular(16),
                  child: InkWell(
                    onTap: source.url.isEmpty
                        ? null
                        : () {
                            final uri = Uri.tryParse(source.url);
                            if (uri != null) launchExternalUrl(uri);
                          },
                    borderRadius: BorderRadius.circular(16),
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(12, 11, 10, 10),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Container(
                                width: 22,
                                height: 22,
                                decoration: BoxDecoration(
                                  color:
                                      assistantIndigo.withValues(alpha: 0.11),
                                  borderRadius: BorderRadius.circular(7),
                                ),
                                alignment: Alignment.center,
                                child: Text(
                                  '${index + 1}',
                                  style: const TextStyle(
                                    color: assistantIndigo,
                                    fontSize: 10,
                                    fontWeight: FontWeight.w800,
                                  ),
                                ),
                              ),
                              const Spacer(),
                              Icon(Icons.north_east_rounded,
                                  size: 15, color: colors.textSecondary),
                            ],
                          ),
                          const SizedBox(height: 7),
                          Text(
                            source.title,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              color: colors.textPrimary,
                              fontSize: 12,
                              height: 1.32,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          const Spacer(),
                          Text(
                            host.isEmpty ? '网页来源' : host,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              color: colors.textSecondary,
                              fontSize: 10,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              );
            },
          ),
        ),
      ],
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

/// 长任务（relay dev-loop）内嵌进度卡：只展示步骤与进度。
class _RelayProgressCard extends StatelessWidget {
  const _RelayProgressCard({required this.progress});

  final RelayTaskProgress progress;

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
                child: progress.status == 'completed'
                    ? Icon(Icons.check_circle, size: 14, color: colors.success)
                    : SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          valueColor: AlwaysStoppedAnimation(colors.brand),
                        ),
                      ),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  '${progress.sourceLabel} · ${_titleForStatus(progress.status)}',
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
    if (progress.source == 'lan') {
      return const ['连接局域网', '电脑执行', '保存结果'];
    }
    return const ['创建任务', '排队等待', '电脑执行', '回写结果'];
  }

  int _activeIndexForStatus(String status) {
    if (progress.source == 'lan') {
      switch (status) {
        case 'queued':
          return 0;
        case 'running':
        case 'assigned':
          return 1;
        case 'completed':
          return 3;
        case 'failed':
        case 'blocked':
        case 'cancelled':
          return -1;
        default:
          return 0;
      }
    }
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
            fontWeight:
                state == _StepState.active ? FontWeight.w600 : FontWeight.w400,
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

class _AssistantWelcome extends StatelessWidget {
  const _AssistantWelcome({
    required this.onQuickQuestion,
    required this.onDeepAnalysis,
    required this.onExecuteTask,
    required this.onMeetingMinutes,
    required this.onlineEmployees,
  });

  final VoidCallback onQuickQuestion;
  final VoidCallback onDeepAnalysis;
  final VoidCallback onExecuteTask;
  final VoidCallback onMeetingMinutes;
  final int onlineEmployees;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final hour = DateTime.now().hour;
    final greeting = hour < 6
        ? '夜深了'
        : hour < 12
            ? '早上好'
            : hour < 18
                ? '下午好'
                : '晚上好';
    final actions = [
      _AssistantWelcomeAction(
        key: const ValueKey('assistant_welcome_quick'),
        icon: Icons.auto_awesome_rounded,
        title: '快速问答',
        subtitle: '一句话获得清晰答案',
        color: assistantIndigo,
        onTap: onQuickQuestion,
      ),
      _AssistantWelcomeAction(
        key: const ValueKey('assistant_welcome_deep'),
        icon: Icons.hub_outlined,
        title: '深度分析',
        subtitle: '拆解依据、风险与选择',
        color: assistantBlue,
        onTap: onDeepAnalysis,
      ),
      _AssistantWelcomeAction(
        key: const ValueKey('assistant_welcome_execute'),
        icon: Icons.near_me_rounded,
        title: '安排任务',
        subtitle: '选择在线员工直接执行',
        color: assistantMint,
        onTap: onExecuteTask,
      ),
      _AssistantWelcomeAction(
        key: const ValueKey('assistant_welcome_meeting'),
        icon: Icons.mic_none_rounded,
        title: '会议纪要',
        subtitle: '录音整理并生成 Word',
        color: assistantRose,
        onTap: onMeetingMinutes,
      ),
    ];
    return ListView(
      padding: const EdgeInsets.fromLTRB(18, 10, 18, 24),
      children: [
        Container(
          height: 232,
          padding: const EdgeInsets.fromLTRB(22, 18, 22, 20),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(30),
            gradient: const LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: [Color(0xFF5253D8), Color(0xFF6C79EA), Color(0xFF78A5F6)],
              stops: [0, 0.55, 1],
            ),
            boxShadow: [
              BoxShadow(
                color: assistantIndigo.withValues(alpha: 0.25),
                blurRadius: 34,
                offset: const Offset(0, 16),
              ),
            ],
          ),
          child: Stack(
            children: [
              Positioned(
                right: -42,
                top: -54,
                child: Container(
                  width: 170,
                  height: 170,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: Colors.white.withValues(alpha: 0.08),
                  ),
                ),
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(
                        'XCAGI  ·  PERSONAL ASSISTANT',
                        style: TextStyle(
                          color: Colors.white.withValues(alpha: 0.70),
                          fontSize: 10,
                          fontWeight: FontWeight.w700,
                          letterSpacing: 0.9,
                        ),
                      ),
                      const Spacer(),
                      Container(
                        width: 8,
                        height: 8,
                        decoration: const BoxDecoration(
                          color: Color(0xFF7EF2C7),
                          shape: BoxShape.circle,
                        ),
                      ),
                    ],
                  ),
                  const Spacer(),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.center,
                    children: [
                      Container(
                        padding: const EdgeInsets.all(3),
                        decoration: BoxDecoration(
                          color: Colors.white.withValues(alpha: 0.20),
                          borderRadius: BorderRadius.circular(22),
                        ),
                        child: AppAvatar(
                          fallback: AppAvatarFallback.assistant,
                          size: 62,
                          borderRadius: BorderRadius.circular(19),
                          contentDescription: '小C助理',
                        ),
                      ),
                      const SizedBox(width: 16),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '$greeting，我是小C',
                              style: const TextStyle(
                                color: Colors.white,
                                fontSize: 25,
                                fontWeight: FontWeight.w800,
                                letterSpacing: -0.7,
                              ),
                            ),
                            const SizedBox(height: 7),
                            Text(
                              '回答、分析、搜索，也能把任务交给超级员工。',
                              style: TextStyle(
                                color: Colors.white.withValues(alpha: 0.76),
                                fontSize: 13,
                                height: 1.4,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  const Spacer(),
                  Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 11, vertical: 7),
                    decoration: BoxDecoration(
                      color: Colors.white.withValues(alpha: 0.13),
                      borderRadius: BorderRadius.circular(999),
                      border: Border.all(
                          color: Colors.white.withValues(alpha: 0.13)),
                    ),
                    child: Text(
                      onlineEmployees > 0
                          ? '$onlineEmployees 位执行员工在线 · 随时可派工'
                          : '对话与联网搜索已就绪',
                      style: TextStyle(
                        color: Colors.white.withValues(alpha: 0.88),
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 26),
        const AssistantSectionLabel('从哪里开始'),
        const SizedBox(height: 12),
        SizedBox(
          height: 128,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            clipBehavior: Clip.none,
            itemCount: actions.length,
            separatorBuilder: (_, __) => const SizedBox(width: 11),
            itemBuilder: (_, index) => actions[index],
          ),
        ),
        const SizedBox(height: 20),
        Container(
          padding: const EdgeInsets.fromLTRB(15, 13, 15, 13),
          decoration: assistantSurfaceDecoration(
            context,
            radius: 18,
            elevated: false,
            color: colors.surface.withValues(alpha: 0.72),
          ),
          child: Row(
            children: [
              const AssistantIconTile(
                icon: Icons.lightbulb_outline_rounded,
                color: assistantAmber,
                size: 38,
                iconSize: 19,
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  '试试说「分析这个方案的风险」或「安排 Codex 修复登录问题」',
                  style: TextStyle(
                    color: colors.textSecondary,
                    fontSize: 12.5,
                    height: 1.45,
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _AssistantWelcomeAction extends StatelessWidget {
  const _AssistantWelcomeAction({
    super.key,
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.color,
    required this.onTap,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final Color color;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Material(
      color: Colors.transparent,
      borderRadius: BorderRadius.circular(20),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(20),
        child: Container(
          width: 158,
          padding: const EdgeInsets.all(14),
          decoration: assistantSurfaceDecoration(context, radius: 20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              AssistantIconTile(
                  icon: icon, color: color, size: 40, iconSize: 20),
              const Spacer(),
              Text(
                title,
                style: TextStyle(
                  color: colors.textPrimary,
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                subtitle,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  color: colors.textSecondary,
                  fontSize: 11,
                  height: 1.35,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _AssistantModeBar extends StatelessWidget {
  const _AssistantModeBar({
    required this.selected,
    required this.onSelected,
  });

  final _AssistantMode selected;
  final ValueChanged<_AssistantMode> onSelected;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    const labels = {
      _AssistantMode.quick: ('快速', Icons.auto_awesome_rounded),
      _AssistantMode.online: ('联网', Icons.public_rounded),
      _AssistantMode.deep: ('深度', Icons.hub_outlined),
      _AssistantMode.execute: ('执行', Icons.near_me_rounded),
    };
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 9, 12, 2),
      child: Container(
        padding: const EdgeInsets.all(4),
        decoration: assistantSurfaceDecoration(
          context,
          radius: 18,
          elevated: false,
          color: colors.surface.withValues(alpha: 0.78),
        ),
        child: Row(
          children: [
            for (final mode in _AssistantMode.values)
              Expanded(
                child: InkWell(
                  key: ValueKey('assistant_mode_${mode.name}'),
                  onTap: () => onSelected(mode),
                  borderRadius: BorderRadius.circular(14),
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 220),
                    curve: Curves.easeOutCubic,
                    padding: const EdgeInsets.symmetric(vertical: 9),
                    decoration: BoxDecoration(
                      gradient: selected == mode
                          ? const LinearGradient(
                              colors: [assistantIndigo, assistantBlue],
                            )
                          : null,
                      borderRadius: BorderRadius.circular(14),
                      boxShadow: selected == mode
                          ? [
                              BoxShadow(
                                color: assistantIndigo.withValues(alpha: 0.22),
                                blurRadius: 14,
                                offset: const Offset(0, 5),
                              ),
                            ]
                          : null,
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(
                          labels[mode]!.$2,
                          size: 15,
                          color: selected == mode
                              ? Colors.white
                              : colors.textSecondary,
                        ),
                        const SizedBox(width: 4),
                        Text(
                          labels[mode]!.$1,
                          style: TextStyle(
                            color: selected == mode
                                ? Colors.white
                                : colors.textSecondary,
                            fontSize: 12,
                            fontWeight: selected == mode
                                ? FontWeight.w600
                                : FontWeight.w400,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _Composer extends StatelessWidget {
  const _Composer({
    required this.controller,
    required this.focusNode,
    required this.onSend,
    required this.onStop,
    required this.busy,
    this.topContent,
    required this.showTools,
    required this.onToggleTools,
    required this.onVoice,
    required this.toolActions,
    this.assistantStyle = false,
  });

  final TextEditingController controller;
  final FocusNode focusNode;
  final VoidCallback onSend;
  final VoidCallback onStop;
  final bool busy;
  final Widget? topContent;
  final bool showTools;
  final VoidCallback onToggleTools;
  final VoidCallback onVoice;
  final List<_ChatToolAction> toolActions;
  final bool assistantStyle;

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
          color: colors.surface.withValues(alpha: assistantStyle ? 0.94 : 1),
          border: Border(
            top: BorderSide(
              color: assistantStyle
                  ? Colors.white.withValues(alpha: 0.75)
                  : colorScheme.outlineVariant,
              width: 0.5,
            ),
          ),
          boxShadow: assistantStyle
              ? [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.055),
                    blurRadius: 24,
                    offset: const Offset(0, -8),
                  ),
                ]
              : null,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (topContent != null) topContent!,
            Padding(
              padding: EdgeInsets.fromLTRB(
                assistantStyle ? 12 : 8,
                8,
                assistantStyle ? 12 : 8,
                assistantStyle ? 10 : 8,
              ),
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
                      height: assistantStyle ? 44 : 38,
                      decoration: BoxDecoration(
                        color: assistantStyle
                            ? colors.surfaceHigh.withValues(alpha: 0.56)
                            : colors.surface,
                        borderRadius:
                            BorderRadius.circular(assistantStyle ? 16 : 10),
                        border: assistantStyle
                            ? Border.all(
                                color: colors.divider.withValues(alpha: 0.55),
                                width: 0.7,
                              )
                            : null,
                      ),
                      alignment: Alignment.center,
                      child: TextField(
                        controller: controller,
                        focusNode: focusNode,
                        maxLines: 1,
                        style: textTheme.bodyMedium?.copyWith(
                          color: colors.textPrimary,
                          fontSize: 15,
                        ),
                        decoration: InputDecoration(
                          isDense: true,
                          hintText: assistantStyle ? '问问小C…' : '发消息',
                          hintStyle: textTheme.bodyMedium?.copyWith(
                            color: colors.textSecondary,
                            fontSize: 15,
                          ),
                          border: InputBorder.none,
                          contentPadding: EdgeInsets.symmetric(
                            horizontal: assistantStyle ? 14 : 12,
                          ),
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
                  ValueListenableBuilder<TextEditingValue>(
                    valueListenable: controller,
                    builder: (context, value, _) {
                      final canSend = value.text.trim().isNotEmpty && !busy;
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
    const columns = 2;
    final rows = <List<_ChatToolAction>>[];
    for (var start = 0; start < actions.length; start += columns) {
      final end = (start + columns).clamp(0, actions.length);
      rows.add(actions.sublist(start, end));
    }

    return Padding(
      key: const ValueKey('chat_tool_card_panel'),
      padding: const EdgeInsets.fromLTRB(12, 7, 12, 18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(left: 2, bottom: 11),
            child: AssistantSectionLabel(
              '常用工具',
              trailing: Text(
                '选择后继续和小C对话',
                style: TextStyle(
                  color: AppTheme.colors(context).textSecondary,
                  fontSize: 10.5,
                ),
              ),
            ),
          ),
          for (var rowIndex = 0; rowIndex < rows.length; rowIndex++) ...[
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (var index = 0; index < columns; index++) ...[
                  Expanded(
                    child: index < rows[rowIndex].length
                        ? _ChatToolCard(action: rows[rowIndex][index])
                        : const SizedBox(height: 74),
                  ),
                  if (index != columns - 1) const SizedBox(width: 10),
                ],
              ],
            ),
            if (rowIndex != rows.length - 1) const SizedBox(height: 10),
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
    final accent = switch (action.title) {
      '联网搜索' => assistantBlue,
      '文件分析' => assistantCyan,
      '会议纪要' => assistantRose,
      'OCR识别' => assistantAmber,
      '语音对话' => assistantIndigo,
      '长期记忆' => assistantMint,
      _ => assistantIndigo,
    };
    return SizedBox(
      key: ValueKey('chat_tool_card_${action.title}'),
      height: 74,
      child: Material(
        color: colors.surfaceHigh.withValues(alpha: 0.44),
        borderRadius: BorderRadius.circular(18),
        child: InkWell(
          onTap: action.onTap,
          borderRadius: BorderRadius.circular(18),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 10),
            child: Row(
              children: [
                AssistantIconTile(
                  key: ValueKey('chat_tool_icon_box_${action.title}'),
                  icon: action.icon,
                  color: accent,
                  size: 40,
                  iconSize: 20,
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Text(
                        action.title,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: textTheme.labelMedium?.copyWith(
                          color: colors.textPrimary,
                          fontSize: 13,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        action.subtitle,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          color: colors.textSecondary,
                          fontSize: 10,
                        ),
                      ),
                    ],
                  ),
                ),
                Icon(
                  Icons.chevron_right_rounded,
                  size: 17,
                  color: colors.textSecondary.withValues(alpha: 0.7),
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
    return DecoratedBox(
      decoration: BoxDecoration(
        gradient: canStop
            ? null
            : const LinearGradient(colors: [assistantIndigo, assistantBlue]),
        color: canStop ? Theme.of(context).colorScheme.errorContainer : null,
        borderRadius: BorderRadius.circular(14),
        boxShadow: canStop
            ? null
            : [
                BoxShadow(
                  color: assistantIndigo.withValues(alpha: 0.24),
                  blurRadius: 12,
                  offset: const Offset(0, 5),
                ),
              ],
      ),
      child: Material(
        color: Colors.transparent,
        borderRadius: BorderRadius.circular(14),
        child: InkWell(
          onTap: canStop ? onStop : onSend,
          borderRadius: BorderRadius.circular(14),
          child: SizedBox(
            height: 44,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 15),
              child: Center(
                child: Text(
                  canStop ? '停止' : '发送',
                  style: textTheme.labelLarge?.copyWith(
                    color: canStop ? colors.danger : Colors.white,
                    fontSize: 14,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
