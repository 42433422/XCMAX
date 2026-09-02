part of 'chat_screen.dart';

// 消息操作菜单、relay 进度卡与回复预览条组件。
class _MessageActionMenu extends StatelessWidget {
  const _MessageActionMenu({
    required this.text,
    required this.onReply,
    required this.onDelete,
    required this.child,
  });

  final String text;
  final VoidCallback onReply;
  final VoidCallback onDelete;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      behavior: HitTestBehavior.translucent,
      onLongPressStart: (details) async {
        if (text.trim().isEmpty) return;
        final selected = await showMenu<String>(
          context: context,
          position: RelativeRect.fromLTRB(
            details.globalPosition.dx,
            details.globalPosition.dy,
            details.globalPosition.dx,
            details.globalPosition.dy,
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
            await Clipboard.setData(ClipboardData(text: text));
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
      },
      child: child,
    );
  }
}

/// 长任务（relay dev-loop）内嵌进度卡：步骤列表 + 进度条 + 中断按钮。
class _RelayProgressCard extends StatelessWidget {
  const _RelayProgressCard({
    required this.progress,
    required this.cancelling,
    required this.onCancel,
  });

  final RelayTaskProgress progress;
  final bool cancelling;
  final VoidCallback? onCancel;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final steps = _stepsForStatus(progress.status);
    final activeIndex = _activeIndexForStatus(progress.status);
    return Container(
      constraints: const BoxConstraints(maxWidth: 236),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: colors.page,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: colors.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              SizedBox(
                width: 14,
                height: 14,
                child: cancelling
                    ? CircularProgressIndicator(
                        strokeWidth: 2,
                        valueColor: AlwaysStoppedAnimation(colors.danger),
                      )
                    : (progress.status == 'completed'
                        ? Icon(
                            Icons.check_circle,
                            size: 14,
                            color: colors.success,
                          )
                        : SizedBox(
                            width: 14,
                            height: 14,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              valueColor: AlwaysStoppedAnimation(
                                colors.brand,
                              ),
                            ),
                          )),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  _titleForStatus(progress.status),
                  style: TextStyle(
                    color: colors.textPrimary,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              if (onCancel != null &&
                  progress.status != 'completed' &&
                  progress.status != 'failed' &&
                  progress.status != 'cancelled')
                GestureDetector(
                  onTap: onCancel,
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 6,
                      vertical: 2,
                    ),
                    decoration: BoxDecoration(
                      color: colors.danger.withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text(
                      cancelling ? '取消中' : '中断',
                      style: TextStyle(
                        color: colors.danger,
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 8),
          for (var i = 0; i < steps.length; i++) ...[
            _StepRow(
              label: steps[i],
              state: _stepState(i, activeIndex, progress.status),
              isLast: i == steps.length - 1,
            ),
          ],
        ],
      ),
    );
  }

  String _titleForStatus(String status) {
    switch (status) {
      case 'queued':
        return '${progress.toolLabel} 任务排队中';
      case 'running':
      case 'assigned':
        return '${progress.toolLabel} 正在执行';
      case 'resuming':
        return '${progress.toolLabel} 恢复中';
      case 'completed':
        return '${progress.toolLabel} 已完成';
      case 'failed':
        return '${progress.toolLabel} 执行失败';
      case 'blocked':
        return '${progress.toolLabel} 已阻塞';
      case 'cancelled':
        return '${progress.toolLabel} 已取消';
      default:
        return progress.toolLabel;
    }
  }

  List<String> _stepsForStatus(String status) {
    return const ['创建任务', '排队等待', '电脑执行', '回写结果'];
  }

  int _activeIndexForStatus(String status) {
    switch (status) {
      case 'queued':
        return 1;
      case 'running':
      case 'assigned':
        return 2;
      case 'completed':
        return 4;
      case 'failed':
      case 'blocked':
      case 'cancelled':
        return -1;
      default:
        return 0;
    }
  }

  _StepState _stepState(int index, int activeIndex, String status) {
    if (status == 'failed' || status == 'blocked' || status == 'cancelled') {
      if (index == activeIndex - 1 || index == activeIndex) {
        return _StepState.failed;
      }
    }
    if (index < activeIndex) return _StepState.done;
    if (index == activeIndex) return _StepState.active;
    return _StepState.pending;
  }
}

enum _StepState { pending, active, done, failed }

class _StepRow extends StatelessWidget {
  const _StepRow({
    required this.label,
    required this.state,
    required this.isLast,
  });

  final String label;
  final _StepState state;
  final bool isLast;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final iconColor = switch (state) {
      _StepState.done => colors.success,
      _StepState.active => colors.brand,
      _StepState.failed => colors.danger,
      _StepState.pending => colors.textTertiary,
    };
    final labelColor = switch (state) {
      _StepState.done => colors.textSecondary,
      _StepState.active => colors.textPrimary,
      _StepState.failed => colors.danger,
      _StepState.pending => colors.textTertiary,
    };
    return Row(
      children: [
        SizedBox(
          width: 16,
          child: Column(
            children: [
              if (state == _StepState.active)
                SizedBox(
                  width: 10,
                  height: 10,
                  child: CircularProgressIndicator(
                    strokeWidth: 1.5,
                    valueColor: AlwaysStoppedAnimation(iconColor),
                  ),
                )
              else
                Icon(
                  state == _StepState.done
                      ? Icons.check_circle
                      : state == _StepState.failed
                          ? Icons.cancel
                          : Icons.radio_button_unchecked,
                  size: 12,
                  color: iconColor,
                ),
              if (!isLast)
                Container(width: 1, height: 8, color: colors.divider),
            ],
          ),
        ),
        const SizedBox(width: 6),
        Text(
          label,
          style: TextStyle(
            color: labelColor,
            fontSize: 11,
            fontWeight:
                state == _StepState.active ? FontWeight.w600 : FontWeight.w400,
          ),
        ),
      ],
    );
  }
}

class _ReplyPreviewBar extends StatelessWidget {
  const _ReplyPreviewBar({required this.message, required this.onCancel});

  final ChatMessage message;
  final VoidCallback onCancel;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final sender = message.role == ChatRole.user ? '我' : '对方';
    return Container(
      color: colors.surface,
      padding: const EdgeInsets.fromLTRB(12, 6, 8, 6),
      child: Row(
        children: [
          Container(
            width: 3,
            height: 28,
            decoration: BoxDecoration(
              color: colors.brand,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              '引用 $sender：${message.body}',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: colors.textSecondary,
                fontSize: 13,
                height: 1.31,
                letterSpacing: 0,
              ),
            ),
          ),
          IconButton(
            onPressed: onCancel,
            icon: const Icon(Icons.close, size: 18),
            color: colors.textSecondary,
            tooltip: '取消引用',
            constraints: const BoxConstraints.tightFor(width: 32, height: 32),
            padding: EdgeInsets.zero,
          ),
        ],
      ),
    );
  }
}
