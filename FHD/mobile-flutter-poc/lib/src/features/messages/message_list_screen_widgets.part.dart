part of 'message_list_screen.dart';

// 群行尾组件、加号菜单、搜索栏与头像堆叠/状态徽标组件。
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
            style: textTheme.bodyMedium?.copyWith(color: colors.textPrimary),
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
              style: textTheme.bodyMedium?.copyWith(color: colors.textPrimary),
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
        border: Border.all(color: color.withValues(alpha: 0.30), width: 0.5),
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
