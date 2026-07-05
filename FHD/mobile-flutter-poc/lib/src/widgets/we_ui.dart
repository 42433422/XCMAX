import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../theme/app_theme.dart';

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
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: actions,
                  ),
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
            style: textTheme.labelSmall?.copyWith(
              color: colors.textSecondary,
            ),
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
                      color: Theme.of(context)
                          .colorScheme
                          .onSurfaceVariant
                          .withValues(alpha: 0.62),
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

class WeField extends StatelessWidget {
  const WeField({
    super.key,
    required this.controller,
    required this.placeholder,
    this.onChanged,
    this.keyboardType,
    this.inputFormatters,
    this.singleLine = true,
    this.maxLength,
    this.obscureText = false,
  });

  final TextEditingController controller;
  final String placeholder;
  final ValueChanged<String>? onChanged;
  final TextInputType? keyboardType;
  final List<TextInputFormatter>? inputFormatters;
  final bool singleLine;
  final int? maxLength;
  final bool obscureText;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    return Container(
      key: ValueKey('we_field_container_$placeholder'),
      constraints: const BoxConstraints(minHeight: 46),
      decoration: BoxDecoration(
        color: colors.weChatInputBg,
        borderRadius: BorderRadius.circular(10),
      ),
      child: TextField(
        controller: controller,
        keyboardType: keyboardType,
        inputFormatters: inputFormatters,
        maxLength: maxLength,
        obscureText: obscureText,
        minLines: 1,
        maxLines: singleLine ? 1 : 4,
        onChanged: onChanged,
        style: textTheme.bodyLarge?.copyWith(
          color: colors.textPrimary,
        ),
        decoration: InputDecoration(
          counterText: '',
          isDense: true,
          border: InputBorder.none,
          contentPadding:
              const EdgeInsets.symmetric(horizontal: 14, vertical: 13),
          hintText: placeholder,
          hintStyle: textTheme.bodyLarge?.copyWith(
            color: colors.textSecondary.withValues(alpha: 0.6),
          ),
        ),
      ),
    );
  }
}

class WeBlockButton extends StatelessWidget {
  const WeBlockButton({
    super.key,
    required this.text,
    required this.onPressed,
    this.enabled = true,
  });

  final String text;
  final VoidCallback onPressed;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: SizedBox(
        key: ValueKey('we_block_button_$text'),
        width: double.infinity,
        height: 44,
        child: FilledButton(
          style: FilledButton.styleFrom(
            backgroundColor: colors.brand,
            foregroundColor: Colors.white,
            disabledBackgroundColor: colors.brand.withValues(alpha: 0.4),
            disabledForegroundColor: Colors.white.withValues(alpha: 0.7),
            elevation: 0,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(8),
            ),
            textStyle: textTheme.bodyLarge?.copyWith(
              fontWeight: FontWeight.w500,
            ),
          ),
          onPressed: enabled ? onPressed : null,
          child: Text(text),
        ),
      ),
    );
  }
}

class WeBlockOutlinedButton extends StatelessWidget {
  const WeBlockOutlinedButton({
    super.key,
    required this.text,
    required this.onPressed,
    this.enabled = true,
  });

  final String text;
  final VoidCallback onPressed;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final textTheme = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: SizedBox(
        width: double.infinity,
        height: 48,
        child: OutlinedButton(
          style: OutlinedButton.styleFrom(
            foregroundColor: colors.brand,
            side: BorderSide(color: colors.divider),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(8),
            ),
            textStyle: textTheme.bodyLarge,
          ),
          onPressed: enabled ? onPressed : null,
          child: Text(text),
        ),
      ),
    );
  }
}

class WeDialog extends StatelessWidget {
  const WeDialog({
    super.key,
    required this.onDismiss,
    required this.title,
    required this.message,
    required this.onConfirm,
    this.confirmText = '确定',
    this.dismissText = '取消',
    this.confirmDanger = false,
  });

  final VoidCallback onDismiss;
  final String title;
  final String message;
  final VoidCallback onConfirm;
  final String confirmText;
  final String? dismissText;
  final bool confirmDanger;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    final confirmTint = confirmDanger ? colors.danger : colors.brand;
    return Dialog(
      insetPadding: EdgeInsets.zero,
      backgroundColor: Colors.transparent,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(16),
        child: SizedBox(
          width: 290,
          child: Material(
            color: colors.surface,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Padding(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 24, vertical: 22),
                  child: Column(
                    children: [
                      Text(
                        title,
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          color: colors.textPrimary,
                          fontSize: 17,
                          height: 1.29,
                          fontWeight: FontWeight.w500,
                          letterSpacing: 0,
                        ),
                      ),
                      if (message.trim().isNotEmpty) ...[
                        const SizedBox(height: 10),
                        Text(
                          message,
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            color: colors.textSecondary,
                            fontSize: 15,
                            height: 1.4,
                            letterSpacing: 0,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
                Divider(height: 0.5, thickness: 0.5, color: colors.divider),
                SizedBox(
                  height: 50,
                  child: Row(
                    children: [
                      if (dismissText != null) ...[
                        Expanded(
                          child: _WeDialogButton(
                            key: const ValueKey('we_dialog_dismiss'),
                            text: dismissText!,
                            tint: colors.textSecondary,
                            onTap: onDismiss,
                          ),
                        ),
                        VerticalDivider(
                          width: 0.5,
                          thickness: 0.5,
                          color: colors.divider,
                        ),
                      ],
                      Expanded(
                        child: _WeDialogButton(
                          key: const ValueKey('we_dialog_confirm'),
                          text: confirmText,
                          tint: confirmTint,
                          bold: true,
                          onTap: onConfirm,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _WeDialogButton extends StatelessWidget {
  const _WeDialogButton({
    super.key,
    required this.text,
    required this.tint,
    required this.onTap,
    this.bold = false,
  });

  final String text;
  final Color tint;
  final VoidCallback onTap;
  final bool bold;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      child: SizedBox.expand(
        child: Center(
          child: Text(
            text,
            style: TextStyle(
              color: tint,
              fontSize: 16,
              height: 1.38,
              fontWeight: bold ? FontWeight.w500 : FontWeight.w400,
              letterSpacing: 0,
            ),
          ),
        ),
      ),
    );
  }
}

class WeRedActionCell extends StatelessWidget {
  const WeRedActionCell({
    super.key,
    required this.text,
    required this.onTap,
  });

  final String text;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Material(
      color: colors.surface,
      child: InkWell(
        onTap: onTap,
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(vertical: 14),
          alignment: Alignment.center,
          child: Text(
            text,
            style: TextStyle(
              color: colors.danger,
              fontSize: 16,
              height: 1.38,
              letterSpacing: 0,
            ),
          ),
        ),
      ),
    );
  }
}
