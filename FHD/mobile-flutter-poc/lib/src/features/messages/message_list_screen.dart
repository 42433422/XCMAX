import 'package:flutter/material.dart';

import '../../api/mobile_models.dart';
import '../../data/mobile_repository.dart';
import '../../data/mobile_repository_scope.dart';
import '../../models/conversation.dart';
import '../../policy/avatar_policy.dart';
import '../../theme/app_theme.dart';
import '../../theme/message_avatar_layout.dart';
import '../../widgets/app_avatar.dart';
import '../../widgets/group_grid_avatar.dart';
import '../bridge/bridge_screen.dart';
import '../chat/chat_screen.dart';
import '../contacts/contacts_screen.dart';
import '../cs/cs_chat_screen.dart';
import '../discover/discover_screen.dart';
import '../groups/ai_group_screens.dart';
import '../scan/scan_qr_screen.dart';

class MessageListScreen extends StatefulWidget {
  const MessageListScreen({
    super.key,
    this.groups = const [],
    required this.items,
    this.account,
    this.repository,
    this.loading = false,
    this.onRefresh,
    this.onOpenScan,
    this.onStartGroupChat,
    this.onOpenGroups,
    this.onOpenEmployees,
    this.onOpenContacts,
    this.onOpenDiscover,
  });

  final List<AiGroupConversation> groups;
  final List<ConversationItem> items;
  final MobileMeData? account;
  final MobileRepository? repository;
  final bool loading;
  final Future<void> Function()? onRefresh;
  final VoidCallback? onOpenScan;
  final VoidCallback? onStartGroupChat;
  final VoidCallback? onOpenGroups;
  final VoidCallback? onOpenEmployees;
  final VoidCallback? onOpenContacts;
  final VoidCallback? onOpenDiscover;

  @override
  State<MessageListScreen> createState() => _MessageListScreenState();
}

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
    final conversationEntries = <Object>[
      ...groups,
      ...items,
    ];
    final hasEcosystemEmployees = widget.items.any(
      (item) => item.type == ConversationType.aiTask,
    );
    final showEcosystemHint = !hasEcosystemEmployees && _query.trim().isEmpty;
    final showEmptyState = conversationEntries.isEmpty;
    final entries = <Object>[
      ...conversationEntries,
      if (showEcosystemHint) const _EcosystemSyncHintEntry(),
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
                    if (entry is _EcosystemSyncHintEntry) {
                      return _EcosystemSyncHint(
                        onRefresh: widget.onRefresh ?? () async {},
                      );
                    }
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
                    if (current is _EcosystemSyncHintEntry ||
                        next is _EcosystemSyncHintEntry ||
                        current is _ConversationEmptyEntry ||
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
        builder: (_) => AiGroupChatScreen(
          initialGroup: group,
          repository: _repository,
        ),
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
          builder: (_) => BridgeScreen.customerService(repository: _repository),
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

class _ConversationSheetAction {
  const _ConversationSheetAction({
    required this.label,
    required this.onTap,
    this.danger = false,
  });

  final String label;
  final VoidCallback onTap;
  final bool danger;
}

class _ConversationActionSheet extends StatelessWidget {
  const _ConversationActionSheet({
    required this.title,
    required this.actions,
  });

  final String title;
  final List<_ConversationSheetAction> actions;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final textTheme = theme.textTheme;
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.only(bottom: XcagiSpacing.lg),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (title.isNotEmpty) ...[
              Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: XcagiSpacing.lg,
                  vertical: XcagiSpacing.sm,
                ),
                child: Text(
                  title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  textAlign: TextAlign.center,
                  style: textTheme.labelMedium?.copyWith(
                    color: colorScheme.onSurfaceVariant,
                  ),
                ),
              ),
              Divider(
                height: 0.5,
                thickness: 0.5,
                color: colorScheme.outlineVariant,
              ),
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
                    style: textTheme.bodyLarge?.copyWith(
                      color: actions[index].danger
                          ? colors.danger
                          : colorScheme.onSurface,
                    ),
                  ),
                ),
              ),
              if (index < actions.length - 1)
                Divider(
                  height: 0.5,
                  thickness: 0.5,
                  color: colorScheme.outlineVariant,
                ),
            ],
          ],
        ),
      ),
    );
  }
}

class _MessageHomeHeader extends StatelessWidget {
  const _MessageHomeHeader({
    required this.account,
    required this.employeeCount,
    required this.query,
    required this.onQueryChanged,
    required this.onClearQuery,
    required this.onMenuSelected,
  });

  final MobileMeData account;
  final int employeeCount;
  final String query;
  final ValueChanged<String> onQueryChanged;
  final VoidCallback onClearQuery;
  final ValueChanged<String> onMenuSelected;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final textTheme = theme.textTheme;
    return Padding(
      key: const ValueKey('message_home_header_padding'),
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 10),
      child: Column(
        children: [
          Row(
            children: [
              AppAvatar(
                imageSource: account.avatarSource,
                fallback: AppAvatarFallback.user,
                size: MessageAvatarLayout.headerAvatarSize,
                borderRadius: MessageAvatarLayout.headerAvatarRadius,
                contentDescription: account.displayName.ifEmpty('admin'),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      account.displayName.ifEmpty('admin'),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: textTheme.titleLarge?.copyWith(
                        color: colorScheme.onSurface,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      _messageHeaderSubtitle(account, employeeCount),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: textTheme.labelMedium?.copyWith(
                        color: colors.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
              _HeaderPlusMenu(onSelected: onMenuSelected),
            ],
          ),
          const SizedBox(
            key: ValueKey('message_home_header_search_gap'),
            height: 12,
          ),
          _SearchBarField(
            value: query,
            onValueChanged: onQueryChanged,
            onClear: onClearQuery,
          ),
        ],
      ),
    );
  }
}

String _messageHeaderSubtitle(MobileMeData account, int employeeCount) {
  final buffer = StringBuffer(
    account.accountKindLabel.trim().isEmpty ? '未登录' : account.accountKindLabel,
  );
  if (employeeCount > 0) {
    buffer.write(' · $employeeCount位AI员工');
  }
  return buffer.toString();
}

class _EcosystemSyncHintEntry {
  const _EcosystemSyncHintEntry();
}

class _ConversationEmptyEntry {
  const _ConversationEmptyEntry({required this.loading});

  final bool loading;
}

class _EcosystemSyncHint extends StatelessWidget {
  const _EcosystemSyncHint({required this.onRefresh});

  final Future<void> Function() onRefresh;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    return Material(
      color: colors.surface,
      child: InkWell(
        onTap: onRefresh,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          child: Row(
            children: [
              Container(
                width: 34,
                height: 34,
                decoration: BoxDecoration(
                  color: colors.surfaceHigh,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Icon(
                  Icons.sync,
                  size: 19,
                  color: colors.textTertiary,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '账号生态待同步',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: textTheme.bodyMedium?.copyWith(
                        color: colors.textPrimary,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '点这里重新同步管理端员工。',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: textTheme.bodySmall?.copyWith(
                        color: colors.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ConversationEmptyState extends StatelessWidget {
  const _ConversationEmptyState({required this.loading});

  final bool loading;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    return SizedBox(
      height: 420,
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (loading) ...[
              SizedBox(
                width: 28,
                height: 28,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: colors.brand,
                ),
              ),
              const SizedBox(height: 8),
            ],
            Text(
              loading ? '正在同步会话…' : '暂无会话',
              style: textTheme.bodyLarge?.copyWith(
                color: colors.textSecondary,
              ),
            ),
            if (!loading) ...[
              const SizedBox(height: 8),
              Text(
                '下拉刷新或和小C助理聊聊吧',
                style: textTheme.bodyMedium?.copyWith(
                  color: colors.textTertiary,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class GroupConversationRow extends StatelessWidget {
  const GroupConversationRow({
    super.key,
    required this.group,
    required this.onTap,
    this.onLongPress,
  });

  final AiGroupConversation group;
  final VoidCallback onTap;
  final VoidCallback? onLongPress;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    final preview = _textOrFallback(
      group.preview,
      group.memberCount == 0
          ? '还没有成员，进群把 AI 拉进来'
          : '${group.memberCount} 个 AI 成员在群里',
    );

    return Material(
      color: group.isPinned ? colors.surfaceHigh : colors.surface,
      child: InkWell(
        onTap: onTap,
        onLongPress: onLongPress,
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: MessageAvatarLayout.conversationRowHorizontalPadding,
            vertical: MessageAvatarLayout.conversationRowVerticalPadding,
          ),
          child: Row(
            children: [
              GroupGridAvatar(members: group.members),
              const SizedBox(
                width: MessageAvatarLayout.conversationAvatarTextGap,
              ),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
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
                        Flexible(
                          child: Text(
                            group.name,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: textTheme.bodyLarge?.copyWith(
                              color: group.isHidden
                                  ? colors.textSecondary.withValues(
                                      alpha: 0.65,
                                    )
                                  : !group.isFollowed
                                      ? colors.textSecondary
                                      : colors.textPrimary,
                              fontWeight: FontWeight.w500,
                            ),
                          ),
                        ),
                        if (group.memberCount > 0) ...[
                          const SizedBox(width: 6),
                          Text(
                            '(${group.memberCount})',
                            style: textTheme.labelMedium?.copyWith(
                              color: colors.textSecondary,
                            ),
                          ),
                        ],
                      ],
                    ),
                    const SizedBox(height: 3),
                    Text(
                      preview,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: textTheme.bodySmall?.copyWith(
                        color: colors.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              _GroupTrailing(group: group),
            ],
          ),
        ),
      ),
    );
  }
}

class ConversationRowTile extends StatelessWidget {
  const ConversationRowTile({
    super.key,
    required this.item,
    required this.onTap,
    this.onLongPress,
  });

  final ConversationItem item;
  final VoidCallback onTap;
  final VoidCallback? onLongPress;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    final hasUnread = item.unreadCount > 0;
    final background = item.isPinned ? colors.surfaceHigh : colors.surface;
    final visibleBadge =
        item.badgeText == null || item.badgeText == item.timestampText
            ? null
            : item.badgeText;
    final titleColor = item.isHidden
        ? colors.textSecondary.withValues(alpha: 0.65)
        : !item.isFollowed
            ? colors.textSecondary
            : colors.textPrimary;

    return Material(
      color: background,
      child: InkWell(
        onTap: onTap,
        onLongPress: onLongPress,
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: MessageAvatarLayout.conversationRowHorizontalPadding,
            vertical: MessageAvatarLayout.conversationRowVerticalPadding,
          ),
          child: Row(
            children: [
              _AvatarStack(item: item),
              const SizedBox(
                width: MessageAvatarLayout.conversationAvatarTextGap,
              ),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            item.title,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: textTheme.titleMedium?.copyWith(
                              color: titleColor,
                              fontWeight:
                                  hasUnread ? FontWeight.w700 : FontWeight.w600,
                            ),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Text(
                          item.timestampText,
                          style: textTheme.labelMedium?.copyWith(
                            color: hasUnread
                                ? colors.textStrongSecondary
                                : colors.textSecondary,
                            fontWeight:
                                hasUnread ? FontWeight.w500 : FontWeight.w400,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 5),
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            item.subtitle,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: textTheme.bodyMedium?.copyWith(
                              color: hasUnread
                                  ? colors.textSecondary
                                  : colors.textStrongSecondary,
                              fontWeight:
                                  hasUnread ? FontWeight.w500 : FontWeight.w400,
                            ),
                          ),
                        ),
                        if (visibleBadge != null) ...[
                          const SizedBox(width: 8),
                          _StatusBadge(
                            text: visibleBadge,
                            color: item.badgeColor == null
                                ? colors.weChatOnline
                                : Color(item.badgeColor!),
                          ),
                        ],
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

String _textOrFallback(String value, String fallback) {
  final trimmed = value.trim();
  return trimmed.isEmpty ? fallback : trimmed;
}

class _GroupTrailing extends StatelessWidget {
  const _GroupTrailing({required this.group});

  final AiGroupConversation group;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    if (group.unreadCount > 0) {
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
        decoration: BoxDecoration(
          color: colors.danger,
          borderRadius: BorderRadius.circular(10),
        ),
        child: Text(
          group.unreadCount > 99 ? '99+' : '${group.unreadCount}',
          style: textTheme.labelSmall?.copyWith(
            color: Colors.white,
            fontSize: 10,
          ),
        ),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.end,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          group.timestampText,
          style: textTheme.labelSmall?.copyWith(
            color: colors.textSecondary.withValues(alpha: 0.7),
            fontWeight: FontWeight.w400,
          ),
        ),
        if (!group.isFollowed) ...[
          const SizedBox(height: 4),
          Text(
            '不再关注',
            style: textTheme.labelSmall?.copyWith(
              color: colors.textSecondary.withValues(alpha: 0.6),
              fontSize: 10,
              fontWeight: FontWeight.w400,
            ),
          ),
        ],
      ],
    );
  }
}

class _HeaderPlusMenu extends StatelessWidget {
  const _HeaderPlusMenu({required this.onSelected});

  final ValueChanged<String> onSelected;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return PopupMenuButton<String>(
      tooltip: '更多',
      onSelected: onSelected,
      color: colors.surface,
      elevation: 12,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      position: PopupMenuPosition.under,
      constraints: const BoxConstraints.tightFor(width: 188),
      menuPadding: EdgeInsets.zero,
      itemBuilder: (context) => const [
        PopupMenuItem(
          value: 'group',
          padding: EdgeInsets.zero,
          height: 43,
          child: _PlusMenuRow(Icons.groups, '发起群聊'),
        ),
        PopupMenuItem(
          value: 'groups',
          padding: EdgeInsets.zero,
          height: 43,
          child: _PlusMenuRow(Icons.group, '我的群聊'),
        ),
        PopupMenuItem(
          value: 'scan',
          padding: EdgeInsets.zero,
          height: 43,
          child: _PlusMenuRow(Icons.qr_code_scanner, '扫一扫'),
        ),
        PopupMenuItem(
          value: 'employees',
          padding: EdgeInsets.zero,
          height: 43,
          child: _PlusMenuRow(Icons.smart_toy, 'AI 员工'),
        ),
        PopupMenuItem(
          value: 'contacts',
          padding: EdgeInsets.zero,
          height: 43,
          child: _PlusMenuRow(Icons.contacts, '通讯录'),
        ),
        PopupMenuItem(
          value: 'circle',
          padding: EdgeInsets.zero,
          height: 43,
          child: _PlusMenuRow(Icons.public, '交流圈'),
        ),
      ],
      child: SizedBox.square(
        key: const ValueKey('message_header_plus_button'),
        dimension: 48,
        child: Icon(Icons.add, color: colors.textPrimary, size: 24),
      ),
    );
  }
}

class _PlusMenuRow extends StatelessWidget {
  const _PlusMenuRow(this.icon, this.label);

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    return Padding(
      key: ValueKey('message_plus_menu_row_$label'),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 11),
      child: Row(
        children: [
          Icon(icon, color: colors.brand, size: 20),
          const SizedBox(width: 14),
          Text(
            label,
            style: textTheme.bodyMedium?.copyWith(
              color: colors.textPrimary,
            ),
          ),
        ],
      ),
    );
  }
}

class _SearchBarField extends StatefulWidget {
  const _SearchBarField({
    required this.value,
    required this.onValueChanged,
    required this.onClear,
  });

  final String value;
  final ValueChanged<String> onValueChanged;
  final VoidCallback onClear;

  @override
  State<_SearchBarField> createState() => _SearchBarFieldState();
}

class _SearchBarFieldState extends State<_SearchBarField> {
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.value);
  }

  @override
  void didUpdateWidget(covariant _SearchBarField oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.value == _controller.text) return;
    _controller.value = TextEditingValue(
      text: widget.value,
      selection: TextSelection.collapsed(offset: widget.value.length),
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    return Container(
      height: 38,
      decoration: BoxDecoration(
        color: colors.surfaceHigh,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: colors.divider, width: 0.5),
      ),
      child: Row(
        children: [
          const SizedBox(width: 14),
          Icon(Icons.search, size: 20, color: colors.textTertiary),
          const SizedBox(width: 8),
          Expanded(
            child: TextField(
              controller: _controller,
              onChanged: widget.onValueChanged,
              maxLines: 1,
              textAlignVertical: TextAlignVertical.center,
              style: textTheme.bodyMedium?.copyWith(
                color: colors.textPrimary,
              ),
              decoration: InputDecoration(
                isCollapsed: true,
                border: InputBorder.none,
                hintText: '查找会话或伙伴',
                hintStyle: textTheme.bodyMedium?.copyWith(
                  color: colors.textTertiary,
                ),
              ),
            ),
          ),
          if (widget.value.isNotEmpty)
            InkWell(
              onTap: widget.onClear,
              borderRadius: BorderRadius.circular(9),
              child: Container(
                width: 18,
                height: 18,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: colors.divider,
                  shape: BoxShape.circle,
                ),
                child: Text(
                  '×',
                  style: TextStyle(
                    color: colors.surface,
                    fontSize: 12,
                    height: 1,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ),
          const SizedBox(width: 14),
        ],
      ),
    );
  }
}

class _AvatarStack extends StatelessWidget {
  const _AvatarStack({required this.item});

  final ConversationItem item;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return SizedBox.square(
      key: ValueKey('conversation_avatar_stack_${item.id}'),
      dimension: MessageAvatarLayout.conversationAvatarSize,
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          AppAvatar(
            imageSource: item.type.usesPinnedAvatar ? null : item.avatarUrl,
            fallback: item.type.usesPinnedAvatar
                ? item.type.avatarFallback
                : employeeAvatarFallback(employeeId: item.id, name: item.title),
            size: MessageAvatarLayout.conversationAvatarSize,
            borderRadius: MessageAvatarLayout.conversationAvatarRadius,
            contentDescription: item.title,
          ),
          if (item.unreadCount > 0)
            Positioned(
              top: MessageAvatarLayout.unreadBadgeOffsetY,
              right: -MessageAvatarLayout.unreadBadgeOffsetX,
              child: UnreadBadge(count: item.unreadCount),
            ),
          if (item.isOnline && item.type == ConversationType.pinnedCs)
            Positioned(
              right: 0,
              bottom: MessageAvatarLayout.onlineIndicatorOffsetY,
              child: Container(
                width: MessageAvatarLayout.onlineIndicatorSize,
                height: MessageAvatarLayout.onlineIndicatorSize,
                padding: const EdgeInsets.all(
                  MessageAvatarLayout.onlineIndicatorPadding,
                ),
                decoration: BoxDecoration(
                  color: colors.surface,
                  shape: BoxShape.circle,
                ),
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    color: colors.weChatOnline,
                    shape: BoxShape.circle,
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _StatusBadge extends StatelessWidget {
  const _StatusBadge({required this.text, required this.color});

  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    return Container(
      key: ValueKey('conversation_status_badge_$text'),
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        border: Border.all(
          color: color.withValues(alpha: 0.30),
          width: 0.5,
        ),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Text(
        text,
        style: textTheme.labelSmall?.copyWith(
          color: color,
          fontSize: 11,
          fontWeight: FontWeight.w500,
        ),
      ),
    );
  }
}
