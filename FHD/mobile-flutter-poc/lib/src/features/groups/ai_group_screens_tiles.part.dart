part of 'ai_group_screens.dart';

// 候选成员、群成员、输入区芯片与工具瓦片组件。
class _CandidateTile extends StatelessWidget {
  const _CandidateTile({
    required this.candidate,
    required this.selected,
    required this.locked,
    required this.onChanged,
  });

  final AiGroupCandidate candidate;
  final bool selected;
  final bool locked;
  final VoidCallback? onChanged;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return InkWell(
      onTap: onChanged,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: Row(
          children: [
            Checkbox(
              value: selected,
              onChanged: locked ? null : (_) => onChanged?.call(),
            ),
            const SizedBox(width: 8),
            AppAvatar(
              imageSource: candidate.avatarUrl,
              fallback: aiGroupAvatarFallback(
                employeeId: candidate.employeeId,
                name: candidate.name,
              ),
              size: MessageAvatarLayout.employeePickerAvatarSize,
              borderRadius: MessageAvatarLayout.employeePickerAvatarRadius,
              contentDescription: candidate.name,
            ),
            const SizedBox(
              width: MessageAvatarLayout.employeePickerAvatarTextGap,
            ),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    candidate.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: colors.textPrimary,
                      fontSize: 16,
                      height: 1.38,
                      fontWeight: FontWeight.w500,
                      letterSpacing: 0,
                    ),
                  ),
                  Text(
                    candidate.summary,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: colors.textSecondary,
                      fontSize: 13,
                      height: 1.31,
                      letterSpacing: 0,
                    ),
                  ),
                ],
              ),
            ),
            if (locked)
              Text(
                '固定',
                style: TextStyle(color: colors.textSecondary, fontSize: 12),
              ),
          ],
        ),
      ),
    );
  }
}

class _MemberTile extends StatelessWidget {
  const _MemberTile({
    required this.name,
    required this.summary,
    required this.employeeId,
    this.avatarUrl,
    this.avatarKey = '',
    this.trailing,
    this.onTap,
  });

  final String name;
  final String summary;
  final String employeeId;
  final String? avatarUrl;
  final String avatarKey;
  final Widget? trailing;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return ListTile(
      onTap: onTap,
      leading: AppAvatar(
        imageSource: avatarUrl,
        fallback: aiGroupAvatarFallback(
          employeeId: employeeId,
          name: name,
          avatarKey: avatarKey,
        ),
        size: 38,
        borderRadius: BorderRadius.circular(8),
        contentDescription: name,
      ),
      title: Text(
        name,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(color: colors.textPrimary),
      ),
      subtitle: Text(
        summary,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(color: colors.textSecondary),
      ),
      trailing: trailing,
    );
  }
}

class _ComposerChip extends StatelessWidget {
  const _ComposerChip({
    super.key,
    required this.icon,
    required this.label,
    required this.onTap,
    this.active = false,
    this.trailingIcon,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final bool active;
  final IconData? trailingIcon;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(16),
      child: Container(
        constraints: const BoxConstraints(maxWidth: 260),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
        decoration: BoxDecoration(
          color: active
              ? colors.brand.withValues(alpha: 0.10)
              : colors.surfaceHigh,
          borderRadius: BorderRadius.circular(16),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 16, color: colors.brand),
            const SizedBox(width: 6),
            Flexible(
              child: Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: textTheme.labelMedium?.copyWith(
                  color: colors.textPrimary,
                ),
              ),
            ),
            if (trailingIcon != null) ...[
              const SizedBox(width: 6),
              Icon(trailingIcon, size: 14, color: colors.textSecondary),
            ],
          ],
        ),
      ),
    );
  }
}

class _ToolTile extends StatelessWidget {
  const _ToolTile(this.action);

  final _GroupToolAction action;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    return InkWell(
      onTap: action.onTap,
      borderRadius: BorderRadius.circular(8),
      child: SizedBox(
        key: ValueKey('group_tool_card_${action.label}'),
        height: 92,
        child: Padding(
          padding: const EdgeInsets.only(top: 1),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                key: ValueKey('group_tool_icon_box_${action.label}'),
                width: 62,
                height: 62,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: colors.surfaceHigh.withValues(alpha: 0.62),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Icon(
                  action.icon,
                  color: colors.textPrimary,
                  size: 27,
                  semanticLabel: action.label,
                ),
              ),
              const SizedBox(height: 8),
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 82),
                child: Text(
                  action.label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  textAlign: TextAlign.center,
                  style: textTheme.labelMedium?.copyWith(
                    color: colors.textSecondary,
                    fontSize: 13,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
