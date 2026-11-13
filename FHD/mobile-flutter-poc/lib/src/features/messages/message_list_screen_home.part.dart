part of 'message_list_screen.dart';

// 会话动作面板、首页头部与空状态组件。
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
  const _ConversationActionSheet({required this.title, required this.actions});

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
    required this.query,
    required this.onQueryChanged,
    required this.onClearQuery,
    required this.onMenuSelected,
  });

  final String query;
  final ValueChanged<String> onQueryChanged;
  final VoidCallback onClearQuery;
  final ValueChanged<String> onMenuSelected;

  @override
  Widget build(BuildContext context) {
    return Padding(
      key: const ValueKey('message_home_header_padding'),
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 10),
      child: Column(
        children: [
          Row(
            children: [
              const Spacer(),
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

class _ConversationEmptyEntry {
  const _ConversationEmptyEntry({required this.loading});

  final bool loading;
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
              loading ? '正在同步…' : '暂无会话',
              style: textTheme.bodyLarge?.copyWith(color: colors.textSecondary),
            ),
          ],
        ),
      ),
    );
  }
}
