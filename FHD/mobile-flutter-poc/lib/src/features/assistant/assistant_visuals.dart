import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';

const assistantIndigo = Color(0xFF5B5CE2);
const assistantBlue = Color(0xFF4B8BFF);
const assistantCyan = Color(0xFF24B8C7);
const assistantMint = Color(0xFF28B789);
const assistantRose = Color(0xFFE86E96);
const assistantAmber = Color(0xFFF0A33A);

class AssistantBackdrop extends StatelessWidget {
  const AssistantBackdrop({
    super.key,
    required this.child,
    this.enabled = true,
  });

  final Widget child;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    if (!enabled) return child;
    final colors = AppTheme.colors(context);
    final dark = Theme.of(context).brightness == Brightness.dark;
    return DecoratedBox(
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: dark
              ? [colors.page, colors.page]
              : const [Color(0xFFF8F8FF), Color(0xFFF5F7FB)],
        ),
      ),
      child: Stack(
        fit: StackFit.expand,
        children: [
          if (!dark) ...[
            const Positioned(
              top: -140,
              right: -95,
              child: _AmbientOrb(
                size: 310,
                colors: [Color(0x1F6B73FF), Color(0x006B73FF)],
              ),
            ),
            const Positioned(
              top: 235,
              left: -150,
              child: _AmbientOrb(
                size: 290,
                colors: [Color(0x1624B8C7), Color(0x0024B8C7)],
              ),
            ),
          ],
          child,
        ],
      ),
    );
  }
}

class _AmbientOrb extends StatelessWidget {
  const _AmbientOrb({required this.size, required this.colors});

  final double size;
  final List<Color> colors;

  @override
  Widget build(BuildContext context) => IgnorePointer(
        child: Container(
          width: size,
          height: size,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            gradient: RadialGradient(colors: colors),
          ),
        ),
      );
}

BoxDecoration assistantSurfaceDecoration(
  BuildContext context, {
  double radius = 22,
  Color? color,
  Color? borderColor,
  bool elevated = true,
}) {
  final colors = AppTheme.colors(context);
  final dark = Theme.of(context).brightness == Brightness.dark;
  return BoxDecoration(
    color: color ?? colors.surface.withValues(alpha: dark ? 0.94 : 0.92),
    borderRadius: BorderRadius.circular(radius),
    border: Border.all(
      color: borderColor ??
          (dark
              ? colors.divider
              : Colors.white.withValues(alpha: elevated ? 0.82 : 0.55)),
      width: 0.8,
    ),
    boxShadow: elevated
        ? [
            BoxShadow(
              color: Colors.black.withValues(alpha: dark ? 0.20 : 0.055),
              blurRadius: 28,
              offset: const Offset(0, 10),
            ),
          ]
        : null,
  );
}

class AssistantSectionLabel extends StatelessWidget {
  const AssistantSectionLabel(this.text, {super.key, this.trailing});

  final String text;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Row(
      children: [
        Text(
          text,
          style: TextStyle(
            color: colors.textPrimary,
            fontSize: 15,
            fontWeight: FontWeight.w700,
            letterSpacing: -0.2,
          ),
        ),
        const Spacer(),
        if (trailing != null) trailing!,
      ],
    );
  }
}

class AssistantTopBar extends StatelessWidget {
  const AssistantTopBar({
    super.key,
    required this.title,
    this.onBack,
    this.actions = const [],
  });

  final String title;
  final VoidCallback? onBack;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return SizedBox(
      key: ValueKey('assistant_top_bar_surface_$title'),
      height: 58,
      child: Row(
        children: [
          const SizedBox(width: 4),
          IconButton(
            onPressed: onBack ?? () => Navigator.of(context).maybePop(),
            icon: const Icon(Icons.arrow_back_ios_new_rounded, size: 20),
            color: colors.textPrimary,
            tooltip: '返回',
          ),
          Expanded(
            child: Text(
              title,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: colors.textPrimary,
                fontSize: 18,
                fontWeight: FontWeight.w700,
                letterSpacing: -0.35,
              ),
            ),
          ),
          if (actions.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(right: 10),
              child: Row(mainAxisSize: MainAxisSize.min, children: actions),
            )
          else
            const SizedBox(width: 16),
        ],
      ),
    );
  }
}

class AssistantIconTile extends StatelessWidget {
  const AssistantIconTile({
    super.key,
    required this.icon,
    this.color = assistantIndigo,
    this.size = 42,
    this.iconSize = 21,
  });

  final IconData icon;
  final Color color;
  final double size;
  final double iconSize;

  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [
              color.withValues(alpha: 0.18),
              color.withValues(alpha: 0.08),
            ],
          ),
          borderRadius: BorderRadius.circular(size * 0.32),
        ),
        alignment: Alignment.center,
        child: Icon(icon, size: iconSize, color: color),
      );
}
