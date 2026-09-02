import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../theme/app_theme.dart';
part 'we_ui_cells.part.dart';
part 'we_ui_dialog.part.dart';

class WeTopBar extends StatelessWidget {
  const WeTopBar({
    super.key,
    required this.title,
    this.titleWidget,
    this.onBack,
    this.showBack = false,
    this.actions = const [],
    this.height = 64,
  });

  final String title;
  final Widget? titleWidget;
  final VoidCallback? onBack;
  final bool showBack;
  final List<Widget> actions;
  final double height;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    return Column(
      children: [
        Container(
          key: ValueKey('we_top_bar_surface_$title'),
          height: height,
          color: colors.surface,
          child: Row(
            children: [
              if (showBack || onBack != null)
                IconButton(
                  onPressed: onBack ?? () => Navigator.of(context).maybePop(),
                  icon: const Icon(Icons.arrow_back, size: 24),
                  color: colors.textPrimary,
                  tooltip: '返回',
                )
              else
                const SizedBox(width: 16),
              Expanded(
                child: titleWidget ??
                    Text(
                      title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: textTheme.titleMedium?.copyWith(
                        color: colors.textPrimary,
                      ),
                    ),
              ),
              if (actions.isEmpty)
                const SizedBox(width: 16)
              else
                Padding(
                  padding: const EdgeInsets.only(right: 12),
                  child: Row(mainAxisSize: MainAxisSize.min, children: actions),
                ),
            ],
          ),
        ),
        Divider(
          key: ValueKey('we_top_bar_divider_$title'),
          height: 0.5,
          thickness: 0.5,
          color: colors.divider.withValues(alpha: 0.4),
        ),
      ],
    );
  }
}

class WeSectionCaption extends StatelessWidget {
  const WeSectionCaption(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    return ColoredBox(
      color: colors.page,
      child: SizedBox(
        width: double.infinity,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
          child: Text(
            text,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: textTheme.labelSmall?.copyWith(color: colors.textSecondary),
          ),
        ),
      ),
    );
  }
}

class WeCellGroup extends StatelessWidget {
  const WeCellGroup({super.key, required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 12),
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(12),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.08),
            blurRadius: 3,
            offset: const Offset(0, 1),
          ),
        ],
      ),
      child: Column(children: children),
    );
  }
}

class WeCell extends StatelessWidget {
  const WeCell({
    super.key,
    required this.title,
    this.subtitle = '',
    this.value = '',
    this.icon,
    this.iconColor = AppTheme.brand,
    this.iconBg = AppTheme.brandContainer,
    this.trailing,
    this.onTap,
    this.titleColor = AppTheme.textPrimary,
    this.showArrow = true,
    this.showDivider = true,
  });

  final String title;
  final String subtitle;
  final String value;
  final IconData? icon;
  final Color iconColor;
  final Color iconBg;
  final Widget? trailing;
  final VoidCallback? onTap;
  final Color titleColor;
  final bool showArrow;
  final bool showDivider;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    final effectiveIconColor = switch (iconColor) {
      AppTheme.brand => colors.brand,
      AppTheme.success => colors.success,
      AppTheme.warning => colors.warning,
      AppTheme.danger => colors.danger,
      AppTheme.textPrimary => colors.textPrimary,
      AppTheme.textSecondary => colors.textSecondary,
      AppTheme.textTertiary => colors.textTertiary,
      _ => iconColor,
    };
    final effectiveIconBg = switch (iconBg) {
      AppTheme.brandContainer => colors.brandContainer,
      AppTheme.surfaceHigh => colors.surfaceHigh,
      AppTheme.page => colors.page,
      AppTheme.surface => colors.surface,
      _ => iconBg,
    };
    final effectiveTitleColor = switch (titleColor) {
      AppTheme.textPrimary => colors.textPrimary,
      AppTheme.textSecondary => colors.textSecondary,
      AppTheme.textTertiary => colors.textTertiary,
      AppTheme.danger => colors.danger,
      _ => titleColor,
    };
    return Material(
      color: colors.surface,
      child: InkWell(
        onTap: onTap,
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              child: Row(
                children: [
                  if (icon != null) ...[
                    Container(
                      key: ValueKey('we_cell_icon_box_$title'),
                      width: 36,
                      height: 36,
                      decoration: BoxDecoration(
                        color: effectiveIconBg,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      alignment: Alignment.center,
                      child: Icon(
                        icon,
                        key: ValueKey('we_cell_icon_$title'),
                        size: 20,
                        color: effectiveIconColor,
                      ),
                    ),
                    const SizedBox(width: 14),
                  ],
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          title,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: textTheme.bodyLarge?.copyWith(
                            color: effectiveTitleColor,
                          ),
                        ),
                        if (subtitle.trim().isNotEmpty)
                          Text(
                            subtitle,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: textTheme.bodySmall?.copyWith(
                              color: colors.textSecondary,
                            ),
                          ),
                      ],
                    ),
                  ),
                  if (value.trim().isNotEmpty) ...[
                    Text(
                      value,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: textTheme.bodyMedium?.copyWith(
                        color: colors.textSecondary,
                      ),
                    ),
                    if (showArrow) const SizedBox(width: 4),
                  ],
                  if (trailing != null)
                    trailing!
                  else if (showArrow)
                    Icon(
                      key: ValueKey('we_cell_arrow_$title'),
                      Icons.chevron_right,
                      size: 16,
                      color: Theme.of(
                        context,
                      ).colorScheme.onSurfaceVariant.withValues(alpha: 0.62),
                    ),
                ],
              ),
            ),
            if (showDivider)
              Divider(
                height: 0.5,
                indent: icon == null ? 16 : 66,
                thickness: 0.5,
              ),
          ],
        ),
      ),
    );
  }
}
