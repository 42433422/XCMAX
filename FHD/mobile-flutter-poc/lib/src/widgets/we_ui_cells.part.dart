part of 'we_ui.dart';

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
        style: textTheme.bodyLarge?.copyWith(color: colors.textPrimary),
        decoration: InputDecoration(
          counterText: '',
          isDense: true,
          border: InputBorder.none,
          contentPadding: const EdgeInsets.symmetric(
            horizontal: 14,
            vertical: 13,
          ),
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
