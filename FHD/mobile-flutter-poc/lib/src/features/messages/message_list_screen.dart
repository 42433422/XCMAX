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
import '../chat/chat_screen.dart';
import '../contacts/contacts_screen.dart';
import '../cs/admin_cs_console_screen.dart';
import '../cs/cs_chat_screen.dart';
import '../discover/discover_screen.dart';
import '../groups/ai_group_screens.dart';
import '../scan/scan_qr_screen.dart';

// 按职责拆分为 part 文件：页面 State、首页头部/空态、会话排序工具与行内组件组。
part 'message_list_screen_state.part.dart';
part 'message_list_screen_home.part.dart';
part 'message_list_screen_entries.part.dart';
part 'message_list_screen_widgets.part.dart';

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
                                  ? colors.textSecondary.withValues(alpha: 0.65)
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
    final visibleBadge = _visibleConversationBadge(item);
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
