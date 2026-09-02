part of 'ai_group_screens.dart';

// part 文件：群聊页主状态（生命周期、渲染与消息收发）。

// 群聊页状态类。
class _AiGroupChatScreenState extends _AiGroupChatStateBase {
  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _group = widget.initialGroup;
    _future = _load();
  }

  @override
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.page,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            WeTopBar(
              title: _group.name.ifEmpty('群聊'),
              showBack: true,
              onBack: () => Navigator.of(context).maybePop(),
              titleWidget: Row(
                children: [
                  GroupGridAvatar(members: _group.members, size: 36),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          _group.name.ifEmpty('群聊'),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            color: colors.textPrimary,
                            fontSize: 17,
                            height: 1.29,
                            fontWeight: FontWeight.w500,
                            letterSpacing: 0,
                          ),
                        ),
                        if (_group.memberCount > 0)
                          Text(
                            '${_group.memberCount} 个 AI 成员',
                            style: TextStyle(
                              color: colors.textSecondary,
                              fontSize: 11,
                              height: 1.27,
                              letterSpacing: 0,
                            ),
                          ),
                      ],
                    ),
                  ),
                ],
              ),
              actions: [
                IconButton(
                  tooltip: '群成员',
                  onPressed: _showMembers,
                  icon: const Icon(Icons.group_add),
                  color: colors.textPrimary,
                ),
              ],
            ),
            Expanded(
              child: FutureBuilder<void>(
                future: _future,
                builder: (context, snapshot) {
                  return Column(
                    children: [
                      Expanded(
                        child: snapshot.connectionState ==
                                    ConnectionState.waiting &&
                                _messages.isEmpty
                            ? Center(
                                child: CircularProgressIndicator(
                                  color: colors.brand,
                                ),
                              )
                            : _messages.isEmpty
                                ? _GroupChatEmptyState(group: _group)
                                : ListView.separated(
                                    controller: _scrollController,
                                    padding: const EdgeInsets.fromLTRB(
                                      12,
                                      12,
                                      12,
                                      16,
                                    ),
                                    itemCount:
                                        _messages.length + (_sending ? 1 : 0),
                                    separatorBuilder: (_, __) =>
                                        const SizedBox(height: 10),
                                    itemBuilder: (context, index) {
                                      if (index >= _messages.length) {
                                        return _GroupTypingRow(
                                          dispatchMode: _pendingDispatchMode,
                                        );
                                      }
                                      return _GroupMessageBubble(
                                        message: _messages[index],
                                        userAvatarUrl: _userAvatarSource,
                                        onReply: () => _replyToGroupMessage(
                                            _messages[index]),
                                        onDelete: () => setState(
                                          () => _messages = [..._messages]
                                            ..removeAt(index),
                                        ),
                                      );
                                    },
                                  ),
                      ),
                      _GroupInputBar(
                        controller: _controller,
                        sending: _sending,
                        showTools: _showTools,
                        selectedBranch: _selectedBranch,
                        workMode: _workMode,
                        onToggleTools: () =>
                            setState(() => _showTools = !_showTools),
                        onVoice: _startVoiceInput,
                        onSend: _send,
                        onBranch: _showBranchPicker,
                        onMembers: _showMembers,
                        onSelectMode: (mode) => setState(() {
                          _workMode = mode;
                          _showTools = false;
                        }),
                        onClearMode: () => setState(() => _workMode = null),
                      ),
                    ],
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _load() async {
    final results = await Future.wait<Object>([
      _repository.loadAiGroupMessages(_group.id),
      _repository.loadGitBranches().catchError((_) => const <GitBranchInfo>[]),
      _repository
          .loadAiEmployees()
          .then(_mobileGroupMemberCatalog)
          .catchError((_) => const <AiGroupCandidate>[]),
      _repository.loadMe().catchError((_) => MobileMeData.adminFallback()),
    ]);
    if (!mounted) return;
    setState(() {
      _messages = results[0] as List<AiGroupMessage>;
      _branches = results[1] as List<GitBranchInfo>;
      _candidates = results[2] as List<AiGroupCandidate>;
      _userAvatarSource = (results[3] as MobileMeData).avatarSource;
    });
    _scrollToBottom();
  }

  Future<void> _send() async {
    final text = _controller.text.trim();
    if (_sending) return;
    if (_workMode == GroupWorkMode.dispatch && text.isEmpty) {
      _showSnack('先输入要派发的任务');
      return;
    }
    if (_workMode == GroupWorkMode.bugfix && text.isEmpty) {
      _showSnack('先输入要修复的问题');
      return;
    }
    if (_workMode == null && text.isEmpty) return;

    final selectedMode = _workMode;
    final body = selectedMode == GroupWorkMode.followup
        ? text.ifEmpty('小C，回访一下最近一次派工的进度和验收结论。')
        : text;
    _controller.clear();
    final local = AiGroupMessage(
      id: 'local-${DateTime.now().microsecondsSinceEpoch}',
      groupId: _group.id,
      role: AiGroupMessageRole.user,
      senderId: 'user',
      senderName: '我',
      body: body,
      createdAt: '刚刚',
    );
    setState(() {
      _messages = [..._messages, local];
      _sending = true;
      _pendingDispatchMode = selectedMode == GroupWorkMode.dispatch ||
          selectedMode == GroupWorkMode.bugfix;
    });
    _scrollToBottom();

    try {
      final result = await _repository.postAiGroupMessage(
        groupId: _group.id,
        message: body,
        branchContext:
            selectedMode == GroupWorkMode.followup ? '' : _selectedBranch,
        forceDispatch: selectedMode == GroupWorkMode.dispatch ||
            selectedMode == GroupWorkMode.bugfix,
        context: {
          if (selectedMode == GroupWorkMode.dispatch)
            'tool_action': 'dispatch_task',
          if (selectedMode == GroupWorkMode.followup)
            'tool_action': 'acceptance_followup',
          if (selectedMode == GroupWorkMode.bugfix)
            'tool_action': 'bugfix_task',
        },
      );
      if (!mounted) return;
      setState(() {
        _messages = _messages
            .where((message) => !message.id.startsWith('local-'))
            .toList(growable: false);
        if (result.messages.isNotEmpty) {
          _messages = [..._messages, ...result.messages];
        }
        _group = result.group ?? _group;
        _workMode = null;
        _sending = false;
        _pendingDispatchMode = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _sending = false;
        _pendingDispatchMode = false;
      });
      _showSnack(error.toString());
    } finally {
      _scrollToBottom();
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scrollController.hasClients) return;
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 220),
        curve: Curves.easeOut,
      );
    });
  }

  void _showSnack(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), behavior: SnackBarBehavior.floating),
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

  void _replyToGroupMessage(AiGroupMessage message) {
    final current = _controller.text;
    _controller.text = '引用「${message.body.take(60)}」\n$current';
    _controller.selection = TextSelection.collapsed(
      offset: _controller.text.length,
    );
  }

  Future<void> _startVoiceInput() async {
    setState(() => _showTools = false);
    final granted = await const AndroidRecordAudioPermission().ensureGranted();
    if (!mounted) return;
    if (!granted) {
      _showSnack('需要麦克风权限才能使用语音输入');
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
}
