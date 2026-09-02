part of 'we_ui.dart';

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
                  padding: const EdgeInsets.symmetric(
                    horizontal: 24,
                    vertical: 22,
                  ),
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
  const WeRedActionCell({super.key, required this.text, required this.onTap});

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
