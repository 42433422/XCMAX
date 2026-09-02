// part 文件：客服聊天空态与消息气泡。

part of 'cs_chat_screen.dart';

class _CsEmptyState extends StatelessWidget {
  const _CsEmptyState({this.error});

  final String? error;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.support_agent, size: 48, color: colors.textTertiary),
            const SizedBox(height: 14),
            Text(
              error == null ? '向专属客服提问' : '客服消息暂时无法加载',
              style: TextStyle(
                color: colors.textSecondary,
                fontSize: 15,
                height: 1.4,
                letterSpacing: 0,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              error == null ? '客服上线后会尽快回复您' : error!,
              textAlign: TextAlign.center,
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
    );
  }
}

class _CsBubble extends StatelessWidget {
  const _CsBubble({
    required this.message,
    required this.streaming,
    required this.onReply,
    required this.onDelete,
  });

  final CsMessage message;
  final bool streaming;
  final VoidCallback onReply;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final isUser = message.isUser;
    final bubble = GestureDetector(
      onLongPressStart: (details) =>
          _showActions(context, details.globalPosition),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 260),
        child: Material(
          key: ValueKey('cs_bubble_${message.messageId}'),
          color: isUser ? colors.weChatGreen : colors.surface,
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(8),
            topRight: const Radius.circular(8),
            bottomLeft: Radius.circular(isUser ? 8 : 2),
            bottomRight: Radius.circular(isUser ? 2 : 8),
          ),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Flexible(
                  child: Text(
                    message.body,
                    style: TextStyle(
                      color: colors.textPrimary,
                      fontSize: 15,
                      height: 1.4,
                      letterSpacing: 0,
                    ),
                  ),
                ),
                if (streaming)
                  Padding(
                    padding: const EdgeInsets.only(left: 2),
                    child: Text(
                      '|',
                      style: TextStyle(
                        color: colors.brand,
                        fontSize: 15,
                        height: 1.4,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );

    return Row(
      mainAxisAlignment:
          isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (!isUser) ...[
          AppAvatar(
            fallback: AppAvatarFallback.customerService,
            size: MessageAvatarLayout.customerServiceBubbleAvatarSize,
            borderRadius: BorderRadius.circular(
              MessageAvatarLayout.customerServiceBubbleAvatarSize / 2,
            ),
            contentDescription: '客服',
          ),
          const SizedBox(
            width: MessageAvatarLayout.customerServiceBubbleAvatarGap,
          ),
        ],
        bubble,
        if (isUser) ...[
          const SizedBox(
            width: MessageAvatarLayout.customerServiceBubbleAvatarGap,
          ),
          Container(
            width: MessageAvatarLayout.customerServiceBubbleAvatarSize,
            height: MessageAvatarLayout.customerServiceBubbleAvatarSize,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: colors.divider,
              shape: BoxShape.circle,
            ),
            child: Text(
              '我',
              style: TextStyle(
                color: colors.surface,
                fontSize: 14,
                height: 1,
                fontWeight: FontWeight.w700,
              ),
            ),
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
