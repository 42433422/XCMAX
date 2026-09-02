part of 'chat_screen.dart';

// 工具面板、页面导航、语音输入与 git 操作入口。
abstract class _ChatStateActions extends _ChatStateMessaging {
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
    final fixedKind = FixedPartnerProfileSpec.kindForConversation(
      widget.conversation,
    );
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
        messageId,
        result.trim().isEmpty ? '电脑工具已完成任务。' : result,
      );
    } catch (error) {
      if (!mounted) return;
      _replaceMessageBody(messageId, '（$error）');
    } finally {
      if (mounted) setState(() => _runningGitOp = false);
    }
  }

  List<_ChatToolAction> _toolActions() {
    final isSuperEmployee = widget.conversation.type.superTool != null;
    final activeGitBranches = _activeGitBranches();
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
      return [
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
        builder: (_) =>
            DiffViewerScreen(branch: branch, repository: repository),
      ),
    );
  }

  void _openBranchDetail(String branch) {
    final repository = _repository;
    if (repository == null) return;
    setState(() => _showToolPanel = false);
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) =>
            BranchDetailScreen(branch: branch, repository: repository),
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
