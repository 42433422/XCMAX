part of 'ai_group_screens.dart';

// part 文件：群聊页状态基类（字段与分支/成员面板方法）。

abstract class _AiGroupChatStateBase extends State<AiGroupChatScreen> {
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
                  padding: const EdgeInsets.symmetric(
                    horizontal: 18,
                    vertical: 8,
                  ),
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

  void _showSnack(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), behavior: SnackBarBehavior.floating),
    );
  }
}
