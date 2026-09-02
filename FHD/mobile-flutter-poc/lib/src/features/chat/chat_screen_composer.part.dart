part of 'chat_screen.dart';

// 输入区与 git 操作条组件。
class _Composer extends StatelessWidget {
  const _Composer({
    required this.controller,
    required this.onSend,
    required this.onStop,
    required this.busy,
    this.topContent,
    required this.showTools,
    required this.onToggleTools,
    required this.onVoice,
    required this.toolActions,
  });

  final TextEditingController controller;
  final VoidCallback onSend;
  final VoidCallback onStop;
  final bool busy;
  final Widget? topContent;
  final bool showTools;
  final VoidCallback onToggleTools;
  final VoidCallback onVoice;
  final List<_ChatToolAction> toolActions;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final textTheme = theme.textTheme;
    return SafeArea(
      top: false,
      child: Container(
        key: const ValueKey('chat_composer_surface'),
        decoration: BoxDecoration(
          color: colors.surface,
          border: Border(
            top: BorderSide(color: colorScheme.outlineVariant, width: 0.5),
          ),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (topContent != null) topContent!,
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
              child: Row(
                children: [
                  _ComposerIconButton(
                    icon: Icons.mic,
                    onPressed: onVoice,
                    tooltip: '语音',
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Container(
                      height: 38,
                      decoration: BoxDecoration(
                        color: colors.surface,
                        borderRadius: BorderRadius.circular(10),
                      ),
                      alignment: Alignment.center,
                      child: TextField(
                        controller: controller,
                        maxLines: 1,
                        style: textTheme.bodyMedium?.copyWith(
                          color: colors.textPrimary,
                          fontSize: 15,
                        ),
                        decoration: InputDecoration(
                          isDense: true,
                          hintText: '发消息',
                          hintStyle: textTheme.bodyMedium?.copyWith(
                            color: colors.textSecondary,
                            fontSize: 15,
                          ),
                          border: InputBorder.none,
                          contentPadding: const EdgeInsets.symmetric(
                            horizontal: 12,
                          ),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 6),
                  _ComposerIconButton(
                    icon: Icons.add,
                    iconSize: 26,
                    selected: showTools,
                    onPressed: onToggleTools,
                    tooltip: '更多工具',
                  ),
                  ValueListenableBuilder<TextEditingValue>(
                    valueListenable: controller,
                    builder: (context, value, _) {
                      final canSend = value.text.trim().isNotEmpty && !busy;
                      if (!canSend && !busy) return const SizedBox.shrink();
                      return Padding(
                        padding: const EdgeInsets.only(left: 6),
                        child: _SendPill(
                          canStop: busy,
                          onSend: onSend,
                          onStop: onStop,
                        ),
                      );
                    },
                  ),
                ],
              ),
            ),
            if (showTools && toolActions.isNotEmpty)
              _ChatToolCardPanel(actions: toolActions),
          ],
        ),
      ),
    );
  }
}

class _ComposerIconButton extends StatelessWidget {
  const _ComposerIconButton({
    required this.icon,
    required this.onPressed,
    required this.tooltip,
    this.iconSize = 22,
    this.selected = false,
  });

  final IconData icon;
  final VoidCallback? onPressed;
  final String tooltip;
  final double iconSize;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return SizedBox(
      width: 38,
      height: 38,
      child: IconButton(
        onPressed: onPressed,
        padding: EdgeInsets.zero,
        icon: Icon(icon, size: iconSize),
        color: selected ? colors.brand : colors.textPrimary,
        tooltip: tooltip,
      ),
    );
  }
}

class _ChatGitActionBar extends StatelessWidget {
  const _ChatGitActionBar({
    required this.branch,
    required this.branches,
    required this.running,
    required this.onSelectBranch,
    required this.onDiff,
    required this.onMerge,
    required this.onDiscard,
  });

  final String branch;
  final List<String> branches;
  final bool running;
  final VoidCallback? onSelectBranch;
  final VoidCallback onDiff;
  final VoidCallback onMerge;
  final VoidCallback onDiscard;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final selectable = onSelectBranch != null && branches.length > 1;
    final suffix = _shortGitBranchLabel(branch);
    return Padding(
      padding: const EdgeInsets.fromLTRB(10, 8, 10, 2),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          InkWell(
            borderRadius: BorderRadius.circular(8),
            onTap: selectable ? onSelectBranch : null,
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.call_merge, size: 13, color: colors.textSecondary),
                  const SizedBox(width: 4),
                  Flexible(
                    child: Text(
                      selectable
                          ? '开发任务分支 · $suffix（点此切换）'
                          : '开发任务分支 · $suffix',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        color: colors.textSecondary,
                        fontSize: 11,
                        height: 1.27,
                        letterSpacing: 0,
                      ),
                    ),
                  ),
                  if (selectable)
                    Icon(
                      Icons.chevron_right,
                      size: 16,
                      color: colors.textSecondary,
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 6),
          Row(
            children: [
              _GitActionChip(
                label: '查看 diff',
                icon: Icons.difference,
                color: colors.textPrimary,
                onTap: running ? null : onDiff,
              ),
              const SizedBox(width: 8),
              _GitActionChip(
                label: '合并到主干',
                icon: Icons.call_merge,
                color: colors.brand,
                filled: true,
                onTap: running ? null : onMerge,
              ),
              const SizedBox(width: 8),
              _GitActionChip(
                label: '丢弃',
                icon: Icons.delete_outline,
                color: colors.danger,
                onTap: running ? null : onDiscard,
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _GitActionChip extends StatelessWidget {
  const _GitActionChip({
    required this.label,
    required this.icon,
    required this.color,
    required this.onTap,
    this.filled = false,
  });

  final String label;
  final IconData icon;
  final Color color;
  final VoidCallback? onTap;
  final bool filled;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final enabled = onTap != null;
    final effective = enabled ? color : color.withValues(alpha: 0.45);
    return InkWell(
      borderRadius: BorderRadius.circular(8),
      onTap: onTap,
      child: Container(
        height: 32,
        padding: const EdgeInsets.symmetric(horizontal: 10),
        decoration: BoxDecoration(
          color: filled
              ? color.withValues(alpha: enabled ? 0.12 : 0.06)
              : colors.surfaceHigh.withValues(alpha: enabled ? 0.5 : 0.3),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 15, color: effective),
            const SizedBox(width: 5),
            Text(
              label,
              style: TextStyle(
                color: effective,
                fontSize: 12,
                height: 1.33,
                fontWeight: filled ? FontWeight.w600 : FontWeight.w500,
                letterSpacing: 0,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
