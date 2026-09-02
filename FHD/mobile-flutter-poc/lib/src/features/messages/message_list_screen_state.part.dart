part of 'message_list_screen.dart';

// 消息首页状态类。
class _MessageListScreenState extends State<MessageListScreen> {
  String _query = '';
  MobileRepository? _fallbackRepository;

  MobileRepository get _repository =>
      widget.repository ??
      MobileRepositoryScope.maybeRead(context) ??
      (_fallbackRepository ??= MobileRepository());

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final colorScheme = Theme.of(context).colorScheme;
    final groups = widget.groups.where(_matchesGroupQuery).toList();
    final items = widget.items.where(_matchesQuery).toList();
    final conversationEntries = _sortMessageEntries(groups, items);
    final showEmptyState = conversationEntries.isEmpty;
    final entries = <Object>[
      ...conversationEntries,
      if (showEmptyState) _ConversationEmptyEntry(loading: widget.loading),
    ];
    final employeeCount = widget.items
        .where((item) => item.type == ConversationType.aiTask)
        .length;

    return SafeArea(
      bottom: false,
      child: ColoredBox(
        key: const ValueKey('message_list_surface'),
        color: colors.surface,
        child: Column(
          children: [
            _MessageHomeHeader(
              account: widget.account ?? MobileMeData.adminFallback(),
              employeeCount: employeeCount,
              query: _query,
              onQueryChanged: (value) => setState(() => _query = value),
              onClearQuery: () => setState(() => _query = ''),
              onMenuSelected: _handleHeaderMenu,
            ),
            Expanded(
              child: RefreshIndicator(
                onRefresh: widget.onRefresh ?? () async {},
                color: colors.brand,
                child: ListView.separated(
                  physics: const AlwaysScrollableScrollPhysics(),
                  padding: EdgeInsets.zero,
                  itemBuilder: (context, index) {
                    final entry = entries[index];
                    if (entry is _ConversationEmptyEntry) {
                      return _ConversationEmptyState(loading: entry.loading);
                    }
                    if (entry is AiGroupConversation) {
                      return GroupConversationRow(
                        group: entry,
                        onTap: () => _openGroup(entry),
                        onLongPress: () => _showGroupActions(entry),
                      );
                    }
                    final item = entry as ConversationItem;
                    return ConversationRowTile(
                      item: item,
                      onTap: () => _openConversation(item),
                      onLongPress: () => _showConversationActions(item),
                    );
                  },
                  separatorBuilder: (_, index) {
                    final current = entries[index];
                    final next = entries[index + 1];
                    if (current is _ConversationEmptyEntry ||
                        next is _ConversationEmptyEntry) {
                      return const SizedBox.shrink();
                    }
                    return Divider(
                      height: 0.5,
                      thickness: 0.5,
                      indent: MessageAvatarLayout.conversationDividerStart,
                      color: colorScheme.outlineVariant,
                    );
                  },
                  itemCount: entries.length,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  bool _matchesQuery(ConversationItem item) {
    final keyword = _query.trim().toLowerCase();
    if (keyword.isEmpty) return true;
    return item.title.toLowerCase().contains(keyword) ||
        item.subtitle.toLowerCase().contains(keyword);
  }

  bool _matchesGroupQuery(AiGroupConversation group) {
    final keyword = _query.trim().toLowerCase();
    if (keyword.isEmpty) return true;
    return group.name.toLowerCase().contains(keyword);
  }

  void _openGroup(AiGroupConversation group) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) =>
            AiGroupChatScreen(initialGroup: group, repository: _repository),
      ),
    );
  }

  void _openConversation(ConversationItem item) {
    if (item.type == ConversationType.pinnedCs) {
      Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => CsChatScreen(repository: _repository),
        ),
      );
      return;
    }
    if (_isAdminCustomerServiceConversation(item)) {
      Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => AdminCsConsoleScreen(repository: _repository),
        ),
      );
      return;
    }
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ChatScreen(
          conversation: item,
          initialMessages: const [],
          repository: _repository,
        ),
      ),
    );
  }

  bool _isAdminCustomerServiceConversation(ConversationItem item) {
    return item.type == ConversationType.aiTask &&
        item.id.split(':').last == 'user-customer-service-officer';
  }

  Future<void> _handleHeaderMenu(String value) async {
    switch (value) {
      case 'group':
        final callback = widget.onStartGroupChat;
        if (callback != null) {
          callback();
          return;
        }
        await Navigator.of(context).push<AiGroupConversation>(
          MaterialPageRoute(
            builder: (_) => AiGroupCreateScreen(repository: _repository),
          ),
        );
        await widget.onRefresh?.call();
        return;
      case 'groups':
        final callback = widget.onOpenGroups;
        if (callback != null) {
          callback();
          return;
        }
        await Navigator.of(context).push<void>(
          MaterialPageRoute(
            builder: (_) => AiGroupListScreen(
              repository: _repository,
              initialGroups: widget.groups,
            ),
          ),
        );
        await widget.onRefresh?.call();
        return;
      case 'scan':
        final callback = widget.onOpenScan;
        if (callback != null) {
          callback();
          return;
        }
        await Navigator.of(context).push<void>(
          MaterialPageRoute(
            builder: (_) => ScanQrScreen(repository: _repository),
          ),
        );
        return;
      case 'employees':
        final callback = widget.onOpenEmployees;
        if (callback != null) {
          callback();
          return;
        }
        await Navigator.of(context).push<void>(
          MaterialPageRoute(
            builder: (routeContext) => AiEmployeesScreen(
              repository: _repository,
              onBack: () => Navigator.of(routeContext).pop(),
            ),
          ),
        );
        return;
      case 'contacts':
        final callback = widget.onOpenContacts;
        if (callback != null) {
          callback();
          return;
        }
        await Navigator.of(context).push<void>(
          MaterialPageRoute(
            builder: (routeContext) => AiEmployeesScreen(
              repository: _repository,
              onBack: () => Navigator.of(routeContext).pop(),
            ),
          ),
        );
        return;
      case 'circle':
        final callback = widget.onOpenDiscover;
        if (callback != null) {
          callback();
          return;
        }
        await Navigator.of(context).push<void>(
          MaterialPageRoute(
            builder: (_) => DiscoverScreen(repository: _repository),
          ),
        );
        return;
      default:
        return;
    }
  }

  void _showGroupActions(AiGroupConversation group) {
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: AppTheme.colors(context).surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
      ),
      builder: (sheetContext) => _ConversationActionSheet(
        title: group.name.isEmpty ? '群聊操作' : group.name,
        actions: [
          _ConversationSheetAction(
            label: '标为未读',
            onTap: () => _runSheetAction(
              sheetContext,
              (repo) => repo.markAiGroupUnread(group.id),
            ),
          ),
          _ConversationSheetAction(
            label: group.isPinned ? '取消置顶' : '置顶聊天',
            onTap: () => _runSheetAction(
              sheetContext,
              (repo) => repo.toggleAiGroupPin(group.id),
            ),
          ),
          _ConversationSheetAction(
            label: group.isFollowed ? '不再关注' : '恢复关注',
            onTap: () => _runSheetAction(
              sheetContext,
              (repo) => repo.toggleAiGroupFollowed(group.id),
            ),
          ),
          _ConversationSheetAction(
            label: group.isHidden ? '显示该聊天' : '不显示该聊天',
            onTap: () => _runSheetAction(
              sheetContext,
              (repo) => repo.toggleAiGroupHidden(group.id),
            ),
          ),
          _ConversationSheetAction(
            label: '删除该聊天',
            danger: true,
            onTap: () => _runSheetAction(
              sheetContext,
              (repo) => repo.deleteAiGroup(group.id),
            ),
          ),
        ],
      ),
    );
  }

  void _showConversationActions(ConversationItem item) {
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: AppTheme.colors(context).surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
      ),
      builder: (sheetContext) => _ConversationActionSheet(
        title: item.title.isEmpty ? '会话操作' : item.title,
        actions: [
          _ConversationSheetAction(
            label: item.unreadCount > 0 ? '标为已读' : '标为未读',
            onTap: () => _runSheetAction(
              sheetContext,
              (repo) => repo.toggleConversationUnread(item),
            ),
          ),
          _ConversationSheetAction(
            label: item.isPinned ? '取消置顶' : '置顶聊天',
            onTap: () => _runSheetAction(
              sheetContext,
              (repo) => repo.toggleConversationPin(item.id),
            ),
          ),
          _ConversationSheetAction(
            label: item.isFollowed ? '不再关注' : '恢复关注',
            onTap: () => _runSheetAction(
              sheetContext,
              (repo) => repo.toggleConversationFollowed(item.id),
            ),
          ),
          _ConversationSheetAction(
            label: item.isHidden ? '显示该聊天' : '不显示该聊天',
            onTap: () => _runSheetAction(
              sheetContext,
              (repo) => repo.toggleConversationHidden(item.id),
            ),
          ),
          _ConversationSheetAction(
            label: '删除该聊天',
            danger: true,
            onTap: () => _runSheetAction(
              sheetContext,
              (repo) => repo.deleteConversation(item.id),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _runSheetAction(
    BuildContext sheetContext,
    Future<void> Function(MobileRepository repository) task,
  ) async {
    Navigator.of(sheetContext).pop();
    try {
      await task(_repository);
      await widget.onRefresh?.call();
    } catch (error) {
      if (!mounted) return;
      final message = error is MobileRepositoryException
          ? error.message
          : error.toString().replaceFirst('Exception: ', '');
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(message.isEmpty ? '操作失败' : message)),
      );
    }
  }
}
