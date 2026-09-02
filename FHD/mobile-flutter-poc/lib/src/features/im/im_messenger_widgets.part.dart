part of 'im_messenger_screen.dart';

class _EmptyConversationHint extends StatelessWidget {
  const _EmptyConversationHint();

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 64),
      child: Column(
        children: [
          Container(
            width: 52,
            height: 52,
            decoration: BoxDecoration(
              color: colors.surfaceHigh,
              borderRadius: BorderRadius.circular(16),
            ),
            alignment: Alignment.center,
            child: Icon(Icons.chat_bubble_outline, color: colors.textSecondary),
          ),
          const SizedBox(height: 8),
          Text(
            '暂无消息',
            style: TextStyle(
              color: colors.textPrimary,
              fontSize: 16,
              height: 1.38,
              fontWeight: FontWeight.w500,
              letterSpacing: 0,
            ),
          ),
          Text(
            '发出第一条消息后会显示在这里',
            style: TextStyle(
              color: colors.textSecondary,
              fontSize: 13,
              height: 1.38,
              letterSpacing: 0,
            ),
          ),
        ],
      ),
    );
  }
}

class _MessageBubble extends StatelessWidget {
  const _MessageBubble(
    this.message, {
    required this.onReply,
    required this.onDelete,
  });

  final ImMessage message;
  final VoidCallback onReply;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final maxBubbleWidth = MediaQuery.sizeOf(context).width * 0.78;
    return Align(
      alignment: message.mine ? Alignment.centerRight : Alignment.centerLeft,
      child: GestureDetector(
        onLongPressStart: (details) =>
            _showActions(context, details.globalPosition),
        child: Container(
          key: ValueKey('im_bubble_${message.id}'),
          constraints: BoxConstraints(maxWidth: maxBubbleWidth),
          margin: const EdgeInsets.only(bottom: 8),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
          decoration: BoxDecoration(
            color: message.mine ? colors.brand : colors.surfaceHigh,
            borderRadius: BorderRadius.circular(14),
          ),
          child: Column(
            crossAxisAlignment: message.mine
                ? CrossAxisAlignment.end
                : CrossAxisAlignment.start,
            children: [
              Text(
                '用户 ${message.senderUserId}',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  color: message.mine
                      ? Theme.of(
                          context,
                        ).colorScheme.onPrimary.withValues(alpha: 0.72)
                      : colors.textTertiary,
                  fontSize: 11,
                  height: 1.27,
                  fontWeight: FontWeight.w500,
                  letterSpacing: 0,
                ),
              ),
              Text(
                message.body,
                style: TextStyle(
                  color: message.mine
                      ? Theme.of(context).colorScheme.onPrimary
                      : colors.textPrimary,
                  fontSize: 15,
                  height: 1.4,
                  letterSpacing: 0,
                ),
              ),
            ],
          ),
        ),
      ),
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

class _ErrorText extends StatelessWidget {
  const _ErrorText(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Text(
        text,
        style: TextStyle(
          color: colors.danger,
          fontSize: 13,
          height: 1.38,
          letterSpacing: 0,
        ),
      ),
    );
  }
}

extension on String {
  String take(int length) {
    final value = trim();
    return value.length <= length ? value : value.substring(0, length);
  }
}
