part of 'ai_group_screens.dart';

// 群列表页状态类。
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
        builder: (_) =>
            AiGroupChatScreen(repository: _repository, initialGroup: group),
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
            onTap: () =>
                _runGroupAction(() => _repository.markAiGroupUnread(group.id)),
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
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(error.toString())));
    }
  }
}
