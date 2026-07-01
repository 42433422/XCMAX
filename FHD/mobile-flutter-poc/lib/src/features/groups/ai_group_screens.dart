import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../api/mobile_models.dart' show MobileMeData;
import '../../data/ai_employee_profile.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../models/conversation.dart';
import '../../policy/avatar_policy.dart';
import '../../policy/pinned_ids.dart';
import '../../theme/app_theme.dart';
import '../../theme/message_avatar_layout.dart';
import '../../widgets/app_avatar.dart';
import '../../widgets/group_grid_avatar.dart';
import '../../widgets/we_ui.dart';
import '../voice/voice_input_sheet.dart';

enum GroupWorkMode {
  dispatch('任务派工', '输入要派发的任务', Icons.groups),
  followup('验收回访', '可补充要回访哪一单', Icons.check),
  bugfix('问题修复', '输入要修复的问题', Icons.refresh);

  const GroupWorkMode(this.label, this.placeholder, this.icon);

  final String label;
  final String placeholder;
  final IconData icon;
}

const _xiaocGroupCandidate = AiGroupCandidate(
  employeeId: AiGroupMemberIds.xiaocAssistant,
  modId: 'xcagi-core-assistant',
  name: '小C助理',
  summary: '负责群内上下文、任务拆解和工作汇报串联。',
  departmentKey: '通用',
  isSuper: false,
);

const _fixedSuperGroupCandidates = <AiGroupCandidate>[
  AiGroupCandidate(
    employeeId: AiGroupMemberIds.codexSuperEmployee,
    modId: 'super-employee',
    name: '超级员工-Codex',
    summary: 'Codex CLI 超级员工，支持代码任务、测试和汇报。',
    departmentKey: '工程协作',
    isSuper: true,
  ),
  AiGroupCandidate(
    employeeId: AiGroupMemberIds.cursorSuperEmployee,
    modId: 'super-employee',
    name: '超级员工-Cursor',
    summary: 'Cursor Agent 超级员工，支持工程修改和上下文协作。',
    departmentKey: '工程协作',
    isSuper: true,
  ),
  AiGroupCandidate(
    employeeId: AiGroupMemberIds.claudeSuperEmployee,
    modId: 'super-employee',
    name: '超级员工-Claude',
    summary: 'Claude CLI 超级员工，支持分析、编写和任务复盘。',
    departmentKey: '工程协作',
    isSuper: true,
  ),
  AiGroupCandidate(
    employeeId: AiGroupMemberIds.traeSuperEmployee,
    modId: 'super-employee',
    name: '超级员工-Trae',
    summary: 'Trae CLI 超级员工，支持 IDE 执行端、备用额度和补位协作。',
    departmentKey: '工程协作',
    isSuper: true,
  ),
];

List<AiGroupCandidate> _androidGroupMemberCatalog(
  List<AiEmployeeProfile> employees,
) {
  final catalog = <AiGroupCandidate>[
    _xiaocGroupCandidate,
    ..._fixedSuperGroupCandidates,
    for (final employee in employees) _candidateFromEmployee(employee),
  ];
  final seen = <String>{};
  return [
    for (final candidate in catalog)
      if (seen.add(candidate.employeeId)) candidate,
  ];
}

AiGroupCandidate _candidateFromEmployee(AiEmployeeProfile employee) {
  return AiGroupCandidate(
    employeeId: employee.employeeId,
    modId: employee.modId,
    name: employee.name,
    avatarUrl: employee.avatarUrl,
    summary: employee.summary,
    departmentKey: employee.industryName.ifEmpty(employee.modName),
    isSuper: false,
  );
}

class AiGroupListScreen extends StatefulWidget {
  const AiGroupListScreen({
    super.key,
    this.repository,
    this.initialGroups = const [],
  });

  final MobileRepository? repository;
  final List<AiGroupConversation> initialGroups;

  @override
  State<AiGroupListScreen> createState() => _AiGroupListScreenState();
}

class _AiGroupListScreenState extends State<AiGroupListScreen> {
  late final MobileRepository _repository;
  late Future<void> _future;
  var _groups = <AiGroupConversation>[];

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _groups = widget.initialGroups;
    _future = _load();
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Scaffold(
      backgroundColor: colors.surface,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            WeTopBar(
              title: '群聊',
              showBack: true,
              onBack: () => Navigator.of(context).maybePop(),
              actions: [
                IconButton(
                  tooltip: '创建群聊',
                  onPressed: _openCreate,
                  icon: const Icon(Icons.add),
                  color: colors.textPrimary,
                ),
              ],
            ),
            Expanded(
              child: FutureBuilder<void>(
                future: _future,
                builder: (context, snapshot) {
                  if (snapshot.connectionState == ConnectionState.waiting &&
                      _groups.isEmpty) {
                    return Center(
                      child: CircularProgressIndicator(color: colors.brand),
                    );
                  }
                  if (_groups.isEmpty) {
                    return const _GroupEmptyState();
                  }
                  return RefreshIndicator(
                    color: colors.brand,
                    onRefresh: _load,
                    child: ListView.separated(
                      physics: const AlwaysScrollableScrollPhysics(),
                      itemCount: _groups.length,
                      separatorBuilder: (_, __) => const Divider(
                        indent: MessageAvatarLayout.conversationDividerStart,
                      ),
                      itemBuilder: (context, index) {
                        final group = _groups[index];
                        return _GroupRow(
                          group: group,
                          onTap: () => _openGroup(group),
                          onLongPress: () => _showGroupActions(group),
                        );
                      },
                    ),
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
    final groups = await _repository.loadAiGroups();
    if (!mounted) return;
    setState(() => _groups = groups);
  }

  Future<void> _openCreate() async {
    final created = await Navigator.of(context).push<AiGroupConversation>(
      MaterialPageRoute(
        builder: (_) => AiGroupCreateScreen(repository: _repository),
      ),
    );
    if (created == null || !mounted) return;
    await _load();
    _openGroup(created);
  }

  Future<void> _openGroup(AiGroupConversation group) async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => AiGroupChatScreen(
          repository: _repository,
          initialGroup: group,
        ),
      ),
    );
    if (mounted) _load();
  }

  void _showGroupActions(AiGroupConversation group) {
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: AppTheme.colors(context).surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
      ),
      builder: (context) => _AiGroupActionSheet(
        title: group.name.isEmpty ? '群聊操作' : group.name,
        actions: [
          _AiGroupSheetAction(
            label: '标为未读',
            onTap: () => _runGroupAction(
              () => _repository.markAiGroupUnread(group.id),
            ),
          ),
          _AiGroupSheetAction(
            label: group.isPinned ? '取消置顶' : '置顶聊天',
            onTap: () =>
                _runGroupAction(() => _repository.toggleAiGroupPin(group.id)),
          ),
          _AiGroupSheetAction(
            label: group.isFollowed ? '不再关注' : '恢复关注',
            onTap: () => _runGroupAction(
              () => _repository.toggleAiGroupFollowed(group.id),
            ),
          ),
          _AiGroupSheetAction(
            label: group.isHidden ? '显示该聊天' : '不显示该聊天',
            onTap: () => _runGroupAction(
              () => _repository.toggleAiGroupHidden(group.id),
            ),
          ),
          _AiGroupSheetAction(
            label: '删除该聊天',
            onTap: () =>
                _runGroupAction(() => _repository.deleteAiGroup(group.id)),
            danger: true,
          ),
        ],
      ),
    );
  }

  Future<void> _runGroupAction(Future<Object?> Function() action) async {
    Navigator.pop(context);
    try {
      await action();
      await _load();
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(error.toString())),
      );
    }
  }
}

class AiGroupChatScreen extends StatefulWidget {
  const AiGroupChatScreen({
    super.key,
    required this.initialGroup,
    this.repository,
  });

  final AiGroupConversation initialGroup;
  final MobileRepository? repository;

  @override
  State<AiGroupChatScreen> createState() => _AiGroupChatScreenState();
}

class _AiGroupChatScreenState extends State<AiGroupChatScreen> {
  late final MobileRepository _repository;
  late Future<void> _future;
  final _controller = TextEditingController();
  final _scrollController = ScrollController();
  late AiGroupConversation _group;
  var _messages = <AiGroupMessage>[];
  var _branches = <GitBranchInfo>[];
  var _candidates = <AiGroupCandidate>[];
  var _userAvatarSource = '';
  var _selectedBranch = '';
  GroupWorkMode? _workMode;
  var _showTools = false;
  var _sending = false;
  var _pendingDispatchMode = false;

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
                                          _messages[index],
                                        ),
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
          .then(_androidGroupMemberCatalog)
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

  void _showBranchPicker() {
    var sheetBranches = _branches;
    var refreshing = false;
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: AppTheme.colors(context).surface,
      builder: (sheetContext) => StatefulBuilder(
        builder: (context, setSheetState) {
          final colors = AppTheme.colors(context);
          Future<void> refreshBranches() async {
            if (refreshing) return;
            setSheetState(() => refreshing = true);
            try {
              final branches = await _repository.loadGitBranches();
              if (!mounted) return;
              setState(() => _branches = branches);
              if (!context.mounted) return;
              setSheetState(() {
                sheetBranches = branches;
                refreshing = false;
              });
            } catch (error) {
              if (!mounted) return;
              _showSnack(error.toString());
              if (!context.mounted) return;
              setSheetState(() => refreshing = false);
            }
          }

          return SafeArea(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Padding(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 18, vertical: 8),
                  child: Row(
                    children: [
                      Expanded(
                        child: Text(
                          '工作分支',
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                      ),
                      IconButton(
                        tooltip: '刷新分支',
                        onPressed: refreshing ? null : refreshBranches,
                        icon: refreshing
                            ? SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: colors.brand,
                                ),
                              )
                            : const Icon(Icons.refresh, size: 20),
                      ),
                    ],
                  ),
                ),
                ListTile(
                  title: Text(
                    '自动新建任务分支',
                    style: TextStyle(color: colors.textPrimary),
                  ),
                  subtitle: Text(
                    '普通派工默认隔离，跑完后再合并',
                    style: TextStyle(color: colors.textSecondary),
                  ),
                  leading: Icon(Icons.call_merge, color: colors.brand),
                  trailing: _selectedBranch.isEmpty
                      ? Icon(Icons.check, color: colors.textPrimary)
                      : null,
                  onTap: () {
                    setState(() => _selectedBranch = '');
                    Navigator.pop(sheetContext);
                  },
                ),
                Divider(color: colors.divider),
                if (sheetBranches.isEmpty)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(18, 12, 18, 18),
                    child: Align(
                      alignment: Alignment.centerLeft,
                      child: Text(
                        '暂无可选分支，点右上角刷新',
                        style: TextStyle(
                          color: colors.textSecondary,
                          fontSize: 13,
                          height: 1.31,
                          letterSpacing: 0,
                        ),
                      ),
                    ),
                  )
                else
                  ConstrainedBox(
                    constraints: const BoxConstraints(maxHeight: 360),
                    child: ListView(
                      shrinkWrap: true,
                      children: [
                        for (final branch in sheetBranches.take(20))
                          ListTile(
                            title: Text(
                              branch.name,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(color: colors.textPrimary),
                            ),
                            subtitle: Text(
                              branch.current
                                  ? '当前分支'
                                  : branch.remote
                                      ? '远端分支'
                                      : '本地分支',
                              style: TextStyle(color: colors.textSecondary),
                            ),
                            leading: Icon(
                              Icons.call_merge,
                              color: colors.textSecondary,
                            ),
                            trailing: _selectedBranch == branch.name
                                ? Icon(Icons.check, color: colors.brand)
                                : null,
                            onTap: () {
                              setState(() => _selectedBranch = branch.name);
                              Navigator.pop(sheetContext);
                            },
                          ),
                      ],
                    ),
                  ),
              ],
            ),
          );
        },
      ),
    );
  }

  void _showMembers() {
    final memberIds = _group.members.map((member) => member.employeeId).toSet();
    final addable = _candidates
        .where((candidate) => !memberIds.contains(candidate.employeeId))
        .toList(growable: false);
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: AppTheme.colors(context).surface,
      builder: (context) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.72,
        minChildSize: 0.42,
        maxChildSize: 0.9,
        builder: (context, controller) => ListView(
          controller: controller,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 14, 18, 8),
              child: Text(
                '群成员（${_group.memberCount}）',
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
            for (final member in _group.members)
              _MemberTile(
                name: member.name,
                summary: member.summary,
                avatarUrl: member.avatarUrl,
                employeeId: member.employeeId,
                avatarKey: member.avatarKey,
                trailing: isRequiredAiGroupMember(member.employeeId)
                    ? const Text('固定')
                    : IconButton(
                        onPressed: () => _removeMember(member.employeeId),
                        icon: Icon(
                          Icons.person_remove,
                          color: AppTheme.colors(context).danger,
                        ),
                      ),
              ),
            Divider(color: AppTheme.colors(context).divider),
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 10, 18, 4),
              child: Text(
                '添加 AI 成员',
                style: TextStyle(
                  color: AppTheme.colors(context).textSecondary,
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  letterSpacing: 0,
                ),
              ),
            ),
            if (addable.isEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(18, 8, 18, 8),
                child: Text(
                  _candidates.isEmpty
                      ? '暂无可用 AI 员工，先在「AI员工」里同步'
                      : '已把所有 AI 员工都拉进群了',
                  style: TextStyle(
                    color: AppTheme.colors(context).textSecondary,
                    fontSize: 13,
                    height: 1.31,
                    letterSpacing: 0,
                  ),
                ),
              )
            else
              for (final candidate in addable)
                _MemberTile(
                  name: candidate.name,
                  summary: candidate.summary,
                  avatarUrl: candidate.avatarUrl,
                  employeeId: candidate.employeeId,
                  trailing: Icon(
                    Icons.add,
                    color: AppTheme.colors(context).brand,
                  ),
                  onTap: () => _addMember(candidate),
                ),
          ],
        ),
      ),
    );
  }

  Future<void> _addMember(AiGroupCandidate candidate) async {
    Navigator.pop(context);
    try {
      final updated = await _repository.addAiGroupMember(
        groupId: _group.id,
        employeeId: candidate.employeeId,
        modId: candidate.modId,
        name: candidate.name,
        avatar: candidate.avatarUrl ?? '',
        summary: candidate.summary,
      );
      if (!mounted) return;
      if (updated != null) setState(() => _group = updated);
    } catch (error) {
      _showSnack(error.toString());
    }
  }

  Future<void> _removeMember(String employeeId) async {
    Navigator.pop(context);
    try {
      final updated = await _repository.removeAiGroupMember(
        groupId: _group.id,
        employeeId: employeeId,
      );
      if (!mounted) return;
      if (updated != null) setState(() => _group = updated);
    } catch (error) {
      _showSnack(error.toString());
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

  void _startVoiceInput() {
    setState(() => _showTools = false);
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

class AiGroupCreateScreen extends StatefulWidget {
  const AiGroupCreateScreen({super.key, this.repository});

  final MobileRepository? repository;

  @override
  State<AiGroupCreateScreen> createState() => _AiGroupCreateScreenState();
}

class _AiGroupCreateScreenState extends State<AiGroupCreateScreen> {
  late final MobileRepository _repository;
  late Future<void> _future;
  final _nameController = TextEditingController();
  var _candidates = <AiGroupCandidate>[];
  var _selected = <String>{};
  var _creating = false;

  @override
  void initState() {
    super.initState();
    _repository = MobileRepositoryScope.resolve(
      context,
      explicit: widget.repository,
    );
    _future = _load();
  }

  @override
  void dispose() {
    _nameController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final picked =
        _candidates.where((candidate) => _selected.contains(candidate.key));
    final autoName = picked.map((item) => item.name).join('、').take(40);
    return Scaffold(
      backgroundColor: colors.surface,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            WeTopBar(
              title: '发起群聊',
              showBack: true,
              onBack: () => Navigator.of(context).maybePop(),
              actions: [
                TextButton(
                  onPressed: _selected.isEmpty || _creating
                      ? null
                      : () => _create(autoName),
                  child: Text(
                    _selected.isEmpty ? '完成' : '完成(${_selected.length})',
                  ),
                ),
              ],
            ),
            Expanded(
              child: FutureBuilder<void>(
                future: _future,
                builder: (context, snapshot) {
                  if (snapshot.connectionState == ConnectionState.waiting &&
                      _candidates.isEmpty) {
                    return Center(
                      child: CircularProgressIndicator(color: colors.brand),
                    );
                  }
                  return Column(
                    children: [
                      Padding(
                        padding: const EdgeInsets.fromLTRB(16, 8, 16, 10),
                        child: TextField(
                          controller: _nameController,
                          decoration: InputDecoration(
                            hintText: autoName.ifEmpty('群名称（可留空，自动命名）'),
                            filled: true,
                            fillColor: colors.page,
                            border: OutlineInputBorder(
                              borderSide: BorderSide.none,
                              borderRadius: BorderRadius.circular(10),
                            ),
                            isDense: true,
                          ),
                          maxLines: 1,
                        ),
                      ),
                      const Divider(),
                      Expanded(
                        child: _candidates.isEmpty
                            ? const Center(
                                child: Text('暂无可选 AI 员工，先在「AI员工」里同步'),
                              )
                            : ListView.separated(
                                itemCount: _candidates.length,
                                separatorBuilder: (_, __) => const Divider(
                                  indent: MessageAvatarLayout
                                      .employeePickerDividerStart,
                                ),
                                itemBuilder: (context, index) {
                                  final candidate = _candidates[index];
                                  final selected =
                                      _selected.contains(candidate.key);
                                  final locked = isRequiredAiGroupMember(
                                    candidate.employeeId,
                                  );
                                  return _CandidateTile(
                                    candidate: candidate,
                                    selected: selected,
                                    locked: locked,
                                    onChanged: locked
                                        ? null
                                        : () {
                                            setState(() {
                                              if (selected) {
                                                _selected.remove(candidate.key);
                                              } else {
                                                _selected.add(candidate.key);
                                              }
                                            });
                                          },
                                  );
                                },
                              ),
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
    final candidates =
        _androidGroupMemberCatalog(await _repository.loadAiEmployees());
    if (!mounted) return;
    final selected = <String>{};
    for (final candidate in candidates) {
      if (isRequiredAiGroupMember(candidate.employeeId)) {
        selected.add(candidate.key);
      }
    }
    setState(() {
      _candidates = candidates;
      _selected = selected;
    });
  }

  Future<void> _create(String autoName) async {
    setState(() => _creating = true);
    final members = _candidates
        .where((candidate) => _selected.contains(candidate.key))
        .toList(growable: false);
    final name = _nameController.text.trim().ifEmpty(
          autoName.ifEmpty('新建群聊'),
        );
    try {
      final group = await _repository.createGroupWithMembers(
        name: name,
        members: members,
      );
      if (!mounted) return;
      Navigator.of(context).pop(group);
    } catch (error) {
      if (!mounted) return;
      setState(() => _creating = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(error.toString())),
      );
    }
  }
}

class _GroupRow extends StatelessWidget {
  const _GroupRow({
    required this.group,
    required this.onTap,
    required this.onLongPress,
  });

  final AiGroupConversation group;
  final VoidCallback onTap;
  final VoidCallback onLongPress;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final preview = group.preview.trim().isEmpty
        ? group.memberCount == 0
            ? '还没有成员，进群把 AI 拉进来'
            : '${group.memberCount} 个 AI 成员在群里'
        : group.preview;
    final dimmed = group.isHidden || !group.isFollowed;
    return Material(
      color: group.isPinned ? colors.surfaceHigh : colors.surface,
      child: InkWell(
        onTap: onTap,
        onLongPress: onLongPress,
        child: Opacity(
          opacity: dimmed ? 0.52 : 1,
          child: Padding(
            padding: const EdgeInsets.symmetric(
              horizontal: MessageAvatarLayout.conversationRowHorizontalPadding,
              vertical: MessageAvatarLayout.conversationRowVerticalPadding,
            ),
            child: Row(
              children: [
                GroupGridAvatar(members: group.members),
                const SizedBox(
                    width: MessageAvatarLayout.conversationAvatarTextGap),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          if (group.isPinned) ...[
                            Icon(
                              Icons.push_pin_outlined,
                              size: 14,
                              color: colors.brand,
                            ),
                            const SizedBox(width: 4),
                          ],
                          Expanded(
                            child: Text(
                              group.name,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                color: colors.textPrimary,
                                fontSize: 16,
                                height: 1.35,
                                fontWeight: FontWeight.w500,
                                letterSpacing: 0,
                              ),
                            ),
                          ),
                          if (group.memberCount > 0)
                            Text(
                              '(${group.memberCount})',
                              style: TextStyle(
                                color: colors.textSecondary,
                                fontSize: 13,
                                height: 1.31,
                                letterSpacing: 0,
                              ),
                            ),
                        ],
                      ),
                      const SizedBox(height: 3),
                      Text(
                        preview,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          color: colors.textSecondary,
                          fontSize: 14,
                          height: 1.36,
                          letterSpacing: 0,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                if (group.unreadCount > 0)
                  UnreadBadge(count: group.unreadCount)
                else
                  Text(
                    group.timestampText,
                    style: TextStyle(
                      color: colors.textTertiary,
                      fontSize: 13,
                      height: 1.31,
                      letterSpacing: 0,
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

class _GroupMessageBubble extends StatelessWidget {
  const _GroupMessageBubble({
    required this.message,
    required this.userAvatarUrl,
    required this.onReply,
    required this.onDelete,
  });

  final AiGroupMessage message;
  final String userAvatarUrl;
  final VoidCallback onReply;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final isUser = message.role == AiGroupMessageRole.user;
    final ui = _AiGroupMessageUi.resolve(
      kind: message.kind,
      status: message.status,
      body: message.body,
    );
    final assistantBubbleColor = switch (ui.tone) {
      _GroupMessageTone.plain => colors.surface,
      _GroupMessageTone.brand => colors.brand.withValues(alpha: 0.10),
      _GroupMessageTone.success => colors.success.withValues(alpha: 0.10),
      _GroupMessageTone.warning => colors.warning.withValues(alpha: 0.12),
    };
    final badgeForeground = switch (ui.tone) {
      _GroupMessageTone.plain => colors.textSecondary,
      _GroupMessageTone.brand => colors.brand,
      _GroupMessageTone.success => colors.success,
      _GroupMessageTone.warning => colors.warning,
    };
    final badgeBackground = badgeForeground.withValues(alpha: 0.12);
    final badgeBorder = badgeForeground.withValues(alpha: 0.32);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisAlignment:
          isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
      children: [
        if (!isUser) ...[
          AppAvatar(
            imageSource: message.senderAvatar,
            fallback: aiGroupAvatarFallback(
              employeeId: message.senderId,
              name: message.senderName,
            ),
            size: MessageAvatarLayout.bubbleAvatarSize,
            borderRadius: MessageAvatarLayout.bubbleAvatarRadius,
            contentDescription: message.senderName,
          ),
          const SizedBox(width: MessageAvatarLayout.bubbleAvatarGap),
        ],
        Flexible(
          child: Column(
            crossAxisAlignment:
                isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start,
            children: [
              if (!isUser)
                Padding(
                  padding: const EdgeInsets.only(bottom: 3),
                  child: Text(
                    message.senderName.ifEmpty('AI员工'),
                    style: TextStyle(
                      color: colors.textSecondary,
                      fontSize: 12,
                      height: 1.2,
                      letterSpacing: 0,
                    ),
                  ),
                ),
              if (!isUser && ui.badge.isNotEmpty)
                Container(
                  margin: const EdgeInsets.only(left: 4, bottom: 4),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 2,
                  ),
                  decoration: BoxDecoration(
                    color: badgeBackground,
                    border: Border.all(color: badgeBorder, width: 0.5),
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Text(
                    ui.badge,
                    style: TextStyle(
                      color: badgeForeground,
                      fontSize: 11,
                      height: 1.27,
                      fontWeight: FontWeight.w600,
                      letterSpacing: 0,
                    ),
                  ),
                ),
              GestureDetector(
                onLongPressStart: (details) =>
                    _showActions(context, details.globalPosition),
                child: Container(
                  key: ValueKey('group_bubble_${message.id}'),
                  constraints: const BoxConstraints(maxWidth: 260),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 10,
                  ),
                  decoration: BoxDecoration(
                    color:
                        isUser ? colors.chatUserBubble : assistantBubbleColor,
                    borderRadius: BorderRadius.only(
                      topLeft: Radius.circular(isUser ? 12 : 4),
                      topRight: Radius.circular(isUser ? 4 : 12),
                      bottomLeft: const Radius.circular(12),
                      bottomRight: const Radius.circular(12),
                    ),
                    boxShadow: [
                      BoxShadow(
                        color: colors.divider.withValues(alpha: 0.32),
                        blurRadius: 1,
                        offset: const Offset(0, 1),
                      ),
                    ],
                  ),
                  child: Text(
                    message.body,
                    style: TextStyle(
                      color: isUser
                          ? colors.chatUserBubbleText
                          : colors.textPrimary,
                      fontSize: 15,
                      height: 1.4,
                      letterSpacing: 0,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
        if (isUser) ...[
          const SizedBox(width: MessageAvatarLayout.bubbleAvatarGap),
          AppAvatar(
            imageSource: userAvatarUrl,
            fallback: AppAvatarFallback.user,
            size: MessageAvatarLayout.bubbleAvatarSize,
            borderRadius: MessageAvatarLayout.bubbleAvatarRadius,
            contentDescription: '我',
          ),
        ],
      ],
    );
  }

  Future<void> _showActions(BuildContext context, Offset position) async {
    final selected = await showMenu<String>(
      context: context,
      position: RelativeRect.fromLTRB(
        position.dx,
        position.dy,
        position.dx,
        position.dy,
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
        await Clipboard.setData(ClipboardData(text: message.body));
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
  }
}

class _GroupTypingRow extends StatelessWidget {
  const _GroupTypingRow({required this.dispatchMode});

  final bool dispatchMode;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: MessageAvatarLayout.bubbleAvatarSize,
          height: MessageAvatarLayout.bubbleAvatarSize,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: colors.divider,
            borderRadius: MessageAvatarLayout.bubbleAvatarRadius,
          ),
          child: Icon(
            Icons.group,
            size: 22,
            color: colors.textTertiary,
          ),
        ),
        const SizedBox(width: MessageAvatarLayout.bubbleAvatarGap),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
          decoration: BoxDecoration(
            color: colors.surface,
            borderRadius: const BorderRadius.only(
              topLeft: Radius.circular(4),
              topRight: Radius.circular(12),
              bottomLeft: Radius.circular(12),
              bottomRight: Radius.circular(12),
            ),
            boxShadow: [
              BoxShadow(
                color: colors.divider.withValues(alpha: 0.32),
                blurRadius: 1,
                offset: const Offset(0, 1),
              ),
            ],
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              SizedBox(
                width: 13,
                height: 13,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: colors.textSecondary,
                ),
              ),
              const SizedBox(width: 8),
              Text(
                dispatchMode ? '员工正在执行并汇报…' : 'AI 成员正在讨论并回复…',
                style: TextStyle(
                  color: colors.textSecondary,
                  fontSize: 14,
                  height: 1.4,
                  letterSpacing: 0,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _AiGroupMessageUi {
  const _AiGroupMessageUi({
    required this.badge,
    required this.tone,
    required this.needsReview,
  });

  final String badge;
  final _GroupMessageTone tone;
  final bool needsReview;

  static _AiGroupMessageUi resolve({
    required String kind,
    required String status,
    required String body,
  }) {
    final normalized = kind.trim().toLowerCase();
    switch (normalized) {
      case 'discussion':
      case 'super_discussion':
        return const _AiGroupMessageUi(
          badge: '讨论',
          tone: _GroupMessageTone.brand,
          needsReview: false,
        );
      case 'routing_decision':
        return const _AiGroupMessageUi(
          badge: '分工',
          tone: _GroupMessageTone.success,
          needsReview: false,
        );
      case 'work_order':
      case 'work_report':
      case 'relay_work_report':
        return _AiGroupMessageUi(
          badge: normalized == 'work_order' ? '派单' : '汇报',
          tone: _GroupMessageTone.brand,
          needsReview: false,
        );
      case 'work_acceptance':
        final review = status.trim().toLowerCase() == 'needs_review' ||
            body.contains('需要复核');
        return _AiGroupMessageUi(
          badge: review ? '待复核' : '可验收',
          tone: review ? _GroupMessageTone.warning : _GroupMessageTone.success,
          needsReview: review,
        );
      default:
        return const _AiGroupMessageUi(
          badge: '',
          tone: _GroupMessageTone.plain,
          needsReview: false,
        );
    }
  }
}

enum _GroupMessageTone { plain, brand, success, warning }

class _GroupInputBar extends StatelessWidget {
  const _GroupInputBar({
    required this.controller,
    required this.sending,
    required this.showTools,
    required this.selectedBranch,
    required this.workMode,
    required this.onToggleTools,
    required this.onVoice,
    required this.onSend,
    required this.onBranch,
    required this.onMembers,
    required this.onSelectMode,
    required this.onClearMode,
  });

  final TextEditingController controller;
  final bool sending;
  final bool showTools;
  final String selectedBranch;
  final GroupWorkMode? workMode;
  final VoidCallback onToggleTools;
  final VoidCallback onVoice;
  final VoidCallback onSend;
  final VoidCallback onBranch;
  final VoidCallback onMembers;
  final ValueChanged<GroupWorkMode> onSelectMode;
  final VoidCallback onClearMode;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final textTheme = theme.textTheme;
    final branchLabel =
        selectedBranch.trim().isEmpty ? '自动新建' : selectedBranch.split('/').last;
    final toolActions = [
      _GroupToolAction(Icons.call_merge, '工作分支', onBranch),
      _GroupToolAction(Icons.group_add, '群成员', onMembers),
      _GroupToolAction(Icons.mic, '语音输入', onVoice),
      _GroupToolAction(
        Icons.groups,
        '任务派工',
        () => onSelectMode(GroupWorkMode.dispatch),
      ),
      _GroupToolAction(
        Icons.check,
        '验收回访',
        () => onSelectMode(GroupWorkMode.followup),
      ),
      _GroupToolAction(
        Icons.refresh,
        '问题修复',
        () => onSelectMode(GroupWorkMode.bugfix),
      ),
    ];
    return SafeArea(
      top: false,
      child: Container(
        key: const ValueKey('group_input_bar_surface'),
        decoration: BoxDecoration(
          color: colors.surface,
          border: Border(
            top: BorderSide(color: colorScheme.outlineVariant, width: 0.5),
          ),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
              width: double.infinity,
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                child: Row(
                  children: [
                    _ComposerChip(
                      key: const ValueKey('group_branch_chip'),
                      icon: Icons.call_merge,
                      label: '工作分支 · $branchLabel',
                      onTap: onBranch,
                    ),
                    if (workMode != null) ...[
                      const SizedBox(width: 8),
                      _ComposerChip(
                        key: const ValueKey('group_work_mode_chip'),
                        icon: workMode!.icon,
                        label: '工作模式 · ${workMode!.label}',
                        active: true,
                        trailingIcon: Icons.close,
                        onTap: onClearMode,
                      ),
                    ],
                  ],
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
              child: ValueListenableBuilder<TextEditingValue>(
                valueListenable: controller,
                builder: (context, value, _) {
                  final canSend = (value.text.trim().isNotEmpty ||
                          workMode == GroupWorkMode.followup) &&
                      !sending;
                  return Row(
                    children: [
                      _GroupComposerIconButton(
                        icon: Icons.mic,
                        tooltip: '语音',
                        onTap: onVoice,
                      ),
                      const SizedBox(width: 6),
                      Expanded(
                        child: SizedBox(
                          height: 38,
                          child: DecoratedBox(
                            decoration: BoxDecoration(
                              color: colors.surface,
                              borderRadius: BorderRadius.circular(10),
                            ),
                            child: TextField(
                              controller: controller,
                              maxLines: 1,
                              textInputAction: TextInputAction.send,
                              onSubmitted: (_) {
                                if (canSend) onSend();
                              },
                              decoration: InputDecoration(
                                isCollapsed: true,
                                contentPadding: const EdgeInsets.symmetric(
                                  horizontal: 12,
                                  vertical: 9,
                                ),
                                border: InputBorder.none,
                                hintText:
                                    workMode?.placeholder ?? '发群消息（@成员 可单独点名）',
                                hintMaxLines: 1,
                                hintStyle: textTheme.bodyMedium?.copyWith(
                                  color: colors.textSecondary,
                                  fontSize: 15,
                                ),
                              ),
                              style: textTheme.bodyMedium?.copyWith(
                                color: colors.textPrimary,
                                fontSize: 15,
                              ),
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(width: 6),
                      _GroupComposerIconButton(
                        icon: Icons.add,
                        iconSize: 26,
                        selected: showTools,
                        tooltip: '更多工具',
                        onTap: onToggleTools,
                      ),
                      if (canSend) ...[
                        const SizedBox(width: 6),
                        _GroupSendPill(onTap: onSend),
                      ],
                    ],
                  );
                },
              ),
            ),
            if (showTools)
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 8, 12, 16),
                child: _GroupToolPanel(actions: toolActions),
              ),
          ],
        ),
      ),
    );
  }
}

class _GroupComposerIconButton extends StatelessWidget {
  const _GroupComposerIconButton({
    required this.icon,
    required this.tooltip,
    required this.onTap,
    this.selected = false,
    this.iconSize = 22,
  });

  final IconData icon;
  final String tooltip;
  final VoidCallback onTap;
  final bool selected;
  final double iconSize;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return IconButton(
      onPressed: onTap,
      tooltip: tooltip,
      padding: EdgeInsets.zero,
      constraints: const BoxConstraints.tightFor(width: 38, height: 38),
      style: IconButton.styleFrom(
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
      ),
      icon: Icon(
        icon,
        size: iconSize,
        color: selected ? colors.brand : colors.textPrimary,
      ),
    );
  }
}

class _GroupSendPill extends StatelessWidget {
  const _GroupSendPill({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Container(
        height: 38,
        padding: const EdgeInsets.symmetric(horizontal: 17),
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: colors.brand,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Text(
          '发送',
          style: textTheme.labelLarge?.copyWith(
            color: colors.surface,
            fontSize: 15,
            fontWeight: FontWeight.w500,
          ),
        ),
      ),
    );
  }
}

class _GroupToolAction {
  const _GroupToolAction(this.icon, this.label, this.onTap);

  final IconData icon;
  final String label;
  final VoidCallback onTap;
}

class _GroupToolPanel extends StatelessWidget {
  const _GroupToolPanel({required this.actions});

  final List<_GroupToolAction> actions;

  @override
  Widget build(BuildContext context) {
    final rows = <Widget>[];
    for (var index = 0; index < actions.length; index += 4) {
      final rowActions = actions.skip(index).take(4).toList();
      rows.add(
        Row(
          children: [
            for (var i = 0; i < 4; i++) ...[
              if (i > 0) const SizedBox(width: 12),
              Expanded(
                child: i < rowActions.length
                    ? _ToolTile(rowActions[i])
                    : const SizedBox.shrink(),
              ),
            ],
          ],
        ),
      );
      if (index + 4 < actions.length) {
        rows.add(const SizedBox(height: 18));
      }
    }
    return Column(mainAxisSize: MainAxisSize.min, children: rows);
  }
}

class _CandidateTile extends StatelessWidget {
  const _CandidateTile({
    required this.candidate,
    required this.selected,
    required this.locked,
    required this.onChanged,
  });

  final AiGroupCandidate candidate;
  final bool selected;
  final bool locked;
  final VoidCallback? onChanged;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return InkWell(
      onTap: onChanged,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: Row(
          children: [
            Checkbox(
                value: selected,
                onChanged: locked ? null : (_) => onChanged?.call()),
            const SizedBox(width: 8),
            AppAvatar(
              imageSource: candidate.avatarUrl,
              fallback: aiGroupAvatarFallback(
                employeeId: candidate.employeeId,
                name: candidate.name,
              ),
              size: MessageAvatarLayout.employeePickerAvatarSize,
              borderRadius: MessageAvatarLayout.employeePickerAvatarRadius,
              contentDescription: candidate.name,
            ),
            const SizedBox(
                width: MessageAvatarLayout.employeePickerAvatarTextGap),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    candidate.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: colors.textPrimary,
                      fontSize: 16,
                      height: 1.38,
                      fontWeight: FontWeight.w500,
                      letterSpacing: 0,
                    ),
                  ),
                  Text(
                    candidate.summary,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: colors.textSecondary,
                      fontSize: 13,
                      height: 1.31,
                      letterSpacing: 0,
                    ),
                  ),
                ],
              ),
            ),
            if (locked)
              Text(
                '固定',
                style: TextStyle(color: colors.textSecondary, fontSize: 12),
              ),
          ],
        ),
      ),
    );
  }
}

class _MemberTile extends StatelessWidget {
  const _MemberTile({
    required this.name,
    required this.summary,
    required this.employeeId,
    this.avatarUrl,
    this.avatarKey = '',
    this.trailing,
    this.onTap,
  });

  final String name;
  final String summary;
  final String employeeId;
  final String? avatarUrl;
  final String avatarKey;
  final Widget? trailing;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return ListTile(
      onTap: onTap,
      leading: AppAvatar(
        imageSource: avatarUrl,
        fallback: aiGroupAvatarFallback(
          employeeId: employeeId,
          name: name,
          avatarKey: avatarKey,
        ),
        size: 38,
        borderRadius: BorderRadius.circular(8),
        contentDescription: name,
      ),
      title: Text(
        name,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(color: colors.textPrimary),
      ),
      subtitle: Text(
        summary,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(color: colors.textSecondary),
      ),
      trailing: trailing,
    );
  }
}

class _ComposerChip extends StatelessWidget {
  const _ComposerChip({
    super.key,
    required this.icon,
    required this.label,
    required this.onTap,
    this.active = false,
    this.trailingIcon,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final bool active;
  final IconData? trailingIcon;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(16),
      child: Container(
        constraints: const BoxConstraints(maxWidth: 260),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
        decoration: BoxDecoration(
          color: active
              ? colors.brand.withValues(alpha: 0.10)
              : colors.surfaceHigh,
          borderRadius: BorderRadius.circular(16),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 16, color: colors.brand),
            const SizedBox(width: 6),
            Flexible(
              child: Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: textTheme.labelMedium?.copyWith(
                  color: colors.textPrimary,
                ),
              ),
            ),
            if (trailingIcon != null) ...[
              const SizedBox(width: 6),
              Icon(trailingIcon, size: 14, color: colors.textSecondary),
            ],
          ],
        ),
      ),
    );
  }
}

class _ToolTile extends StatelessWidget {
  const _ToolTile(this.action);

  final _GroupToolAction action;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    return InkWell(
      onTap: action.onTap,
      borderRadius: BorderRadius.circular(8),
      child: SizedBox(
        key: ValueKey('group_tool_card_${action.label}'),
        height: 92,
        child: Padding(
          padding: const EdgeInsets.only(top: 1),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                key: ValueKey('group_tool_icon_box_${action.label}'),
                width: 62,
                height: 62,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: colors.surfaceHigh.withValues(alpha: 0.62),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Icon(
                  action.icon,
                  color: colors.textPrimary,
                  size: 27,
                  semanticLabel: action.label,
                ),
              ),
              const SizedBox(height: 8),
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 82),
                child: Text(
                  action.label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  textAlign: TextAlign.center,
                  style: textTheme.labelMedium?.copyWith(
                    color: colors.textSecondary,
                    fontSize: 13,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _AiGroupSheetAction {
  const _AiGroupSheetAction({
    required this.label,
    required this.onTap,
    this.danger = false,
  });

  final String label;
  final VoidCallback onTap;
  final bool danger;
}

class _AiGroupActionSheet extends StatelessWidget {
  const _AiGroupActionSheet({
    required this.title,
    required this.actions,
  });

  final String title;
  final List<_AiGroupSheetAction> actions;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (title.isNotEmpty) ...[
              Padding(
                padding:
                    const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
                child: Text(
                  title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: colors.textSecondary,
                    fontSize: 13,
                    height: 1.31,
                    fontWeight: FontWeight.w500,
                    letterSpacing: 0,
                  ),
                ),
              ),
              const Divider(height: 1),
            ],
            for (var index = 0; index < actions.length; index++) ...[
              SizedBox(
                height: 52,
                width: double.infinity,
                child: TextButton(
                  onPressed: actions[index].onTap,
                  style: TextButton.styleFrom(
                    foregroundColor: actions[index].danger
                        ? colors.danger
                        : colors.textPrimary,
                    shape: const RoundedRectangleBorder(),
                  ),
                  child: Text(
                    actions[index].label,
                    style: TextStyle(
                      color: actions[index].danger
                          ? colors.danger
                          : colors.textPrimary,
                      fontSize: 16,
                      height: 1.35,
                      fontWeight: FontWeight.w400,
                      letterSpacing: 0,
                    ),
                  ),
                ),
              ),
              if (index < actions.length - 1) const Divider(height: 1),
            ],
          ],
        ),
      ),
    );
  }
}

class _GroupEmptyState extends StatelessWidget {
  const _GroupEmptyState();

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Center(
      child: Text(
        '暂无群聊，点右上角创建',
        style: TextStyle(color: colors.textSecondary),
      ),
    );
  }
}

class _GroupChatEmptyState extends StatelessWidget {
  const _GroupChatEmptyState({required this.group});

  final AiGroupConversation group;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final emptyMembers = group.memberCount == 0;
    return Center(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(40, 0, 40, 40),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            GroupGridAvatar(members: group.members, size: 64),
            const SizedBox(height: 16),
            Text(
              emptyMembers ? '群里还没有 AI 成员' : '群里安静得很',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: colors.textPrimary,
                fontSize: 16,
                height: 1.38,
                fontWeight: FontWeight.w500,
                letterSpacing: 0,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              emptyMembers ? '点右上角把 AI 员工拉进群，然后开聊' : '发条消息，群成员会各自回复你',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: colors.textSecondary,
                fontSize: 14,
                height: 1.36,
                letterSpacing: 0,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

extension on String {
  String ifEmpty(String fallback) => trim().isEmpty ? fallback : this;

  String take(int length) {
    final value = trim();
    return value.length <= length ? value : value.substring(0, length);
  }
}
