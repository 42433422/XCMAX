part of 'fixed_partner_profile_screen.dart';

class _FixedPartnerProfileTopBar extends StatelessWidget {
  const _FixedPartnerProfileTopBar({required this.onBack});

  final VoidCallback onBack;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      height: 64,
      color: colors.surface,
      child: Row(
        children: [
          IconButton(
            onPressed: onBack,
            icon: const Icon(Icons.arrow_back, size: 24),
            tooltip: '返回',
            color: colors.textPrimary,
          ),
          const Spacer(),
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: IconButton(
              onPressed: () {},
              icon: const Icon(Icons.more_horiz),
              tooltip: '更多',
              color: colors.textPrimary,
            ),
          ),
        ],
      ),
    );
  }
}

class _FixedPartnerHeader extends StatelessWidget {
  const _FixedPartnerHeader({required this.spec});

  final FixedPartnerProfileSpec spec;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      color: colors.surface,
      padding: const EdgeInsets.fromLTRB(28, 34, 24, 34),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          AppAvatar(
            fallback: spec.avatarFallback,
            size: 76,
            borderRadius: BorderRadius.circular(8),
            contentDescription: spec.name,
          ),
          const SizedBox(width: 18),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  spec.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: colors.textPrimary,
                    fontSize: 22,
                    height: 1.27,
                    fontWeight: FontWeight.w600,
                    letterSpacing: 0,
                  ),
                ),
                const SizedBox(height: 10),
                Text(
                  '昵称：${spec.alias}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: _bodyStyle(context),
                ),
                const SizedBox(height: 6),
                Text(
                  'AI号：${spec.accountId}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: _bodyStyle(context),
                ),
                const SizedBox(height: 6),
                Text(
                  '来源：${spec.source}',
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
        ],
      ),
    );
  }
}

class _PlainCell extends StatelessWidget {
  const _PlainCell({
    required this.title,
    required this.subtitle,
    required this.showArrow,
  });

  final String title;
  final String subtitle;
  final bool showArrow;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      color: colors.surface,
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: TextStyle(
                    color: colors.textPrimary,
                    fontSize: 17,
                    height: 1.29,
                    fontWeight: FontWeight.w500,
                    letterSpacing: 0,
                  ),
                ),
                if (subtitle.trim().isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Text(
                    subtitle,
                    style: TextStyle(
                      color: colors.textSecondary,
                      fontSize: 13,
                      height: 1.31,
                      letterSpacing: 0,
                    ),
                  ),
                ],
              ],
            ),
          ),
          if (showArrow)
            Icon(Icons.chevron_right, size: 20, color: colors.textTertiary),
        ],
      ),
    );
  }
}

class _CirclePreview extends StatelessWidget {
  const _CirclePreview({required this.spec, required this.onTap});

  final FixedPartnerProfileSpec spec;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final labels = spec.circleLabels.take(3).toList(growable: false);
    final colors = AppTheme.colors(context);
    final accent = _resolvePartnerColor(context, spec.avatarColor);
    return Material(
      color: colors.surface,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
          child: Column(
            children: [
              Row(
                children: [
                  Icon(Icons.forum, size: 20, color: colors.momentAccent),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'AI交流圈',
                          style: TextStyle(
                            color: colors.textPrimary,
                            fontSize: 17,
                            height: 1.29,
                            fontWeight: FontWeight.w500,
                            letterSpacing: 0,
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          '进入交流圈 · 查看 ${spec.name} 的动态与能力更新',
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
                  Icon(
                    Icons.chevron_right,
                    size: 20,
                    color: colors.textTertiary,
                  ),
                ],
              ),
              if (labels.isNotEmpty) ...[
                const SizedBox(height: 12),
                Row(
                  children: [
                    const SizedBox(width: 30),
                    for (final label in labels) ...[
                      Container(
                        width: 44,
                        height: 44,
                        alignment: Alignment.center,
                        decoration: BoxDecoration(
                          color: accent.withValues(alpha: 0.16),
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(
                          label.length > 2 ? label.substring(0, 2) : label,
                          style: TextStyle(
                            color: accent,
                            fontSize: 11,
                            height: 1.27,
                            fontWeight: FontWeight.w600,
                            letterSpacing: 0,
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                    ],
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _ActionRow extends StatelessWidget {
  const _ActionRow({
    required this.text,
    required this.icon,
    required this.onTap,
  });

  final String text;
  final IconData icon;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Material(
      color: colors.surface,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icon, size: 22, color: colors.brand),
              const SizedBox(width: 10),
              Text(
                text,
                style: TextStyle(
                  color: colors.brand,
                  fontSize: 17,
                  height: 1.29,
                  fontWeight: FontWeight.w500,
                  letterSpacing: 0,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

TextStyle _bodyStyle(BuildContext context) {
  final colors = AppTheme.colors(context);
  return TextStyle(
    color: colors.textSecondary,
    fontSize: 15,
    height: 1.4,
    letterSpacing: 0,
  );
}

Color _resolvePartnerColor(BuildContext context, Color color) {
  final colors = AppTheme.colors(context);
  return switch (color) {
    AppTheme.brand => colors.brand,
    AppTheme.success => colors.success,
    AppTheme.momentAccent => colors.momentAccent,
    AppTheme.textPrimary => colors.textPrimary,
    _ => color,
  };
}
