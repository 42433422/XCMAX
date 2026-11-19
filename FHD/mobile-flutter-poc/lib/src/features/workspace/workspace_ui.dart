import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';

class WorkspaceScaffold extends StatelessWidget {
  const WorkspaceScaffold({
    super.key,
    required this.backgroundColor,
    required this.body,
    this.appBar,
    this.bottomNavigationBar,
  });

  final Color backgroundColor;
  final Widget body;
  final PreferredSizeWidget? appBar;
  final Widget? bottomNavigationBar;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final actionColors = theme.brightness == Brightness.dark
        ? scheme.copyWith(onPrimary: const Color(0xFF101333))
        : scheme.copyWith(primary: const Color(0xFF5659D9));
    return Theme(
      data: theme.copyWith(colorScheme: actionColors),
      child: Scaffold(
        backgroundColor: backgroundColor,
        appBar: appBar,
        body: body,
        bottomNavigationBar: bottomNavigationBar,
      ),
    );
  }
}

class WorkspacePanel extends StatelessWidget {
  const WorkspacePanel({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(16),
  });

  final Widget child;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Material(
      color: colors.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(18),
        side: BorderSide(color: colors.divider),
      ),
      clipBehavior: Clip.antiAlias,
      child: Padding(padding: padding, child: child),
    );
  }
}

class WorkspaceBadge extends StatelessWidget {
  const WorkspaceBadge({super.key, required this.label, this.color});

  final String label;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: color?.withValues(alpha: 0.14) ?? scheme.primaryContainer,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        child: Text(
          label,
          style: theme.textTheme.labelMedium?.copyWith(
            color: color == null ? scheme.onPrimaryContainer : scheme.onSurface,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    );
  }
}

class WorkspaceTransition extends StatelessWidget {
  const WorkspaceTransition({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    final duration = AppTheme.motionDuration(context, milliseconds: 200);
    if (duration == Duration.zero) return child;
    return TweenAnimationBuilder<double>(
      key: child.key,
      tween: Tween(begin: 0, end: 1),
      duration: duration,
      curve: Curves.easeOutCubic,
      builder: (context, progress, child) => FractionalTranslation(
        translation: Offset(0, (1 - progress) * 0.035),
        child: Opacity(opacity: progress, child: child),
      ),
      child: child,
    );
  }
}
