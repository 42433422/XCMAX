// part 文件：协议勾选与扫码入口组件。

part of 'auth_screen.dart';

class _OtpCell extends StatelessWidget {
  const _OtpCell({required this.char, required this.focused});

  final String char;
  final bool focused;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      height: 48,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: focused ? colors.brand : colors.divider,
          width: focused ? 1.5 : 1,
        ),
      ),
      child: Text(
        char,
        textAlign: TextAlign.center,
        style: TextStyle(
          color: colors.textPrimary,
          fontSize: 18,
          height: 1.44,
          fontWeight: FontWeight.w500,
          letterSpacing: 0,
        ),
      ),
    );
  }
}

class _ScanButton extends StatelessWidget {
  const _ScanButton({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(22),
      child: Container(
        height: 44,
        decoration: BoxDecoration(
          color: colors.brand.withValues(alpha: 0.06),
          borderRadius: BorderRadius.circular(22),
          border: Border.all(
            color: colors.brand.withValues(alpha: 0.35),
            width: 0.5,
          ),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.qr_code_scanner, size: 18, color: colors.brand),
            const SizedBox(width: 8),
            Text(
              '扫码绑定/登录',
              style: TextStyle(
                color: colors.brand,
                fontSize: 15,
                height: 1.4,
                fontWeight: FontWeight.w500,
                letterSpacing: 0,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _RegisterLink extends StatelessWidget {
  const _RegisterLink({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Center(
      child: InkWell(
        key: const ValueKey('android-register-link'),
        onTap: onTap,
        borderRadius: BorderRadius.circular(4),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          child: Text(
            '账号注册',
            style: TextStyle(
              color: colors.brand,
              fontSize: 13,
              height: 1.31,
              fontWeight: FontWeight.w500,
              letterSpacing: 0,
            ),
          ),
        ),
      ),
    );
  }
}

class _LoginCheckbox extends StatelessWidget {
  const _LoginCheckbox({
    required this.checked,
    required this.label,
    required this.onTap,
  });

  final bool checked;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          _CheckBoxMark(checked: checked, size: 18, radius: 3),
          const SizedBox(width: 6),
          Text(
            label,
            style: TextStyle(
              color: colors.textSecondary,
              fontSize: 13,
              height: 1.31,
              letterSpacing: 0,
            ),
          ),
        ],
      ),
    );
  }
}

class _AgreementRow extends StatelessWidget {
  const _AgreementRow({
    required this.agreed,
    required this.onToggle,
    required this.openExternalUrl,
  });

  final bool agreed;
  final VoidCallback onToggle;
  final ExternalUrlLauncher openExternalUrl;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
      child: Row(
        children: [
          GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: onToggle,
            child: _CheckBoxMark(checked: agreed, size: 20, radius: 4),
          ),
          const SizedBox(width: 8),
          Text(
            '已阅读并同意 ',
            style: TextStyle(
              color: colors.textSecondary,
              fontSize: 11,
              height: 1.27,
              letterSpacing: 0,
            ),
          ),
          _AgreementLink(
            label: '服务协议',
            url: _termsUrl,
            openExternalUrl: openExternalUrl,
          ),
          Text(
            ' 和 ',
            style: TextStyle(
              color: colors.textSecondary,
              fontSize: 11,
              height: 1.27,
              letterSpacing: 0,
            ),
          ),
          _AgreementLink(
            label: '隐私政策',
            url: _privacyUrl,
            openExternalUrl: openExternalUrl,
          ),
        ],
      ),
    );
  }
}

class _CheckBoxMark extends StatelessWidget {
  const _CheckBoxMark({
    required this.checked,
    required this.size,
    required this.radius,
  });

  final bool checked;
  final double size;
  final double radius;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: checked ? colors.brand : colors.divider,
        borderRadius: BorderRadius.circular(radius),
        border: checked ? null : Border.all(color: colors.divider, width: 0.5),
      ),
      alignment: Alignment.center,
      child: checked
          ? Icon(Icons.check, size: size == 20 ? 13 : 12, color: Colors.white)
          : null,
    );
  }
}

class _AgreementLink extends StatelessWidget {
  const _AgreementLink({
    required this.label,
    required this.url,
    required this.openExternalUrl,
  });

  final String label;
  final String url;
  final ExternalUrlLauncher openExternalUrl;

  @override
  Widget build(BuildContext context) {
    final colors = AppTheme.colors(context);
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () async {
        final opened = await openExternalUrl(Uri.parse(url));
        if (!context.mounted || opened) return;
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('无法打开$label')));
      },
      child: Text(
        label,
        style: TextStyle(
          color: colors.brand,
          fontSize: 11,
          height: 1.27,
          fontWeight: FontWeight.w500,
          letterSpacing: 0,
        ),
      ),
    );
  }
}
