part of 'ai_group_screens.dart';

// 群行、群消息气泡、输入中指示与消息 UI 常量。
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
                  width: MessageAvatarLayout.conversationAvatarTextGap,
                ),
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
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('已复制')));
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
          child: Icon(Icons.group, size: 22, color: colors.textTertiary),
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
