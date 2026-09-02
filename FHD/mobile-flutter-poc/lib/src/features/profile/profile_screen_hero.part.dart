part of 'profile_screen.dart';

// 资料主卡、可编辑头像、信息芯片与状态徽标组件。
class _ProfileHeroCard extends StatelessWidget {
  const _ProfileHeroCard({
    required this.displayName,
    required this.avatarPath,
    required this.accountKindLabel,
    required this.serverModeLabel,
    required this.profilePage,
    required this.syncing,
    required this.onEdit,
    required this.onSync,
  });

  final String displayName;
  final String avatarPath;
  final String accountKindLabel;
  final String serverModeLabel;
  final MobileProfilePageConfig? profilePage;
  final bool syncing;
  final VoidCallback onEdit;
  final VoidCallback onSync;

  @override
  Widget build(BuildContext context) {
    final page = profilePage;
    final colors = AppTheme.colors(context);
    final accent = _profileAccentColor(context, page?.accent);
    final solidHero = page?.heroVariant.toLowerCase() == 'solid';
    final headline = page?.headline.trim() ?? '';
    final subtitle = (page?.subtitle ?? '').ifEmpty('个人资料与工作身份');
    final readyStatus = (page?.statusReady ?? '').ifEmpty('资料、头像和工作台状态已就绪');
    final syncingStatus = (page?.statusSyncing ?? '').ifEmpty('正在同步你的资料与工作台状态');
    final primaryChip = (page?.primaryChip ?? '').ifEmpty(accountKindLabel);
    final secondaryChip = (page?.secondaryChip ?? '').ifEmpty(serverModeLabel);
    final titleColor =
        solidHero ? colors.chatUserBubbleText : colors.textPrimary;
    final bodyColor = solidHero
        ? colors.chatUserBubbleText.withValues(alpha: 0.78)
        : colors.textSecondary;
    final cardBorder = solidHero
        ? colors.chatUserBubbleText.withValues(alpha: 0.24)
        : colors.divider.withValues(alpha: 0.72);
    final glassAccent = Color.alphaBlend(accent.withAlpha(31), colors.surface);
    final glassTail = Color.alphaBlend(
      Theme.of(context).colorScheme.secondaryContainer.withAlpha(70),
      colors.surface,
    );

    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onEdit,
        borderRadius: BorderRadius.circular(22),
        child: Container(
          key: const ValueKey('profile_hero_card'),
          margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(22),
            border: Border.all(color: cardBorder),
            gradient: LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: solidHero
                  ? [
                      accent,
                      accent.withValues(alpha: 0.82),
                      Theme.of(context).colorScheme.tertiary,
                    ]
                  : [colors.surface, glassAccent, glassTail],
              stops: solidHero ? null : const [0, 0.7, 1],
            ),
          ),
          child: Column(
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  _EditableAvatar(
                    avatarPath: avatarPath,
                    accent: accent,
                    solidHero: solidHero,
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        if (headline.isNotEmpty) ...[
                          Text(
                            headline,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              color: bodyColor,
                              fontSize: 11,
                              height: 1.27,
                              fontWeight: FontWeight.w500,
                              letterSpacing: 0,
                            ),
                          ),
                          const SizedBox(height: 2),
                        ],
                        Row(
                          children: [
                            Expanded(
                              child: Text(
                                displayName,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: TextStyle(
                                  color: titleColor,
                                  fontSize: 18,
                                  height: 1.44,
                                  fontWeight: FontWeight.w600,
                                  letterSpacing: 0,
                                ),
                              ),
                            ),
                            Icon(
                              key: const ValueKey('profile_hero_chevron'),
                              Icons.chevron_right,
                              size: 20,
                              color: bodyColor,
                            ),
                          ],
                        ),
                        const SizedBox(height: 4),
                        Text(
                          subtitle,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            color: bodyColor,
                            fontSize: 13,
                            height: 1.31,
                            fontWeight: FontWeight.w500,
                            letterSpacing: 0,
                          ),
                        ),
                        const SizedBox(height: 12),
                        Row(
                          children: [
                            _InfoChip(
                              icon: Icons.verified,
                              label: primaryChip,
                              accent: accent,
                              solidHero: solidHero,
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: _InfoChip(
                                icon: Icons.tag,
                                label: secondaryChip,
                                accent: accent,
                                solidHero: solidHero,
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 9),
              Row(
                children: [
                  Expanded(
                    child: Text(
                      syncing ? syncingStatus : readyStatus,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        color: bodyColor,
                        fontSize: 13,
                        height: 1.31,
                        fontWeight: FontWeight.w500,
                        letterSpacing: 0,
                      ),
                    ),
                  ),
                  _StatusPill(
                    label: syncing ? '同步中…' : '同步',
                    selected: syncing,
                    onTap: onSync,
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _EditableAvatar extends StatelessWidget {
  const _EditableAvatar({
    required this.avatarPath,
    required this.accent,
    required this.solidHero,
  });

  final String avatarPath;
  final Color accent;
  final bool solidHero;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return SizedBox(
      width: 72,
      height: 72,
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          Positioned(
            left: 0,
            top: 0,
            child: Container(
              key: const ValueKey('profile_avatar_frame'),
              width: 72,
              height: 72,
              padding: const EdgeInsets.all(3),
              decoration: BoxDecoration(
                color: solidHero
                    ? colors.chatUserBubbleText.withValues(alpha: 0.92)
                    : colors.surface,
                shape: BoxShape.circle,
              ),
              child: _ProfileAvatarPreview(avatarPath: avatarPath, size: 66),
            ),
          ),
          Positioned(
            right: -3,
            bottom: -3,
            child: Container(
              key: const ValueKey('profile_avatar_badge_shell'),
              width: 22,
              height: 22,
              padding: const EdgeInsets.all(2),
              decoration: BoxDecoration(
                color: solidHero
                    ? colors.chatUserBubbleText.withValues(alpha: 0.92)
                    : colors.surface,
                shape: BoxShape.circle,
              ),
              child: Container(
                key: const ValueKey('profile_avatar_badge_accent'),
                decoration: BoxDecoration(
                  color: accent,
                  shape: BoxShape.circle,
                ),
                child: const Icon(Icons.photo, size: 13, color: Colors.white),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ProfileAvatarPreview extends StatelessWidget {
  const _ProfileAvatarPreview({required this.avatarPath, required this.size});

  final String avatarPath;
  final double size;

  @override
  Widget build(BuildContext context) {
    return AppAvatar(
      imageSource: avatarPath,
      fallback: AppAvatarFallback.user,
      size: size,
      borderRadius: BorderRadius.circular(size / 2),
      contentDescription: '头像',
    );
  }
}

class _InfoChip extends StatelessWidget {
  const _InfoChip({
    required this.icon,
    required this.label,
    required this.accent,
    required this.solidHero,
  });

  final IconData icon;
  final String label;
  final Color accent;
  final bool solidHero;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      constraints: const BoxConstraints(minHeight: 28),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: solidHero
            ? colors.chatUserBubbleText.withValues(alpha: 0.18)
            : colors.surface.withValues(alpha: 0.74),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(
          color: solidHero
              ? colors.chatUserBubbleText.withValues(alpha: 0.26)
              : colors.divider.withValues(alpha: 0.62),
        ),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            icon,
            size: 14,
            color: solidHero ? colors.chatUserBubbleText : accent,
          ),
          const SizedBox(width: 4),
          Flexible(
            child: Text(
              label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: solidHero
                    ? colors.chatUserBubbleText.withValues(alpha: 0.9)
                    : colors.textSecondary,
                fontSize: 11,
                height: 1.27,
                fontWeight: FontWeight.w500,
                letterSpacing: 0,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _StatusPill extends StatelessWidget {
  const _StatusPill({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: colors.divider),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                Icons.refresh_outlined,
                size: 14,
                color: colors.textTertiary,
              ),
              const SizedBox(width: 4),
              Text(
                label,
                style: TextStyle(
                  color: selected ? colors.brand : colors.textSecondary,
                  fontSize: 11,
                  height: 1.27,
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

Color _profileAccentColor(BuildContext context, String? accent) {
  final colors = AppTheme.colors(context);
  switch (accent?.trim().toLowerCase()) {
    case 'emerald':
    case 'green':
    case 'success':
      return colors.success;
    case 'amber':
    case 'yellow':
    case 'warning':
      return colors.warning;
    case 'red':
    case 'danger':
      return colors.danger;
    case 'violet':
    case 'purple':
      return colors.brandGradientEnd;
    default:
      return colors.brand;
  }
}
